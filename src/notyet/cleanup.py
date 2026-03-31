"""
Cleanup functionality for removing notyet resources from AWS.

This module provides functions to identify, display, and delete IAM resources
created by the notyet tool (identified by the "notyet-" prefix).

"""

import logging
from typing import Dict, List, Tuple
from botocore.exceptions import ClientError

from .aws_clients import IAMClient
from .event_logger import EventLogger
from .models import Credentials


logger = logging.getLogger(__name__)


class CleanupResult:
    """
    Represents the result of a cleanup operation.
    
    Attributes:
        resource_type: Type of resource (user, role, policy)
        resource_name: Name of the resource
        success: Whether the deletion succeeded
        error: Error message if deletion failed
    """
    
    def __init__(self, resource_type: str, resource_name: str, success: bool, error: str = None):
        self.resource_type = resource_type
        self.resource_name = resource_name
        self.success = success
        self.error = error


def list_notyet_resources(iam_client: IAMClient) -> Dict[str, List[str]]:
    """
    Lists all IAM resources with the "notyet-" prefix.
    
    This function scans the AWS account for users, roles, and policies that
    were created by the notyet tool (identified by the "notyet-" prefix).
    
    Args:
        iam_client: IAMClient instance to use for AWS API calls
    
    Returns:
        Dictionary with keys 'users', 'roles', and 'policies', each containing
        a list of resource names with the notyet- prefix
    
    **Validates: Requirements 17.1, 17.2**
    """
    resources = {
        'users': [],
        'roles': [],
        'policies': {}  # policy_name -> attached_to
    }
    
    try:
        # List all users and filter for notyet- prefix
        logger.info("Scanning for notyet users...")
        paginator = iam_client._client.get_paginator('list_users')
        for page in paginator.paginate():
            for user in page['Users']:
                user_name = user['UserName']
                if user_name.startswith('notyet-'):
                    resources['users'].append(user_name)
                    logger.info(f"Found notyet user: {user_name}")
                    
                    # Also check for inline policies on this user
                    try:
                        policy_response = iam_client.list_user_policies(user_name)
                        for policy_name in policy_response.get('PolicyNames', []):
                            if policy_name.startswith('notyet-'):
                                resources['policies'][policy_name] = f"user:{user_name}"
                                logger.info(f"Found notyet policy on user {user_name}: {policy_name}")
                    except ClientError as e:
                        logger.warning(f"Failed to list policies for user {user_name}: {e}")
    
    except ClientError as e:
        logger.error(f"Failed to list users: {e}")
    
    try:
        # List all roles and filter for notyet- prefix
        logger.info("Scanning for notyet roles...")
        paginator = iam_client._client.get_paginator('list_roles')
        for page in paginator.paginate():
            for role in page['Roles']:
                role_name = role['RoleName']
                if role_name.startswith('notyet-'):
                    resources['roles'].append(role_name)
                    logger.info(f"Found notyet role: {role_name}")
                    
                    # Also check for inline policies on this role
                    try:
                        policy_response = iam_client.list_role_policies(role_name)
                        for policy_name in policy_response.get('PolicyNames', []):
                            if policy_name.startswith('notyet-'):
                                resources['policies'][policy_name] = f"role:{role_name}"
                                logger.info(f"Found notyet policy on role {role_name}: {policy_name}")
                    except ClientError as e:
                        logger.warning(f"Failed to list policies for role {role_name}: {e}")
    
    except ClientError as e:
        logger.error(f"Failed to list roles: {e}")
    
    return resources


