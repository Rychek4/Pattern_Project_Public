"""Memory tool definitions."""

from typing import Any, Dict

SEARCH_MEMORIES_TOOL: Dict[str, Any] = {
    "name": "search_memories",
    "description": """Search the semantic memory archive for relevant past conversations and stored information.

Use this when:
- The user asks about past conversations ("What did we discuss about...")
- You need more context than the automatically-recalled memories provide
- The user references something with "remember when..." or similar
- You want to proactively recall relevant context before responding

The search uses semantic similarity - describe what you're looking for naturally.
Results include relevance scores and timestamps for context.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query describing what you're looking for"
            }
        },
        "required": ["query"]
    }
}
