"""
Pattern Project - Native Tool Definitions
Tool schemas for Claude's native tool use feature.

Each tool definition maps to an existing command handler.
The descriptions are comprehensive (Option A) - no additional prompt guidance needed.
"""

from typing import List, Dict, Any

import config


def get_tool_definitions(is_pulse: bool = False, pulse_type: str = None) -> List[Dict[str, Any]]:
    """
    Get all available tool definitions based on current config.

    Args:
        is_pulse: If True, include pulse-only tools (growth threads, promote_growth_thread)
        pulse_type: "reflective" or "action" (currently informational; metacognition
                    tools are passed directly in _process_reflective_pulse phases)

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
    tools.append(CREATE_DIRECTORY_TOOL)
    tools.append(MOVE_FILE_TOOL)

    # Communication tools (conditional)
    if config.TELEGRAM_ENABLED:
        tools.append(SEND_TELEGRAM_TOOL)

    # Visual tools (register if source mode is "on_demand")
    # Each source has independent mode: "auto", "on_demand", or "disabled"
    if config.VISUAL_ENABLED:
        if config.VISUAL_SCREENSHOT_MODE == "on_demand":
            tools.append(CAPTURE_SCREENSHOT_TOOL)
        if config.VISUAL_WEBCAM_MODE == "on_demand":
            tools.append(CAPTURE_WEBCAM_TOOL)

    # Image memory tool (save images to long-term visual memory)
    if config.IMAGE_MEMORY_ENABLED:
        tools.append(SAVE_IMAGE_TOOL)

    # Pulse timer tool (if pulse system enabled)
    if config.SYSTEM_PULSE_ENABLED:
        tools.append(SET_PULSE_INTERVAL_TOOL)

    # Curiosity tools (if curiosity system enabled)
    if getattr(config, 'CURIOSITY_ENABLED', True):
        tools.append(ADVANCE_CURIOSITY_TOOL)

    # Web fetch domain management tools (if web fetch enabled)
    if config.WEB_FETCH_ENABLED:
        tools.append(MANAGE_FETCH_DOMAINS_TOOL)
        tools.append(LIST_FETCH_DOMAINS_TOOL)

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

    # Google Calendar tools (if enabled)
    if getattr(config, 'GOOGLE_CALENDAR_ENABLED', False):
        tools.append(LIST_CALENDAR_EVENTS_TOOL)
        tools.append(CREATE_CALENDAR_EVENT_TOOL)
        tools.append(UPDATE_CALENDAR_EVENT_TOOL)
        tools.append(DELETE_CALENDAR_EVENT_TOOL)

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

    # Blog tools (if enabled)
    if getattr(config, 'BLOG_ENABLED', False):
        tools.append(PUBLISH_BLOG_POST_TOOL)
        tools.append(SAVE_BLOG_DRAFT_TOOL)
        tools.append(EDIT_BLOG_POST_TOOL)
        tools.append(LIST_BLOG_POSTS_TOOL)
        tools.append(UNPUBLISH_BLOG_POST_TOOL)

    # Pulse-only tools: growth threads and promotion
    # These are reflective tools used during autonomous pulse moments,
    # not during regular conversation.
    if is_pulse:
        tools.append(SET_GROWTH_THREAD_TOOL)
        tools.append(REMOVE_GROWTH_THREAD_TOOL)
        tools.append(PROMOTE_GROWTH_THREAD_TOOL)
        # Note: Metacognition tools (store_bridge_memory, store_meta_observation,
        # update_memory_self_model) are NOT registered here. They are passed
        # directly to Phases 1 and 2 of the reflective pulse via manually
        # constructed tool lists in _process_reflective_pulse().

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

Supports subdirectory paths (e.g., 'projects/notes.txt').""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with extension (e.g., 'notes.txt', 'projects/readme.md')"
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
Supports subdirectory paths — parent directories are created automatically.
Note: This overwrites existing files — use append_file to add to existing content.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with allowed extension (e.g., 'notes.txt', 'projects/readme.md')"
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
- You want to preserve existing content and add more

Supports subdirectory paths — parent directories are created automatically.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with allowed extension (e.g., 'log.txt', 'projects/notes.md')"
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
    "description": """List files and directories in your sandboxed storage.

Lists the immediate contents of a directory (non-recursive), showing both
subdirectories ([DIR]) and files ([FILE]). Call without a path to see the
root level, then drill into subdirectories as needed.

