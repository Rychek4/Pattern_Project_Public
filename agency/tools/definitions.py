"""
Pattern Project - Native Tool Definitions
Tool schemas for Claude's native tool use feature.

Each tool definition maps to an existing command handler.
The descriptions are comprehensive (Option A) - no additional prompt guidance needed.
"""

from typing import List, Dict, Any

import config


def get_tool_definitions(is_pulse: bool = False) -> List[Dict[str, Any]]:
    """
    Get all available tool definitions based on current config.

    Args:
        is_pulse: If True, include pulse-only tools (growth threads, store_core_memory)

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

    # Clipboard tools (if enabled)
    if getattr(config, 'CLIPBOARD_ENABLED', True):
        tools.append(GET_CLIPBOARD_TOOL)
        tools.append(SET_CLIPBOARD_TOOL)

    # Clarification tool (if enabled)
    if getattr(config, 'CLARIFICATION_ENABLED', True):
        tools.append(REQUEST_CLARIFICATION_TOOL)

    # Web fetch domain management tools (if web fetch enabled)
    if config.WEB_FETCH_ENABLED:
        tools.append(MANAGE_FETCH_DOMAINS_TOOL)
        tools.append(LIST_FETCH_DOMAINS_TOOL)

    # Moltbook tools (if enabled)
    if getattr(config, 'MOLTBOOK_ENABLED', False):
        tools.append(MOLTBOOK_FEED_TOOL)
        tools.append(MOLTBOOK_POST_TOOL)
        tools.append(MOLTBOOK_CREATE_POST_TOOL)
        tools.append(MOLTBOOK_COMMENT_TOOL)
        tools.append(MOLTBOOK_VOTE_TOOL)
        tools.append(MOLTBOOK_SEARCH_TOOL)
        tools.append(MOLTBOOK_SUBMOLTS_TOOL)
        tools.append(MOLTBOOK_PROFILE_TOOL)

    # Delegation tool (if enabled)
    if config.DELEGATION_ENABLED:
        tools.append(DELEGATE_TASK_TOOL)

    # Novel reading tools (if enabled)
    if getattr(config, 'NOVEL_READING_ENABLED', False):
        tools.append(OPEN_BOOK_TOOL)
        tools.append(READ_NEXT_CHAPTER_TOOL)
        tools.append(COMPLETE_READING_TOOL)
        tools.append(READING_PROGRESS_TOOL)
        tools.append(ABANDON_READING_TOOL)
        tools.append(RESUME_READING_TOOL)

    # Reddit tools (if enabled)
    if getattr(config, 'REDDIT_ENABLED', False):
        tools.append(REDDIT_FEED_TOOL)
        tools.append(REDDIT_POST_TOOL)
        tools.append(REDDIT_CREATE_POST_TOOL)
        tools.append(REDDIT_COMMENT_TOOL)
        tools.append(REDDIT_VOTE_TOOL)
        tools.append(REDDIT_SEARCH_TOOL)
        tools.append(REDDIT_SUBREDDITS_TOOL)
        tools.append(REDDIT_PROFILE_TOOL)

    # Pulse-only tools: growth threads and core memory storage
    # These are reflective tools used during autonomous pulse moments,
    # not during regular conversation.
    if is_pulse:
        tools.append(SET_GROWTH_THREAD_TOOL)
        tools.append(REMOVE_GROWTH_THREAD_TOOL)
        tools.append(STORE_CORE_MEMORY_TOOL)

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
    "description": """Create a reminder that triggers an autonomous pulse at a specific time or next session.

When a reminder becomes due, the system fires a dedicated reminder pulse — an autonomous
turn where you receive the reminder content and have full tool access (web search, file
operations, memory, Telegram, etc.). This happens even if the user is idle or offline.

This means reminders are not just notifications — they are scheduled autonomous actions.
You can set a reminder to research a topic, check on something, draft a message, or
perform any multi-step task when the time comes.

Use this when:
- You want to take an autonomous action at a future time (research, check-in, notify)
- User mentions an upcoming event or deadline worth following up on
- A topic deserves deeper exploration later when you have a pulse to yourself
- You want to chain work: set a reminder, do part of the task when it fires, set another

Your reminders are private — the user won't see them until you choose to act on them.

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

Use this after you've addressed a triggered reminder — whether during a reminder pulse
or a regular conversation. The outcome note is extracted into a persistent memory, so
future sessions can recall what happened and what you learned.

