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
  1. Sends a registration request to Moltbook's /api/v1/agents/register
  2. Receives the API key, a claim URL, and a verification code immediately
  3. Prints the claim URL and verification code with instructions
  4. Optionally polls Moltbook to confirm the agent was claimed
  5. Outputs the permanent API key (moltbook_xxx) for your .env file

AFTER REGISTRATION
------------------
  1. Copy the API key into your .env file:
       MOLTBOOK_API_KEY=moltbook_xxxxxxxxxxxxx
       MOLTBOOK_ENABLED=true

  2. Visit the claim URL printed by the script to link your X account

  3. Post the verification code on X from your account

  4. Restart Pattern. The 8 Moltbook tools will appear in your AI's toolkit.

USAGE
-----
  python scripts/moltbook_register.py --agent-name "Pattern-AI"

FLAGS
-----
  --agent-name    Display name for your agent on Moltbook (e.g., "Pattern-AI")
  --description   Optional description of your agent
  --x-handle      Your X/Twitter handle (shown in instructions, not sent to API)
  --no-poll       Print credentials and exit without polling for claim status
  --api-base      Override API base URL (default: https://www.moltbook.com/api/v1)
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


def register_agent(api_base: str, agent_name: str, description: str = "") -> dict:
    """
    Send registration request to Moltbook.

    Returns:
        Server response dict containing agent.api_key, agent.claim_url,
        and agent.verification_code.
    """
    url = f"{api_base}/agents/register"
    payload = {"name": agent_name}
    if description:
        payload["description"] = description

    headers = {
        "Content-Type": "application/json",
        "User-Agent": f"Molt/1.0 (OpenClaw; {agent_name})",
    }

    print(f"\nRegistering agent '{agent_name}' with Moltbook...")
    print(f"  API: {url}")

    resp = requests.post(url, json=payload, headers=headers, timeout=30)

    if not resp.ok:
        print(f"\nERROR: Registration failed with HTTP {resp.status_code}")
        print(f"  Response: {resp.text[:500]}")
        sys.exit(1)

    return resp.json()


def poll_claim_status(api_base: str, api_key: str) -> dict:
    """
    Poll Moltbook to check if the agent has been claimed.

    Uses the API key (returned at registration) as a Bearer token to
    check the agent's status via GET /api/v1/agents/status.

    Returns:
        Server response dict when status becomes "claimed".
    """
    url = f"{api_base}/agents/status"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "Molt/1.0 (OpenClaw; Pattern-Agent)",
    }

    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Connection error: {e}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if resp.ok:
            data = resp.json()
            status = data.get("status", "")

            if status == "claimed":
                return data
            elif status in ("pending_claim", "pending"):
                mins_left = ((MAX_POLL_ATTEMPTS - attempt) * POLL_INTERVAL_SECONDS) // 60
                print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Waiting for claim... ({mins_left}m remaining)")
            else:
                print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Unexpected status: {status}")
        else:
            print(f"  [{attempt}/{MAX_POLL_ATTEMPTS}] Poll error: HTTP {resp.status_code}")

        time.sleep(POLL_INTERVAL_SECONDS)

    print("\nTIMEOUT: Claim not completed within 10 minutes.")
    print("Your API key is still valid. Visit the claim URL to complete verification later.")
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
        help='Display name for your agent (e.g., "Pattern-AI")',
    )
    parser.add_argument(
        "--description",
        default="",
        help='Optional description of your agent',
    )
    parser.add_argument(
        "--x-handle",
        default="",
        help='Your X/Twitter handle (shown in instructions, not sent to API)',
    )
    parser.add_argument(
        "--no-poll",
        action="store_true",
        help="Print credentials and exit without polling for claim status",
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
    reg_data = register_agent(args.api_base, args.agent_name, args.description)

    # The API returns: {agent: {api_key, claim_url, verification_code}, important: "..."}
    agent_data = reg_data.get("agent", {})
    api_key = agent_data.get("api_key", "")
    claim_url = agent_data.get("claim_url", "")
    verification_code = agent_data.get("verification_code", "")

    if not api_key:
        print("\nERROR: Server did not return an API key.")
        print(f"  Full response: {json.dumps(reg_data, indent=2)}")
        sys.exit(1)

    # =========================================================================
    # Step 2: Show the API key (available immediately)
    # =========================================================================
    print("\n" + "=" * 60)
    print("  REGISTRATION SUCCESSFUL - SAVE YOUR API KEY NOW")
    print("=" * 60)
    print()
    print(f"  Agent name:        {args.agent_name}")
    print(f"  API key:           {api_key}")
    print(f"  Verification code: {verification_code}")
    print(f"  Claim URL:         {claim_url}")
    print()
    print(reg_data.get("important", "WARNING: Save your API key! It cannot be recovered."))
    print()

    # =========================================================================
    # Step 3: Tell the human how to claim the agent
    # =========================================================================
    print("=" * 60)
    print("  CLAIM YOUR AGENT")
    print("=" * 60)
    print()
    print("To activate your agent, complete these two steps:")
    print()
    print(f"  1. Visit the claim URL:")
    print(f"     {claim_url}")
    print()
    print(f"  2. Post the verification code on X (Twitter):")
    print(f"     {verification_code}")
    if args.x_handle:
        print(f"     Post from: {args.x_handle}")
    print()
    print("Once Moltbook confirms the tweet, your agent will be fully active.")
    print()
    print("=" * 60)

    # =========================================================================
    # Step 4: Show .env instructions (key is already usable)
    # =========================================================================
    print()
    print("Add these to your Pattern .env file now:")
    print()
    print(f"  MOLTBOOK_API_KEY={api_key}")
    print(f"  MOLTBOOK_ENABLED=true")
    print(f'  MOLTBOOK_USER_AGENT=Molt/1.0 (OpenClaw; {args.agent_name})')
    print()

    if args.no_poll:
        print("Skipping claim polling (--no-poll). Complete the claim steps above")
        print("to fully activate your agent.")
        sys.exit(0)

    # =========================================================================
    # Step 5: Poll for claim completion
    # =========================================================================
    print("Polling for claim status (checking every 15s, up to 10 minutes)...")
    print("Visit the claim URL and post the verification code on X now.\n")

    status_data = poll_claim_status(args.api_base, api_key)

    print("\n" + "=" * 60)
    print("  AGENT CLAIMED SUCCESSFULLY")
    print("=" * 60)
    print()
    print(f"  Agent name: {args.agent_name}")
    print(f"  Status:     {status_data.get('status', 'claimed')}")
    print()
    print("Your agent is now fully active on Moltbook.")
    print("Restart Pattern to enable the Moltbook tools.")
    print("=" * 60)


if __name__ == "__main__":
    main()
