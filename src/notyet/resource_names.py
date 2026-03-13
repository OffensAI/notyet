"""Resource name generation utilities for IAM resources.

This module provides functions to generate unique resource names with the
"notyet-" prefix and random alphanumeric suffixes.
"""

import random
import string


def generate_random_suffix() -> str:
    """Generate a random 6-character alphanumeric suffix.
    
    Returns:
        str: A 6-character string containing only lowercase letters and digits.
    
    Example:
        >>> suffix = generate_random_suffix()
        >>> len(suffix)
        6
        >>> all(c in string.ascii_lowercase + string.digits for c in suffix)
        True
    """
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(6))


def generate_role_name() -> str:
    """Generate a unique role name with the notyet- prefix.
    
    Returns:
        str: A role name in the format "notyet-role-{suffix}".
    
    Example:
        >>> name = generate_role_name()
        >>> name.startswith("notyet-role-")
        True
        >>> len(name)
        18
    """
    suffix = generate_random_suffix()
    return f"notyet-role-{suffix}"


def generate_user_name() -> str:
    """Generate a unique user name with the notyet- prefix.
    
    Returns:
        str: A user name in the format "notyet-user-{suffix}".
    
    Example:
        >>> name = generate_user_name()
        >>> name.startswith("notyet-user-")
        True
        >>> len(name)
        18
    """
    suffix = generate_random_suffix()
    return f"notyet-user-{suffix}"


def generate_policy_name() -> str:
    """Generate a unique policy name with the notyet- prefix.
    
    Returns:
        str: A policy name in the format "notyet-policy-{suffix}".
    
    Example:
        >>> name = generate_policy_name()
        >>> name.startswith("notyet-policy-")
        True
        >>> len(name)
        20
    """
    suffix = generate_random_suffix()
    return f"notyet-policy-{suffix}"