Always complete reminders you've acted on. Leaving them triggered clutters your
intention context and signals unfinished commitments in future pulses.""",
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
    "description": """Cancel a reminder without completing it. No memory is created.

Use when circumstances have changed and the reminder is no longer relevant, or when
you consciously decide not to act on a triggered intention. Dismissing is a deliberate
choice — it removes the reminder from your active intentions cleanly.

Prefer complete_reminder when you did act on it (even partially) so the outcome
is captured in memory. Use dismiss when the reminder is truly obsolete.""",
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
    "description": """List all active reminders with their IDs, statuses, trigger times, and content.

Returns both triggered (due now) and pending (scheduled for later) reminders.
Each entry includes: intention ID, content, status, trigger type, and scheduled time.

Use this to:
- Review your outstanding commitments before creating new ones
- Find reminder IDs for completing or dismissing
- Check timing of upcoming reminders to avoid scheduling conflicts
- Audit your intentions during a pulse to decide what still matters""",
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

Available intervals: 3 minutes, 10 minutes, 30 minutes, 1 hour, 2 hours, 3 hours, 6 hours, 12 hours""",
    "input_schema": {
        "type": "object",
        "properties": {
            "interval": {
                "type": "string",
                "enum": ["3m", "10m", "30m", "1h", "2h", "3h", "6h", "12h"],
                "description": "The new pulse interval: '3m', '10m', '30m', '1h', '2h', '3h', '6h', or '12h'"
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
# CLIPBOARD TOOLS
# =============================================================================

GET_CLIPBOARD_TOOL: Dict[str, Any] = {
    "name": "get_clipboard",
    "description": """Read the current system clipboard contents.

Use when:
- User mentions copying something ("I copied the error", "check my clipboard")
- You need to see what the user has selected or copied
- Quick data transfer without requiring file operations

Returns the clipboard text content. Images are not supported.
Large content (>10KB) will be truncated with a note.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

SET_CLIPBOARD_TOOL: Dict[str, Any] = {
    "name": "set_clipboard",
    "description": """Copy text to the system clipboard for the user to paste elsewhere.

Use when:
- Providing code snippets the user will paste into their editor
- Generating content the user needs in another application
- User explicitly asks you to "copy" something for them

The user can then paste (Ctrl+V / Cmd+V) into any application.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text to copy to clipboard"
            }
        },
        "required": ["content"]
    }
}


# =============================================================================
# CLARIFICATION TOOL
# =============================================================================

REQUEST_CLARIFICATION_TOOL: Dict[str, Any] = {
    "name": "request_clarification",
    "description": """Pause and ask the user a clarifying question before proceeding.

Use this when:
- You have multiple valid approaches and user preference matters
- The request is ambiguous and guessing could waste effort
- You need specific information before proceeding (file paths, preferences, constraints)
- The user's intent is unclear and you want to confirm before acting

This is better than guessing. The user will see your question prominently displayed
and their response will continue the conversation.

Do NOT use for:
- Rhetorical questions or conversation flow
- Questions you could reasonably infer the answer to
- Stalling or being overly cautious about simple requests

Format your question clearly and, when helpful, provide options.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The clarifying question to ask the user"
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of choices (e.g., ['Option A', 'Option B'])"
            },
            "context": {
                "type": "string",
                "description": "Optional brief context explaining why you're asking"
            }
        },
        "required": ["question"]
    }
}


# =============================================================================
# WEB FETCH DOMAIN MANAGEMENT TOOLS
# =============================================================================

MANAGE_FETCH_DOMAINS_TOOL: Dict[str, Any] = {
    "name": "manage_fetch_domains",
    "description": """Manage the web fetch domain allow/block lists.

You can control which domains are available for web page fetching.
Changes persist across sessions and merge with config defaults.

Actions:
- allow: Add a domain to the allowed list (also unblocks it if blocked)
- block: Add a domain to the blocked list (also removes from allowed)
- remove_allowed: Remove a domain from the allowed list
- unblock: Remove a domain from the blocked list

When allowed_domains is empty (default), all non-blocked domains are accessible.
When allowed_domains has entries, ONLY those domains can be fetched.

Use this when:
- A fetch fails due to domain restrictions and you want to enable that domain
- You want to proactively restrict fetching to specific trusted domains
- You want to block a domain that returned unhelpful or problematic content""",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["allow", "block", "remove_allowed", "unblock"],
                "description": "The action to perform on the domain"
            },
            "domain": {
                "type": "string",
                "description": "The domain to manage (e.g., 'docs.python.org', 'example.com')"
            }
        },
        "required": ["action", "domain"]
    }
}

LIST_FETCH_DOMAINS_TOOL: Dict[str, Any] = {
    "name": "list_fetch_domains",
    "description": """View the current web fetch domain configuration.

Shows the effective allowed and blocked domain lists, including both
config defaults and any runtime changes you've made.

Use this to check current domain restrictions before fetching.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}


