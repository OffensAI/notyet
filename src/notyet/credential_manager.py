"""
Credential management for the notyet application.
"""

import logging
from configparser import ConfigParser
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, ProfileNotFound

from notyet.models import Credentials, CallerIdentity
from notyet.exceptions import (
    CredentialConflictError,
    InvalidCredentialsError,
    ProfileNotFoundError,
)


logger = logging.getLogger(__name__)


class CredentialManager:
    """
    Manages AWS credential loading, validation, and identity retrieval.
    
    This class handles credential input from CLI flags or AWS profiles,
    validates credential types, and retrieves caller identity information.
    """
    
    def __init__(self):
        """Initialize the credential manager."""
        self._credentials: Optional[Credentials] = None
        self._identity: Optional[CallerIdentity] = None
    
    def load_credentials(
        self,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> Credentials:
        """
        Load credentials from CLI flags or AWS profile.
        
        Args:
            access_key_id: AWS access key ID (optional if using profile)
            secret_access_key: AWS secret access key (optional if using profile)
            session_token: AWS session token (optional)
            profile: AWS profile name (optional if using explicit credentials)
        
        Returns:
            Credentials: Loaded credentials object
        
        Raises:
            ProfileNotFoundError: If specified profile doesn't exist
            InvalidCredentialsError: If credentials cannot be loaded
        """
        # Load from explicit credentials
        if access_key_id and secret_access_key:
            credentials = Credentials(
                access_key_id=access_key_id,
                secret_access_key=secret_access_key,
                session_token=session_token,
            )
            self._credentials = credentials
            return credentials
        
        # Load from profile
        if profile:
            try:
                credentials = self._load_from_profile(profile)
                self._credentials = credentials
                return credentials
            except ProfileNotFound as e:
                raise ProfileNotFoundError(
                    f"AWS profile '{profile}' not found. "
                    f"Check your ~/.aws/credentials file."
                ) from e
        
        raise InvalidCredentialsError(
            "No credentials provided. Use --access-key-id and --secret-access-key "
            "flags, or specify a --profile."
        )
    
    def _load_from_profile(self, profile_name: str) -> Credentials:
        """
        Load credentials from an AWS profile.
        
        Args:
            profile_name: Name of the AWS profile
        
        Returns:
            Credentials: Loaded credentials
        
        Raises:
            ProfileNotFoundError: If profile doesn't exist
            InvalidCredentialsError: If profile is missing required fields
        """
        credentials_path = Path.home() / ".aws" / "credentials"
        
        if not credentials_path.exists():
            raise ProfileNotFoundError(
                f"AWS credentials file not found at {credentials_path}"
            )
        
        config = ConfigParser()
        config.read(credentials_path)
        
        if profile_name not in config:
            available_profiles = list(config.sections())
            raise ProfileNotFoundError(
                f"Profile '{profile_name}' not found. "
                f"Available profiles: {', '.join(available_profiles)}"
            )
        
        profile_section = config[profile_name]
        
        access_key_id = profile_section.get("aws_access_key_id")
        secret_access_key = profile_section.get("aws_secret_access_key")
        session_token = profile_section.get("aws_session_token")
        
        if not access_key_id or not secret_access_key:
            raise InvalidCredentialsError(
                f"Profile '{profile_name}' is missing required credentials. "
                f"Ensure aws_access_key_id and aws_secret_access_key are set."
            )
        
        return Credentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
        )
    
    def validate_credentials(self, credentials: Credentials) -> None:
        """
        Validate credential format and type consistency.
        
        Args:
            credentials: Credentials to validate
        
        Raises:
            CredentialConflictError: If AKIA* access key provided with session token
            InvalidCredentialsError: If access key format is invalid
        """
        access_key = credentials.access_key_id
        has_session_token = credentials.session_token is not None
        
        # Check for credential type conflict
        if has_session_token and access_key.startswith("AKIA"):
            raise CredentialConflictError(
                "Credential type conflict: AKIA* access keys are for persistent "
                "credentials and should not have a session token. "
                "Temporary credentials should use ASIA* access keys."
            )
        
        # Validate access key format when no session token
        if not has_session_token and not access_key.startswith("AKIA"):
            raise InvalidCredentialsError(
                f"Invalid access key format: '{access_key}'. "
                f"Persistent credentials (without session token) must use "
                f"AKIA* access keys."
            )
    
    def get_identity(self, credentials: Credentials) -> CallerIdentity:
        """
        Retrieve caller identity using STS GetCallerIdentity.
        
        Args:
            credentials: Credentials to use for the STS call
        
        Returns:
            CallerIdentity: Identity information
        
        Raises:
            InvalidCredentialsError: If STS call fails
        """
        try:
            # Create STS client with provided credentials
            sts_client = boto3.client(
                "sts",
                aws_access_key_id=credentials.access_key_id,
                aws_secret_access_key=credentials.secret_access_key,
                aws_session_token=credentials.session_token,
            )
            
            response = sts_client.get_caller_identity()
            
            identity = CallerIdentity(
                user_id=response["UserId"],
                account=response["Account"],
                arn=response["Arn"],
            )
            
            self._identity = identity
            return identity
            
        except NoCredentialsError as e:
            raise InvalidCredentialsError(
                "No credentials found. Ensure credentials are properly configured."
            ) from e
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))
            
            raise InvalidCredentialsError(
                f"Failed to validate credentials with STS GetCallerIdentity. "
                f"Error: {error_code} - {error_message}"
            ) from e
        except Exception as e:
            raise InvalidCredentialsError(
                f"Unexpected error during credential validation: {str(e)}"
            ) from e
    
    @property
    def credentials(self) -> Optional[Credentials]:
        """Get the currently loaded credentials."""
        return self._credentials
    
    @property
    def identity(self) -> Optional[CallerIdentity]:
        """Get the current caller identity."""
        return self._identity