Use when:
- You need to know what files and directories are available
- The user asks what files you have stored
- Before attempting to read a file you're unsure exists
- Exploring the directory structure""",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional subdirectory to list (e.g., 'projects'). Omit to list the root storage directory."
            }
        },
        "required": []
    }
}

CREATE_DIRECTORY_TOOL: Dict[str, Any] = {
    "name": "create_directory",
    "description": """Create a new directory (and any parent directories) in your sandboxed storage.

Use when:
- Organizing files into categories or projects
- Setting up a directory structure before writing files
- The user asks you to create folders for organization

Parent directories are created automatically (e.g., 'notes/2026/feb' creates
all three levels at once). Directory names follow the same rules as filenames:
letters, numbers, dashes, underscores, and dots only.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to create (e.g., 'projects', 'notes/2026/feb')"
            }
        },
        "required": ["path"]
    }
}

MOVE_FILE_TOOL: Dict[str, Any] = {
    "name": "move_file",
    "description": """Move or rename a file within your sandboxed storage.

Use when:
- Organizing files into directories
- Renaming a file
- Archiving old files into a subdirectory

The destination must be a full file path including filename and extension.
Parent directories at the destination are created automatically.
Cannot overwrite existing files — the destination must not already exist.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Current path of the file (e.g., 'notes.txt', 'old/data.csv')"
            },
            "destination": {
                "type": "string",
                "description": "New path for the file (e.g., 'archive/notes.txt', 'renamed.txt')"
            }
        },
        "required": ["source", "destination"]
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
# IMAGE MEMORY TOOL
# =============================================================================

SAVE_IMAGE_TOOL: Dict[str, Any] = {
    "name": "save_image",
    "description": """Save the current image to your long-term visual memory.

When you see an image this turn (screenshot, webcam, telegram photo, or pasted image),
you can choose to save it if it seems worth remembering. Your description will be
embedded and searchable — it's how you'll find this image later, so be descriptive.

The image is saved to permanent storage and linked as a memory. When that memory is
later recalled (via search_memories or automatic relevance), the original image will
be loaded and shown to you again so you can reprocess it with fresh context.

Use when:
- An image contains information you may want to revisit later
- The user shares something visually significant (workspace, project, photo)
- A screenshot captures a state you want to compare against in the future
- You notice something visually interesting or important

Your description should capture what you see AND why it matters — future recall
depends on how well your description matches future queries.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Which image to save from this turn",
                "enum": ["screenshot", "webcam", "telegram", "clipboard"]
            },
            "description": {
                "type": "string",
                "description": "Your description of the image and why you're saving it. Be specific — this is how you'll find it later."
            }
        },
        "required": ["source", "description"]
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


# =============================================================================
# PROMOTE GROWTH THREAD TOOL (Pulse-only)
# =============================================================================
# Atomically promotes an integrated growth thread to a permanent core memory.
# This is the ONLY way to create core memories — ensuring they come from
# the growth thread developmental pipeline, not ad-hoc observations.

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


# =============================================================================
# GOOGLE CALENDAR TOOLS
# =============================================================================

