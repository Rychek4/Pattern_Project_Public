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
Results include relevance scores, timestamps, and memory IDs for context.

Explore mode: When a search result feels like the edge of a larger structure — a fragment that implies related memories — pass its memory ID as explore_from to discover the neighborhood around that memory. This finds things connected to what you found, not things matching a new query. You can chain explorations: explore from memory A, find neighbor B, explore from B.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language search query describing what you're looking for. In explore mode, this is optional but serves as a weak contextual tether (10% weight) to bias results toward conversational relevance."
            },
            "explore_from": {
                "type": "integer",
                "description": "Memory ID to explore from. When provided, retrieves the neighborhood around this memory instead of standard search. The memory ID comes from a previous search result."
            }
        },
        "required": ["query"]
    }
}
