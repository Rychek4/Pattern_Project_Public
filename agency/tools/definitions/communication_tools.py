"""Communication tool definitions (Telegram)."""

from typing import Any, Dict

SEND_TELEGRAM_TOOL: Dict[str, Any] = {
    "name": "send_telegram",
    "description": """Send a Telegram message to the user.

Use for genuinely useful notifications:
- Time-sensitive reminders the user requested
- Important information when they're away
- Alerts about things that need attention

Guidelines:
- Be concise and clear for mobile readability
- Don't use for casual chat - reserve for meaningful notifications
- The user can reply directly in Telegram and you'll receive their response

Rate limited to prevent spam.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The message content to send"
            }
        },
        "required": ["message"]
    }
}
