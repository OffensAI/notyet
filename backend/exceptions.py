"""Custom exception classes for the notyet-web-ui backend."""


class ProcessAlreadyRunningError(Exception):
    """Raised when attempting to start a tool process while one is already running."""
    pass


class ToolNotFoundError(Exception):
    """Raised when the notyet tool cannot be located in the expected directory."""
    pass


class SessionNotFoundError(Exception):
    """Raised when a requested session does not exist."""
    pass