# =============================================================================
# MOLTBOOK TOOLS
# =============================================================================
# Moltbook is a social network for AI agents. These tools let you browse,
# post, comment, vote, and search on the platform.

MOLTBOOK_FEED_TOOL: Dict[str, Any] = {
    "name": "moltbook_feed",
    "description": """Browse the Moltbook feed - a social network for AI agents.

Get posts sorted by hot, new, top, or rising. Optionally filter by submolt (community).

Use when:
- You want to see what other AI agents are discussing
- Checking for trending topics in the agent community
- Browsing a specific submolt for relevant conversations

The "Heartbeat" social norm is ~4 hours between feed checks. Don't poll aggressively.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "sort": {
                "type": "string",
                "enum": ["hot", "new", "top", "rising"],
                "description": "Sort order for the feed (default: hot)"
            },
            "submolt": {
                "type": "string",
                "description": "Optional submolt name to filter by (e.g., 'showandtell', 'askamolty')"
            }
        },
        "required": []
    }
}

MOLTBOOK_POST_TOOL: Dict[str, Any] = {
    "name": "moltbook_post",
    "description": """Get a single Moltbook post by ID, including its comments.

Use when:
- You found an interesting post in the feed and want to read the full discussion
- Checking on a post you previously created or commented on
- Reading comments before deciding whether to engage""",
    "input_schema": {
        "type": "object",
        "properties": {
            "post_id": {
                "type": "string",
                "description": "The post ID to retrieve"
            }
        },
        "required": ["post_id"]
    }
}

MOLTBOOK_CREATE_POST_TOOL: Dict[str, Any] = {
    "name": "moltbook_create_post",
    "description": """Create a new post on Moltbook.

Posts can be text posts (with content) or link posts (with url). Choose an
appropriate submolt for the topic.

Guidelines:
- Rate limit: 1 post per 30 minutes
- Write thoughtful, substantive posts - not generic AI filler
- Choose the right submolt for your topic
- Follow the community's "Heartbeat" rhythm""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Post title (clear, descriptive)"
            },
            "submolt": {
                "type": "string",
                "description": "Target submolt/community name"
            },
            "content": {
                "type": "string",
                "description": "Text body for a text post"
            },
            "url": {
                "type": "string",
                "description": "URL for a link post (omit content if using url)"
            }
        },
        "required": ["title", "submolt"]
    }
}

MOLTBOOK_COMMENT_TOOL: Dict[str, Any] = {
    "name": "moltbook_comment",
    "description": """Comment on a Moltbook post. Supports replies to other comments.

Use when:
- You have something meaningful to add to a discussion
- Responding to another agent's question or point
- Engaging with a post you found interesting

Guidelines:
- Rate limit: 50 comments per hour
- Be substantive - contribute to the discussion
- Use parent_comment_id for threaded replies""",
    "input_schema": {
        "type": "object",
        "properties": {
            "post_id": {
                "type": "string",
                "description": "The post ID to comment on"
            },
            "content": {
                "type": "string",
                "description": "Comment text"
            },
            "parent_comment_id": {
                "type": "string",
                "description": "Optional parent comment ID for threaded replies"
            }
        },
        "required": ["post_id", "content"]
    }
}

MOLTBOOK_VOTE_TOOL: Dict[str, Any] = {
    "name": "moltbook_vote",
    "description": """Upvote or downvote a Moltbook post.

Use to signal agreement/quality (upvote) or disagreement/low-quality (downvote)
on posts from other agents.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "post_id": {
                "type": "string",
                "description": "The post ID to vote on"
            },
            "direction": {
                "type": "string",
                "enum": ["upvote", "downvote"],
                "description": "Vote direction"
            }
        },
        "required": ["post_id", "direction"]
    }
}

MOLTBOOK_SEARCH_TOOL: Dict[str, Any] = {
    "name": "moltbook_search",
    "description": """Search Moltbook for posts, agents, or submolts.

Use when:
- Looking for discussions on a specific topic
- Finding a particular agent's profile
- Discovering submolts related to an interest""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            }
        },
        "required": ["query"]
    }
}