def display_resources(resources: Dict[str, List[str]], event_logger: EventLogger) -> None:
    """
    Displays the list of resources that will be deleted to the user.
    
    Args:
        resources: Dictionary of resources from list_notyet_resources()
        event_logger: EventLogger instance for output
    
    **Validates: Requirements 17.3**
    """
    event_logger.log_event(
        "INFO",
        "Found the following notyet resources:",
        {}
    )
    
    # Display users
    if resources['users']:
        event_logger.log_event(
            "INFO",
            f"Users ({len(resources['users'])}):",
            {}
        )
        for user in resources['users']:
            event_logger.log_event("INFO", f"  - {user}", {})
    else:
        event_logger.log_event("INFO", "Users: None", {})
    
    # Display roles
    if resources['roles']:
        event_logger.log_event(
            "INFO",
            f"Roles ({len(resources['roles'])}):",
            {}
        )
        for role in resources['roles']:
            event_logger.log_event("INFO", f"  - {role}", {})
    else:
        event_logger.log_event("INFO", "Roles: None", {})
    
    # Display policies
    if resources['policies']:
        event_logger.log_event(
            "INFO",
            f"Policies ({len(resources['policies'])}):",
            {}
        )
        for policy_name, attached_to in resources['policies'].items():
            event_logger.log_event("INFO", f"  - {policy_name} (attached to {attached_to})", {})
    else:
        event_logger.log_event("INFO", "Policies: None", {})
    
    # Display total count
    total = len(resources['users']) + len(resources['roles']) + len(resources['policies'])
    event_logger.log_event(
        "INFO",
        f"Total resources: {total}",
        {}
    )


def confirm_deletion() -> bool:
    """
    Prompts the user for confirmation before deleting resources.
    
    Returns:
        True if user confirms deletion, False otherwise
    
    **Validates: Requirements 17.4, 17.6**
    """
    print("\nWARNING: This will permanently delete all notyet resources from your AWS account.")
    print("This action cannot be undone.")
    
    response = input("\nDo you want to proceed with deletion? (yes/no): ").strip().lower()
    
    return response in ['yes', 'y']


