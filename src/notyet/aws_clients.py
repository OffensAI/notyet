"""
AWS client wrappers with retry logic and exponential backoff.
"""

import logging
import time
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError

from .models import Credentials, CallerIdentity


logger = logging.getLogger(__name__)


class IAMClient:
    """
    Wrapper around boto3 IAM client with retry logic and exponential backoff.
    
    Implements exponential backoff for rate limiting and logs all IAM operations.
    """
    
    def __init__(self, credentials: Credentials, max_retries: int = 5):
        """
        Initialize IAM client with credentials.
        
        Args:
            credentials: AWS credentials to use
            max_retries: Maximum number of retry attempts (default: 5)
        """
        self.credentials = credentials
        self.max_retries = max_retries
        self._client = self._create_client()
    
    def _create_client(self):
        """Create boto3 IAM client with credentials."""
        session_kwargs = {
            'aws_access_key_id': self.credentials.access_key_id,
            'aws_secret_access_key': self.credentials.secret_access_key,
        }
        if self.credentials.session_token:
            session_kwargs['aws_session_token'] = self.credentials.session_token
        
        session = boto3.Session(**session_kwargs)
        return session.client('iam')
    
    def _retry_with_backoff(self, operation: str, **kwargs) -> Any:
        """
        Execute an operation with exponential backoff retry logic.
        
        Args:
            operation: Name of the IAM operation to execute
            **kwargs: Arguments to pass to the operation
        
        Returns:
            The response from the AWS API call
        
        Raises:
            ClientError: If all retries are exhausted
        """
        delay = 1  # Start with 1 second delay
        start_time = time.time()
        
        # Extract resource name for better error messages
        resource_name = (
            kwargs.get('RoleName') or 
            kwargs.get('UserName') or 
            kwargs.get('PolicyName') or 
            'unknown'
        )
        
        for attempt in range(self.max_retries):
            try:
                method = getattr(self._client, operation)
                response = method(**kwargs)
                
                # Log eventual consistency delays if they occurred
                elapsed = time.time() - start_time
                if attempt > 0:
                    logger.info(
                        f"IAM operation {operation} succeeded after {attempt + 1} attempts "
                        f"(eventual consistency delay: {elapsed:.2f}s)"
                    )
                
                return response
            
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', 'No message')
                
                # Check if this is a rate limiting error
                if error_code in ['Throttling', 'TooManyRequestsException', 'RequestLimitExceeded']:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            f"Rate limiting detected for {operation} on {resource_name}: "
                            f"{error_code}. Retrying in {delay}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error(
                            f"Rate limiting persisted for {operation} on {resource_name} "
                            f"after {self.max_retries} attempts: {error_code}"
                        )
                        raise
                
                # For non-rate-limiting errors, check if it's an expected propagation error
                if error_code == 'AccessDenied' and 'no identity-based policy allows' in error_message:
                    # This is expected during policy propagation - log at debug level only
                    logger.debug(
                        f"IAM operation {operation} failed on {resource_name}: "
                        f"Error code: {error_code}, Message: {error_message}"
                    )
                else:
                    # Unexpected error - log at error level
                    logger.error(
                        f"IAM operation {operation} failed on {resource_name}: "
                        f"Error code: {error_code}, Message: {error_message}"
                    )
                raise
        
        # Should not reach here, but just in case
        raise Exception(f"Unexpected error in retry logic for {operation}")

    
    def create_role(self, role_name: str, assume_role_policy_document: str, **kwargs) -> Dict[str, Any]:
        """
        Create an IAM role with retry logic.
        
        Args:
            role_name: Name of the role to create
            assume_role_policy_document: Trust policy document as JSON string
            **kwargs: Additional arguments to pass to create_role
        
        Returns:
            Response from create_role API call
        """
        return self._retry_with_backoff(
            'create_role',
            RoleName=role_name,
            AssumeRolePolicyDocument=assume_role_policy_document,
            **kwargs
        )
    
    def delete_role(self, role_name: str) -> Dict[str, Any]:
        """
        Delete an IAM role with retry logic.
        
        Args:
            role_name: Name of the role to delete
        
        Returns:
            Response from delete_role API call
        """
        return self._retry_with_backoff('delete_role', RoleName=role_name)
    
    def put_role_policy(self, role_name: str, policy_name: str, policy_document: str) -> Dict[str, Any]:
        """
        Attach an inline policy to a role with retry logic.
        
        Args:
            role_name: Name of the role
            policy_name: Name of the policy
            policy_document: Policy document as JSON string
        
        Returns:
            Response from put_role_policy API call
        """
        return self._retry_with_backoff(
            'put_role_policy',
            RoleName=role_name,
            PolicyName=policy_name,
            PolicyDocument=policy_document
        )
    
    def delete_role_policy(self, role_name: str, policy_name: str) -> Dict[str, Any]:
        """
        Delete an inline policy from a role with retry logic.
        
        Args:
            role_name: Name of the role
            policy_name: Name of the policy to delete
        
        Returns:
            Response from delete_role_policy API call
        """
        return self._retry_with_backoff(
            'delete_role_policy',
            RoleName=role_name,
            PolicyName=policy_name
        )
    
    def create_user(self, user_name: str, **kwargs) -> Dict[str, Any]:
        """
        Create an IAM user with retry logic.
        
        Args:
            user_name: Name of the user to create
            **kwargs: Additional arguments to pass to create_user
        
        Returns:
            Response from create_user API call
        """
        return self._retry_with_backoff('create_user', UserName=user_name, **kwargs)
    
    def delete_user(self, user_name: str) -> Dict[str, Any]:
        """
        Delete an IAM user with retry logic.
        
        Args:
            user_name: Name of the user to delete
        
        Returns:
            Response from delete_user API call
        """
        return self._retry_with_backoff('delete_user', UserName=user_name)
    
    def put_user_policy(self, user_name: str, policy_name: str, policy_document: str) -> Dict[str, Any]:
        """
        Attach an inline policy to a user with retry logic.
        
        Args:
            user_name: Name of the user
            policy_name: Name of the policy
            policy_document: Policy document as JSON string
        
        Returns:
            Response from put_user_policy API call
        """
        return self._retry_with_backoff(
            'put_user_policy',
            UserName=user_name,
            PolicyName=policy_name,
            PolicyDocument=policy_document
        )
    
    def delete_user_policy(self, user_name: str, policy_name: str) -> Dict[str, Any]:
        """
        Delete an inline policy from a user with retry logic.
        
        Args:
            user_name: Name of the user
            policy_name: Name of the policy to delete
        
        Returns:
            Response from delete_user_policy API call
        """
        return self._retry_with_backoff(
            'delete_user_policy',
            UserName=user_name,
            PolicyName=policy_name
        )
    
    def create_access_key(self, user_name: str) -> Dict[str, Any]:
        """
        Create access keys for a user with retry logic.
        
        Args:
            user_name: Name of the user
        
        Returns:
            Response from create_access_key API call
        """
        return self._retry_with_backoff('create_access_key', UserName=user_name)
    
    def delete_access_key(self, user_name: str, access_key_id: str) -> Dict[str, Any]:
        """
        Delete an access key with retry logic.
        
        Args:
            user_name: Name of the user
            access_key_id: Access key ID to delete
        
        Returns:
            Response from delete_access_key API call
        """
        return self._retry_with_backoff(
            'delete_access_key',
            UserName=user_name,
            AccessKeyId=access_key_id
        )
    
    def list_role_policies(self, role_name: str) -> Dict[str, Any]:
        """
        List inline policies attached to a role with retry logic.
        
        Args:
            role_name: Name of the role
        
        Returns:
            Response from list_role_policies API call
        """
        return self._retry_with_backoff('list_role_policies', RoleName=role_name)
    
    def list_attached_role_policies(self, role_name: str) -> Dict[str, Any]:
        """
        List managed policies attached to a role with retry logic.
        
        Args:
            role_name: Name of the role
        
        Returns:
            Response from list_attached_role_policies API call
        """
        return self._retry_with_backoff('list_attached_role_policies', RoleName=role_name)
    
    def list_user_policies(self, user_name: str) -> Dict[str, Any]:
        """
        List inline policies attached to a user with retry logic.
        
        Args:
            user_name: Name of the user
        
        Returns:
            Response from list_user_policies API call
        """
        return self._retry_with_backoff('list_user_policies', UserName=user_name)
    
    def list_attached_user_policies(self, user_name: str) -> Dict[str, Any]:
        """
        List managed policies attached to a user with retry logic.
        
        Args:
            user_name: Name of the user
        
        Returns:
            Response from list_attached_user_policies API call
        """
        return self._retry_with_backoff('list_attached_user_policies', UserName=user_name)
    
    def detach_role_policy(self, role_name: str, policy_arn: str) -> Dict[str, Any]:
        """
        Detach a managed policy from a role with retry logic.
        
        Args:
            role_name: Name of the role
            policy_arn: ARN of the policy to detach
        
        Returns:
            Response from detach_role_policy API call
        """
        return self._retry_with_backoff(
            'detach_role_policy',
            RoleName=role_name,
            PolicyArn=policy_arn
        )
    
    def detach_user_policy(self, user_name: str, policy_arn: str) -> Dict[str, Any]:
        """
        Detach a managed policy from a user with retry logic.
        
        Args:
            user_name: Name of the user
            policy_arn: ARN of the policy to detach
        
        Returns:
            Response from detach_user_policy API call
        """
        return self._retry_with_backoff(
            'detach_user_policy',
            UserName=user_name,
            PolicyArn=policy_arn
        )



