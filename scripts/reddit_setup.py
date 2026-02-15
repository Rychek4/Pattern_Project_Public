#!/usr/bin/env python3
"""
Reddit Integration Setup - Credential Validation
==================================================

This script validates your Reddit API credentials and confirms
that Pattern can authenticate successfully.

Run this after configuring your .env file with Reddit credentials.

PREREQUISITES
-------------
  - Python 3.7+ with `praw` installed (pip install praw)
  - A Reddit account
  - A Reddit "script" app created at https://www.reddit.com/prefs/apps

USAGE
-----
  python scripts/reddit_setup.py

See docs/reddit_setup.md for full setup instructions.
"""

import os
import sys

# Add project root to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    print()
    print("=" * 60)
    print("  Reddit Integration Setup - Credential Validation")
    print("=" * 60)
    print()

    # Check for praw
    try:
        import praw
    except ImportError:
        print("ERROR: PRAW (Python Reddit API Wrapper) is not installed.")
        print("  Run: pip install praw")
        sys.exit(1)

    # Load environment
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass  # dotenv is optional for this script

    # Check required env vars
    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    username = os.getenv("REDDIT_USERNAME", "")
    password = os.getenv("REDDIT_PASSWORD", "")
    user_agent = os.getenv("REDDIT_USER_AGENT", f"python:pattern-agent:v1.0 (by /u/{username or 'unknown'})")

    missing = []
    if not client_id:
        missing.append("REDDIT_CLIENT_ID")
    if not client_secret:
        missing.append("REDDIT_CLIENT_SECRET")
    if not username:
        missing.append("REDDIT_USERNAME")
    if not password:
        missing.append("REDDIT_PASSWORD")

    if missing:
        print("ERROR: Missing required environment variables:")
        for var in missing:
            print(f"  - {var}")
        print()
        print("Add these to your .env file. See docs/reddit_setup.md for instructions.")
        sys.exit(1)

    print(f"  Client ID:   {client_id[:8]}...")
    print(f"  Username:    u/{username}")
    print(f"  User-Agent:  {user_agent}")
    print()
    print("Attempting to authenticate with Reddit...")
    print()

    # Try to authenticate
    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent=user_agent,
        )

        # Force authentication by fetching the user's profile
        me = reddit.user.me()

        print("=" * 60)
        print("  AUTHENTICATION SUCCESSFUL")
        print("=" * 60)
        print()
        print(f"  Account:        u/{me.name}")
        print(f"  Link karma:     {me.link_karma:,}")
        print(f"  Comment karma:  {me.comment_karma:,}")
        print(f"  Verified email: {getattr(me, 'has_verified_email', 'N/A')}")
        print()

        # Check REDDIT_ENABLED
        enabled = os.getenv("REDDIT_ENABLED", "false").lower() == "true"
        if enabled:
            print("  REDDIT_ENABLED=true  (Reddit tools will be active)")
        else:
            print("  REDDIT_ENABLED=false (set to 'true' in .env to activate)")
        print()
        print("Restart Pattern to enable the 8 Reddit tools.")
        print("=" * 60)

    except Exception as e:
        print("=" * 60)
        print("  AUTHENTICATION FAILED")
        print("=" * 60)
        print()
        print(f"  Error: {e}")
        print()
        print("Common issues:")
        print("  - Wrong client_id or client_secret (check reddit.com/prefs/apps)")
        print("  - Wrong username or password")
        print("  - Account has 2FA enabled (use an app password or disable 2FA)")
        print("  - Invalid user_agent format")
        print()
        print("See docs/reddit_setup.md for troubleshooting.")
        sys.exit(1)


if __name__ == "__main__":
    main()
