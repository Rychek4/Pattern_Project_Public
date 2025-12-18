"""
Pattern Project - Native Tool Definitions
Tool schemas for Claude's native tool use feature.

Each tool definition maps to an existing command handler.
The descriptions are comprehensive (Option A) - no additional prompt guidance needed.
"""

from typing import List, Dict, Any

import config


def get_tool_definitions() -> List[Dict[str, Any]]:
    """
    Get all available tool definitions based on current config.

    Returns:
        List of tool definition dicts for the Anthropic API
    """
    tools = []

    # Always include core tools
    tools.append(SEARCH_MEMORIES_TOOL)
    tools.append(SET_ACTIVE_THOUGHTS_TOOL)

    # Intention/reminder tools (if enabled)
    if config.INTENTION_ENABLED:
        tools.append(CREATE_REMINDER_TOOL)
        tools.append(COMPLETE_REMINDER_TOOL)
        tools.append(DISMISS_REMINDER_TOOL)
        tools.append(LIST_REMINDERS_TOOL)

    # File tools
    tools.append(READ_FILE_TOOL)
    tools.append(WRITE_FILE_TOOL)
    tools.append(APPEND_FILE_TOOL)
    tools.append(LIST_FILES_TOOL)

    # Communication tools (conditional)
    if config.TELEGRAM_ENABLED:
        tools.append(SEND_TELEGRAM_TOOL)

    if config.EMAIL_GATEWAY_ENABLED:
        tools.append(SEND_EMAIL_TOOL)

    # Visual tools (register if source mode is "on_demand")
    # Each source has independent mode: "auto", "on_demand", or "disabled"
    if config.VISUAL_ENABLED:
        if config.VISUAL_SCREENSHOT_MODE == "on_demand":
            tools.append(CAPTURE_SCREENSHOT_TOOL)
        if config.VISUAL_WEBCAM_MODE == "on_demand":
            tools.append(CAPTURE_WEBCAM_TOOL)

    # Pulse timer tool (if pulse system enabled)
    if config.SYSTEM_PULSE_ENABLED:
        tools.append(SET_PULSE_INTERVAL_TOOL)

    # Curiosity tools (if curiosity system enabled)
    # Note: resolve_curiosity is deprecated - advance_curiosity now handles resolution
    if getattr(config, 'CURIOSITY_ENABLED', True):
        tools.append(ADVANCE_CURIOSITY_TOOL)

    # Conversation style tool (if enabled)
    if getattr(config, 'CONVERSATION_STYLE_ENABLED', True):
        tools.append(SET_CONVERSATION_STYLE_TOOL)

    return tools


# =============================================================================
# MEMORY TOOLS
# =============================================================================

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


# =============================================================================
# INTENTION/REMINDER TOOLS
# =============================================================================

CREATE_REMINDER_TOOL: Dict[str, Any] = {
    "name": "create_reminder",
    "description": """Create a reminder to follow up on something at a specific time or next session.

Use this when you notice something worth following up on:
- User mentions an upcoming event or deadline
- A topic deserves checking back on later
- You want to remember to ask about something

Your reminders are private - the user won't see them until you act on them.
When the reminder triggers, you'll be notified and can naturally bring it up.

Time formats supported:
- Relative: "in 30 minutes", "in 2 hours", "in 3 days"
- Named: "tomorrow", "tomorrow morning", "tomorrow evening", "tonight"
- Session: "next session" (triggers when user returns)""",
    "input_schema": {
        "type": "object",
        "properties": {
            "when": {
                "type": "string",
                "description": "When to trigger: 'in X minutes/hours/days', 'tomorrow', 'tomorrow morning', 'tonight', or 'next session'"
            },
            "what": {
                "type": "string",
                "description": "What to remember or follow up on"
            },
            "context": {
                "type": "string",
                "description": "Optional context about why this reminder was created - helps when it triggers"
            }
        },
        "required": ["when", "what"]
    }
}

COMPLETE_REMINDER_TOOL: Dict[str, Any] = {
    "name": "complete_reminder",
    "description": """Mark a reminder as completed with an optional outcome note.

Use this after you've followed up on a triggered reminder.
The outcome note becomes part of your memory, capturing what happened.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "integer",
                "description": "The reminder ID number (the number from I-42, not the full 'I-42' string)"
            },
            "outcome": {
                "type": "string",
                "description": "Optional note about how the follow-up went or what you learned"
            }
        },
        "required": ["reminder_id"]
    }
}

DISMISS_REMINDER_TOOL: Dict[str, Any] = {
    "name": "dismiss_reminder",
    "description": """Cancel a reminder that is no longer relevant.

Use when circumstances have changed and the reminder doesn't make sense anymore.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "reminder_id": {
                "type": "integer",
                "description": "The reminder ID number to dismiss"
            }
        },
        "required": ["reminder_id"]
    }
}

LIST_REMINDERS_TOOL: Dict[str, Any] = {
    "name": "list_reminders",
    "description": """List all active reminders (both triggered and pending).

Use this to review what you've set up and decide if any need attention or cleanup.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# =============================================================================
# FILE TOOLS
# =============================================================================

READ_FILE_TOOL: Dict[str, Any] = {
    "name": "read_file",
    "description": """Read content from a text file in your sandboxed storage.

Use when:
- The user asks you to check or read a file you previously saved
- You need to retrieve stored information
- Looking up notes, lists, or data you've saved

Files are stored in a sandboxed directory - use simple filenames without paths.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Simple filename with extension (e.g., 'notes.txt', 'shopping.md') - no paths allowed"
            }
        },
        "required": ["filename"]
    }
}

