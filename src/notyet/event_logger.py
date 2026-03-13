"""
Event logging with console output and file logging.
"""

from pathlib import Path
from typing import Any, Dict
from datetime import datetime, UTC
from colorama import Fore, Style, init as colorama_init

from .models import LogEvent


class EventLogger:
    """
    Handles structured logging with color-coded console output and file logging.
    
    Attributes:
        log_file: Path to the log file
        enable_console: Whether to output to console
        json_output: Whether to output events as JSON (streaming format)
    
    **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5, 10.1, 10.2, 10.3, 10.4, 12.1, 12.2, 12.3, 12.4, 12.5**
    """
    
    def __init__(self, log_file_path: Path, enable_console: bool = True, json_output: bool = False):
        """
        Initialize the EventLogger.
        
        Args:
            log_file_path: Path to the log file where events will be written
            enable_console: Whether to output events to console (default: True)
            json_output: Whether to output events as JSON instead of text (default: False)
        """
        self.log_file = log_file_path
        self.enable_console = enable_console
        self.json_output = json_output
        
        # Initialize colorama for cross-platform color support
        colorama_init(autoreset=True)
        
        # Ensure log file directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def log_defender_action(self, action: str, details: Dict[str, Any]) -> None:
        """
        Logs a detected defender action with red color in console.
        
        Args:
            action: Description of the defender action
            details: Additional structured information about the action
        
        **Validates: Requirements 8.2, 10.3**
        """
        event = LogEvent(
            timestamp=datetime.now(UTC),
            event_type="DEFENDER_ACTION",
            action=f"Detected: {action}",
            details=details
        )
        self._write_event(event, Fore.RED)
    
    def log_attacker_response(self, action: str, details: Dict[str, Any]) -> None:
        """
        Logs the tool's response to a defender action with green color in console.
        
        Args:
            action: Description of the attacker response
            details: Additional structured information about the response
        
        **Validates: Requirements 8.3, 10.3**
        """
        event = LogEvent(
            timestamp=datetime.now(UTC),
            event_type="ATTACKER_RESPONSE",
            action=f"Action: {action}",
            details=details
        )
        self._write_event(event, Fore.GREEN)
    
    def log_event(self, event_type: str, action: str, details: Dict[str, Any]) -> None:
        """
        Logs a general event.
        
        Args:
            event_type: Type of event (e.g., INFO, ERROR, SUCCESS, FAILURE)
            action: Description of the event
            details: Additional structured information about the event
        
        **Validates: Requirements 8.1, 8.4, 8.5**
        """
        event = LogEvent(
            timestamp=datetime.now(UTC),
            event_type=event_type,
            action=action,
            details=details
        )
        
        # Choose color based on event type
        color = Style.RESET_ALL
        if event_type == "SUCCESS":
            color = Fore.GREEN + Style.BRIGHT
        elif event_type == "FAILURE" or event_type == "ERROR":
            color = Fore.RED + Style.BRIGHT
        elif event_type == "TIMING":
            color = Fore.YELLOW
        
        self._write_event(event, color)
    
    def output_json(self, data: Dict[str, Any]) -> None:
        """
        Outputs structured JSON data for consumption by other systems.
        
        Args:
            data: Dictionary to output as JSON
        
        **Validates: Requirements 12.1, 12.2, 12.3, 12.4, 12.5**
        """
        import json
        json_line = json.dumps(data)
        
        # Write to console if enabled
        if self.enable_console:
            print(json_line)
        
        # Write to log file
        try:
            with open(self.log_file, "a") as f:
                f.write(json_line + "\n")
        except Exception as e:
            # Log to stderr if file write fails
            import sys
            print(f"Failed to write to log file: {e}", file=sys.stderr)
    
    def _write_event(self, event: LogEvent, console_color: str) -> None:
        """
        Internal method to write an event to both console and log file.
        
        Args:
            event: The LogEvent to write
            console_color: The colorama color code for console output (ignored in JSON mode)
        """
        if self.json_output:
            # Output as JSON (streaming format - one JSON object per line)
            json_line = event.to_json()
            
            # Write to console if enabled
            if self.enable_console:
                print(json_line)
            
            # Write to log file
            try:
                with open(self.log_file, "a") as f:
                    f.write(json_line + "\n")
            except Exception as e:
                # Log to stderr if file write fails, but continue operation
                import sys
                print(f"Failed to write to log file: {e}", file=sys.stderr)
        else:
            # Output as text log line with color
            log_line = event.to_log_line()
            
            # Write to console with color if enabled
            if self.enable_console:
                print(f"{console_color}{log_line}{Style.RESET_ALL}")
            
            # Write to log file
            try:
                with open(self.log_file, "a") as f:
                    f.write(log_line + "\n")
            except Exception as e:
                # Log to stderr if file write fails, but continue operation
                import sys
                print(f"Failed to write to log file: {e}", file=sys.stderr)
