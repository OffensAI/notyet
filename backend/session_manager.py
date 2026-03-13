"""Session management for the notyet-web-ui backend."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
import uuid

from backend.models import (
    Session,
    SessionSummary,
    ToolConfig,
    ToolStatus,
    LogEvent,
    EventType,
    AccessStatus,
)
from backend.exceptions import SessionNotFoundError

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages session data persistence and loading.
    
    Attributes:
        sessions_dir: Path to .notyet/sessions/
        sessions: dict[SessionID, Session]
        current_session_id: SessionID | None
    """
    
    def __init__(self, sessions_dir: str = ".notyet/sessions"):
        """
        Initialize the session manager.
        
        Args:
            sessions_dir: Directory path for storing session files
        """
        self.sessions_dir = Path(sessions_dir)
        self.sessions: Dict[str, Session] = {}
        self.current_session_id: str | None = None
        
        # Create sessions directory if it doesn't exist
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        
        # Load existing sessions on initialization
        self.load_sessions()
    
    def create_session(self, config: ToolConfig) -> Session:
        """
        Create new session with unique ID and timestamp.
        
        Args:
            config: Tool configuration for this session
            
        Returns:
            New Session object
        """
        session_id = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc)
        
        session = Session(
            id=session_id,
            timestamp=timestamp,
            config=config,
            status=ToolStatus.STOPPED,
            access_status=AccessStatus.UNKNOWN,
            bucket_list=[],
            logs=[],
            exit_code=None,
            error_message=None,
        )
        
        self.sessions[session_id] = session
        self.current_session_id = session_id
        self._persist_session(session)
        
        logger.info(f"Created new session: {session_id}")
        return session
    
    def append_log_event(self, session_id: str, event: LogEvent) -> None:
        """
        Add log event to session and persist to disk.
        
        Args:
            session_id: Target session ID
            event: Log event to append
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        session.logs.append(event)
        self._persist_session(session)
    
    def update_session_status(
        self, 
        session_id: str, 
        status: ToolStatus,
        exit_code: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Update session status and persist to disk.
        
        Args:
            session_id: Target session ID
            status: New tool status
            exit_code: Optional exit code if process terminated
            error_message: Optional error message if status is ERROR
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        session.status = status
        
        if exit_code is not None:
            session.exit_code = exit_code
        
        if error_message is not None:
            session.error_message = error_message
        
        self._persist_session(session)
        logger.info(f"Updated session {session_id} status to {status}")
    
    def update_access_status(
        self,
        session_id: str,
        access_status: AccessStatus,
        bucket_list: list[str] | None = None,
    ) -> None:
        """
        Update session access status and persist to disk.
        
        Args:
            session_id: Target session ID
            access_status: New access status
            bucket_list: Optional list of S3 buckets if access granted
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        session.access_status = access_status
        
        if bucket_list is not None:
            session.bucket_list = bucket_list
        
        self._persist_session(session)
        logger.info(f"Updated session {session_id} access status to {access_status}")
    
    def load_sessions(self) -> None:
        """
        Load all session files from disk on startup.
        Skip corrupted files with error logging.
        """
        if not self.sessions_dir.exists():
            logger.warning(f"Sessions directory does not exist: {self.sessions_dir}")
            return
        
        session_files = list(self.sessions_dir.glob("session-*.json"))
        logger.info(f"Loading {len(session_files)} session files from {self.sessions_dir}")
        
        for session_file in session_files:
            try:
                with open(session_file, "r") as f:
                    session_data = json.load(f)
                
                # Parse the session data using Pydantic model
                session = Session(**session_data)
                self.sessions[session.id] = session
                logger.debug(f"Loaded session: {session.id}")
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse session file {session_file}: {e}")
            except Exception as e:
                logger.error(f"Failed to load session file {session_file}: {e}")
        
        logger.info(f"Successfully loaded {len(self.sessions)} sessions")
    
    def get_session(self, session_id: str) -> Session:
        """
        Retrieve session by ID.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Session object
            
        Raises:
            SessionNotFoundError: If session doesn't exist
        """
        if session_id not in self.sessions:
            raise SessionNotFoundError(f"Session {session_id} not found")
        
        return self.sessions[session_id]
    
    def list_sessions(self) -> list[SessionSummary]:
        """
        Get list of all sessions with summary info.
        
        Returns:
            List of session summaries (id, timestamp, config, status)
        """
        summaries = []
        
        for session in self.sessions.values():
            # Count defender actions and attacker responses
            defender_count = sum(
                1 for log in session.logs 
                if log.event_type == EventType.DEFENDER_ACTION
            )
            attacker_count = sum(
                1 for log in session.logs 
                if log.event_type == EventType.ATTACKER_RESPONSE
            )
            
            summary = SessionSummary(
                id=session.id,
                timestamp=session.timestamp,
                config=session.config,
                status=session.status,
                log_count=len(session.logs),
                defender_action_count=defender_count,
                attacker_response_count=attacker_count,
            )
            summaries.append(summary)
        
        # Sort by timestamp, most recent first
        summaries.sort(key=lambda s: s.timestamp, reverse=True)
        
        return summaries
    
    def _persist_session(self, session: Session) -> None:
        """
        Write session to disk as JSON file.
        Filename format: session-{id}-{timestamp}.json
        
        Args:
            session: Session object to persist
        """
        try:
            # Format timestamp as YYYYMMDD-HHMMSS
            timestamp_str = session.timestamp.strftime("%Y%m%d-%H%M%S")
            filename = f"session-{session.id}-{timestamp_str}.json"
            filepath = self.sessions_dir / filename
            
            # Convert session to dict using Pydantic's model_dump
            session_dict = session.model_dump(mode='json')
            
            # Write to file with pretty formatting
            with open(filepath, "w") as f:
                json.dump(session_dict, f, indent=2, default=str)
            
            logger.debug(f"Persisted session to {filepath}")
            
        except Exception as e:
            logger.error(f"Failed to persist session {session.id}: {e}")
            raise
