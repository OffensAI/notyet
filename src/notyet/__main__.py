"""
Main entry point for the notyet CLI application.

This module implements the CLI interface using Click for continuous monitoring mode.

"""

import sys
import logging
import asyncio
from pathlib import Path
from typing import Optional

import click
from colorama import init as colorama_init, Fore, Style

from notyet.credential_manager import CredentialManager
from notyet.persistence_orchestrator import PersistenceOrchestrator
from notyet.cleanup import (
    list_notyet_resources,
    display_resources,
    confirm_deletion,
    delete_resources,
    report_cleanup_results,
)
from notyet.aws_clients import IAMClient
from notyet.event_logger import EventLogger
from notyet.models import Credentials
from notyet.exceptions import (
    CredentialConflictError,
    InvalidCredentialsError,
    ProfileNotFoundError,
)


# Initialize colorama for cross-platform color support
colorama_init(autoreset=True)

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False) -> None:
    """Configure logging for the application."""
    log_dir = Path.home() / ".notyet" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / "notyet.log"
    
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr)
        ]
    )


def display_warnings() -> None:
    """
    Display safety and ethics warnings.
    
    **Validates: Requirements 15.1, 15.2, 15.3**
    """
    print(f"\n{Fore.RED}{Style.BRIGHT}  notyet - AWS IAM Eventual Consistency Persistence{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  By OFFENSAI Inc. | Eduard Agavriloae (saw_your_packet){Style.RESET_ALL}\n")

    print(f"{Fore.YELLOW}  IAM MODIFICATIONS THIS TOOL WILL PERFORM:{Style.RESET_ALL}")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Remove ALL existing inline policies from the current user/role")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Remove ALL managed policies from the current user/role")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Attach a new 'notyet' policy with AdministratorAccess permissions")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Create new IAM users with access keys (when credentials are rotated)")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Create temporary IAM roles (when credentials are rotated)")
    print(f"    {Fore.MAGENTA}-{Style.RESET_ALL} Continuously monitor and restore the 'notyet' policy if removed\n")

    print(f"{Fore.RED}{Style.BRIGHT}  FOR AUTHORIZED SECURITY TESTING ONLY.{Style.RESET_ALL}")
    print(f"{Fore.RED}  Unauthorized use may violate applicable laws.{Style.RESET_ALL}\n")


def require_acknowledgment() -> bool:
    """
    Require explicit acknowledgment of warnings before proceeding.
    
    Returns:
        True if user acknowledges, False otherwise
    
    **Validates: Requirements 15.5**
    """
    print(f"{Fore.YELLOW}By using this tool, you acknowledge that you have read and understood the warnings above.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}You confirm that you have proper authorization and will use this tool responsibly.{Style.RESET_ALL}\n")
    
    response = input(f"{Fore.CYAN}Do you acknowledge and accept these terms? (yes/no): {Style.RESET_ALL}").strip().lower()
    
    return response in ['yes', 'y']


