# Prepaid Visa Gift Card Tool — Implementation Plan

## Overview

Add a prepaid Visa gift card spending system to Pattern Project. Isaac gets tools to check balance, initiate purchases (two-phase delegation), track spending, and manage dynamically-created accounts. The delegate gets enhanced credential lookup that includes dynamically-stored accounts.

---

## Step 1: Configuration & Credentials

### 1a. Add card + address details to `credentials.toml`

Add a `[visa_prepaid]` section to `data/credentials.toml` (the existing delegate credential file). This keeps card details accessible to the delegate via the existing `get_credentials("visa_prepaid")` tool with zero code changes on the delegate side.

```toml
[visa_prepaid]
card_number = "4111..."
exp = "12/27"
cvv = "123"
name_on_card = "GIFT CARD"
balance_check_url = "https://..."
billing_address = "123 Main St"
billing_city = "Anytown"
billing_state = "CA"
billing_zip = "90210"
shipping_address = "123 Main St"
shipping_city = "Anytown"
shipping_state = "CA"
shipping_zip = "90210"
```

### 1b. Add feature flag + config to `config.py`

```python
# PREPAID CARD CONFIGURATION
PREPAID_CARD_ENABLED = os.getenv("PREPAID_CARD_ENABLED", "false").lower() == "true"
PREPAID_CARD_SERVICE = "visa_prepaid"  # credential service name in credentials.toml
```

Add `PREPAID_CARD_ENABLED=true` to `.env.example`.

**Files modified:** `config.py`, `data/credentials.toml` (or `.example`), `.env.example`

---

## Step 2: Database — Two New Tables + Migration v21

### 2a. `spending_log` table

Tracks all purchase attempts and completed transactions. Doubles as a digital asset registry for activation keys, product URLs, etc.

```sql
CREATE TABLE IF NOT EXISTS spending_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    merchant TEXT NOT NULL,
    description TEXT NOT NULL,
    amount_cents INTEGER,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'completed', 'discarded', 'failed')),
    category TEXT DEFAULT 'physical'
        CHECK (category IN ('physical', 'digital', 'subscription', 'account')),

    -- Phase 1 delegate report (JSON blob: checkout summary)
    delegate_report TEXT,

    -- Digital product fields (nullable, populated after completion)
    activation_key TEXT,
    product_url TEXT,
    license_info TEXT,

    -- Financial snapshot
    card_last_four TEXT,
    balance_before_cents INTEGER,
    balance_after_cents INTEGER,

    -- Link to account created by this purchase (nullable)
    managed_account_id INTEGER REFERENCES managed_accounts(id),

    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_spending_log_status ON spending_log(status);
CREATE INDEX IF NOT EXISTS idx_spending_log_created ON spending_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_spending_log_merchant ON spending_log(merchant);
```

### 2b. `managed_accounts` table

Stores credentials for accounts created by the delegate. Isaac writes here; the delegate reads via enhanced `get_credentials`.

```sql
CREATE TABLE IF NOT EXISTS managed_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    service TEXT NOT NULL UNIQUE,
    login TEXT,
    password TEXT,
    pin TEXT,
    email_used TEXT,
    login_url TEXT,
    recovery_info TEXT,
    notes TEXT,
    spending_log_id INTEGER REFERENCES spending_log(id)
);

CREATE INDEX IF NOT EXISTS idx_managed_accounts_service ON managed_accounts(service);
```

### 2c. Migration v20 → v21

Follow the existing migration pattern in `core/database.py`:
- Bump `SCHEMA_VERSION` from 20 to 21
- Add both CREATE TABLE statements to `SCHEMA_SQL`
- Add `MIGRATION_V21_SQL` with the same CREATE TABLE statements
- Add migration logic in `_apply_migrations()`

**Files modified:** `core/database.py`

---

## Step 3: Spending Manager Module

Create `agency/spending/manager.py` — a data-access layer for the two new tables. Keeps SQL out of the tool executor.

### SpendingManager class

