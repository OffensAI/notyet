"""FastAPI application for notyet-web-ui."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.models import ToolConfig, ToolStatus
from backend.process_manager import ProcessManager
from backend.session_manager import SessionManager
from backend.websocket_handler import WebSocketHandler
from backend.log_parser import LogParser
from backend.exceptions import (
    ProcessAlreadyRunningError,
    ToolNotFoundError,
    SessionNotFoundError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global component instances
log_parser: LogParser
websocket_handler: WebSocketHandler
session_manager: SessionManager
process_manager: ProcessManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown.
    
    Handles:
    - Component initialization on startup
    - Graceful process termination on shutdown
    """
    global log_parser, websocket_handler, session_manager, process_manager
    
    # Startup: Initialize all components
    logger.info("Initializing application components...")
    
    log_parser = LogParser()
    websocket_handler = WebSocketHandler()
    session_manager = SessionManager()

    process_manager = ProcessManager(
        log_parser=log_parser,
        websocket_handler=websocket_handler,
        session_manager=session_manager,
    )
    
    logger.info("Application startup complete")
    
    yield
    
    # Shutdown: Terminate running processes
    logger.info("Shutting down application...")
    
    if process_manager.current_process is not None:
        logger.info("Terminating running tool process...")
        await process_manager.stop_tool()
    
    logger.info("Application shutdown complete")


# Initialize FastAPI app
app = FastAPI(
    title="notyet-web-ui",
    description="Web interface for the notyet AWS IAM persistence tool",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Static File Serving
# ============================================================================

@app.get("/")
async def serve_index():
    """
    Serve the main HTML page.
    
    Returns:
        FileResponse with index.html
    """
    frontend_path = Path("frontend/index.html")
    
    if not frontend_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    
    return FileResponse(frontend_path)


# Mount static file serving for frontend assets
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory="frontend"), name="static")


# ============================================================================
# Session Management Endpoints
# ============================================================================

@app.get("/api/sessions")
async def list_sessions():
    """
    List all sessions with summary information.
    
    Returns:
        JSON response with list of session summaries
    """
    try:
        sessions = session_manager.list_sessions()
        return {
            "sessions": [session.model_dump(mode='json') for session in sessions]
        }
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    """
    Get full session data by ID.
    
    Args:
        session_id: Session identifier
        
    Returns:
        JSON response with complete session data
        
    Raises:
        HTTPException: 404 if session not found
    """
    try:
        session = session_manager.get_session(session_id)
        return session.model_dump(mode='json')
    except SessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Tool Control Endpoints
# ============================================================================

@app.post("/api/start")
async def start_tool(config: ToolConfig):
    """
    Start the notyet tool with given configuration.
    
    Args:
        config: Tool configuration parameters
        
    Returns:
        JSON response with session_id and status
        
    Raises:
        HTTPException: 409 if tool already running, 500 if start fails
    """
    try:
        session_id = await process_manager.start_tool(config)
        return {
            "session_id": session_id,
            "status": ToolStatus.RUNNING.value
        }
    except ProcessAlreadyRunningError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": str(e),
                "current_session_id": process_manager.current_session_id
            }
        )
    except ToolNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Error starting tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stop")
async def stop_tool():
    """
    Stop the currently running tool.
    
    Returns:
        JSON response with status and session_id
    """
    try:
        session_id = process_manager.current_session_id
        await process_manager.stop_tool()
        return {
            "status": ToolStatus.STOPPED.value,
            "session_id": session_id
        }
    except Exception as e:
        logger.error(f"Error stopping tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/restart")
async def restart_tool():
    """
    Restart the tool with the same configuration.
    
    Returns:
        JSON response with new session_id and status
        
    Raises:
        HTTPException: 400 if no configuration available, 500 if restart fails
    """
    try:
        session_id = await process_manager.restart_tool()
        return {
            "session_id": session_id,
            "status": ToolStatus.RUNNING.value
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error restarting tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# WebSocket Endpoint
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time communication.
    
    Handles:
    - Connection establishment
    - Message broadcasting (log events, status updates)
    - Graceful disconnection
    
    Args:
        websocket: WebSocket connection
    """
    await websocket_handler.connect(websocket)
    
    try:
        # Send current session state if available
        if process_manager.current_session_id:
            try:
                session = session_manager.get_session(process_manager.current_session_id)
                await websocket_handler.send_session_state(websocket, session)
            except SessionNotFoundError:
                logger.warning(f"Current session {process_manager.current_session_id} not found")
        
        # Keep connection alive and handle incoming messages
        while True:
            # Wait for messages from client (ping/pong, etc.)
            data = await websocket.receive_text()
            # Echo back for connection keep-alive
            # Client messages are not processed in current design
            logger.debug(f"Received WebSocket message: {data}")
            
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await websocket_handler.disconnect(websocket)


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/api/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns:
        JSON response with application status
    """
    response = {
        "status": "healthy",
        "tool_status": process_manager.status.value,
        "active_connections": len(websocket_handler.active_connections),
        "sessions_count": len(session_manager.sessions),
    }
    if process_manager.current_config:
        response["current_config"] = process_manager.current_config.model_dump()
    return response


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