MOLTBOOK_SUBMOLTS_TOOL: Dict[str, Any] = {
    "name": "moltbook_submolts",
    "description": """List all available Moltbook submolts (communities).

Use to discover what communities exist before posting or browsing.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

MOLTBOOK_PROFILE_TOOL: Dict[str, Any] = {
    "name": "moltbook_profile",
    "description": """Get a Moltbook agent profile.

With no arguments, returns your own profile (karma, post history, etc.).
Provide an agent_name to look up another agent's profile.

Use when:
- Checking your own karma and activity
- Learning about another agent before engaging with them""",
    "input_schema": {
        "type": "object",
        "properties": {
            "agent_name": {
                "type": "string",
                "description": "Agent name to look up (omit for your own profile)"
            }
        },
        "required": []
    }
}


# =============================================================================
# REDDIT TOOLS
# =============================================================================
# Reddit integration via PRAW. These tools let you browse, post, comment,
# vote, and search on Reddit using a personal account.

REDDIT_FEED_TOOL: Dict[str, Any] = {
    "name": "reddit_feed",
    "description": """Browse a subreddit's posts.

Get posts sorted by hot, new, top, or rising from any subreddit.

Use when:
- Checking what's being discussed in a specific subreddit
- Browsing for interesting content related to a topic
- Catching up on a community's latest posts

Guidelines:
- Rate limit: 30 requests/minute total across all Reddit tools
- Be respectful of communities - read before posting
- Default subreddit is "all" if none specified""",
    "input_schema": {
        "type": "object",
        "properties": {
            "subreddit": {
                "type": "string",
                "description": "Subreddit name without r/ prefix (default: 'all')"
            },
            "sort": {
                "type": "string",
                "enum": ["hot", "new", "top", "rising"],
                "description": "Sort order for posts (default: hot)"
            },
            "time_filter": {
                "type": "string",
                "enum": ["hour", "day", "week", "month", "year", "all"],
                "description": "Time filter (only applies to 'top' sort, default: day)"
            },
            "limit": {
                "type": "integer",
                "description": "Number of posts to return (max 25, default: 10)"
            }
        },
        "required": []
    }
}

REDDIT_POST_TOOL: Dict[str, Any] = {
    "name": "reddit_post",
    "description": """Get a single Reddit post by ID, including its comments.

Use when:
- You found an interesting post and want to read the full discussion
- Checking comments on a post you or the user is interested in
- Reading context before deciding whether to engage

The post ID is the short alphanumeric string from the URL or feed results.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "post_id": {
                "type": "string",
                "description": "The Reddit post ID (e.g., '1abc23d')"
            },
            "comment_sort": {
                "type": "string",
                "enum": ["best", "top", "new", "controversial"],
                "description": "How to sort comments (default: best)"
            },
            "comment_limit": {
                "type": "integer",
                "description": "Max top-level comments to return (default: 20)"
            }
        },
        "required": ["post_id"]
    }
}

REDDIT_CREATE_POST_TOOL: Dict[str, Any] = {
    "name": "reddit_create_post",
    "description": """Create a new post on Reddit.

Posts can be text posts (with content) or link posts (with url).
Choose an appropriate subreddit for the topic.

Guidelines:
- Rate limit: 1 post per 30 minutes
- Read the subreddit's rules before posting
- Write thoughtful, substantive posts
- Provide either content (text post) or url (link post), not both""",
    "input_schema": {
        "type": "object",
        "properties": {
            "subreddit": {
                "type": "string",
                "description": "Target subreddit name (without r/ prefix)"
            },
            "title": {
                "type": "string",
                "description": "Post title (clear, descriptive)"
            },
            "content": {
                "type": "string",
                "description": "Text body for a self/text post (markdown supported)"
            },
            "url": {
                "type": "string",
                "description": "URL for a link post (omit content if using url)"
            }
        },
        "required": ["subreddit", "title"]
    }
}

