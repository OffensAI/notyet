"""Data models for the notyet-web-ui backend."""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Log event types."""
    DEFENDER_ACTION = "DEFENDER_ACTION"
    ATTACKER_RESPONSE = "ATTACKER_RESPONSE"
    HEALTH_CHECK = "HEALTH_CHECK"
    INFO = "INFO"
    ERROR = "ERROR"
    RAW_OUTPUT = "RAW_OUTPUT"


class ToolStatus(str, Enum):
    """Tool operational status."""
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"


class AccessStatus(str, Enum):
    """AWS access status."""
    HAS_ACCESS = "has_access"
    ACCESS_DENIED = "access_denied"
    UNKNOWN = "unknown"


class ToolConfig(BaseModel):
    """Tool configuration parameters."""
    aws_profile: str = Field(..., description="AWS profile name")
    output_profile: str = Field(..., description="Output profile name")
    exit_on_access_denied: bool = Field(default=False, description="Exit when access is denied")
    debug: bool = Field(default=False, description="Enable debug logging")


class LogEvent(BaseModel):
    """Structured log event."""
    timestamp: datetime
    event_type: EventType
    action: str | None = None
    details: dict | str | None = None
    raw_line: str | None = None


class Session(BaseModel):
    """Tool execution session."""
    id: str = Field(..., description="Unique session identifier")
    timestamp: datetime = Field(..., description="Session creation time")
    config: ToolConfig
    status: ToolStatus = ToolStatus.STOPPED
    access_status: AccessStatus = AccessStatus.UNKNOWN
    bucket_list: list[str] = Field(default_factory=list)
    logs: list[LogEvent] = Field(default_factory=list)
    exit_code: int | None = None
    error_message: str | None = None


class SessionSummary(BaseModel):
    """Session summary for list view."""
    id: str
    timestamp: datetime
    config: ToolConfig
    status: ToolStatus
    log_count: int
    defender_action_count: int
    attacker_response_count: int


class WSMessageType(str, Enum):
    """WebSocket message types."""
    LOG_EVENT = "log_event"
    STATUS_UPDATE = "status_update"
    ACCESS_STATUS_UPDATE = "access_status_update"
    SESSION_STATE = "session_state"
    ERROR = "error"


class WSMessage(BaseModel):
    """WebSocket message wrapper."""
    type: WSMessageType
    payload: dict
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
