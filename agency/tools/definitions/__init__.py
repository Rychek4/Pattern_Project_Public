"""
Pattern Project - Native Tool Definitions
Tool schemas for Claude's native tool use feature, organized by domain.

Each tool definition maps to an existing command handler.
The descriptions are comprehensive — no additional prompt guidance needed.

Modules:
    memory_tools       — Semantic memory search
    reminder_tools     — Intention/reminder lifecycle
    file_tools         — Sandboxed file operations
    communication_tools — Telegram messaging
    visual_tools       — Screenshot, webcam, image memory
    agency_tools       — Active thoughts, pulse, curiosity, delegation
    web_tools          — Web fetch domain management
    reddit_tools       — Reddit browsing, posting, commenting
    growth_tools       — Growth thread lifecycle (pulse-only)
    reading_tools      — Novel reading system
    calendar_tools     — Google Calendar integration
    blog_tools         — Blog publishing
    metacognition_tools — Memory metacognition (pulse-only)
"""

from typing import List, Dict, Any

import config

# --- Memory ---
from agency.tools.definitions.memory_tools import SEARCH_MEMORIES_TOOL

# --- Reminders ---
from agency.tools.definitions.reminder_tools import (
    CREATE_REMINDER_TOOL,
    COMPLETE_REMINDER_TOOL,
    DISMISS_REMINDER_TOOL,
    LIST_REMINDERS_TOOL,
)

# --- Files ---
from agency.tools.definitions.file_tools import (
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    APPEND_FILE_TOOL,
    LIST_FILES_TOOL,
    CREATE_DIRECTORY_TOOL,
    MOVE_FILE_TOOL,
)

# --- Communication ---
from agency.tools.definitions.communication_tools import SEND_TELEGRAM_TOOL

# --- Visual ---
from agency.tools.definitions.visual_tools import (
    CAPTURE_SCREENSHOT_TOOL,
    CAPTURE_WEBCAM_TOOL,
    SAVE_IMAGE_TOOL,
)

# --- Agency ---
from agency.tools.definitions.agency_tools import (
    SET_PULSE_INTERVAL_TOOL,
    SET_ACTIVE_THOUGHTS_TOOL,
    ADVANCE_CURIOSITY_TOOL,
    DELEGATE_TASK_TOOL,
)

# --- Web ---
from agency.tools.definitions.web_tools import (
    MANAGE_FETCH_DOMAINS_TOOL,
    LIST_FETCH_DOMAINS_TOOL,
)

# --- Reddit ---
from agency.tools.definitions.reddit_tools import (
    REDDIT_FEED_TOOL,
    REDDIT_POST_TOOL,
    REDDIT_CREATE_POST_TOOL,
    REDDIT_COMMENT_TOOL,
    REDDIT_VOTE_TOOL,
    REDDIT_SEARCH_TOOL,
    REDDIT_SUBREDDITS_TOOL,
    REDDIT_PROFILE_TOOL,
)

# --- Growth Threads (pulse-only) ---
from agency.tools.definitions.growth_tools import (
    SET_GROWTH_THREAD_TOOL,
    REMOVE_GROWTH_THREAD_TOOL,
    PROMOTE_GROWTH_THREAD_TOOL,
)

# --- Novel Reading ---
from agency.tools.definitions.reading_tools import (
    OPEN_BOOK_TOOL,
    READ_NEXT_CHAPTER_TOOL,
    COMPLETE_READING_TOOL,
    READING_PROGRESS_TOOL,
    ABANDON_READING_TOOL,
    RESUME_READING_TOOL,
)

# --- Google Calendar ---
from agency.tools.definitions.calendar_tools import (
    LIST_CALENDAR_EVENTS_TOOL,
    CREATE_CALENDAR_EVENT_TOOL,
    UPDATE_CALENDAR_EVENT_TOOL,
    DELETE_CALENDAR_EVENT_TOOL,
)

# --- Blog ---
from agency.tools.definitions.blog_tools import (
    PUBLISH_BLOG_POST_TOOL,
    SAVE_BLOG_DRAFT_TOOL,
    EDIT_BLOG_POST_TOOL,
    LIST_BLOG_POSTS_TOOL,
    UNPUBLISH_BLOG_POST_TOOL,
)

# --- Metacognition (pulse-only) ---
from agency.tools.definitions.metacognition_tools import (
    STORE_BRIDGE_MEMORY_TOOL,
    STORE_META_OBSERVATION_TOOL,
    UPDATE_MEMORY_SELF_MODEL_TOOL,
)


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