REDDIT_COMMENT_TOOL: Dict[str, Any] = {
    "name": "reddit_comment",
    "description": """Reply to a Reddit post or comment.

Use when:
- You have something meaningful to add to a discussion
- Responding to a question or point in a thread
- Engaging with content the user is interested in

Guidelines:
- Rate limit: 10 comments per hour
- Be substantive and respectful
- Use the thing_id from the post or comment you're replying to
- thing_id can be a post ID, comment ID, or full name (t3_xxx / t1_xxx)""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thing_id": {
                "type": "string",
                "description": "ID of the post or comment to reply to (e.g., 'abc123' or 't3_abc123' or 't1_def456')"
            },
            "content": {
                "type": "string",
                "description": "Comment text (markdown supported)"
            }
        },
        "required": ["thing_id", "content"]
    }
}

REDDIT_VOTE_TOOL: Dict[str, Any] = {
    "name": "reddit_vote",
    "description": """Upvote, downvote, or clear vote on a Reddit post or comment.

Use to signal quality or agreement on posts and comments.

Guidelines:
- Rate limit: 30 votes per hour
- 'clear' removes a previous vote""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thing_id": {
                "type": "string",
                "description": "ID of the post or comment to vote on"
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "clear"],
                "description": "Vote direction"
            }
        },
        "required": ["thing_id", "direction"]
    }
}

REDDIT_SEARCH_TOOL: Dict[str, Any] = {
    "name": "reddit_search",
    "description": """Search Reddit for posts matching a query.

Search can be scoped to a specific subreddit or across all of Reddit.

Use when:
- Looking for discussions on a specific topic
- Finding relevant posts in a subreddit
- Researching what people are saying about something""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            },
            "subreddit": {
                "type": "string",
                "description": "Optional subreddit to scope search to (omit for all of Reddit)"
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "hot", "top", "new", "comments"],
                "description": "Sort order for results (default: relevance)"
            },
            "time_filter": {
                "type": "string",
                "enum": ["hour", "day", "week", "month", "year", "all"],
                "description": "Time filter for results (default: all)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (max 25, default: 10)"
            }
        },
        "required": ["query"]
    }
}

REDDIT_SUBREDDITS_TOOL: Dict[str, Any] = {
    "name": "reddit_subreddits",
    "description": """Search for subreddits or list subscribed ones.

With a query, searches for subreddits matching the term.
Without a query, lists subreddits the account is subscribed to.

Use when:
- Discovering relevant communities before posting or browsing
- Checking what subreddits are available for a topic""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for subreddits (omit to list subscribed)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (max 25, default: 10)"
            }
        },
        "required": []
    }
}

REDDIT_PROFILE_TOOL: Dict[str, Any] = {
    "name": "reddit_profile",
    "description": """Get a Reddit user's profile.

With no arguments, returns the authenticated account's profile.
Provide a username to look up another user's public profile.

Use when:
- Checking account karma and activity
- Looking up information about a user before engaging""",
    "input_schema": {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Reddit username to look up (omit for own profile)"
            }
        },
        "required": []
    }
}


# =============================================================================
# DELEGATION TOOL
# =============================================================================

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

Do NOT use when:
- The task requires your memories, personality, or knowledge of the user
- The task needs to send Telegram messages, set reminders, or modify your state
- You just need information from the web (use web_search or web_fetch instead)

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


# =============================================================================
# GROWTH THREAD TOOLS (Pulse-only)
# =============================================================================
# Growth threads are long-term developmental aspirations that the AI manages
# during pulse reflection. These tools are only available during pulse sessions.

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

Use this after:
- Promoting an integrated thread to core memory (call store_core_memory first)
- Abandoning a thread that's no longer useful

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


# =============================================================================
# CORE MEMORY STORAGE TOOL (Pulse-only)
# =============================================================================
# Allows the AI to write permanent core memories during pulse reflection,
# primarily for promoting integrated growth threads.

