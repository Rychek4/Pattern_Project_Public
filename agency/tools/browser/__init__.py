"""
Pattern Project - Browser Automation for Delegate Sub-Agents

Provides Playwright-based browser tools for the delegation system.
The delegate sub-agent uses these tools to interact with websites:
navigate, read pages, click elements, type text, and access credentials.

Browser instances are lazy-initialized (only started on first tool use)
and run headless. Per-service session persistence (cookies/storage) allows
logins to survive across delegation tasks.
"""
