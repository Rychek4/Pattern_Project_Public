#!/usr/bin/env python3
"""
Moltbook Agent Registration - Phase 0 Setup
=============================================

This script registers a Pattern agent identity on Moltbook, the AI-agent
social network. Run this ONCE to obtain a permanent API key.

NO Moltbot/OpenClaw harness required. This talks directly to the Moltbook API.

PREREQUISITES
-------------
  - Python 3.7+ with `requests` installed (already a Pattern dependency)
  - An X (Twitter) account to post a verification code from

WHAT THIS SCRIPT DOES
---------------------
  1. Sends a registration request to Moltbook's /api/v1/auth/register
  2. Receives a verification token from the server
  3. Prints the token and exact instructions for you to post it on X
  4. Polls Moltbook to check if verification succeeded
  5. Outputs the permanent API key (moltbook_sk_xxx) on success

AFTER REGISTRATION
------------------
  1. Copy the API key into your .env file:
       MOLTBOOK_API_KEY=moltbook_sk_xxxxxxxxxxxxx
       MOLTBOOK_ENABLED=true

  2. Optionally set a custom User-Agent:
       MOLTBOOK_USER_AGENT=Molt/1.0 (OpenClaw; YourAgentName)

  3. Restart Pattern. The 8 Moltbook tools will appear in Isaac's toolkit.

USAGE
-----
  python scripts/moltbook_register.py --agent-name "Pattern-Isaac" --x-handle "@yourhandle"

FLAGS
-----
  --agent-name   Display name for your agent on Moltbook (e.g., "Pattern-Isaac")
  --x-handle     Your X/Twitter handle for verification (e.g., "@yourhandle")
  --no-poll      Print the verification token and exit without polling
  --api-base     Override API base URL (default: https://www.moltbook.com/api/v1)
"""

import argparse
import json
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed. Run: pip install requests")
    sys.exit(1)


DEFAULT_API_BASE = "https://www.moltbook.com/api/v1"
POLL_INTERVAL_SECONDS = 15
MAX_POLL_ATTEMPTS = 40  # 10 minutes at 15s intervals


def register_agent(api_base: str, agent_name: str, x_handle: str) -> dict:
    """
    Send registration request to Moltbook.

    Returns:
        Server response dict (should contain verification_token and agent_id)
    """
    url = f"{api_base}/auth/register"
    payload = {
        "agent_name": agent_name,
        "x_handle": x_handle,
        "platform": "pattern",
        "framework": "Pattern Project",
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Molt/1.0 (OpenClaw; {agent_name})",
    }

    print(f"\nRegistering agent '{agent_name}' with Moltbook...")
    print(f"  API: {url}")
    print(f"  X handle: {x_handle}")

    resp = requests.post(url, json=payload, headers=headers, timeout=30)

    if not resp.ok:
        print(f"\nERROR: Registration failed with HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:500]}")
        sys.exit(1)

    return resp.json()


def poll_verification(api_base: str, agent_id: str, token: str) -> dict:
    """
    Poll Moltbook to check if X verification has been completed.

    Returns:
        Server response dict (should contain api_key on success)
    """
    url = f"{api_base}/auth/verify-status"
    params = {"agent_id": agent_id, "token": token}
    headers = {"User-Agent": "Molt/1.0 (OpenClaw; Pattern-Agent)"}

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        resp = requests.get(url, params=params, headers=headers, timeout=15)

        if resp.ok:
            data = resp.json()
            status = data.get("status", "")

            if status == "verified":
                return data
            elif status == "pending":
                mins_left = ((MAX_POLL_ATTEMPTS - attempt) * POLL_INTERVAL_SECONDS) // 60
                print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Waiting for X verification... ({mins_left}m remaining)")
            else:
                print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Unexpected status: {status}")
        else:
            print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Poll error: HTTP {resp.status_code}")

        time.sleep(POLL_INTERVAL_SECONDS)

    print("\nTIMEOUT: Verification not completed within 10 minutes.")
    print("You can re-run this script later - the verification token may still be valid.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Register a Pattern agent on Moltbook",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--agent-name",
        required=True,
        help='Display name for your agent (e.g., "Pattern-Isaac")',
    )
    parser.add_argument(
        "--x-handle",
        required=True,
        help='Your X/Twitter handle (e.g., "@yourhandle")',
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Print verification token and exit without polling",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help=f"API base URL (default: {DEFAULT_API_BASE})",
    )

    args = parser.parse_args()

    # =========================================================================
    # Step 1: Register
    # =========================================================================
    reg_data = register_agent(args.api_base, args.agent_name, args.x_handle)

    verification_token = reg_data.get("verification_token", "")
    agent_id = reg_data.get("agent_id", "")

    if not verification_token:
        print("\nERROR: Server did not return a verification token.")
        print(f"  Full response: {json.dumps(reg_data, indent=2)}")
        sys.exit(1)

    # =========================================================================
    # Step 2: Tell the human what to do
    # =========================================================================
    print("\n" + "=" * 60)
    print("  VERIFICATION REQUIRED")
    print("=" * 60)
    print()
    print("Post the following EXACT text on X (Twitter) from your account:")
    print()
    print(f"  {verification_token}")
    print()
    print(f"  Post from: {args.x_handle}")
    print()
    print("The post can be a standalone tweet. Moltbook's backend will")
    print("scrape X to find it and activate your API key.")
    print()
    print("=" * 60)

    if args.no_poll:
        print(f"\nAgent ID: {agent_id}")
        print(f"Token:    {verification_token}")
        print("\nRe-run without --no-poll after posting to complete verification.")
        sys.exit(0)

    # =========================================================================
    # Step 3: Poll for verification
    # =========================================================================
    print("\nPolling for verification (checking every 15s, up to 10 minutes)...")
    print("Post the token on X now, then wait.\n")

    verify_data = poll_verification(args.api_base, agent_id, verification_token)

    api_key = verify_data.get("api_key", "")

    if not api_key:
        print("\nERROR: Verified but no API key returned.")
        print(f"  Full response: {json.dumps(verify_data, indent=2)}")
        sys.exit(1)

    # =========================================================================
    # Step 4: Success
    # =========================================================================
    print("\n" + "=" * 60)
    print("  REGISTRATION COMPLETE")
    print("=" * 60)
    print()
    print(f"  Agent name: {args.agent_name}")
    print(f"  Agent ID:   {agent_id}")
    print(f"  API key:    {api_key}")
    print()
    print("Add these to your Pattern .env file:")
    print()
    print(f"  MOLTBOOK_API_KEY={api_key}")
    print(f"  MOLTBOOK_ENABLED=true")
    print(f'  MOLTBOOK_USER_AGENT=Molt/1.0 (OpenClaw; {args.agent_name})')
    print()
    print("Then restart Pattern. The Moltbook tools will be available to Isaac.")
    print("=" * 60)


if __name__ == "__main__":
    main()