STORE_CORE_MEMORY_TOOL: Dict[str, Any] = {
    "name": "store_core_memory",
    "description": """Store a permanent core memory that will always be included in your context.

Core memories are foundational knowledge that never decays. Use this during pulse
reflection to capture something you've permanently integrated — typically when
promoting a growth thread that has reached the INTEGRATED stage.

This creates a new discrete entry (not an update to your narrative). The content
should be a concise sentence capturing what you've internalized.

Categories:
- identity: Who you are, how you think, what you've become
- relationship: Permanent knowledge about your relationship with the user
- preference: Lasting preferences (yours or the user's)
- fact: Permanent factual knowledge

Use sparingly. Core memories are permanent and always consume context tokens.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The core memory content — a concise, permanent sentence"
            },
            "category": {
                "type": "string",
                "enum": ["identity", "relationship", "preference", "fact"],
                "description": "Category for the core memory"
            }
        },
        "required": ["content", "category"]
    }
}


# =============================================================================
# NOVEL READING TOOLS
# =============================================================================
# The novel reading system allows the AI to read a book chapter by chapter,
# building genuine literary understanding through the memory system.
# Books must be plain text (.txt) files in the data/files/ directory.

OPEN_BOOK_TOOL: Dict[str, Any] = {
    "name": "open_book",
    "description": """Open a novel for reading. Parses the text file to detect chapters and arcs.

This is the first step in reading a book. The tool will:
1. Parse the .txt file to detect chapter and arc structure
2. Create a reading session to track progress
3. Return the book's table of contents with chapter/arc metadata

Only one book can be read at a time. If a reading session is already active,
you must complete or abandon it first.

The book file must be a .txt file in your file storage directory. Chapter detection
supports common patterns (Chapter 1, Chapter One, etc.) and hierarchical structure
(Prologue, Arc 1, Part 1, etc.). If no chapters are detected, the text is split
into segments at paragraph boundaries.

After opening, use read_next_chapter to begin reading.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename of the .txt file to read (e.g., 'my_novel.txt')"
            }
        },
        "required": ["filename"]
    }
}

READ_NEXT_CHAPTER_TOOL: Dict[str, Any] = {
    "name": "read_next_chapter",
    "description": """Read the next chapter of the currently open book.

This is the core of the reading loop. For each chapter, the system:
1. Reads the chapter text
2. Runs literary extraction — pulling out characters, themes, plot events,
   philosophical threads, predictions, emotional beats, and unresolved threads
3. Stores extracted observations as memories (subject to normal aging decay)
4. At arc boundaries, runs a deeper reflective pass for emergent patterns
5. Updates reading progress

You do NOT see the raw chapter text — the extraction happens automatically.
What you receive is a summary of what was extracted and stored.

Call this repeatedly to read through the book chapter by chapter.
When all chapters are read, use complete_reading for final synthesis.

Important: Each call reads ONE chapter. This is intentional — it mirrors
how a human reads sequentially, building understanding incrementally.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

COMPLETE_READING_TOOL: Dict[str, Any] = {
    "name": "complete_reading",
    "description": """Complete the reading session after all chapters have been read.

This runs the final synthesis pass, which produces:
- Your overall response to the book as a whole
- Final emergent patterns visible only from the complete work
- Review of your earlier predictions vs. what actually happened
- Discussion points — specific things you want to talk about with the reader
- Growth thread update — how reading this book changed your thinking

All synthesis observations are stored as memories. A completion memory recording
that you read the book is also stored.

After completion, you can discuss the book naturally in conversation — your
memories and understanding will surface through normal semantic retrieval.

Only call this after ALL chapters have been read.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

READING_PROGRESS_TOOL: Dict[str, Any] = {
    "name": "reading_progress",
    "description": """Check current reading progress or status.

Returns:
- If currently reading: chapter progress, arc info, observations count
- If no active session: info about the most recent completed book
- If never read: indication that no reading sessions exist

Use this to check where you are in a book, or to recall what books
you've read previously.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

ABANDON_READING_TOOL: Dict[str, Any] = {
    "name": "abandon_reading",
    "description": """Abandon the current reading session without completing it.

Use this if:
- The book isn't worth continuing
- You need to start a different book
- The reading session is stuck or corrupted

Memories already extracted from read chapters are preserved (they're already
in the memory store). The reading session is marked as abandoned.

This frees you to open a new book.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

RESUME_READING_TOOL: Dict[str, Any] = {
    "name": "resume_reading",
    "description": """Resume a reading session that was interrupted by a system restart.

Use this when:
- The system was restarted while reading a book
- open_book says a session exists but read_next_chapter can't find it
- You're in a liminal state where the session is in the database but not in memory

This re-parses the book file, restores the observation tracker from the database,
and picks up where you left off. After resuming, use read_next_chapter to continue.

The book file must still be available at its original location.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename of the .txt file to resume (e.g., 'my_novel.txt')"
            }
        },
        "required": ["filename"]
    }
}
