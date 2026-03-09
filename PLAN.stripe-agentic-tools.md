# Plan: Add Stripe Agentic Tools

## Goal
Give Isaac (the AI companion) the ability to **shop on behalf of Brian** — browse products, create payment links, and make purchases using Stripe's agentic commerce capabilities.

---

## Background

### The Project Today
Pattern Project is a Python AI companion (Isaac) powered by Claude, with:
- **Native tool use** — tools defined in `agency/tools/definitions.py` (schemas) and executed via `agency/tools/executor.py` (routing to handlers in `agency/commands/handlers/`)
- **Config-gated features** — each capability has a flag in `config.py` (e.g. `TELEGRAM_ENABLED`, `VISUAL_ENABLED`) and tools are conditionally registered
- **Existing precedent** — Reddit, Google Calendar, Telegram, browser delegation, file I/O all follow the same define-schema → register-conditionally → handler pattern

### Stripe Agent Toolkit
Stripe provides [`stripe-agent-toolkit`](https://github.com/stripe/agent-toolkit) for Python, which wraps the Stripe API into function-calling-ready tools. Key capabilities:
- **Products & Prices** — list, create, search products and prices
- **Payment Links** — create checkout links the user can click
- **Customers** — create and manage customer records
- **Invoices** — create and send invoices
- **Balance** — read account balance, list charges
- **Issuing (virtual cards)** — create single-use virtual cards for agent spending

Install: `pip install stripe-agent-toolkit` (requires Python 3.11+)

---

## Implementation Plan

### Step 1: Configuration (`config.py`)
Add Stripe feature flags and API key config:
```python
# Stripe (Agentic Commerce)
STRIPE_ENABLED = os.getenv("STRIPE_ENABLED", "false").lower() == "true"
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
# Spending limit per transaction (cents) — safety guardrail
STRIPE_MAX_AMOUNT_CENTS = int(os.getenv("STRIPE_MAX_AMOUNT_CENTS", "5000"))  # $50 default
```

### Step 2: Dependency (`requirements.txt`)
```
# Stripe Agentic Commerce
stripe-agent-toolkit>=0.3.0
```

### Step 3: Tool Definitions (`agency/tools/definitions.py`)
Add Stripe tool schemas following the existing pattern. Start with a focused, safe set:

| Tool Name | Purpose | Risk Level |
|---|---|---|
| `stripe_list_products` | Browse available products | Read-only |
| `stripe_search_products` | Search products by query | Read-only |
| `stripe_list_prices` | Get pricing info for products | Read-only |
| `stripe_create_payment_link` | Generate a checkout link for Brian to click | Low — requires user action |
| `stripe_get_balance` | Check account balance | Read-only |

Register conditionally:
```python
if config.STRIPE_ENABLED:
    tools.append(STRIPE_LIST_PRODUCTS_TOOL)
    tools.append(STRIPE_SEARCH_PRODUCTS_TOOL)
    tools.append(STRIPE_LIST_PRICES_TOOL)
    tools.append(STRIPE_CREATE_PAYMENT_LINK_TOOL)
    tools.append(STRIPE_GET_BALANCE_TOOL)
```

### Step 4: Handler (`agency/commands/handlers/stripe_handler.py`) — NEW FILE
New handler that wraps `stripe-agent-toolkit`:
- Lazy-load the toolkit (only import/init on first tool call, like browser tools)
- Initialize with `config.STRIPE_SECRET_KEY`
- Each handler function maps a tool call → toolkit method
- Enforce `STRIPE_MAX_AMOUNT_CENTS` guardrail before any payment-adjacent action
- Format results as clean text summaries (not raw JSON) for Isaac's responses

### Step 5: Executor Wiring (`agency/tools/executor.py`)
Register new tool names → handler methods:
```python
"stripe_list_products": self._exec_stripe_list_products,
"stripe_search_products": self._exec_stripe_search_products,
"stripe_list_prices": self._exec_stripe_list_prices,
"stripe_create_payment_link": self._exec_stripe_create_payment_link,
"stripe_get_balance": self._exec_stripe_get_balance,
```
Each `_exec_*` method delegates to `stripe_handler`.

### Step 6: Credentials (`credentials.toml.example`)
Add a Stripe section:
```toml
[stripe]
secret_key = "rk_test_..."  # Use restricted API keys for safety
```

---

## Safety Guardrails

| Guardrail | Detail |
|---|---|
| **Disabled by default** | `STRIPE_ENABLED=false` — must opt in |
| **Restricted API keys** | Docs recommend `rk_*` keys with minimal permissions |
| **Spending cap** | `STRIPE_MAX_AMOUNT_CENTS` hard limit per action |
| **No auto-charge** | Payment links require Brian to click through — no silent charges |
| **Test mode first** | Initial dev/testing uses `sk_test_*` / `rk_test_*` keys |
| **Lazy loading** | Toolkit only initialized when a Stripe tool is actually called |

---

## Files Changed

| File | Action | Scope |
|---|---|---|
| `config.py` | Edit | Add 3 env vars |
| `requirements.txt` | Edit | Add 1 dependency |
| `agency/tools/definitions.py` | Edit | Add 5 tool schemas + conditional registration |
| `agency/tools/executor.py` | Edit | Wire 5 tool names to handler methods |
| `agency/commands/handlers/stripe_handler.py` | **Create** | ~120 lines — Stripe handler (lazy-loaded) |
| `credentials.toml.example` | Edit | Add `[stripe]` section |

---

## Open Questions

1. **Virtual cards (Issuing)** — Should Isaac be able to create virtual cards and spend autonomously, or start with payment links only (user approves each purchase)? **Recommendation: payment links only to start** — safer, and we can add Issuing later.

2. **Connected accounts** — Is this for a single Stripe account or multi-account?

3. **MCP alternative** — Stripe also offers a remote MCP server at `mcp.stripe.com`. The toolkit approach fits the existing architecture better, but MCP could be a future option.

---

## Implementation Order

```
Step 1 (config.py)              — Quick, foundation
Step 2 (requirements.txt)       — Quick
Step 3 (definitions.py)         — Tool schemas
Step 4 (stripe_handler.py)      — Core logic, new file
Step 5 (executor.py)            — Wire it up
Step 6 (credentials.toml)       — Documentation
```

Steps 1-2 first, then 3-5 can be done in parallel, Step 6 last.
