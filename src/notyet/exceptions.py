"""
Custom exceptions for the notyet application.
"""


class NotyetError(Exception):
    """Base exception for all notyet errors."""
    pass


class CredentialError(NotyetError):
    """Base exception for credential-related errors."""
    pass


class CredentialConflictError(CredentialError):
    """Raised when credential types conflict (e.g., AKIA* with session token)."""
    pass


class InvalidCredentialsError(CredentialError):
    """Raised when credentials are invalid or cannot be validated."""
    pass


class ProfileNotFoundError(CredentialError):
    """Raised when a specified AWS profile cannot be found."""
    pass


class AWSAPIError(NotyetError):
    """Base exception for AWS API errors."""
    
    def __init__(self, operation: str, resource: str, error_code: str, message: str):
        """
        Initialize AWS API error with detailed context.
        
        Args:
            operation: The AWS operation that failed (e.g., 'CreateUser')
            resource: The resource being operated on (e.g., 'notyet-user-abc123')
            error_code: AWS error code (e.g., 'AccessDenied', 'Throttling')
            message: Error message from AWS
        """
        self.operation = operation
        self.resource = resource
        self.error_code = error_code
        self.message = message
        super().__init__(
            f"AWS API error during {operation} on {resource}: "
            f"{error_code} - {message}"
        )


class RateLimitError(AWSAPIError):
    """Raised when AWS API rate limiting occurs."""
    pass


class EventualConsistencyError(AWSAPIError):
    """Raised when eventual consistency delays occur."""
    pass


class FileSystemError(NotyetError):
    """Base exception for file system errors."""
    
    def __init__(self, operation: str, path: str, message: str):
        """
        Initialize file system error with context.
        
        Args:
            operation: The operation that failed (e.g., 'write', 'read')
            path: The file path involved
            message: Error message
        """
        self.operation = operation
        self.path = path
        self.message = message
        super().__init__(
            f"File system error during {operation} on {path}: {message}"
        )