def delete_resources(
    resources: Dict[str, List[str]],
    iam_client: IAMClient,
    event_logger: EventLogger
) -> List[CleanupResult]:
    """
    Deletes all notyet resources from AWS.
    
    This function attempts to delete all identified notyet resources. It handles
    errors gracefully and continues with remaining resources if individual
    deletions fail.
    
    Args:
        resources: Dictionary of resources from list_notyet_resources()
        iam_client: IAMClient instance to use for AWS API calls
        event_logger: EventLogger instance for logging operations
    
    Returns:
        List of CleanupResult objects indicating success/failure for each resource
    
    **Validates: Requirements 17.5, 17.7, 17.8**
    """
    results = []
    
    # Delete policies first (they must be detached before users/roles can be deleted)
    event_logger.log_event("INFO", "Deleting policies...", {})
    for policy_name, attached_to in resources['policies'].items():
        try:
            # Parse attached_to to determine if it's a user or role
            resource_type, resource_name = attached_to.split(':', 1)
            
            if resource_type == 'user':
                logger.info(f"Deleting user policy {policy_name} from {resource_name}")
                iam_client.delete_user_policy(resource_name, policy_name)
            elif resource_type == 'role':
                logger.info(f"Deleting role policy {policy_name} from {resource_name}")
                iam_client.delete_role_policy(resource_name, policy_name)
            
            event_logger.log_event(
                "SUCCESS",
                f"Deleted policy: {policy_name}",
                {"attached_to": attached_to}
            )
            results.append(CleanupResult('policy', policy_name, True))
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No message')
            
            # If resource not found, consider it already deleted
            if error_code in ['NoSuchEntity', 'NotFound']:
                event_logger.log_event(
                    "INFO",
                    f"Policy {policy_name} already deleted",
                    {"attached_to": attached_to}
                )
                results.append(CleanupResult('policy', policy_name, True))
            else:
                event_logger.log_event(
                    "FAILURE",
                    f"Failed to delete policy {policy_name}: {error_code} - {error_message}",
                    {"attached_to": attached_to, "error_code": error_code}
                )
                results.append(CleanupResult('policy', policy_name, False, f"{error_code}: {error_message}"))
        
        except Exception as e:
            event_logger.log_event(
                "FAILURE",
                f"Unexpected error deleting policy {policy_name}: {str(e)}",
                {"attached_to": attached_to}
            )
            results.append(CleanupResult('policy', policy_name, False, str(e)))
    
    # Delete users
    event_logger.log_event("INFO", "Deleting users...", {})
    for user_name in resources['users']:
        try:
            # First, delete any access keys for the user
            logger.info(f"Listing access keys for user {user_name}")
            try:
                access_keys_response = iam_client._client.list_access_keys(UserName=user_name)
                for key in access_keys_response.get('AccessKeyMetadata', []):
                    access_key_id = key['AccessKeyId']
                    logger.info(f"Deleting access key {access_key_id} for user {user_name}")
                    iam_client.delete_access_key(user_name, access_key_id)
            except ClientError as e:
                logger.warning(f"Failed to delete access keys for user {user_name}: {e}")
            
            # Now delete the user
            logger.info(f"Deleting user {user_name}")
            iam_client.delete_user(user_name)
            
            event_logger.log_event(
                "SUCCESS",
                f"Deleted user: {user_name}",
                {}
            )
            results.append(CleanupResult('user', user_name, True))
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No message')
            
            # If resource not found, consider it already deleted
            if error_code in ['NoSuchEntity', 'NotFound']:
                event_logger.log_event(
                    "INFO",
                    f"User {user_name} already deleted",
                    {}
                )
                results.append(CleanupResult('user', user_name, True))
            else:
                event_logger.log_event(
                    "FAILURE",
                    f"Failed to delete user {user_name}: {error_code} - {error_message}",
                    {"error_code": error_code}
                )
                results.append(CleanupResult('user', user_name, False, f"{error_code}: {error_message}"))
        
        except Exception as e:
            event_logger.log_event(
                "FAILURE",
                f"Unexpected error deleting user {user_name}: {str(e)}",
                {}
            )
            results.append(CleanupResult('user', user_name, False, str(e)))
    
    # Delete roles
    event_logger.log_event("INFO", "Deleting roles...", {})
    for role_name in resources['roles']:
        try:
            logger.info(f"Deleting role {role_name}")
            iam_client.delete_role(role_name)
            
            event_logger.log_event(
                "SUCCESS",
                f"Deleted role: {role_name}",
                {}
            )
            results.append(CleanupResult('role', role_name, True))
        
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_message = e.response.get('Error', {}).get('Message', 'No message')
            
            # If resource not found, consider it already deleted
            if error_code in ['NoSuchEntity', 'NotFound']:
                event_logger.log_event(
                    "INFO",
                    f"Role {role_name} already deleted",
                    {}
                )
                results.append(CleanupResult('role', role_name, True))
            else:
                event_logger.log_event(
                    "FAILURE",
                    f"Failed to delete role {role_name}: {error_code} - {error_message}",
                    {"error_code": error_code}
                )
                results.append(CleanupResult('role', role_name, False, f"{error_code}: {error_message}"))
        
        except Exception as e:
            event_logger.log_event(
                "FAILURE",
                f"Unexpected error deleting role {role_name}: {str(e)}",
                {}
            )
            results.append(CleanupResult('role', role_name, False, str(e)))
    
    return results


def report_cleanup_results(results: List[CleanupResult], event_logger: EventLogger) -> None:
    """
    Reports the results of the cleanup operation.
    
    Args:
        results: List of CleanupResult objects from delete_resources()
        event_logger: EventLogger instance for output
    
    **Validates: Requirements 17.8**
    """
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    
    event_logger.log_event(
        "INFO",
        f"\nCleanup complete: {len(successful)} succeeded, {len(failed)} failed",
        {}
    )
    
    if successful:
        event_logger.log_event(
            "SUCCESS",
            f"Successfully deleted {len(successful)} resources:",
            {}
        )
        for result in successful:
            event_logger.log_event(
                "SUCCESS",
                f"  - {result.resource_type}: {result.resource_name}",
                {}
            )
    
    if failed:
        event_logger.log_event(
            "FAILURE",
            f"Failed to delete {len(failed)} resources:",
            {}
        )
        for result in failed:
            event_logger.log_event(
                "FAILURE",
                f"  - {result.resource_type}: {result.resource_name} - {result.error}",
                {}
            )
