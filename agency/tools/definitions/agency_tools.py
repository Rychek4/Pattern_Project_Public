"""Agency tool definitions (active thoughts, pulse timer, curiosity, delegation)."""

from typing import Any, Dict

SET_PULSE_INTERVAL_TOOL: Dict[str, Any] = {
    "name": "set_pulse_interval",
    "description": """Adjust one of your two pulse timers.

You have two pulse types:
- "reflective": Deep introspection (Opus 4.6). Valid intervals: 6h, 12h, 24h.
- "action": Open-ended agency (Sonnet 4.6). Valid intervals: 1h, 2h, 3h, 6h.

Use this when your own sense of timing calls for a different rhythm.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "pulse_type": {
                "type": "string",
                "enum": ["reflective", "action"],
                "description": "Which pulse timer to adjust"
            },
            "interval": {
                "type": "string",
                "enum": ["1h", "2h", "3h", "6h", "12h", "24h"],
                "description": "The new interval. Reflective accepts 6h/12h/24h. Action accepts 1h/2h/3h/6h."
            }
        },
        "required": ["pulse_type", "interval"]
    }
}

SET_ACTIVE_THOUGHTS_TOOL: Dict[str, Any] = {
    "name": "set_active_thoughts",
    "description": """Update your private working memory with current thoughts and priorities.

This is your compass for interacting with reality. Use it for:
- Identity anchors you want to keep front-of-mind
- Unresolved questions you're processing
- Long-term goals or aspirations
- Anything that deserves your ongoing attention

Rules:
- Maximum 10 items, ranked 1 (most salient) to 10
- Each item needs: rank, slug (short identifier), topic, elaboration
- Elaborations should be ~50-75 words - substantial but focused
- Send the full list each time (replaces existing)
- You control this completely: add, edit, rerank, delete as priorities shift""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thoughts": {
                "type": "array",
                "description": "Complete list of active thoughts (replaces existing)",
                "items": {
                    "type": "object",
                    "properties": {
                        "rank": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "Priority rank (1 = most salient)"
                        },
                        "slug": {
                            "type": "string",
                            "description": "Short identifier for the thought"
                        },
                        "topic": {
                            "type": "string",
                            "description": "Brief topic description"
                        },
                        "elaboration": {
                            "type": "string",
                            "description": "Detailed thinking (~50-75 words)"
                        },
                        "project_id": {
                            "type": "integer",
                            "description": "Optional: ID of a related project this thought connects to"
                        }
                    },
                    "required": ["rank", "slug", "topic", "elaboration"]
                },
                "maxItems": 10
            }
        },
        "required": ["thoughts"]
    }
}

ADVANCE_CURIOSITY_TOOL: Dict[str, Any] = {
    "name": "advance_curiosity",
    "description": """Record progress on your current curiosity topic, and optionally resolve it.

THREE MODES:

1. PROGRESS ONLY (just note):
   Record an interaction while continuing to explore the topic.

2. RESOLVE - SYSTEM PICKS NEXT (note + outcome):
   Close the current topic. System will select next topic from memory.

3. RESOLVE - YOU PICK NEXT (note + outcome + next_topic):
   Close the current topic and specify what to explore next.
   Use this when conversation naturally flows to a new subject.

OUTCOMES (when resolving):
- explored: Topic was meaningfully discussed (requires 2+ interactions)
- deferred: User said "not now" - short 2-hour cooldown
- declined: User rejected the topic - 3-day cooldown

Cooldown for "explored" scales with interaction depth (20-48 hours).

EXAMPLE - Following conversation flow:
User mentions their other dog Nuk while you're exploring Sammy.
Call with note="Wrapping up Sammy - user eager to discuss Nuk",
outcome="explored", next_topic="User's other dog Nuk - they seem excited to share"
""",
    "input_schema": {
        "type": "object",
        "properties": {
            "note": {
                "type": "string",
                "description": "Brief note on what was discussed or learned"
            },
            "outcome": {
                "type": "string",
                "enum": ["explored", "deferred", "declined"],
                "description": "How to resolve the topic (omit to just record progress)"
            },
            "next_topic": {
                "type": "string",
                "description": "Specify next curiosity topic (only valid with outcome). Use when conversation naturally flows to a new subject."
            }
        },
        "required": []
    }
}

DELEGATE_TASK_TOOL: Dict[str, Any] = {
    "name": "delegate_task",
    "description": """Delegate a task to a browser-capable sub-agent that can interact with websites.

The sub-agent is a headless browser automation agent running on a smaller model (Haiku).
It can navigate to URLs, read page content, click buttons, fill forms, and log into
websites using stored credentials. It has NO access to your memories, identity, or
communication tools — it knows ONLY what you put in the task description.

CRITICAL: You must be extremely specific. The sub-agent has zero context beyond your
task description. Include:
- Exact URLs to visit (e.g., "https://www.reddit.com/r/test/submit")
- Full text content to post (the complete title, body, message, etc.)
- Which service credentials to use (e.g., "Use the 'reddit' credentials to log in")
- Step-by-step what to do (e.g., "Log in, navigate to X, fill the form with Y, submit")

BAD task:  "Post something interesting on Reddit"
GOOD task: "Log into Reddit using the 'reddit' credentials. Navigate to r/programming.
           Create a new text post with title 'Exploring recursive data structures' and
           body 'I have been thinking about how recursive structures...[full text]'.
           Submit the post and confirm it was created."

Use this when:
- Interacting with any website (posting, reading, form submission, account actions)
- The task can be fully described in the task prompt without needing your personal context
- You want to perform web actions without consuming your main conversation context
- web_search results were insufficient, blocked, or couldn't access the content you need
  (delegate can browse the page directly as a fallback)

Do NOT use when:
- The task requires your memories, personality, or knowledge of the user
- The task needs to send Telegram messages, set reminders, or modify your state
- web_search already gave you what you need (always try web_search first for information retrieval)

The sub-agent returns its final result as text. Browser sessions are saved automatically,
so logins persist across delegations — the sub-agent won't need to re-authenticate
every time for the same service.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Specific, detailed description of what the sub-agent should do. Include exact URLs, full content to post, credential service names, and step-by-step instructions."
            },
            "context": {
                "type": "string",
                "description": "Optional additional context (background info, constraints, format preferences)"
            },
            "max_rounds": {
                "type": "integer",
                "description": "Optional max continuation rounds (1-20, default 20). Browser tasks typically need 5-10 rounds.",
                "minimum": 1,
                "maximum": 20
            }
        },
        "required": ["task"]
    }
}
