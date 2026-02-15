"""
Pattern Project - API Prompt Logger
JSON Lines logging for all API requests and responses
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from threading import Lock

from config import PROMPT_LOG_PATH

# Thread-safe file writing
_write_lock = Lock()


def log_api_request(
    provider: str,
    model: str,
    system_prompt: Optional[str],
    messages: List[Dict[str, str]],
    settings: Dict[str, Any],
    response_text: str,
    tokens_in: int,
    tokens_out: int,
    success: bool,
    error: Optional[str] = None
) -> None:
    """
    Log an API request and response to the JSON Lines file.

    Args:
        provider: LLM provider name (anthropic, kobold)
        model: Model identifier
        system_prompt: Full system prompt sent to API
        messages: Conversation messages array
        settings: Request settings (temperature, max_tokens, etc.)
        response_text: The response text from the API
        tokens_in: Input token count
        tokens_out: Output token count
        success: Whether the request succeeded
        error: Error message if failed
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "messages": messages,
        "settings": settings,
        "response": {
            "text": response_text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "success": success,
            "error": error
        }
    }

    _write_entry(entry)


def _write_entry(entry: Dict[str, Any]) -> None:
    """Write a single entry to the log file (thread-safe)."""
    # Ensure logs directory exists
    PROMPT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _write_lock:
        try:
            with open(PROMPT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            # Don't let logging failures break the main application
            print(f"Warning: Failed to write prompt log: {e}")


def read_recent_logs(limit: int = 10) -> List[Dict[str, Any]]:
    """
    Read the most recent log entries.

    Args:
        limit: Maximum number of entries to return

    Returns:
        List of log entries (most recent last)
    """
    if not PROMPT_LOG_PATH.exists():
        return []

    entries = []
    try:
        with open(PROMPT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception:
        return []

    # Return last N entries
    return entries[-limit:] if len(entries) > limit else entries


def get_log_stats() -> Dict[str, Any]:
    """
    Get statistics about the prompt log.

    Returns:
        Dict with entry count, total tokens, date range, etc.
    """
    if not PROMPT_LOG_PATH.exists():
        return {"entries": 0, "total_tokens_in": 0, "total_tokens_out": 0}

    entries = 0
    total_tokens_in = 0
    total_tokens_out = 0
    first_timestamp = None
    last_timestamp = None

    try:
        with open(PROMPT_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entries += 1
                        total_tokens_in += entry.get("response", {}).get("tokens_in", 0)
                        total_tokens_out += entry.get("response", {}).get("tokens_out", 0)

                        ts = entry.get("timestamp")
                        if ts:
                            if first_timestamp is None:
                                first_timestamp = ts
                            last_timestamp = ts
                    except json.JSONDecodeError:
                        continue
    except Exception:
        pass

    return {
        "entries": entries,
        "total_tokens_in": total_tokens_in,
        "total_tokens_out": total_tokens_out,
        "first_entry": first_timestamp,
        "last_entry": last_timestamp
    }
