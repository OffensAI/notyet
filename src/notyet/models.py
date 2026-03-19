"""
Data models for the notyet application.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set
import json


@dataclass
class Credentials:
    """
    Represents AWS credentials with support for both persistent and temporary credentials.
    
    Attributes:
        access_key_id: AWS access key ID (AKIA* for persistent, ASIA* for temporary)
        secret_access_key: AWS secret access key
        session_token: Optional session token for temporary credentials
        expiration: Optional expiration time for temporary credentials
    """
    access_key_id: str
    secret_access_key: str
    session_token: Optional[str] = None
    expiration: Optional[datetime] = None
    
    @property
    def is_temporary(self) -> bool:
        """
        Returns True if credentials are temporary (have a session token).
        
        Returns:
            bool: True if session_token is present, False otherwise
        """
        return self.session_token is not None
    
    @property
    def is_persistent(self) -> bool:
        """
        Returns True if credentials are persistent (no session token).
        
        Returns:
            bool: True if session_token is None, False otherwise
        """
        return self.session_token is None


@dataclass
class CallerIdentity:
    """
    Represents the identity information from STS GetCallerIdentity.
    
    Attributes:
        user_id: The unique identifier for the user or role
        account: The AWS account ID
        arn: The Amazon Resource Name (ARN) of the identity
    """
    user_id: str
    account: str
    arn: str
    
    @property
    def identity_type(self) -> str:
        """
        Determines the identity type based on the ARN.

        Returns:
            str: 'user' if ARN contains ':user/', 'role' if ARN contains ':role/'
                 or ':assumed-role/', 'unknown' otherwise
        """
        if ":user/" in self.arn:
            return "user"
        elif ":role/" in self.arn or ":assumed-role/" in self.arn:
            return "role"
        else:
            return "unknown"

    @property
    def identity_name(self) -> str:
        """
        Extracts the user or role name from the ARN.

        For users: arn:aws:iam::123:user/my-user → my-user
        For roles: arn:aws:iam::123:role/my-role → my-role
        For assumed roles: arn:aws:sts::123:assumed-role/my-role/session → my-role

        Returns:
            str: The name portion of the ARN
        """
        if ":assumed-role/" in self.arn:
            # arn:aws:sts::123:assumed-role/role-name/session-name
            parts = self.arn.split("/")
            return parts[-2]  # role name, not session name
        return self.arn.split("/")[-1]


@dataclass
class PolicyDocument:
    """
    Represents an AWS IAM policy document.
    
    Attributes:
        version: The policy language version (default: "2012-10-17")
        statements: List of policy statements
    """
    version: str = "2012-10-17"
    statements: list = None
    
    def __post_init__(self):
        """Initialize statements to empty list if None."""
        if self.statements is None:
            self.statements = []
    
    @classmethod
    def administrator_access(cls) -> "PolicyDocument":
        """
        Creates a policy document with AdministratorAccess permissions.
        
        Returns:
            PolicyDocument: A policy granting full access to all AWS services and resources
        """
        return cls(statements=[{
            "Effect": "Allow",
            "Action": "*",
            "Resource": "*"
        }])
    
    @classmethod
    def same_account_trust(cls, account_id: str) -> "PolicyDocument":
        """
        Creates a trust policy allowing same-account role assumption.
        
        Args:
            account_id: The AWS account ID to trust
            
        Returns:
            PolicyDocument: A trust policy allowing the account root to assume the role
        """
        return cls(statements=[{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "sts:AssumeRole"
        }])
    
    def to_json(self) -> str:
        """
        Converts the policy document to JSON string format.
        
        Returns:
            str: JSON representation of the policy document
        """
        import json
        return json.dumps({
            "Version": self.version,
            "Statement": self.statements
        })


@dataclass
class LogEvent:
    """
    Represents a logged event with structured information.
    
    Attributes:
        timestamp: The time when the event occurred
        event_type: The type of event (e.g., DEFENDER_ACTION, ATTACKER_RESPONSE, INFO, ERROR)
        action: Description of the action that occurred
        details: Additional structured information about the event
    """
    timestamp: datetime
    event_type: str
    action: str
    details: Dict[str, Any]
    
    def to_log_line(self) -> str:
        """
        Formats the event as a log line.
        
        Returns:
            str: Formatted log line in the format "[ISO8601_TIMESTAMP] [EVENT_TYPE] Action: <description>"
        
        **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
        """
        ts = self.timestamp.isoformat()
        return f"[{ts}] [{self.event_type}] {self.action}"
    
    def to_json(self) -> str:
        """
        Formats the event as a JSON string.
        
        Returns:
            str: JSON representation of the event with timestamp, event_type, action, and details
        
        **Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5**
        """
        return json.dumps({
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "action": self.action,
            "details": self.details
        })


@dataclass
class ResourceTracker:
    """
    Tracks IAM resources created by the tool for cleanup purposes.
    
    This class maintains sets of created users, roles, and policies to enable
    cleanup after the tool terminates. The state can be persisted to disk and
    loaded later for cleanup operations.
    
    Attributes:
        users: Set of IAM user names created by the tool
        roles: Set of IAM role names created by the tool
        policies: Dictionary mapping policy names to the resource they're attached to
    
    **Validates: Requirements 16.5, 17.1, 17.2**
    """
    users: Set[str] = field(default_factory=set)
    roles: Set[str] = field(default_factory=set)
    policies: Dict[str, str] = field(default_factory=dict)
    
    def add_user(self, username: str) -> None:
        """
        Adds a user to the tracking set.
        
        Args:
            username: The IAM user name to track
        
        **Validates: Requirements 16.5, 17.1**
        """
        self.users.add(username)
    
    def add_role(self, role_name: str) -> None:
        """
        Adds a role to the tracking set.
        
        Args:
            role_name: The IAM role name to track
        
        **Validates: Requirements 16.5, 17.1**
        """
        self.roles.add(role_name)
    
    def add_policy(self, policy_name: str, attached_to: str) -> None:
        """
        Adds a policy to the tracking dictionary.
        
        Args:
            policy_name: The IAM policy name to track
            attached_to: The resource (user or role name) the policy is attached to
        
        **Validates: Requirements 16.5, 17.1**
        """
        self.policies[policy_name] = attached_to
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the tracker state to a dictionary for serialization.
        
        Returns:
            Dict[str, Any]: Dictionary containing users (list), roles (list), 
                           and policies (dict)
        
        **Validates: Requirements 17.1**
        """
        return {
            "users": list(self.users),
            "roles": list(self.roles),
            "policies": self.policies
        }
    
    def save(self, path: Path) -> None:
        """
        Saves the tracker state to a JSON file for cleanup after process termination.
        
        Args:
            path: Path to the file where state should be saved
        
        Raises:
            IOError: If the file cannot be written
        
        **Validates: Requirements 16.5, 17.1**
        """
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> "ResourceTracker":
        """
        Loads tracker state from a JSON file.
        
        Args:
            path: Path to the file containing saved state
        
        Returns:
            ResourceTracker: A new ResourceTracker instance with loaded state
        
        Raises:
            IOError: If the file cannot be read
            json.JSONDecodeError: If the file contains invalid JSON
        
        **Validates: Requirements 17.1, 17.2**
        """
        with open(path, "r") as f:
            data = json.load(f)
        tracker = cls()
        tracker.users = set(data["users"])
        tracker.roles = set(data["roles"])
        tracker.policies = data["policies"]
        return tracker
