"""WebSocket connection management and message broadcasting."""

import logging
from typing import Set
from fastapi import WebSocket
from backend.models import (
    LogEvent,
    ToolStatus,
    AccessStatus,
    Session,
    WSMessage,
    WSMessageType,
)

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """
    Manages WebSocket connections and message broadcasting.
    
    Attributes:
        active_connections: Set of active WebSocket connections
    """
    
    def __init__(self):
        """Initialize the WebSocket handler with an empty connection set."""
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket) -> None:
        """
        Accept new WebSocket connection and add to active set.
        
        Args:
            websocket: The WebSocket connection to accept
        """
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")
    
    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove WebSocket from active connections.
        
        Args:
            websocket: The WebSocket connection to remove
        """
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")
    
    async def broadcast_log_event(self, event: LogEvent) -> None:
        """
        Send log event to all connected clients.
        
        Args:
            event: The log event to broadcast
        """
        message = WSMessage(
            type=WSMessageType.LOG_EVENT,
            payload=event.model_dump(mode='json')
        )
        await self._broadcast(message)
    
    async def broadcast_status_change(self, status: ToolStatus, session_id: str | None = None) -> None:
        """
        Send status update to all connected clients.
        
        Args:
            status: The new tool status
            session_id: Optional session ID associated with the status
        """
        payload = {"status": status.value}
        if session_id:
            payload["session_id"] = session_id
        
        message = WSMessage(
            type=WSMessageType.STATUS_UPDATE,
            payload=payload
        )
        await self._broadcast(message)
    
    async def broadcast_access_status(
        self,
        access_status: AccessStatus,
        bucket_list: list[str] | None = None
    ) -> None:
        """
        Send access status update to all connected clients.
        
        Args:
            access_status: The current AWS access status
            bucket_list: Optional list of S3 buckets (when access is available)
        """
        payload = {"access_status": access_status.value}
        if bucket_list is not None:
            payload["bucket_list"] = bucket_list
        
        message = WSMessage(
            type=WSMessageType.ACCESS_STATUS_UPDATE,
            payload=payload
        )
        await self._broadcast(message)
    
    async def send_session_state(self, websocket: WebSocket, session: Session) -> None:
        """
        Send complete session state to specific client (for reconnection).
        
        Args:
            websocket: The WebSocket connection to send to
            session: The session data to send
        """
        message = WSMessage(
            type=WSMessageType.SESSION_STATE,
            payload={"session": session.model_dump(mode='json')}
        )
        await self._send_to_client(websocket, message)
    
    async def broadcast_error(self, error_message: str, details: str | None = None) -> None:
        """
        Send error message to all connected clients.
        
        Args:
            error_message: The error message to broadcast
            details: Optional additional error details
        """
        payload = {"message": error_message}
        if details:
            payload["details"] = details
        
        message = WSMessage(
            type=WSMessageType.ERROR,
            payload=payload
        )
        await self._broadcast(message)
    
    async def _broadcast(self, message: WSMessage) -> None:
        """
        Send message to all connected clients.
        
        Handles connection errors gracefully by removing disconnected clients.
        
        Args:
            message: The message to broadcast
        """
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await self._send_to_client(connection, message)
            except Exception as e:
                logger.error(f"Failed to send message to client: {e}")
                disconnected.add(connection)
        
        # Remove disconnected clients
        for connection in disconnected:
            await self.disconnect(connection)
    
    async def _send_to_client(self, websocket: WebSocket, message: WSMessage) -> None:
        """
        Send message to a specific client.
        
        Args:
            websocket: The WebSocket connection to send to
            message: The message to send
            
        Raises:
            Exception: If sending fails (connection closed, etc.)
        """
        try:
            await websocket.send_json(message.model_dump(mode='json'))
        except Exception as e:
            logger.error(f"Error sending message to client: {e}")
            raise