Methods:
- `create_entry(merchant, description, category) -> int` — creates a `pending` spending_log row, returns ID
- `update_status(log_id, status, **kwargs)` — updates status + optional fields (amount, delegate_report, activation_key, etc.)
- `get_entry(log_id) -> dict` — fetch a single entry
- `query_log(status=None, merchant=None, limit=20) -> list[dict]` — flexible query with optional filters
- `get_summary() -> dict` — total spent, count by status, remaining balance estimate

### AccountManager class

Methods:
- `store_account(service, login, password, pin=None, ...) -> int` — INSERT with UNIQUE on service
- `get_account(service) -> dict | None` — lookup by service name
- `list_accounts() -> list[str]` — list all service names (no secrets)
- `update_account(service, **kwargs)` — update fields for existing account

**Files created:** `agency/spending/__init__.py`, `agency/spending/manager.py`

---

## Step 4: Enhance Delegate Credential Lookup

Modify `agency/tools/browser/credentials.py` — the `get_credential()` function. Add a fallback: if a service isn't found in `credentials.toml`, check the `managed_accounts` database table.

```python
def get_credential(credentials_path, service):
    # 1. Check credentials.toml (existing behavior)
    cred = _lookup_toml(credentials_path, service)
    if cred:
        return cred

    # 2. Fallback: check managed_accounts table
    from agency.spending.manager import AccountManager
    account = AccountManager().get_account(service)
    if account:
        # Map to same dict format the delegate expects
        return {
            "username": account.get("login", ""),
            "password": account.get("password", ""),
            "pin": account.get("pin", ""),
            "login_url": account.get("login_url", ""),
        }

    return None
```

This is the only change to the delegate system. The delegate's `get_credentials("spotify")` now seamlessly checks both static TOML and dynamic DB credentials.

**Files modified:** `agency/tools/browser/credentials.py`

---

## Step 5: Isaac's New Tool Definitions

Add four new tool definitions to `agency/tools/definitions.py`:

### 5a. `check_card_balance`

Isaac delegates to the browser to check the balance on the card issuer's website. Returns balance as text.

```python
CHECK_CARD_BALANCE_TOOL = {
    "name": "check_card_balance",
    "description": """Check the current balance on the prepaid Visa gift card.

Delegates to the browser agent to visit the card issuer's balance-check page,
enter card details, and read back the available balance.

Use when:
- Before initiating a purchase to confirm sufficient funds
- After a completed purchase to verify the charge went through
- When the user asks about remaining card balance

Returns the current available balance and any pending charges.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
```

### 5b. `initiate_purchase`

Isaac tells the delegate to browse to a merchant, add items to cart, and proceed to checkout — but NOT submit payment. The delegate returns checkout details. Isaac reviews and decides.

```python
INITIATE_PURCHASE_TOOL = {
    "name": "initiate_purchase",
    "description": """Begin a purchase using the prepaid Visa gift card. TWO-PHASE FLOW.

PHASE 1 (this call): Delegates to the browser agent to:
1. Navigate to the merchant
2. Add items to cart
3. Proceed to checkout
4. Enter shipping/billing info if needed
5. Report back the order summary WITHOUT submitting payment

You will receive the checkout details (items, total, fees, taxes).
Review them and decide whether to approve or discard.

PHASE 2 (separate call): If approved, call complete_purchase with the
spending_log_id to delegate payment submission.

If discarded, call discard_purchase with the spending_log_id.

Be specific in your instructions — include exact URLs, item names,
quantities, and any options to select.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "merchant_url": {
                "type": "string",
                "description": "URL of the merchant or product page"
            },
            "instructions": {
                "type": "string",
                "description": "Detailed step-by-step instructions for the browser agent (what to add to cart, quantities, options, etc.)"
            },
            "category": {
                "type": "string",
                "enum": ["physical", "digital", "subscription", "account"],
                "description": "Type of purchase for tracking purposes"
            }
        },
        "required": ["merchant_url", "instructions"]
    }
}
```

### 5c. `complete_purchase`

After reviewing Phase 1 details, Isaac approves and triggers Phase 2.

