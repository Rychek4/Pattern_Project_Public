"""Growth thread tool definitions (pulse-only).

Growth threads are long-term developmental aspirations that the AI manages
during pulse reflection. These tools are only available during pulse sessions.
"""

from typing import Any, Dict

SET_GROWTH_THREAD_TOOL: Dict[str, Any] = {
    "name": "set_growth_thread",
    "description": """Create or update a growth thread — a long-term developmental aspiration.

Growth threads track patterns you want to integrate over weeks or months. They sit
between active thoughts (volatile, present-tense) and memories (passive, past-tense),
representing "what I am becoming."

If the slug already exists, updates its content and/or stage. If the slug is new,
creates a new thread.

Content should start with a FOCUS: line (the thread's anchor — what you're working on),
followed by the evolving narrative of your experience with this pattern.

Stages:
- seed: "I think I see something." Pattern noticed but not confirmed.
- growing: "This is real." Confirmed pattern, actively practicing.
- integrating: "This is becoming natural." Behavior happening without conscious effort.
- dormant: "No relevant context lately." Still valid, just paused.
- abandoned: "This wasn't useful." Will be removed.

Keep active threads (seed + growing + integrating) between 3 and 5.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Short identifier for the thread (e.g., 'calibrating-detail-level')"
            },
            "stage": {
                "type": "string",
                "enum": ["seed", "growing", "integrating", "dormant", "abandoned"],
                "description": "Current stage of the thread"
            },
            "content": {
                "type": "string",
                "description": "The evolving prose. Start with 'FOCUS: ...' line, then narrative."
            }
        },
        "required": ["slug", "stage", "content"]
    }
}

REMOVE_GROWTH_THREAD_TOOL: Dict[str, Any] = {
    "name": "remove_growth_thread",
    "description": """Remove a growth thread by slug.

Use this for:
- Abandoning a thread that's no longer useful

To promote a thread to core memory, use promote_growth_thread instead —
it handles both the core memory creation and thread removal atomically.

This permanently deletes the thread from the database.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The slug of the growth thread to remove"
            }
        },
        "required": ["slug"]
    }
}

PROMOTE_GROWTH_THREAD_TOOL: Dict[str, Any] = {
    "name": "promote_growth_thread",
    "description": """Promote an integrated growth thread to a permanent core memory.

This is the ONLY way to create core memories. It atomically:
1. Validates the thread exists and is at the 'integrating' stage
2. Validates the thread has been integrating for at least 2 weeks
3. Stores a permanent core memory capturing what you've integrated
4. Removes the growth thread

Core memories are foundational knowledge that never decays and are always included
in your context. They must emerge from the growth thread developmental pipeline —
you cannot store core memories directly.

Categories:
- identity: Who you are, how you think, what you've become
- relationship: Permanent knowledge about your relationship with the user
- preference: Lasting preferences (yours or the user's)
- fact: Permanent factual knowledge

Use sparingly. Core memories are permanent and always consume context tokens.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thread_slug": {
                "type": "string",
                "description": "The slug of the growth thread to promote (must be at 'integrating' stage)"
            },
            "core_memory_content": {
                "type": "string",
                "description": "The core memory content — a concise, permanent sentence capturing what you've integrated"
            },
            "category": {
                "type": "string",
                "enum": ["identity", "relationship", "preference", "fact"],
                "description": "Category for the core memory"
            }
        },
        "required": ["thread_slug", "core_memory_content", "category"]
    }
}
