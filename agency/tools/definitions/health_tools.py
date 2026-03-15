"""Health check tool definition."""

from typing import Any, Dict

HEALTH_CHECK_TOOL: Dict[str, Any] = {
    "name": "health_check",
    "description": """Check the health status of all system infrastructure.

Returns a structured report showing:
- Per-system status (healthy, degraded, critical, recovered)
- Error counts per system (last 1 hour, last 24 hours, total)
- Recent error/critical entries with timestamps

Use this when:
- Something feels off (slow responses, missing data, failed tools)
- During reflective pulses to assess infrastructure state
- After recovering from an error to verify system health
- Proactively, to maintain situational awareness of your own infrastructure

This tool takes no parameters — just call it.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}