@click.group(invoke_without_command=True)
@click.option(
    '--access-key-id',
    type=str,
    help='AWS access key ID (alternative to --profile)'
)
@click.option(
    '--secret-access-key',
    type=str,
    help='AWS secret access key (required with --access-key-id)'
)
@click.option(
    '--session-token',
    type=str,
    help='AWS session token (optional, for temporary credentials)'
)
@click.option(
    '--profile',
    type=str,
    help='AWS profile name (alternative to explicit credentials)'
)
@click.option(
    '--output-profile',
    type=str,
    help='AWS profile name to write rotated credentials to (required for CLI mode)'
)
@click.option(
    '--exit-on-access-denied',
    is_flag=True,
    default=False,
    help='Exit when access is denied (default: disabled, continues running)'
)
@click.option(
    '--json-output',
    is_flag=True,
    default=False,
    help='Output events as JSON (one JSON object per line) for web interface integration'
)
@click.option(
    '--debug',
    is_flag=True,
    default=False,
    help='Enable debug logging'
)
@click.option(
    '--confirm-run',
    is_flag=True,
    default=False,
    help='Skip interactive confirmation prompt (for automated/web usage)'
)
@click.pass_context
def cli(
    ctx: click.Context,
    access_key_id: Optional[str],
    secret_access_key: Optional[str],
    session_token: Optional[str],
    profile: Optional[str],
    output_profile: Optional[str],
    exit_on_access_denied: bool,
    json_output: bool,
    debug: bool,
    confirm_run: bool
):
    """
    notyet - AWS IAM Eventual Consistency Persistence Tool

    This tool demonstrates AWS IAM eventual consistency vulnerabilities by
    exploiting the ~4 second propagation window where IAM changes don't take
    effect immediately.

    \b
    Example: notyet --profile my-profile --output-profile persistence-profile

    Use 'notyet cleanup' to remove all notyet resources from your AWS account.
    """
    setup_logging(debug)
    
    # If a subcommand is being invoked, don't run the main logic
    if ctx.invoked_subcommand is not None:
        return
    
    # Require output-profile
    if not output_profile:
        click.echo(
            f"{Fore.RED}Error: --output-profile is required for CLI mode.{Style.RESET_ALL}\n"
            f"Specify a profile name where rotated credentials will be written.\n"
            f"Example: notyet --profile my-profile --output-profile persistence-profile",
            err=True
        )
        sys.exit(1)
    
    # Display warnings and require acknowledgment
    display_warnings()

    if not confirm_run and not require_acknowledgment():
        click.echo(f"\n{Fore.YELLOW}Acknowledgment required to proceed. Exiting.{Style.RESET_ALL}")
        sys.exit(0)
    
    click.echo(f"\n{Fore.GREEN}Starting notyet in CLI mode...{Style.RESET_ALL}\n")
    
    try:
        # Load and validate credentials
        cred_manager = CredentialManager()
        
        credentials = cred_manager.load_credentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            profile=profile
        )
        
        cred_manager.validate_credentials(credentials)
        identity = cred_manager.get_identity(credentials)
        
        click.echo(f"{Fore.GREEN}✓ Credentials validated{Style.RESET_ALL}")
        click.echo(f"  Identity: {identity.identity_type} - {identity.identity_name}")
        click.echo(f"  Account: {identity.account}")
        click.echo(f"  Credential Type: {'Temporary (ASIA*)' if credentials.is_temporary else 'Persistent (AKIA*)'}\n")
        
        # If using --profile, copy credentials to output profile initially
        if profile:
            from notyet.profile_writer import ProfileWriter
            writer = ProfileWriter()
            writer.copy_profile(profile, output_profile)
            click.echo(f"{Fore.GREEN}✓ Copied credentials from '{profile}' to '{output_profile}'{Style.RESET_ALL}\n")
        
        # Start persistence orchestrator
        orchestrator = PersistenceOrchestrator(
            credentials=credentials,
            identity=identity,
            output_profile=output_profile,
            exit_on_access_denied=exit_on_access_denied,
            json_output=json_output
        )
        
        # Run orchestrator (blocks until stopped)
        asyncio.run(orchestrator.start())
        
    except CredentialConflictError as e:
        click.echo(f"\n{Fore.RED}Credential Conflict Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except InvalidCredentialsError as e:
        click.echo(f"\n{Fore.RED}Invalid Credentials Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except ProfileNotFoundError as e:
        click.echo(f"\n{Fore.RED}Profile Not Found Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except KeyboardInterrupt:
        click.echo(f"\n{Fore.YELLOW}Interrupted by user. Shutting down gracefully...{Style.RESET_ALL}")
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        click.echo(f"\n{Fore.RED}Unexpected Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    '--access-key-id',
    type=str,
    help='AWS access key ID (alternative to --profile)'
)
@click.option(
    '--secret-access-key',
    type=str,
    help='AWS secret access key (required with --access-key-id)'
)
@click.option(
    '--session-token',
    type=str,
    help='AWS session token (optional, for temporary credentials)'
)
@click.option(
    '--profile',
    type=str,
    help='AWS profile name (alternative to explicit credentials)'
)
def cleanup(
    access_key_id: Optional[str],
    secret_access_key: Optional[str],
    session_token: Optional[str],
    profile: Optional[str]
):
    """
    Clean up all notyet resources from your AWS account.
    
    This command identifies and deletes all IAM resources created by notyet
    (users, roles, and policies with the "notyet-" prefix).
    
    Example: notyet cleanup --profile my-profile
    
    **Validates: Requirements 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8**
    """
    click.echo(f"\n{Fore.CYAN}{Style.BRIGHT}notyet Cleanup Utility{Style.RESET_ALL}\n")
    
    try:
        # Load credentials
        cred_manager = CredentialManager()
        
        credentials = cred_manager.load_credentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            profile=profile
        )
        
        cred_manager.validate_credentials(credentials)
        identity = cred_manager.get_identity(credentials)
        
        click.echo(f"{Fore.GREEN}✓ Credentials validated{Style.RESET_ALL}")
        click.echo(f"  Account: {identity.account}\n")
        
        # Create IAM client and event logger
        iam_client = IAMClient(credentials)
        log_dir = Path.home() / ".notyet" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "cleanup.log"
        event_logger = EventLogger(log_file, enable_console=True)
        
        # List resources
        click.echo(f"{Fore.CYAN}Scanning for notyet resources...{Style.RESET_ALL}\n")
        resources = list_notyet_resources(iam_client)
        
        # Display resources
        display_resources(resources, event_logger)
        
        # Check if any resources found
        total = len(resources['users']) + len(resources['roles']) + len(resources['policies'])
        if total == 0:
            click.echo(f"\n{Fore.GREEN}No notyet resources found. Nothing to clean up.{Style.RESET_ALL}")
            return
        
        # Confirm deletion
        if not confirm_deletion():
            click.echo(f"\n{Fore.YELLOW}Cleanup cancelled by user.{Style.RESET_ALL}")
            return
        
        # Delete resources
        click.echo(f"\n{Fore.CYAN}Deleting resources...{Style.RESET_ALL}\n")
        results = delete_resources(resources, iam_client, event_logger)
        
        # Report results
        report_cleanup_results(results, event_logger)
        
        click.echo(f"\n{Fore.GREEN}Cleanup complete!{Style.RESET_ALL}")
        
    except CredentialConflictError as e:
        click.echo(f"\n{Fore.RED}Credential Conflict Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except InvalidCredentialsError as e:
        click.echo(f"\n{Fore.RED}Invalid Credentials Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except ProfileNotFoundError as e:
        click.echo(f"\n{Fore.RED}Profile Not Found Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)
    
    except Exception as e:
        logger.error(f"Unexpected error during cleanup: {str(e)}", exc_info=True)
        click.echo(f"\n{Fore.RED}Unexpected Error:{Style.RESET_ALL} {str(e)}", err=True)
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