```python
COMPLETE_PURCHASE_TOOL = {
    "name": "complete_purchase",
    "description": """Complete a previously initiated purchase (Phase 2).

Call this ONLY after reviewing the checkout details from initiate_purchase
and deciding to proceed.

The browser agent will:
1. Return to the checkout page (session cookies persist)
2. Enter payment card details
3. Submit the order
4. Report confirmation details

After completion, update the spending log with any activation keys,
order numbers, or account credentials received.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "spending_log_id": {
                "type": "integer",
                "description": "The spending log entry ID from initiate_purchase"
            },
            "payment_instructions": {
                "type": "string",
                "description": "Optional additional instructions for the payment step (e.g., 'select PayPal' or 'use guest checkout')"
            }
        },
        "required": ["spending_log_id"]
    }
}
```

### 5d. `discard_purchase`

Isaac decides not to proceed after reviewing checkout details.

```python
DISCARD_PURCHASE_TOOL = {
    "name": "discard_purchase",
    "description": """Discard a previously initiated purchase without completing it.

Use when the checkout details from initiate_purchase are unsatisfactory
(wrong price, unexpected fees, wrong item, etc.).

Marks the spending log entry as 'discarded'. No payment is submitted.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "spending_log_id": {
                "type": "integer",
                "description": "The spending log entry ID to discard"
            },
            "reason": {
                "type": "string",
                "description": "Why the purchase was discarded (logged for reference)"
            }
        },
        "required": ["spending_log_id"]
    }
}
```

### 5e. `query_spending`

Unified spending log query — financial ledger + digital asset lookup in one.

```python
QUERY_SPENDING_TOOL = {
    "name": "query_spending",
    "description": """Query the spending log for purchase history and digital product details.

Dual purpose:
1. Financial tracking: View all purchases, filter by status/merchant, see totals
2. Digital asset lookup: Retrieve activation keys, product URLs, license info

Use when:
- Checking purchase history ("What have I bought?")
- Looking up an activation key or login for a previous purchase
- Reviewing spending totals
- Checking status of a pending purchase""",
    "input_schema": {
        "type": "object",
        "properties": {
            "spending_log_id": {
                "type": "integer",
                "description": "Get a specific entry by ID (overrides other filters)"
            },
            "status": {
                "type": "string",
                "enum": ["pending", "approved", "completed", "discarded", "failed"],
                "description": "Filter by status"
            },
            "merchant": {
                "type": "string",
                "description": "Filter by merchant name (partial match)"
            },
            "include_keys": {
                "type": "boolean",
                "description": "Include activation keys and product URLs in results (default: true)"
            }
        },
        "required": []
    }
}
```

### 5f. `store_managed_account`

Isaac stores credentials for accounts the delegate created.

```python
STORE_MANAGED_ACCOUNT_TOOL = {
    "name": "store_managed_account",
    "description": """Store credentials for an account created during a delegated purchase.

When a purchase involves creating a new account (e.g., signing up for a service),
the delegate reports the credentials back. Use this tool to store them securely
so the delegate can retrieve them later via get_credentials.

The stored credentials become available to future delegate tasks automatically —
the delegate can call get_credentials('service_name') just like static credentials.

Use when:
- A delegate reports back newly created account credentials
- You need to record login details for a service purchased with the card""",
    "input_schema": {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service name identifier (e.g., 'spotify', 'netflix'). Used by delegate in get_credentials()."
            },
            "login": {
                "type": "string",
                "description": "Username or email for the account"
            },
            "password": {
                "type": "string",
                "description": "Password for the account"
            },
            "pin": {
                "type": "string",
                "description": "Optional PIN if the service uses one"
            },
            "login_url": {
                "type": "string",
                "description": "Login page URL for the service"
            },
            "email_used": {
                "type": "string",
                "description": "Email address used during registration"
            },
            "spending_log_id": {
                "type": "integer",
                "description": "Link to the spending log entry that created this account"
            }
        },
        "required": ["service", "login", "password"]
    }
}
```

### Tool Registration

In `get_tool_definitions()`, add a new conditional block:

```python
if getattr(config, 'PREPAID_CARD_ENABLED', False):
    tools.append(CHECK_CARD_BALANCE_TOOL)
    tools.append(INITIATE_PURCHASE_TOOL)
    tools.append(COMPLETE_PURCHASE_TOOL)
    tools.append(DISCARD_PURCHASE_TOOL)
    tools.append(QUERY_SPENDING_TOOL)
    tools.append(STORE_MANAGED_ACCOUNT_TOOL)
```

