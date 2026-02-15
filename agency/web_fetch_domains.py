"""
Pattern Project - Web Fetch Domain Manager
Manages allowed/blocked domain lists with config defaults + runtime DB overrides.

Config.py provides default domain lists. The AI can add/remove domains at runtime
via tools. Runtime changes persist in the database state table and merge on top
of config defaults.

Merge logic:
    effective_allowed = config.WEB_FETCH_ALLOWED_DOMAINS + runtime_added_allowed - runtime_removed_allowed
    effective_blocked = config.WEB_FETCH_BLOCKED_DOMAINS + runtime_added_blocked - runtime_removed_blocked
"""

import json
from typing import List, Dict, Any, Optional

from core.database import get_database
from core.logger import log_info, log_warning, log_error
import config


# State keys for persistence
STATE_KEY_ADDED_ALLOWED = "web_fetch_added_allowed_domains"
STATE_KEY_REMOVED_ALLOWED = "web_fetch_removed_allowed_domains"
STATE_KEY_ADDED_BLOCKED = "web_fetch_added_blocked_domains"
STATE_KEY_REMOVED_BLOCKED = "web_fetch_removed_blocked_domains"


class WebFetchDomainManager:
    """
    Manages web fetch domain allow/block lists.

    Config.py provides baseline defaults. Runtime modifications by the AI
    are stored in the database and merged on top of config defaults.
    """

    def __init__(self):
        self._db = None

    def _get_db(self):
        """Lazy-load database."""
        if self._db is None:
            self._db = get_database()
        return self._db

    def _load_list(self, state_key: str) -> List[str]:
        """Load a domain list from database state."""
        try:
            db = self._get_db()
            raw = db.get_state(state_key)
            if raw is None:
                return []
            if isinstance(raw, str):
                return json.loads(raw)
            if isinstance(raw, list):
                return raw
            return []
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_list(self, state_key: str, domains: List[str]) -> None:
        """Save a domain list to database state."""
        db = self._get_db()
        db.set_state(state_key, json.dumps(sorted(set(domains))))

    def get_effective_allowed(self) -> List[str]:
        """
        Get the effective allowed domains list.

        Merges config defaults with runtime additions/removals.

        Returns:
            List of allowed domains (empty means allow all)
        """
        try:
            base = list(config.WEB_FETCH_ALLOWED_DOMAINS)
            added = self._load_list(STATE_KEY_ADDED_ALLOWED)
            removed = self._load_list(STATE_KEY_REMOVED_ALLOWED)

            effective = set(base) | set(added)
            effective -= set(removed)
            return sorted(effective)
        except Exception as e:
            log_error(f"Error computing effective allowed domains: {e}")
            return list(config.WEB_FETCH_ALLOWED_DOMAINS)

    def get_effective_blocked(self) -> List[str]:
        """
        Get the effective blocked domains list.

        Merges config defaults with runtime additions/removals.

        Returns:
            List of blocked domains
        """
        try:
            base = list(config.WEB_FETCH_BLOCKED_DOMAINS)
            added = self._load_list(STATE_KEY_ADDED_BLOCKED)
            removed = self._load_list(STATE_KEY_REMOVED_BLOCKED)

            effective = set(base) | set(added)
            effective -= set(removed)
            return sorted(effective)
        except Exception as e:
            log_error(f"Error computing effective blocked domains: {e}")
            return list(config.WEB_FETCH_BLOCKED_DOMAINS)

    def add_allowed_domain(self, domain: str) -> str:
        """
        Add a domain to the allowed list.

        If the domain was previously removed from allowed, it is restored.
        Also removes it from the blocked list if present.

        Args:
            domain: Domain to allow (e.g., "docs.python.org")

        Returns:
            Status message
        """
        try:
            domain = domain.strip().lower()
            if not domain:
                return "Error: empty domain"

            # Add to allowed
            added = self._load_list(STATE_KEY_ADDED_ALLOWED)
            if domain not in added:
                added.append(domain)
                self._save_list(STATE_KEY_ADDED_ALLOWED, added)

            # Remove from the removed-allowed list (restore if previously removed)
            removed = self._load_list(STATE_KEY_REMOVED_ALLOWED)
            if domain in removed:
                removed.remove(domain)
                self._save_list(STATE_KEY_REMOVED_ALLOWED, removed)

            # Also unblock it if it was blocked
            self._unblock_domain_internal(domain)

            log_info(f"Web fetch domain allowed: {domain}", prefix="🌐")
            return f"Domain '{domain}' added to allowed list."
        except Exception as e:
            log_error(f"Error adding allowed domain: {e}")
            return f"Error: {e}"

    def remove_allowed_domain(self, domain: str) -> str:
        """
        Remove a domain from the allowed list.

        Args:
            domain: Domain to remove from allowed list

        Returns:
            Status message
        """
        try:
            domain = domain.strip().lower()
            if not domain:
                return "Error: empty domain"

            # If it was runtime-added, remove from additions
            added = self._load_list(STATE_KEY_ADDED_ALLOWED)
            if domain in added:
                added.remove(domain)
                self._save_list(STATE_KEY_ADDED_ALLOWED, added)

            # If it's a config default, mark as removed
            if domain in config.WEB_FETCH_ALLOWED_DOMAINS:
                removed = self._load_list(STATE_KEY_REMOVED_ALLOWED)
                if domain not in removed:
                    removed.append(domain)
                    self._save_list(STATE_KEY_REMOVED_ALLOWED, removed)

            log_info(f"Web fetch domain removed from allowed: {domain}", prefix="🌐")
            return f"Domain '{domain}' removed from allowed list."
        except Exception as e:
            log_error(f"Error removing allowed domain: {e}")
            return f"Error: {e}"

    def add_blocked_domain(self, domain: str) -> str:
        """
        Add a domain to the blocked list.

        Also removes it from the allowed list if present.

        Args:
            domain: Domain to block (e.g., "example.com")

        Returns:
            Status message
        """
        try:
            domain = domain.strip().lower()
            if not domain:
                return "Error: empty domain"

            # Add to blocked
            added = self._load_list(STATE_KEY_ADDED_BLOCKED)
            if domain not in added:
                added.append(domain)
                self._save_list(STATE_KEY_ADDED_BLOCKED, added)

            # Remove from the removed-blocked list (restore if previously removed)
            removed = self._load_list(STATE_KEY_REMOVED_BLOCKED)
            if domain in removed:
                removed.remove(domain)
                self._save_list(STATE_KEY_REMOVED_BLOCKED, removed)

            # Also un-allow it if it was allowed
            self._unallow_domain_internal(domain)

            log_info(f"Web fetch domain blocked: {domain}", prefix="🌐")
            return f"Domain '{domain}' added to blocked list."
        except Exception as e:
            log_error(f"Error adding blocked domain: {e}")
            return f"Error: {e}"

    def remove_blocked_domain(self, domain: str) -> str:
        """
        Remove a domain from the blocked list (unblock it).

        Args:
            domain: Domain to unblock

        Returns:
            Status message
        """
        try:
            domain = domain.strip().lower()
            if not domain:
                return "Error: empty domain"

            # If it was runtime-added, remove from additions
            added = self._load_list(STATE_KEY_ADDED_BLOCKED)
            if domain in added:
                added.remove(domain)
                self._save_list(STATE_KEY_ADDED_BLOCKED, added)

            # If it's a config default, mark as removed
            if domain in config.WEB_FETCH_BLOCKED_DOMAINS:
                removed = self._load_list(STATE_KEY_REMOVED_BLOCKED)
                if domain not in removed:
                    removed.append(domain)
                    self._save_list(STATE_KEY_REMOVED_BLOCKED, removed)

            log_info(f"Web fetch domain unblocked: {domain}", prefix="🌐")
            return f"Domain '{domain}' removed from blocked list."
        except Exception as e:
            log_error(f"Error removing blocked domain: {e}")
            return f"Error: {e}"

    def _unblock_domain_internal(self, domain: str) -> None:
        """Remove a domain from blocked lists (internal helper, no logging)."""
        added_blocked = self._load_list(STATE_KEY_ADDED_BLOCKED)
        if domain in added_blocked:
            added_blocked.remove(domain)
            self._save_list(STATE_KEY_ADDED_BLOCKED, added_blocked)

        if domain in config.WEB_FETCH_BLOCKED_DOMAINS:
            removed_blocked = self._load_list(STATE_KEY_REMOVED_BLOCKED)
            if domain not in removed_blocked:
                removed_blocked.append(domain)
                self._save_list(STATE_KEY_REMOVED_BLOCKED, removed_blocked)

    def _unallow_domain_internal(self, domain: str) -> None:
        """Remove a domain from allowed lists (internal helper, no logging)."""
        added_allowed = self._load_list(STATE_KEY_ADDED_ALLOWED)
        if domain in added_allowed:
            added_allowed.remove(domain)
            self._save_list(STATE_KEY_ADDED_ALLOWED, added_allowed)

        if domain in config.WEB_FETCH_ALLOWED_DOMAINS:
            removed_allowed = self._load_list(STATE_KEY_REMOVED_ALLOWED)
            if domain not in removed_allowed:
                removed_allowed.append(domain)
                self._save_list(STATE_KEY_REMOVED_ALLOWED, removed_allowed)

    def get_domain_config(self) -> Dict[str, Any]:
        """
        Get the full domain configuration for the API request.

        Returns:
            Dict with allowed_domains and blocked_domains lists,
            only including non-empty lists.
        """
        result = {}
        allowed = self.get_effective_allowed()
        blocked = self.get_effective_blocked()

        if allowed:
            result["allowed_domains"] = allowed
        if blocked:
            result["blocked_domains"] = blocked

        return result

    def get_status_summary(self) -> str:
        """
        Get a human-readable summary of domain configuration.

        Returns:
            Formatted string showing effective domain lists.
        """
        allowed = self.get_effective_allowed()
        blocked = self.get_effective_blocked()

        parts = []
        if allowed:
            parts.append(f"Allowed domains ({len(allowed)}): {', '.join(allowed)}")
        else:
            parts.append("Allowed domains: all (no restrictions)")

        if blocked:
            parts.append(f"Blocked domains ({len(blocked)}): {', '.join(blocked)}")
        else:
            parts.append("Blocked domains: none")

        return "\n".join(parts)

    def reset_runtime_overrides(self) -> str:
        """
        Clear all runtime domain overrides, reverting to config.py defaults.

        Returns:
            Status message
        """
        try:
            db = self._get_db()
            db.set_state(STATE_KEY_ADDED_ALLOWED, json.dumps([]))
            db.set_state(STATE_KEY_REMOVED_ALLOWED, json.dumps([]))
            db.set_state(STATE_KEY_ADDED_BLOCKED, json.dumps([]))
            db.set_state(STATE_KEY_REMOVED_BLOCKED, json.dumps([]))
            log_info("Web fetch domain overrides reset to config defaults", prefix="🌐")
            return "Domain configuration reset to defaults."
        except Exception as e:
            log_error(f"Error resetting domain overrides: {e}")
            return f"Error: {e}"


# Global instance
_manager: WebFetchDomainManager = None


def get_web_fetch_domain_manager() -> WebFetchDomainManager:
    """Get the global web fetch domain manager instance."""
    global _manager
    if _manager is None:
        _manager = WebFetchDomainManager()
    return _manager
