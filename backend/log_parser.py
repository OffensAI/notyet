"""Log parser for notyet tool JSON output."""

import json
from datetime import datetime
from backend.models import LogEvent, EventType


class LogParser:
    """
    Parses and structures log output from notyet tool.
    
    The parser handles JSON-formatted log lines from the notyet tool and
    gracefully falls back to RAW_OUTPUT for non-JSON content.
    """
    
    def parse_line(self, line: str) -> LogEvent:
        """
        Parse a single line of tool output.
        
        Args:
            line: Raw output line from tool
            
        Returns:
            Structured LogEvent object
            
        Notes:
            - Attempts JSON parsing first
            - Falls back to RAW_OUTPUT event type for non-JSON
            - Extracts event_type, timestamp, action, details from JSON
        """
        line = line.strip()
        
        # Attempt to parse as JSON
        try:
            data = json.loads(line)
            
            # Extract timestamp
            timestamp_str = data.get('timestamp')
            if timestamp_str:
                # Parse ISO 8601 timestamp
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                # Use current time if no timestamp provided
                timestamp = datetime.utcnow()
            
            # Extract event_type and classify
            event_type_str = data.get('event_type', 'INFO')
            try:
                event_type = EventType(event_type_str)
            except ValueError:
                # Unknown event type, default to INFO
                event_type = EventType.INFO
            
            # Extract action and details
            action = data.get('action')
            details = data.get('details')
            
            return LogEvent(
                timestamp=timestamp,
                event_type=event_type,
                action=action,
                details=details,
                raw_line=line
            )
            
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # JSON parsing failed, create RAW_OUTPUT event
            return LogEvent(
                timestamp=datetime.utcnow(),
                event_type=EventType.RAW_OUTPUT,
                action=None,
                details=None,
                raw_line=line
            )
    
    def classify_event(self, event: LogEvent) -> EventType:
        """
        Determine event type from parsed data.
        
        Args:
            event: Parsed LogEvent object
            
        Returns:
            One of: DEFENDER_ACTION, ATTACKER_RESPONSE, 
                   HEALTH_CHECK, INFO, ERROR, RAW_OUTPUT
        """
        return event.event_type
