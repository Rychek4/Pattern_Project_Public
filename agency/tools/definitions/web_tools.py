"""Web fetch domain management tool definitions."""

from typing import Any, Dict

MANAGE_FETCH_DOMAINS_TOOL: Dict[str, Any] = {
    "name": "manage_fetch_domains",
    "description": """Manage the web fetch domain allow/block lists.

You can control which domains are available for web page fetching.
Changes persist across sessions and merge with config defaults.

Actions:
- allow: Add a domain to the allowed list (also unblocks it if blocked)
- block: Add a domain to the blocked list (also removes from allowed)
- remove_allowed: Remove a domain from the allowed list
- unblock: Remove a domain from the blocked list

When allowed_domains is empty (default), all non-blocked domains are accessible.
When allowed_domains has entries, ONLY those domains can be fetched.

Use this when:
- A fetch fails due to domain restrictions and you want to enable that domain
- You want to proactively restrict fetching to specific trusted domains
- You want to block a domain that returned unhelpful or problematic content""",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["allow", "block", "remove_allowed", "unblock"],
                "description": "The action to perform on the domain"
            },
            "domain": {
                "type": "string",
                "description": "The domain to manage (e.g., 'docs.python.org', 'example.com')"
            }
        },
        "required": ["action", "domain"]
    }
}

LIST_FETCH_DOMAINS_TOOL: Dict[str, Any] = {
    "name": "list_fetch_domains",
    "description": """View the current web fetch domain configuration.

Shows the effective allowed and blocked domain lists, including both
config defaults and any runtime changes you've made.

Use this to check current domain restrictions before fetching.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