class STSClient:
    """
    Wrapper around boto3 STS client with retry logic.
    
    Implements retry logic for STS operations like GetCallerIdentity and AssumeRole.
    """
    
    def __init__(self, credentials: Credentials, max_retries: int = 5):
        """
        Initialize STS client with credentials.
        
        Args:
            credentials: AWS credentials to use
            max_retries: Maximum number of retry attempts (default: 5)
        """
        self.credentials = credentials
        self.max_retries = max_retries
        self._client = self._create_client()
    
    def _create_client(self):
        """Create boto3 STS client with credentials."""
        session_kwargs = {
            'aws_access_key_id': self.credentials.access_key_id,
            'aws_secret_access_key': self.credentials.secret_access_key,
        }
        if self.credentials.session_token:
            session_kwargs['aws_session_token'] = self.credentials.session_token
        
        session = boto3.Session(**session_kwargs)
        return session.client('sts')
    
    def _retry_with_backoff(self, operation: str, **kwargs) -> Any:
        """
        Execute an operation with exponential backoff retry logic.
        
        Args:
            operation: Name of the STS operation to execute
            **kwargs: Arguments to pass to the operation
        
        Returns:
            The response from the AWS API call
        
        Raises:
            ClientError: If all retries are exhausted
        """
        delay = 1  # Start with 1 second delay
        start_time = time.time()
        
        # Extract resource name for better error messages
        resource_name = kwargs.get('RoleArn', 'unknown')
        
        for attempt in range(self.max_retries):
            try:
                method = getattr(self._client, operation)
                response = method(**kwargs)
                
                # Log eventual consistency delays if they occurred
                elapsed = time.time() - start_time
                if attempt > 0:
                    logger.info(
                        f"STS operation {operation} succeeded after {attempt + 1} attempts "
                        f"(eventual consistency delay: {elapsed:.2f}s)"
                    )
                
                return response
            
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                error_message = e.response.get('Error', {}).get('Message', 'No message')
                
                # Check if this is a rate limiting error or eventual consistency issue
                if error_code in ['Throttling', 'TooManyRequestsException', 'RequestLimitExceeded']:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            f"Rate limiting detected for {operation} on {resource_name}: "
                            f"{error_code}. Retrying in {delay}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error(
                            f"Rate limiting persisted for {operation} on {resource_name} "
                            f"after {self.max_retries} attempts: {error_code}"
                        )
                        raise
                
                # For AssumeRole, retry on certain errors that indicate eventual consistency
                if operation == 'assume_role' and error_code in ['InvalidIdentityToken', 'AccessDenied']:
                    if attempt < self.max_retries - 1:
                        elapsed = time.time() - start_time
                        logger.warning(
                            f"Eventual consistency delay for AssumeRole on {resource_name}: "
                            f"{error_code}. Role not ready yet. Retrying in {delay}s "
                            f"(elapsed: {elapsed:.2f}s, attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                
                # For GetCallerIdentity, retry on InvalidClientTokenId (new credentials not yet valid)
                if operation == 'get_caller_identity' and error_code == 'InvalidClientTokenId':
                    if attempt < self.max_retries - 1:
                        elapsed = time.time() - start_time
                        logger.warning(
                            f"Eventual consistency delay for GetCallerIdentity: "
                            f"{error_code}. New credentials not yet valid. Retrying in {delay}s "
                            f"(elapsed: {elapsed:.2f}s, attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                        continue
                
                # For non-retryable errors, log with full context and raise immediately
                logger.error(
                    f"STS operation {operation} failed on {resource_name}: "
                    f"Error code: {error_code}, Message: {error_message}"
                )
                raise
        
        # Should not reach here, but just in case
        raise Exception(f"Unexpected error in retry logic for {operation}")
    
    def get_caller_identity(self) -> CallerIdentity:
        """
        Get the caller identity using STS GetCallerIdentity.
        
        Returns:
            CallerIdentity object with user_id, account, and arn
        
        Raises:
            ClientError: If the API call fails
        """
        # Use retry logic to handle eventual consistency for new credentials
        response = self._retry_with_backoff('get_caller_identity')
        
        return CallerIdentity(
            user_id=response['UserId'],
            account=response['Account'],
            arn=response['Arn']
        )
    
    def assume_role(
        self,
        role_arn: str,
        role_session_name: str,
        duration_seconds: int = 3600
    ) -> Credentials:
        """
        Assume an IAM role and return temporary credentials.
        
        Args:
            role_arn: ARN of the role to assume
            role_session_name: Name for the assumed role session
            duration_seconds: Duration of the session in seconds (default: 3600)
        
        Returns:
            Credentials object with temporary credentials
        
        Raises:
            ClientError: If the API call fails
        """
        response = self._retry_with_backoff(
            'assume_role',
            RoleArn=role_arn,
            RoleSessionName=role_session_name,
            DurationSeconds=duration_seconds
        )
        
        creds = response['Credentials']
        
        return Credentials(
            access_key_id=creds['AccessKeyId'],
            secret_access_key=creds['SecretAccessKey'],
            session_token=creds['SessionToken'],
            expiration=creds['Expiration']
        )



class S3Client:
    """
    Wrapper around boto3 S3 client for health checks.
    
    Used to perform periodic health checks by calling ListBuckets in us-east-1.
    """
    
    def __init__(self, credentials: Credentials):
        """
        Initialize S3 client with credentials.
        
        Args:
            credentials: AWS credentials to use
        """
        self.credentials = credentials
        self._client = self._create_client()
    
    def _create_client(self):
        """Create boto3 S3 client with credentials for us-east-1."""
        session_kwargs = {
            'aws_access_key_id': self.credentials.access_key_id,
            'aws_secret_access_key': self.credentials.secret_access_key,
        }
        if self.credentials.session_token:
            session_kwargs['aws_session_token'] = self.credentials.session_token
        
        session = boto3.Session(**session_kwargs)
        return session.client('s3', region_name='us-east-1')
    
    def list_buckets(self) -> tuple[bool, Optional[str]]:
        """
        Perform a health check by listing S3 buckets in us-east-1.
        
        This is used to detect if access has been revoked. The operation is
        chosen because it's a simple, low-cost operation that requires valid
        credentials.
        
        Returns:
            Tuple of (success: bool, error_code: Optional[str])
            - (True, None) if the call succeeded
            - (False, error_code) if the call failed, with the AWS error code
        
        Note:
            AccessDenied error indicates credentials are still valid but lack
            S3 permissions, which is expected behavior for detecting revocation.
        """
        try:
            logger.info("S3 health check: ListBuckets in us-east-1")
            self._client.list_buckets()
            logger.info("S3 health check succeeded")
            return (True, None)
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No message')
            
            if error_code == 'AccessDenied':
                logger.warning(f"S3 health check: AccessDenied detected - {error_message}")
            else:
                logger.error(f"S3 health check failed: {error_code} - {error_message}")
            
            return (False, error_code)
        
        except Exception as e:
            logger.error(f"S3 health check failed with unexpected error: {str(e)}")
            return (False, "UnexpectedError")
