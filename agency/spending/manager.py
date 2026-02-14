"""
Pattern Project - Spending & Account Manager
Data access layer for the spending_log and managed_accounts tables.

SpendingManager handles purchase tracking (the financial ledger + digital asset registry).
AccountManager handles dynamically-created service credentials.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.database import get_db
from core.logger import log_info, log_error


# =============================================================================
# SPENDING MANAGER
# =============================================================================

class SpendingManager:
    """
    Manages the spending_log table — purchase tracking, digital asset registry.

    Status lifecycle:
        pending → approved → completed
                           → failed
                → discarded
    """

    def create_entry(
        self,
        merchant: str,
        description: str,
        category: str = "physical",
        card_last_four: str = "",
    ) -> int:
        """
        Create a new spending log entry in 'pending' status.

        Returns:
            The new entry's ID
        """
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO spending_log
                   (merchant, description, category, card_last_four, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (merchant, description, category, card_last_four)
            )
            entry_id = cursor.lastrowid
            log_info(f"Spending log entry created: #{entry_id} ({merchant})", prefix="💳")
            return entry_id

    def update_status(
        self,
        log_id: int,
        status: str,
        **kwargs: Any,
    ) -> bool:
        """
        Update a spending log entry's status and optional fields.

        Accepted kwargs: amount_cents, delegate_report, activation_key,
        product_url, license_info, balance_before_cents, balance_after_cents,
        managed_account_id, notes
        """
        allowed_fields = {
            "amount_cents", "delegate_report", "activation_key",
            "product_url", "license_info", "balance_before_cents",
            "balance_after_cents", "managed_account_id", "notes",
        }

        set_clauses = ["status = ?"]
        params: list = [status]

        for key, value in kwargs.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = ?")
                params.append(value)

        params.append(log_id)

        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE spending_log SET {', '.join(set_clauses)} WHERE id = ?",
                params
            )
            if cursor.rowcount == 0:
                log_error(f"Spending log entry #{log_id} not found")
                return False

            log_info(f"Spending log #{log_id} → {status}", prefix="💳")
            return True

    def get_entry(self, log_id: int) -> Optional[Dict[str, Any]]:
        """Fetch a single spending log entry by ID."""
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM spending_log WHERE id = ?", (log_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    def query_log(
        self,
        status: Optional[str] = None,
        merchant: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Query spending log with optional filters.

        Args:
            status: Filter by status (exact match)
            merchant: Filter by merchant (partial match, case-insensitive)
            limit: Maximum entries to return
        """
        conditions = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if merchant:
            conditions.append("merchant LIKE ?")
            params.append(f"%{merchant}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                f"SELECT * FROM spending_log {where} ORDER BY created_at DESC LIMIT ?",
                params
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_summary(self) -> Dict[str, Any]:
        """
        Get spending summary: total spent, count by status.
        """
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                """SELECT status, COUNT(*) as count,
                          COALESCE(SUM(amount_cents), 0) as total_cents
                   FROM spending_log GROUP BY status"""
            )
            rows = cursor.fetchall()

        summary = {
            "by_status": {},
            "total_completed_cents": 0,
            "total_entries": 0,
        }
        for row in rows:
            row_dict = dict(row)
            summary["by_status"][row_dict["status"]] = {
                "count": row_dict["count"],
                "total_cents": row_dict["total_cents"],
            }
            summary["total_entries"] += row_dict["count"]
            if row_dict["status"] == "completed":
                summary["total_completed_cents"] = row_dict["total_cents"]

        return summary


# =============================================================================
# ACCOUNT MANAGER
# =============================================================================

class AccountManager:
    """
    Manages the managed_accounts table — dynamically-created service credentials.

    These accounts are created by Isaac after a delegate signs up for a service.
    The delegate can later retrieve them via get_credentials(), which falls back
    to this table when a service isn't found in credentials.toml.
    """

    def store_account(
        self,
        service: str,
        login: str,
        password: str,
        pin: Optional[str] = None,
        email_used: Optional[str] = None,
        login_url: Optional[str] = None,
        recovery_info: Optional[str] = None,
        notes: Optional[str] = None,
        spending_log_id: Optional[int] = None,
    ) -> int:
        """
        Store a new managed account. Raises on duplicate service name.

        Returns:
            The new account's ID
        """
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO managed_accounts
                   (service, login, password, pin, email_used,
                    login_url, recovery_info, notes, spending_log_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (service, login, password, pin, email_used,
                 login_url, recovery_info, notes, spending_log_id)
            )
            account_id = cursor.lastrowid
            log_info(f"Managed account stored: '{service}' (#{account_id})", prefix="🔑")
            return account_id

    def get_account(self, service: str) -> Optional[Dict[str, Any]]:
        """Look up a managed account by service name."""
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM managed_accounts WHERE service = ?", (service,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return dict(row)

    def list_accounts(self) -> List[str]:
        """List all managed service names (no secrets exposed)."""
        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT service FROM managed_accounts ORDER BY service"
            )
            return [row[0] for row in cursor.fetchall()]

    def update_account(self, service: str, **kwargs: Any) -> bool:
        """
        Update fields on an existing managed account.

        Accepted kwargs: login, password, pin, email_used,
        login_url, recovery_info, notes
        """
        allowed_fields = {
            "login", "password", "pin", "email_used",
            "login_url", "recovery_info", "notes",
        }

        set_clauses = []
        params: list = []

        for key, value in kwargs.items():
            if key in allowed_fields:
                set_clauses.append(f"{key} = ?")
                params.append(value)

        if not set_clauses:
            return False

        params.append(service)

        db = get_db()
        with db.get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE managed_accounts SET {', '.join(set_clauses)} WHERE service = ?",
                params
            )
            return cursor.rowcount > 0