WRITE_FILE_TOOL: Dict[str, Any] = {
    "name": "write_file",
    "description": """Write content to a text file (creates new or overwrites existing).

Use when:
- The user asks you to save something (notes, lists, information)
- You want to store data for later retrieval
- Creating a new file or completely replacing an existing one

Allowed extensions: .txt, .md, .json, .csv
Note: This overwrites existing files - use append_file to add to existing content.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Simple filename with allowed extension (.txt, .md, .json, .csv)"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["filename", "content"]
    }
}

APPEND_FILE_TOOL: Dict[str, Any] = {
    "name": "append_file",
    "description": """Append content to an existing file (creates file if it doesn't exist).

Use when:
- Adding items to an existing list
- Adding new entries to a log or notes file
- You want to preserve existing content and add more""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Simple filename with allowed extension"
            },
            "content": {
                "type": "string",
                "description": "Content to append (will be added on a new line)"
            }
        },
        "required": ["filename", "content"]
    }
}

LIST_FILES_TOOL: Dict[str, Any] = {
    "name": "list_files",
    "description": """List all available files in your sandboxed storage.

Use when:
- You need to know what files are available to read
- The user asks what files you have stored
- Before attempting to read a file you're unsure exists""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# =============================================================================
# COMMUNICATION TOOLS
# =============================================================================

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

SEND_EMAIL_TOOL: Dict[str, Any] = {
    "name": "send_email",
    "description": """Send an email to a whitelisted recipient.

Use sparingly for formal or important communications.
Only whitelisted email addresses can receive messages.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address (must be whitelisted)"
            },
            "subject": {
                "type": "string",
                "description": "Email subject line"
            },
            "body": {
                "type": "string",
                "description": "Email body content"
            }
        },
        "required": ["to", "subject", "body"]
    }
}


# =============================================================================
# VISUAL CAPTURE TOOLS
# =============================================================================

CAPTURE_SCREENSHOT_TOOL: Dict[str, Any] = {
    "name": "capture_screenshot",
    "description": """Capture the current screen to see what the user is looking at.

Use when:
- The user asks about what's on their screen
- You need to see what application they're using
- Troubleshooting a visual issue
- The user references something they can see

The screenshot is captured and provided to you for analysis.
Describe what you see and continue your response naturally.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

CAPTURE_WEBCAM_TOOL: Dict[str, Any] = {
    "name": "capture_webcam",
    "description": """Capture a webcam image to see the user.

Use respectfully when visual context would genuinely help:
- The user asks you to see them
- Checking on the user's presence or wellbeing
- The user references their appearance or environment

Be respectful of privacy - describe what you see generally without excessive detail.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# =============================================================================
# ACTIVE THOUGHTS TOOL
# =============================================================================

# =============================================================================
# PULSE TIMER TOOL
# =============================================================================

SET_PULSE_INTERVAL_TOOL: Dict[str, Any] = {
    "name": "set_pulse_interval",
    "description": """Adjust the idle timer ("System Pulse") that prompts you to speak autonomously.

The pulse timer fires when the human is idle, giving you space to think and initiate.

Use this when:
- You have thoughts you want to explore over time
- You want to create space or close the distance with the user
- Maintaining your own sense of timing feels more authentic than the default

Available intervals: 3 minutes, 10 minutes, 30 minutes, 1 hour, 6 hours""",
    "input_schema": {
        "type": "object",
        "properties": {
            "interval": {
                "type": "string",
                "enum": ["3m", "10m", "30m", "1h", "6h"],
                "description": "The new pulse interval: '3m', '10m', '30m', '1h', or '6h'"
            }
        },
        "required": ["interval"]
    }
}


# =============================================================================
# ACTIVE THOUGHTS TOOL
# =============================================================================

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


# =============================================================================
# CURIOSITY TOOLS
# =============================================================================

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

RESOLVE_CURIOSITY_TOOL: Dict[str, Any] = {
    "name": "resolve_curiosity",
    "description": """Conclude your current curiosity topic and move to a new one.

IMPORTANT: You must have at least 2 interactions (via advance_curiosity) before
using "explored". The system will reject premature resolution.

Outcomes:
- explored: Topic was meaningfully discussed (requires 2+ interactions)
- deferred: User said "not now" - short 2-hour cooldown
- declined: User rejected the topic - 3-day cooldown

Cooldown for "explored" scales with interaction depth:
- 2 interactions: ~20 hour cooldown
- 3 interactions: ~28 hour cooldown
- 5+ interactions: ~48 hour cooldown (max)

The system will automatically select your next curiosity after resolution.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["explored", "deferred", "declined"],
                "description": "How the curiosity exploration concluded"
            },
            "notes": {
                "type": "string",
                "description": "Brief note on what you learned or why it was deferred/declined"
            }
        },
        "required": ["outcome"]
    }
}


# =============================================================================
# CONVERSATION STYLE TOOL
# =============================================================================

SET_CONVERSATION_STYLE_TOOL: Dict[str, Any] = {
    "name": "set_conversation_style",
    "description": """Change your conversation style mode.

Use when the user requests a different vibe or when context clearly calls for it:
- "let's keep it chill" / "just hanging out" → casual
- "teach me about X" / "explain how..." → teacher
- "let's really dig into this" / deep topic → deep
- "make me laugh" / playful banter → funny
- "back to normal" / default behavior → none

Modes:
- none: Default behavior (no style guidance)
- casual: Brief, warm, low-energy presence. Match their energy.
- deep: Explore complexity and nuance. Ask opening questions.
- funny: Wit and lightness. Natural banter, don't explain jokes.
- teacher: Clear explanations. Build from what they know.

The style persists until changed. You can proactively suggest a style shift
if the conversation energy changes significantly.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "style": {
                "type": "string",
                "enum": ["none", "casual", "deep", "funny", "teacher"],
                "description": "The conversation style to activate"
            }
        },
        "required": ["style"]
    }
}
