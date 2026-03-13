"""
Profile writer for managing AWS CLI configuration files.
"""

import configparser
import logging
from pathlib import Path
from typing import Optional

from .models import Credentials
from .exceptions import ProfileNotFoundError


logger = logging.getLogger(__name__)


class ProfileWriter:
    """
    Manages writing and updating AWS CLI credential profiles.
    
    This class handles updating the AWS credentials file with new credentials
    while preserving other profiles and configuration settings.
    """
    
    def __init__(self):
        """
        Initialize the ProfileWriter with default AWS credential file paths.
        """
        self.credentials_path = Path.home() / ".aws" / "credentials"
        self.config_path = Path.home() / ".aws" / "config"
    
    def write_credentials(
        self,
        profile_name: str,
        credentials: Credentials
    ) -> None:
        """
        Updates AWS credentials file with new credentials.
        
        This method preserves other profiles and their settings while updating
        or creating the specified profile with new credentials.
        
        Args:
            profile_name: The name of the profile to update or create
            credentials: The Credentials object containing the new credentials
        
        Raises:
            No exceptions are raised. Errors are logged and operation continues.
        """
        try:
            # Ensure .aws directory exists
            try:
                self.credentials_path.parent.mkdir(parents=True, exist_ok=True)
            except PermissionError as e:
                logger.error(
                    f"Permission denied creating directory {self.credentials_path.parent}: {e}. "
                    f"Check directory permissions."
                )
                return
            except OSError as e:
                logger.error(
                    f"OS error creating directory {self.credentials_path.parent}: {e}"
                )
                return
            
            # Read existing credentials file
            config = configparser.ConfigParser()
            if self.credentials_path.exists():
                try:
                    config.read(self.credentials_path)
                except configparser.Error as e:
                    logger.error(
                        f"Failed to parse credentials file {self.credentials_path}: {e}. "
                        f"File may be corrupted."
                    )
                    return
            
            # Create or update the profile section
            if not config.has_section(profile_name):
                config.add_section(profile_name)
            
            # Write credentials
            config.set(profile_name, "aws_access_key_id", credentials.access_key_id)
            config.set(profile_name, "aws_secret_access_key", credentials.secret_access_key)
            
            # Write session token if present (for temporary credentials)
            if credentials.session_token:
                config.set(profile_name, "aws_session_token", credentials.session_token)
            elif config.has_option(profile_name, "aws_session_token"):
                # Remove session token if it exists but new credentials don't have one
                config.remove_option(profile_name, "aws_session_token")
            
            # Write back to file
            try:
                with open(self.credentials_path, "w") as f:
                    config.write(f)
            except PermissionError as e:
                logger.error(
                    f"Permission denied writing to {self.credentials_path}: {e}. "
                    f"Check file permissions."
                )
                return
            except OSError as e:
                logger.error(
                    f"OS error writing to {self.credentials_path}: {e}. "
                    f"Check disk space and file system."
                )
                return
        
        except Exception as e:
            logger.error(
                f"Unexpected error writing credentials to profile '{profile_name}': {e}",
                exc_info=True
            )
            # Don't raise - continue operation even if profile write fails
    
    def copy_profile(
        self,
        source_profile: str,
        dest_profile: str
    ) -> None:
        """
        Copies credentials from source profile to destination profile.
        
        This is used for initial profile copying when using --profile flag.
        
        Args:
            source_profile: The name of the profile to copy from
            dest_profile: The name of the profile to copy to
        
        Raises:
            ProfileNotFoundError: If the source profile doesn't exist
        """
        try:
            # Ensure credentials file exists
            if not self.credentials_path.exists():
                raise ProfileNotFoundError(
                    f"Credentials file not found at {self.credentials_path}"
                )
            
            # Read existing credentials file
            config = configparser.ConfigParser()
            config.read(self.credentials_path)
            
            # Check if source profile exists
            if not config.has_section(source_profile):
                raise ProfileNotFoundError(
                    f"Profile '{source_profile}' not found in {self.credentials_path}"
                )
            
            # Create destination profile section
            if not config.has_section(dest_profile):
                config.add_section(dest_profile)
            
            # Copy all options from source to destination
            for option in config.options(source_profile):
                value = config.get(source_profile, option)
                config.set(dest_profile, option, value)
            
            # Write back to file
            with open(self.credentials_path, "w") as f:
                config.write(f)
        
        except ProfileNotFoundError:
            # Re-raise ProfileNotFoundError
            raise
        except Exception as e:
            logger.error(
                f"Failed to copy profile '{source_profile}' to '{dest_profile}': {e}",
                exc_info=True
            )
            # Don't raise - log error but continue
