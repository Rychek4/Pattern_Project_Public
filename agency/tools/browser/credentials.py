"""
Pattern Project - Credential Loader for Browser Agent

Read-only access to service credentials stored in a TOML file.
The delegate sub-agent can look up credentials by service name
but cannot modify the file.

Credential file format (data/credentials.toml):

    [reddit]
    username = "my_username"
    password = "my_password"
    login_url = "https://www.reddit.com/login/"

    [twitter]
    username = "my_handle"
    password = "my_password"
    login_url = "https://twitter.com/i/flow/login"

    [gmail]
    username = "me@gmail.com"
    password = "app_password_here"
    login_url = "https://accounts.google.com"
"""

from pathlib import Path
from typing import Any, Dict, Optional

from core.logger import log_info, log_warning


def load_credentials(credentials_path: Path) -> Dict[str, Dict[str, str]]:
    """
    Load all credentials from the TOML file.

    Args:
        credentials_path: Path to the credentials.toml file

    Returns:
        Dict mapping service names to their credential dicts.
        Empty dict if file doesn't exist or can't be parsed.
    """
    if not credentials_path.exists():
        log_warning(f"Credentials file not found: {credentials_path}")
        return {}

    try:
        # Python 3.11+ has tomllib in stdlib
        try:
            import tomllib
        except ImportError:
            # Fallback for Python < 3.11
            try:
                import tomli as tomllib
            except ImportError:
                log_warning("No TOML parser available. Install tomli: pip install tomli")
                return {}

        with open(credentials_path, "rb") as f:
            data = tomllib.load(f)

        # Validate structure: each top-level key should map to a dict
        credentials = {}
        for service_name, service_data in data.items():
            if isinstance(service_data, dict):
                credentials[service_name] = service_data
            else:
                log_warning(f"Skipping invalid credential entry: {service_name}")

        log_info(f"Loaded credentials for {len(credentials)} service(s)", prefix="🔑")
        return credentials

    except Exception as e:
        log_warning(f"Failed to load credentials: {e}")
        return {}


def get_credential(
    credentials_path: Path,
    service: str
) -> Optional[Dict[str, Any]]:
    """
    Look up credentials for a specific service.

    Checks two sources in order:
    1. Static credentials.toml file (hand-configured)
    2. managed_accounts database table (dynamically created by Isaac)

    Args:
        credentials_path: Path to the credentials.toml file
        service: Service name (e.g., "reddit", "twitter", "gmail")

    Returns:
        Dict with service credentials, or None if not found.
        Passwords are included — this is intentional for browser automation.
        The credential data stays inside the delegate's ephemeral context.
    """
    # 1. Check credentials.toml (static, hand-configured)
    all_creds = load_credentials(credentials_path)

    if service in all_creds:
        # Return a copy so the caller can't modify the cached data
        return dict(all_creds[service])

    # 2. Fallback: check managed_accounts database table
    try:
        from agency.spending.manager import AccountManager
        account = AccountManager().get_account(service)
        if account:
            # Map to the same dict format the delegate expects
            cred = {}
            if account.get("login"):
                cred["username"] = account["login"]
            if account.get("password"):
                cred["password"] = account["password"]
            if account.get("pin"):
                cred["pin"] = account["pin"]
            if account.get("login_url"):
                cred["login_url"] = account["login_url"]
            if account.get("email_used"):
                cred["email"] = account["email_used"]
            if account.get("notes"):
                cred["note"] = account["notes"]
            log_info(f"Credential loaded from managed_accounts: {service}", prefix="🔑")
            return cred
    except Exception as e:
        # Don't let DB issues break credential lookup entirely
        log_warning(f"Failed to check managed_accounts for '{service}': {e}")

    log_warning(f"No credentials found for service: {service}")
    return None


def list_services(credentials_path: Path) -> list:
    """
    List all available service names (without revealing credentials).

    Includes both static (credentials.toml) and dynamic (managed_accounts) sources.

    Args:
        credentials_path: Path to the credentials.toml file

    Returns:
        List of service name strings (deduplicated)
    """
    services = set(load_credentials(credentials_path).keys())

    # Also include dynamically-managed accounts
    try:
        from agency.spending.manager import AccountManager
        managed = AccountManager().list_accounts()
        services.update(managed)
    except Exception:
        pass  # Don't let DB issues break service listing

    return sorted(services)
