"""Process management for the notyet tool."""

import asyncio
import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from backend.models import ToolConfig, ToolStatus, AccessStatus, EventType
from backend.exceptions import ProcessAlreadyRunningError, ToolNotFoundError
from backend.log_parser import LogParser
from backend.websocket_handler import WebSocketHandler
from backend.session_manager import SessionManager

logger = logging.getLogger(__name__)


class ProcessManager:
    """
    Manages tool process lifecycle and output streaming.
    
    Attributes:
        current_process: subprocess.Popen | None
        current_config: ToolConfig | None
        status: ToolStatus
        log_parser: LogParser
        websocket_handler: WebSocketHandler
        session_manager: SessionManager
        current_session_id: str | None
        _output_thread: threading.Thread | None
    """
    
    def __init__(
        self,
        log_parser: LogParser,
        websocket_handler: WebSocketHandler,
        session_manager: SessionManager,
    ):
        """
        Initialize the process manager.
        
        Args:
            log_parser: LogParser instance for parsing tool output
            websocket_handler: WebSocketHandler for broadcasting events
            session_manager: SessionManager for session persistence
        """
        self.current_process: Optional[subprocess.Popen] = None
        self.current_config: Optional[ToolConfig] = None
        self.status: ToolStatus = ToolStatus.STOPPED
        self.log_parser = log_parser
        self.websocket_handler = websocket_handler
        self.session_manager = session_manager
        self.current_session_id: Optional[str] = None
        self._output_thread: Optional[threading.Thread] = None
        self._stop_streaming = threading.Event()
    
    async def start_tool(self, config: ToolConfig) -> str:
        """
        Start notyet tool with given configuration.
        
        Args:
            config: Tool configuration parameters
            
        Returns:
            Session ID for the new session
            
        Raises:
            ProcessAlreadyRunningError: If tool is already running
            ToolNotFoundError: If notyet tool cannot be located
        """
        if self.current_process is not None and self.current_process.poll() is None:
            raise ProcessAlreadyRunningError("Tool is already running")
        
        # Locate the tool and verify uv command
        tool_path = self._locate_tool()
        
        # Create new session
        session = self.session_manager.create_session(config)
        self.current_session_id = session.id
        self.current_config = config
        
        # Build command arguments
        cmd = [
            "uv", "run", "notyet",
            "--profile", config.aws_profile,
            "--output-profile", config.output_profile,
            "--json-output",
            "--confirm-run",
        ]
        
        if config.exit_on_access_denied:
            cmd.append("--exit-on-access-denied")
        
        if config.debug:
            cmd.append("--debug")
        
        logger.info(f"Starting tool with command: {' '.join(cmd)}")
        
        try:
            # Spawn the process
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,  # Line buffered
                universal_newlines=True,
                cwd=tool_path.parent.parent,  # Run from project root
            )
            
            # Update status
            self.status = ToolStatus.RUNNING
            self.session_manager.update_session_status(session.id, ToolStatus.RUNNING)
            await self.websocket_handler.broadcast_status_change(
                ToolStatus.RUNNING,
                session.id
            )
            
            # Start output streaming in background thread
            self._stop_streaming.clear()
            self._output_thread = threading.Thread(
                target=self._stream_output,
                args=(self.current_process, session.id),
                daemon=True
            )
            self._output_thread.start()
            
            logger.info(f"Tool started successfully with session ID: {session.id}")
            return session.id
            
        except Exception as e:
            logger.error(f"Failed to start tool process: {e}")
            self.status = ToolStatus.ERROR
            self.session_manager.update_session_status(
                session.id,
                ToolStatus.ERROR,
                error_message=str(e)
            )
            await self.websocket_handler.broadcast_error(
                "Failed to start tool process",
                str(e)
            )
            raise
    
    async def stop_tool(self) -> None:
        """
        Gracefully terminate the running tool process.
        Sends SIGTERM and waits up to 5 seconds before SIGKILL.
        """
        if self.current_process is None:
            logger.warning("No process to stop")
            return
        
        if self.current_process.poll() is not None:
            logger.info("Process already terminated")
            return
        
        logger.info("Stopping tool process...")
        
        try:
            # Send SIGTERM for graceful shutdown
            self.current_process.terminate()
            
            # Wait up to 5 seconds for graceful termination
            try:
                self.current_process.wait(timeout=5)
                logger.info("Process terminated gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if still running
                logger.warning("Process did not terminate gracefully, sending SIGKILL")
                self.current_process.kill()
                self.current_process.wait()
                logger.info("Process killed")
            
            # Signal streaming thread to stop
            self._stop_streaming.set()
            
            # Update status
            exit_code = self.current_process.returncode
            self.status = ToolStatus.STOPPED
            
            if self.current_session_id:
                self.session_manager.update_session_status(
                    self.current_session_id,
                    ToolStatus.STOPPED,
                    exit_code=exit_code
                )
                await self.websocket_handler.broadcast_status_change(
                    ToolStatus.STOPPED,
                    self.current_session_id
                )
            
            logger.info(f"Tool stopped with exit code: {exit_code}")
            
        except Exception as e:
            logger.error(f"Error stopping process: {e}")
            raise
        finally:
            self.current_process = None
    
    async def restart_tool(self) -> str:
        """
        Stop current tool and start with same configuration.
        
        Returns:
            Session ID for the new session
            
        Raises:
            ValueError: If no configuration is available (no previous run)
        """
        if self.current_config is None:
            raise ValueError("No configuration available for restart")
        
        logger.info("Restarting tool with same configuration")
        
        # Stop current process if running
        await self.stop_tool()
        
        # Start with same configuration
        return await self.start_tool(self.current_config)
    
    def _stream_output(self, process: subprocess.Popen, session_id: str) -> None:
        """
        Read stdout/stderr line-by-line and forward to log parser.
        Runs in background thread to avoid blocking.
        
        Args:
            process: The subprocess to read from
            session_id: Session ID for logging events
        """
        logger.info("Starting output streaming thread")
        
        def read_stdout():
            """Read stdout line by line."""
            try:
                for line in process.stdout:
                    if self._stop_streaming.is_set():
                        break
                    
                    if line:
                        # Parse the line
                        event = self.log_parser.parse_line(line)
                        
                        # Append to session
                        try:
                            self.session_manager.append_log_event(session_id, event)
                        except Exception as e:
                            logger.error(f"Failed to append log event: {e}")
                        
                        # Broadcast to WebSocket clients
                        try:
                            asyncio.run(self.websocket_handler.broadcast_log_event(event))
                        except Exception as e:
                            logger.error(f"Failed to broadcast log event: {e}")
                        
                        # Check for health check events to update access status
                        if event.event_type == EventType.HEALTH_CHECK:
                            self._handle_health_check(session_id, event)
                        
            except Exception as e:
                logger.error(f"Error reading stdout: {e}")
        
        def read_stderr():
            """Read stderr line by line."""
            try:
                for line in process.stderr:
                    if self._stop_streaming.is_set():
                        break
                    
                    if line:
                        stripped = line.strip()
                        # Only surface ERROR/CRITICAL from stderr as events;
                        # INFO/DEBUG/WARNING and tracebacks are filtered out since
                        # structured JSON events on stdout cover all important actions
                        if ' - ERROR - ' not in stripped and ' - CRITICAL - ' not in stripped:
                            continue

                        event = self.log_parser.parse_line(line)
                        event.event_type = EventType.ERROR
                        
                        # Append to session
                        try:
                            self.session_manager.append_log_event(session_id, event)
                        except Exception as e:
                            logger.error(f"Failed to append error event: {e}")
                        
                        # Broadcast to WebSocket clients
                        try:
                            asyncio.run(self.websocket_handler.broadcast_log_event(event))
                        except Exception as e:
                            logger.error(f"Failed to broadcast error event: {e}")
                        
            except Exception as e:
                logger.error(f"Error reading stderr: {e}")
        
        # Create threads for stdout and stderr
        stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        
        stdout_thread.start()
        stderr_thread.start()
        
        # Wait for process to complete
        exit_code = process.wait()
        
        # Wait for output threads to finish
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        
        logger.info(f"Process exited with code: {exit_code}")
        
        # Update status based on exit code
        if exit_code == 0:
            final_status = ToolStatus.STOPPED
        else:
            final_status = ToolStatus.ERROR
            logger.error(f"Process exited with non-zero code: {exit_code}")
        
        # Update session status
        try:
            self.session_manager.update_session_status(
                session_id,
                final_status,
                exit_code=exit_code,
                error_message=f"Process exited with code {exit_code}" if exit_code != 0 else None
            )
            
            # Broadcast status change
            asyncio.run(self.websocket_handler.broadcast_status_change(
                final_status,
                session_id
            ))
            
        except Exception as e:
            logger.error(f"Failed to update session status after exit: {e}")
        
        self.status = final_status
    
    def _handle_health_check(self, session_id: str, event) -> None:
        """
        Handle health check events to update access status.
        
        Args:
            session_id: Session ID
            event: Health check log event
        """
        try:
            details = event.details
            if isinstance(details, dict):
                status = details.get('status')
                
                if status == 'success':
                    # Access granted
                    bucket_list = details.get('buckets', [])
                    self.session_manager.update_access_status(
                        session_id,
                        AccessStatus.HAS_ACCESS,
                        bucket_list=bucket_list
                    )
                    asyncio.run(self.websocket_handler.broadcast_access_status(
                        AccessStatus.HAS_ACCESS,
                        bucket_list=bucket_list
                    ))
                    
                elif status == 'denied' or 'AccessDenied' in str(details):
                    # Access denied
                    self.session_manager.update_access_status(
                        session_id,
                        AccessStatus.ACCESS_DENIED
                    )
                    asyncio.run(self.websocket_handler.broadcast_access_status(
                        AccessStatus.ACCESS_DENIED
                    ))
                    
        except Exception as e:
            logger.error(f"Error handling health check event: {e}")
    
    def _locate_tool(self) -> Path:
        """
        Find notyet tool in src/notyet/ directory.
        Verify uv command is available.
        
        Returns:
            Path to notyet tool directory
            
        Raises:
            ToolNotFoundError: If tool or uv not found
        """
        # Check if uv command is available
        if shutil.which("uv") is None:
            raise ToolNotFoundError("uv command not found in PATH")
        
        # Look for src/notyet directory
        tool_path = Path("src/notyet")
        
        if not tool_path.exists():
            raise ToolNotFoundError(f"Notyet tool not found at {tool_path}")
        
        if not tool_path.is_dir():
            raise ToolNotFoundError(f"Expected directory at {tool_path}, found file")
        
        # Verify __main__.py exists (entry point for the tool)
        main_file = tool_path / "__main__.py"
        if not main_file.exists():
            raise ToolNotFoundError(f"Tool entry point not found at {main_file}")
        
        logger.info(f"Located notyet tool at {tool_path}")
        return tool_path