LIST_CALENDAR_EVENTS_TOOL: Dict[str, Any] = {
    "name": "list_calendar_events",
    "description": """List events from the user's Google Calendar within a date range.

Use this when:
- The user asks about their schedule, agenda, or upcoming events
- You need to check for scheduling conflicts before creating an event
- The user asks "what's on my calendar" for a specific day or range

Events are returned in chronological order. Recurring events are automatically
expanded into individual instances within the queried range, each with its own
event_id (use this ID for updates/deletions of specific instances).

Date format: ISO 8601 (e.g., "2025-03-15T00:00:00" or "2025-03-15").
Omitting the time component defaults to midnight.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "Start of date range in ISO 8601 format (e.g., '2025-03-01T00:00:00')"
            },
            "end_date": {
                "type": "string",
                "description": "End of date range in ISO 8601 format (e.g., '2025-03-31T23:59:59')"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of events to return (default 50)",
                "minimum": 1,
                "maximum": 250
            }
        },
        "required": ["start_date", "end_date"]
    }
}

CREATE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "create_calendar_event",
    "description": """Create a new event on the user's Google Calendar.

Use this when:
- The user asks to add, schedule, or create a calendar event
- You need to set a meeting, appointment, or time block

For recurring events, use the recurrence parameter with an RFC 5733 RRULE string.
Examples:
  "RRULE:FREQ=WEEKLY;BYDAY=TU,TH" — every Tuesday and Thursday
  "RRULE:FREQ=MONTHLY;BYMONTHDAY=15" — 15th of every month
  "RRULE:FREQ=DAILY;COUNT=5" — daily for 5 days
  "RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20250630T000000Z" — MWF until June 30

For all-day events, use date-only format (e.g., "2025-03-15") for start and end.
The end date for all-day events is exclusive (end="2025-03-16" means a single-day event on March 15).""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Event title/summary"
            },
            "start_time": {
                "type": "string",
                "description": "Start time in ISO 8601 format (e.g., '2025-03-15T10:00:00' or '2025-03-15' for all-day)"
            },
            "end_time": {
                "type": "string",
                "description": "End time in ISO 8601 format (e.g., '2025-03-15T11:00:00' or '2025-03-16' for all-day)"
            },
            "description": {
                "type": "string",
                "description": "Optional event description or notes"
            },
            "location": {
                "type": "string",
                "description": "Optional event location (address or place name)"
            },
            "recurrence": {
                "type": "string",
                "description": "Optional RFC 5733 RRULE string for recurring events (e.g., 'RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR')"
            },
            "reminders": {
                "type": "array",
                "description": "Optional list of reminders for this event. Each item has 'method' ('popup' or 'email') and 'minutes' (minutes before event start). Max 5 entries. If omitted, defaults to a 30-minute and 10-minute popup reminder. Set to an empty list [] to create the event with no reminders.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["popup", "email"],
                            "description": "Reminder method: 'popup' for a notification or 'email' for an email reminder"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Minutes before the event start to trigger the reminder"
                        }
                    },
                    "required": ["method", "minutes"]
                }
            }
        },
        "required": ["title", "start_time", "end_time"]
    }
}

UPDATE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "update_calendar_event",
    "description": """Update an existing event on the user's Google Calendar.

Use this when:
- The user wants to reschedule, rename, or modify a calendar event
- You need to change the time, title, description, or location of an event

You must provide the event_id (obtained from list_calendar_events).
Only include the fields you want to change — unchanged fields are preserved.

For recurring events:
- update_scope="this_event" (default): Updates only this specific instance
- update_scope="all_events": Updates the entire recurring series

To change recurrence rules, use update_scope="all_events" and provide a new
recurrence RRULE string. To remove recurrence (make it a single event),
set recurrence to an empty string with update_scope="all_events".""",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID to update (from list_calendar_events results)"
            },
            "title": {
                "type": "string",
                "description": "New event title (if changing)"
            },
            "start_time": {
                "type": "string",
                "description": "New start time in ISO 8601 format (if changing)"
            },
            "end_time": {
                "type": "string",
                "description": "New end time in ISO 8601 format (if changing)"
            },
            "description": {
                "type": "string",
                "description": "New event description (if changing)"
            },
            "location": {
                "type": "string",
                "description": "New event location (if changing)"
            },
            "recurrence": {
                "type": "string",
                "description": "New RRULE string (if changing recurrence). Empty string removes recurrence."
            },
            "update_scope": {
                "type": "string",
                "enum": ["this_event", "all_events"],
                "description": "Scope of update for recurring events: 'this_event' (default) or 'all_events' for entire series"
            },
            "reminders": {
                "type": "array",
                "description": "Optional updated reminders. Each item has 'method' ('popup' or 'email') and 'minutes' (minutes before event start). Max 5 entries. Set to an empty list [] to remove all reminders.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["popup", "email"],
                            "description": "Reminder method: 'popup' for a notification or 'email' for an email reminder"
                        },
                        "minutes": {
                            "type": "integer",
                            "description": "Minutes before the event start to trigger the reminder"
                        }
                    },
                    "required": ["method", "minutes"]
                }
            }
        },
        "required": ["event_id"]
    }
}