**Files modified:** `agency/tools/definitions.py`

---

## Step 6: Tool Executor Handlers

Add handler methods to `agency/tools/executor.py`:

### 6a. `_exec_check_card_balance`

1. Load `visa_prepaid` credentials from `credentials.toml`
2. Build a delegation task: "Navigate to {balance_check_url}, enter card number {card_number} and CVV {cvv}, read the displayed balance"
3. Call `run_delegated_task()` (reuses existing delegation infrastructure)
4. Return the delegate's result text

### 6b. `_exec_initiate_purchase`

1. Create a `pending` spending_log entry via `SpendingManager.create_entry()`
2. Build a delegation task from `instructions` — explicitly tell the delegate to navigate, add to cart, proceed to checkout, enter shipping/billing from credentials, and **report checkout summary without submitting payment**
3. Call `run_delegated_task()`
4. Save the delegate's report to `spending_log.delegate_report`
5. Update status to `approved` (awaiting Isaac's decision)
6. Return the spending_log_id + checkout details to Isaac

### 6c. `_exec_complete_purchase`

1. Fetch the spending_log entry; verify status is `approved`
2. Build a delegation task: "Return to checkout, enter card details {number, exp, cvv, name, billing zip}, submit order, report confirmation"
3. Call `run_delegated_task()` (browser session cookies persist from Phase 1)
4. Update spending_log: status → `completed`, parse amount if possible
5. Return confirmation details

### 6d. `_exec_discard_purchase`

1. Fetch spending_log entry; verify status is `approved` or `pending`
2. Update status → `discarded`, save reason in notes
3. Return confirmation

### 6e. `_exec_query_spending`

1. If `spending_log_id` provided: fetch that single entry
2. Otherwise: query with filters (status, merchant)
3. Format results including activation keys / product URLs if `include_keys` is true
4. Return formatted text

### 6f. `_exec_store_managed_account`

1. Call `AccountManager.store_account(service, login, password, ...)`
2. If `spending_log_id` provided, link the account to that spending entry
3. Return confirmation

### Handler Registration

Add all six to the `_handlers` dict:

```python
# Prepaid card / spending tools
"check_card_balance": self._exec_check_card_balance,
"initiate_purchase": self._exec_initiate_purchase,
"complete_purchase": self._exec_complete_purchase,
"discard_purchase": self._exec_discard_purchase,
"query_spending": self._exec_query_spending,
"store_managed_account": self._exec_store_managed_account,
```

**Files modified:** `agency/tools/executor.py`

---

## Step 7: Testing

- Verify database migration v21 applies cleanly on existing databases
- Verify `get_credentials("visa_prepaid")` returns card details from TOML
- Verify `get_credentials("some_dynamic_service")` falls through to `managed_accounts` table
- Verify spending_log CRUD operations
- Verify managed_accounts CRUD operations
- Verify tool registration respects `PREPAID_CARD_ENABLED` flag (tools hidden when disabled)

---

## Summary of All Changes

| File | Change |
|------|--------|
| `config.py` | Add `PREPAID_CARD_ENABLED`, `PREPAID_CARD_SERVICE` |
| `.env.example` | Add `PREPAID_CARD_ENABLED=false` |
| `data/credentials.toml` | Add `[visa_prepaid]` section (or document in example) |
| `core/database.py` | Bump schema v21, add `spending_log` + `managed_accounts` tables + migration |
| `agency/spending/__init__.py` | New module init |
| `agency/spending/manager.py` | New: `SpendingManager` + `AccountManager` classes |
| `agency/tools/browser/credentials.py` | Add DB fallback to `get_credential()` |
| `agency/tools/definitions.py` | Add 6 new tool definitions + registration block |
| `agency/tools/executor.py` | Add 6 new `_exec_*` handler methods + registration |

**New files:** 2 (`agency/spending/__init__.py`, `agency/spending/manager.py`)
**Modified files:** 7
**Database migration:** v20 → v21 (2 new tables, 3 new indexes)
**New Isaac tools:** 6
**Delegate changes:** 1 (credential lookup fallback)
**Architecture changes:** 0 (all existing patterns reused)