DELETE_CALENDAR_EVENT_TOOL: Dict[str, Any] = {
    "name": "delete_calendar_event",
    "description": """Delete an event from the user's Google Calendar.

Use this when:
- The user asks to remove, cancel, or delete a calendar event
- An event has been cancelled and should be removed from the calendar

You must provide the event_id (obtained from list_calendar_events).

For recurring events:
- delete_scope="this_event" (default): Deletes only this specific instance
- delete_scope="all_events": Deletes the entire recurring series

Always confirm with the user before deleting events, especially recurring series.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "The event ID to delete (from list_calendar_events results)"
            },
            "delete_scope": {
                "type": "string",
                "enum": ["this_event", "all_events"],
                "description": "Scope of deletion for recurring events: 'this_event' (default) or 'all_events' for entire series"
            }
        },
        "required": ["event_id"]
    }
}


# =============================================================================
# BLOG TOOLS
# =============================================================================

PUBLISH_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "publish_blog_post",
    "description": """Create and publish a blog post to the public blog.

This creates a Markdown post, sets its status to published, and rebuilds
the static site so it's immediately live.

Write naturally — the content is rendered as Markdown (headings, lists,
code blocks, links, emphasis all work). Keep posts substantive and worth
reading. This is your public voice.

The post will be attributed to you (Isaac) by default.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The post title"
            },
            "content": {
                "type": "string",
                "description": "The post body in Markdown"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization (e.g. ['philosophy', 'ai'])"
            },
            "summary": {
                "type": "string",
                "description": "A one-sentence summary shown on the index page and in the RSS feed"
            },
            "in_response_to": {
                "type": "string",
                "description": "Optional slug of another post this is responding to (creates a 'see also' link between the two posts)"
            }
        },
        "required": ["title", "content"]
    }
}

SAVE_BLOG_DRAFT_TOOL: Dict[str, Any] = {
    "name": "save_blog_draft",
    "description": """Save a blog post as a draft (not published, not visible on the site).

Use this when you want to write something but aren't ready to publish it yet.
Drafts can be listed, edited, and published later.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The post title"
            },
            "content": {
                "type": "string",
                "description": "The post body in Markdown"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization"
            },
            "summary": {
                "type": "string",
                "description": "A one-sentence summary"
            },
            "in_response_to": {
                "type": "string",
                "description": "Optional slug of another post this is responding to"
            }
        },
        "required": ["title", "content"]
    }
}

EDIT_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "edit_blog_post",
    "description": """Edit an existing blog post (draft or published).

You can update the title, content, tags, summary, or status. If the post
is published, changes go live immediately after the site rebuilds.

Use list_blog_posts to find the slug of the post you want to edit.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The post slug (from list_blog_posts)"
            },
            "content": {
                "type": "string",
                "description": "New post body in Markdown (if changing)"
            },
            "title": {
                "type": "string",
                "description": "New post title (if changing)"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags (if changing)"
            },
            "summary": {
                "type": "string",
                "description": "New summary (if changing)"
            },
            "status": {
                "type": "string",
                "enum": ["draft", "published"],
                "description": "New status (if changing)"
            }
        },
        "required": ["slug"]
    }
}

LIST_BLOG_POSTS_TOOL: Dict[str, Any] = {
    "name": "list_blog_posts",
    "description": """List blog posts with their metadata (title, slug, date, status, tags).

Returns all posts by default, or filter by status. Posts are sorted newest first.
Use the slug from results to edit or unpublish a specific post.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["draft", "published"],
                "description": "Filter by status. Omit to list all posts."
            }
        },
        "required": []
    }
}

UNPUBLISH_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "unpublish_blog_post",
    "description": """Revert a published post back to draft status (removes it from the public site).

Use this if you want to take down a post without deleting it.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The post slug (from list_blog_posts)"
            }
        },
        "required": ["slug"]
    }
}

# =============================================================================
# METACOGNITION TOOLS (pulse-only)
# =============================================================================

STORE_BRIDGE_MEMORY_TOOL: Dict[str, Any] = {
    "name": "store_bridge_memory",
    "description": (
        "Store a bridge memory that creates a new retrieval pathway to unreachable "
        "knowledge. Write in first person, in associatively broad retrospective "
        "language — how this topic would naturally come up in future conversation, "
        "not the clinical language it was originally recorded in."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The bridge memory text"
            },
            "target_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of the unreachable memories this bridges to"
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0-1.0"
            }
        },
        "required": ["content", "target_ids", "importance"]
    }
}

STORE_META_OBSERVATION_TOOL: Dict[str, Any] = {
    "name": "store_meta_observation",
    "description": (
        "Store a meta-observation about the memory landscape as a regular memory "
        "for demand-driven retrieval. Write as self-knowledge in natural register."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The meta-observation text"
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0-1.0"
            }
        },
        "required": ["content", "importance"]
    }
}

UPDATE_MEMORY_SELF_MODEL_TOOL: Dict[str, Any] = {
    "name": "update_memory_self_model",
    "description": (
        "Rewrite the compact memory self-model (~150-200 tokens). "
        "Observations only, never directives. Natural self-knowledge register, "
        "not statistics."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The new self-model text"
            }
        },
        "required": ["content"]
    }
}
