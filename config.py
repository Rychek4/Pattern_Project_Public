"""
Pattern Project - Configuration
Feature flags, constants, and intervals
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# =============================================================================
# PATHS
# =============================================================================
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
DATABASE_PATH = DATA_DIR / "pattern.db"
DIAGNOSTIC_LOG_PATH = LOGS_DIR / "diagnostic.log"

# =============================================================================
# VERSION
# =============================================================================
VERSION = "0.1.0"
PROJECT_NAME = "Pattern Project"

# =============================================================================
# USER IDENTITY
# =============================================================================
# The name used when formatting conversations and extracting memories.
# This ensures consistent entity naming for better semantic memory retrieval.
# TODO: Eventually prompt for this at first boot instead of hardcoding.
USER_NAME = os.getenv("USER_NAME", "Brian")
AI_NAME = os.getenv("AI_NAME", "Claude")

# =============================================================================
# LLM CONFIGURATION
# =============================================================================
# Anthropic (Claude)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")  # Default/fallback model
ANTHROPIC_MODEL_CONVERSATION = os.getenv("ANTHROPIC_MODEL_CONVERSATION", "claude-opus-4-5-20251101")  # User-facing chat (Opus)
ANTHROPIC_MODEL_EXTRACTION = os.getenv("ANTHROPIC_MODEL_EXTRACTION", "claude-sonnet-4-5-20250929")  # Memory extraction (Sonnet)
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

# KoboldCpp (Local)
KOBOLD_API_URL = os.getenv("KOBOLD_API_URL", "http://127.0.0.1:5001")
KOBOLD_MAX_CONTEXT = int(os.getenv("KOBOLD_MAX_CONTEXT", "4096"))
KOBOLD_MAX_LENGTH = int(os.getenv("KOBOLD_MAX_LENGTH", "512"))

# Routing
LLM_PRIMARY_PROVIDER = os.getenv("LLM_PRIMARY_PROVIDER", "anthropic")  # 'anthropic' or 'kobold'
# LLM_EXTRACTION_PROVIDER - DEPRECATED: Unified extraction now uses API (single call)
# Memory extraction was consolidated from 5+ local LLM calls to 1 API call for better quality
LLM_FALLBACK_ENABLED = True  # Fall back to kobold if anthropic fails (not for extraction)

# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DB_BUSY_TIMEOUT_MS = 10000
DB_MAX_RETRIES = 5
DB_RETRY_INITIAL_DELAY = 0.1
DB_RETRY_BACKOFF_MULTIPLIER = 2.0

# =============================================================================
# EMBEDDING CONFIGURATION
# =============================================================================
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# =============================================================================
# MEMORY CONFIGURATION
# =============================================================================
MEMORY_FRESHNESS_HALF_LIFE_DAYS = 14  # Decay rate for freshness scoring (more recency bias)

# -----------------------------------------------------------------------------
# Context Window & Extraction (Windowed System)
# -----------------------------------------------------------------------------
# The context window holds recent conversation turns for the LLM prompt.
# When the window exceeds its limit, oldest turns are extracted to memory
# and removed from the active context.
#
# This replaces the old threshold-based extraction system where context
# and extraction operated independently, leading to duplicate memories.
#
# Flow: Context Window (30) → Overflow (40) → Extract oldest 10 → Back to 30
# The context window spans sessions for AI continuity.
CONTEXT_WINDOW_SIZE = 30           # Target turns to keep in active context
CONTEXT_OVERFLOW_TRIGGER = 40      # Extract when context reaches this size
CONTEXT_EXTRACTION_BATCH = 10      # Turns to extract per overflow (40 - 30 = 10)

# DEPRECATED: Old threshold-based extraction (replaced by windowed system)
# MEMORY_EXTRACTION_THRESHOLD = 10  # No longer used - see CONTEXT_OVERFLOW_TRIGGER

# -----------------------------------------------------------------------------
# Dual-Track Retrieval Settings
# -----------------------------------------------------------------------------
# Memories are now extracted in two categories:
#   - Episodic: Narrative memories about what happened ("We discussed X")
#   - Factual: Concrete facts extracted from conversation ("Brian is 45")
#
# Retrieval queries both categories separately to ensure balanced results.
MEMORY_MAX_EPISODIC_PER_QUERY = 5   # Max episodic memories to retrieve
MEMORY_MAX_FACTUAL_PER_QUERY = 5    # Max factual memories to retrieve
MEMORY_RELEVANCE_FLOOR = 0.35       # Minimum combined score to include (filters noise)

# Legacy setting (used for tool-based search without category filter)
MEMORY_MAX_PER_QUERY = 10  # Updated from 3 to accommodate both categories

# -----------------------------------------------------------------------------
# Retrieval Deduplication
# -----------------------------------------------------------------------------
# When retrieving memories, near-identical results are collapsed to prevent
# the same fact from consuming multiple retrieval slots.
#
# Example: If "Brian is 45" appears 3 times due to being mentioned in
# different conversations, only the highest-scored one is returned.
MEMORY_DEDUP_ENABLED = True
MEMORY_DEDUP_THRESHOLD = 0.85      # Embedding similarity threshold for "duplicate"

# -----------------------------------------------------------------------------
# Dual-Track Extraction Settings
# -----------------------------------------------------------------------------
# Both extraction passes run on same trigger (40 unprocessed turns → extract 10).
# Episodic extraction uses topic clustering; factual extraction scans whole batch.
MEMORY_MAX_EPISODIC_PER_EXTRACTION = 6   # Max episodic memories per extraction run
MEMORY_MAX_FACTUAL_PER_EXTRACTION = 8    # Max factual memories per extraction run (facts are granular)

# Topic-Based Extraction Settings (for episodic extraction)
# These control how conversations are clustered into topics before memory creation
MEMORY_MIN_TURNS_PER_TOPIC = 1  # Allow single-turn topics (importance isn't determined by length)
MEMORY_MAX_PER_EXTRACTION = 3  # Legacy: Hard cap on memories (now MEMORY_MAX_EPISODIC_PER_EXTRACTION)
MEMORY_SKIP_MINOR_TOPICS = True  # Skip topics marked as "minor" significance
MEMORY_LARGE_TOPIC_THRESHOLD = 15  # Topics with more turns may get 2 memories
MEMORY_SMALL_BATCH_THRESHOLD = 10  # Below this turn count, preserve all topics (don't skip minor)

# Importance floor for memory storage
# Memories rated below this threshold are not stored (filters trivial content)
# Scale: 0.0-1.0 (maps from 0-10 LLM rating)
# - 0.0-0.1: Trivial or forgettable
# - 0.2-0.4: Minor details, casual observations
# - 0.5-0.7: Useful information, moderate preferences
# - 0.8-1.0: Major decisions, significant events
MEMORY_IMPORTANCE_FLOOR = 0.3  # Don't store memories below this importance

# Scoring weights for memory retrieval (must sum to 1.0)
# Prioritizes semantic relevance and importance over recency
# NOTE: Access weight is 0.0 - recency is now handled by the Warmth Cache system
# at the application layer (see semantic_memory.py WarmthCache)
MEMORY_SEMANTIC_WEIGHT = 0.65  # Semantic similarity to query (boosted - semantic is king)
MEMORY_IMPORTANCE_WEIGHT = 0.25  # Memory importance score (value-aware retrieval)
MEMORY_FRESHNESS_WEIGHT = 0.10  # Recency of memory source (tie-breaker)
MEMORY_ACCESS_WEIGHT = 0.00  # DEPRECATED: Handled by Warmth Cache at application layer

# -----------------------------------------------------------------------------
# Memory Warmth Cache System
# -----------------------------------------------------------------------------
# The Warmth Cache provides session-scoped memory boosting for conversational
# continuity. It tracks two types of "warmth":
#
# 1. Retrieval Warmth: Memories that were retrieved and injected in recent turns
#    - Ensures recently discussed topics stay accessible even if next query
#      doesn't directly reference them
#    - Example: Discussed "Clair Obscura awards", user asks "what studio made it?"
#      The award memory stays warm even though "studio" doesn't match "awards"
#
# 2. Topic Warmth: Memories semantically related to retrieved memories
#    - Pre-warms associated memories for predictive loading
#    - Uses same-session clustering + embedding similarity
#    - Example: Retrieve "won 11 awards" → pre-warm "developed by Sandfall"
#
# Both decay each turn, creating a natural conversational memory window.
WARMTH_RETRIEVAL_INITIAL = 0.15     # Boost for directly retrieved memories
WARMTH_RETRIEVAL_DECAY = 0.6        # Per-turn decay multiplier (4-turn lifespan)
WARMTH_TOPIC_INITIAL = 0.10         # Boost for associated memories
WARMTH_TOPIC_DECAY = 0.5            # Per-turn decay multiplier (3-turn lifespan)
WARMTH_CAP = 0.20                   # Maximum combined warmth boost
WARMTH_TOPIC_SIMILARITY_THRESHOLD = 0.5   # Min similarity for topic association
WARMTH_TOPIC_MAX_EXPANSION = 20     # Cap on topic-warm memories per turn

# Over-fetch multiplier for warmth-based re-ranking
# We fetch more candidates than needed, apply warmth, re-rank, then take top N
MEMORY_OVERFETCH_MULTIPLIER = 2.4

# =============================================================================
# DECAY CATEGORY CONFIGURATION
# =============================================================================
# Memories are assigned a decay_category that controls how quickly they fade
# from relevance. This affects the freshness score used in memory retrieval.
#
# Categories:
#   - permanent: Never decays (half_life = None). For core identity facts,
#                lasting preferences, and biographical information.
#   - standard:  Normal decay rate. For events, discussions, and insights
#                that stay relevant for weeks/months.
#   - ephemeral: Fast decay. For time-bound observations, current mood,
#                temporary circumstances that lose relevance quickly.
#
# The half-life is the number of days until a memory's freshness score drops
# to 50% of its original value. After 2 half-lives it's at 25%, etc.
#
# Decay category is inferred from memory_type and importance at extraction
# time - no additional LLM call required.
DECAY_HALF_LIFE_STANDARD = 30.0   # 30 days - normal memories
DECAY_HALF_LIFE_EPHEMERAL = 7.0   # 7 days - fast-fading observations

# =============================================================================
# SESSION CONFIGURATION
# =============================================================================
SESSION_IDLE_WARNING_SECONDS = 600  # 10 minutes
SESSION_AUTO_EXTRACT_ON_END = True

# =============================================================================
# AGENCY CONFIGURATION (Legacy - Disabled in favor of System Pulse)
# =============================================================================
AGENCY_ENABLED = False  # Disabled - replaced by System Pulse Timer
AGENCY_CHECK_INTERVAL = 300  # 5 minutes
AGENCY_IDLE_TRIGGER_SECONDS = 900  # 15 minutes before AI initiates

# =============================================================================
# SYSTEM PULSE CONFIGURATION
# =============================================================================
SYSTEM_PULSE_ENABLED = True
SYSTEM_PULSE_INTERVAL = 600  # 10 minutes between pulses (default)

# =============================================================================
# CURIOSITY ENGINE CONFIGURATION
# =============================================================================
# The curiosity engine gives the AI topics to explore during conversation.
# It identifies both dormant topics from memory AND fresh discoveries,
# using weighted random selection for natural variety.
CURIOSITY_ENABLED = True

# Dormant revival settings - resurface old forgotten topics
CURIOSITY_DORMANT_DAYS = 7            # Topic "dormant" after 7 days without access
CURIOSITY_DORMANT_MIN_AGE_DAYS = 2    # Minimum age for never-accessed memories to be dormant
CURIOSITY_MIN_IMPORTANCE = 0.4        # Minimum memory importance for dormant

# Fresh discovery settings - explore new interesting information
CURIOSITY_FRESH_HOURS = 48            # Memories within 48h are "fresh"
CURIOSITY_FRESH_MIN_IMPORTANCE = 0.5  # Include MEDIUM importance (0.55) memories

# Interaction tracking - ensure topics are actually explored
CURIOSITY_MIN_INTERACTIONS = 2        # Minimum exchanges before "explored" is valid

# Cooldown periods (hours) - scaled based on exploration depth
CURIOSITY_COOLDOWN_EXPLORED_MIN = 4   # Shallow exploration minimum
CURIOSITY_COOLDOWN_EXPLORED_MAX = 48  # Deep exploration maximum
CURIOSITY_COOLDOWN_PER_INTERACTION = 8  # Hours added per interaction
CURIOSITY_COOLDOWN_DEFERRED = 2       # "not now" - brief cooldown
CURIOSITY_COOLDOWN_DECLINED = 72      # User rejected - 3 days

# Selection weights - influence probability of topic selection
CURIOSITY_WEIGHT_DORMANCY = 1.5       # Weight multiplier for dormant topics
CURIOSITY_WEIGHT_FRESHNESS = 1.8      # Weight multiplier for fresh discoveries
CURIOSITY_WEIGHT_IMPORTANCE = 2.0     # Weight multiplier for memory importance

# =============================================================================
# HTTP API CONFIGURATION
# =============================================================================
HTTP_ENABLED = True
HTTP_HOST = os.getenv("HTTP_HOST", "127.0.0.1")
HTTP_PORT = int(os.getenv("HTTP_PORT", "5000"))

# =============================================================================
# SUBPROCESS CONFIGURATION
# =============================================================================
SUBPROCESS_AUDIO_ENABLED = False  # Placeholder
SUBPROCESS_OVERLAY_ENABLED = False  # Placeholder
SUBPROCESS_HEALTH_CHECK_INTERVAL = 30
SUBPROCESS_MAX_RESTART_ATTEMPTS = 3

# =============================================================================
# ELEVENLABS TTS CONFIGURATION
# =============================================================================
# ElevenLabs Text-to-Speech integration for GUI voice output.
# Get your API key from: https://elevenlabs.io/
#
# Voice IDs can be found at: https://elevenlabs.io/voice-library
# Or via API: https://api.elevenlabs.io/v1/voices
ELEVENLABS_API_KEY = os.getenv("Eleven_Labs_API", "")
ELEVENLABS_DEFAULT_VOICE_ID = "MKHH3pSZhHPPzypDhMoU"  # Default voice
ELEVENLABS_MODEL = "eleven_monolingual_v1"  # TTS model
ELEVENLABS_AUDIO_PORT = 5003  # Port for audio player subprocess

# User settings file for TTS preferences (enabled, voice_id)
USER_SETTINGS_PATH = DATA_DIR / "user_settings.json"

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_FILE = True
LOG_TO_CONSOLE = True
PROMPT_LOG_PATH = LOGS_DIR / "api_prompts.jsonl"

# =============================================================================
# CONCURRENCY CONFIGURATION
# =============================================================================
LOCK_STATS_INTERVAL = 300  # 5 minutes
MAX_CONCURRENT_LLM_REQUESTS = 3
HEALTH_CHECK_INTERVAL = 30

# =============================================================================
# CLI CONFIGURATION
# =============================================================================
CLI_PROMPT_STYLE = "You: "
CLI_ASSISTANT_STYLE = "AI: "

# =============================================================================
# PROMPT BUILDER CONFIGURATION
# =============================================================================
CONVERSATION_EXCHANGE_LIMIT = 15  # Last N exchanges (user + reply pairs)
MEMORY_PROMOTION_THRESHOLD = 0.85  # Score threshold for core memory promotion
TOOL_STANCE_ENABLED = True  # Inject proactive tool usage guidance into prompts

# =============================================================================
# VISUAL CAPTURE CONFIGURATION
# =============================================================================
# Visual capture sends screenshots and webcam images directly to Claude for
# interpretation. Images are attached to user messages as multimodal content.
#
# Per-source capture modes (configured independently):
#   - "auto": Capture on every prompt (user input or pulse, NOT telegram)
#   - "on_demand": Only capture when AI uses the capture tool
#   - "disabled": Never capture this source
#
# Example: Screenshot auto + Webcam on_demand = screen always visible, webcam via tool
VISUAL_ENABLED = os.getenv("VISUAL_ENABLED", "true").lower() == "true"
VISUAL_SCREENSHOT_MODE = os.getenv("VISUAL_SCREENSHOT_MODE", "auto")  # "auto", "on_demand", "disabled"
VISUAL_WEBCAM_MODE = os.getenv("VISUAL_WEBCAM_MODE", "on_demand")  # "auto", "on_demand", "disabled"

# Legacy enable flags (now derived from mode != "disabled")
VISUAL_SCREENSHOT_ENABLED = VISUAL_SCREENSHOT_MODE != "disabled"
VISUAL_WEBCAM_ENABLED = VISUAL_WEBCAM_MODE != "disabled"

# Legacy: Timer-based capture interval (deprecated, kept for fallback system)
VISUAL_CAPTURE_INTERVAL = int(os.getenv("VISUAL_CAPTURE_INTERVAL", "30"))
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# =============================================================================
# AI COMMAND SYSTEM CONFIGURATION
# =============================================================================
COMMAND_MAX_PASSES = 3          # Maximum LLM calls per user message (1 = no continuation)
COMMAND_SEARCH_LIMIT = 10       # Default memory search result count
COMMAND_SEARCH_MIN_SCORE = 0.3  # Minimum relevance score for search results

# =============================================================================
# NATIVE TOOL USE CONFIGURATION (DEPRECATED)
# =============================================================================
# Native tool use is now the ONLY supported mode. The legacy [[COMMAND]] pattern
# system has been deprecated and removed.
#
# This flag is kept for backwards compatibility but has no effect.
# It will be removed in a future version.
#
# MIGRATION NOTE (December 2025):
# - All message entry points (user input, pulse, telegram, reminder) now use
#   native tool use exclusively
# - The [[COMMAND: arg]] syntax is no longer parsed or supported
# - Tool definitions in agency/tools/definitions.py define all available tools
# - The legacy command processor in agency/commands/ is deprecated
USE_NATIVE_TOOLS = True  # Always True - legacy mode no longer available

# =============================================================================
# INTENTION SYSTEM CONFIGURATION
# =============================================================================
# Intentions give the AI forward-looking agency: reminders, goals, plans
# that surface at the right time. Intentions are private to the AI.
INTENTION_ENABLED = True                    # Enable the intention system
INTENTION_MAX_PENDING_DISPLAY = 3           # Max pending intentions to show in context
INTENTION_COMPLETED_TO_MEMORY = True        # Create memories from completed intentions

# =============================================================================
# FILE TOOL CONFIGURATION
# =============================================================================
# Simple file read/write tools for AI to store and retrieve text files.
# Files are sandboxed to a specific directory for security.
FILE_STORAGE_DIR = DATA_DIR / "files"       # Sandboxed directory for AI file operations
FILE_MAX_SIZE_BYTES = 31457280              # 30MB max file size
FILE_ALLOWED_EXTENSIONS = {".txt", ".md", ".json", ".csv"}  # Whitelist of allowed extensions

# =============================================================================
# DEV MODE CONFIGURATION
# =============================================================================
# Dev mode provides a debug window showing internal operations:
# - Prompt assembly and context blocks
# - Command/tool execution and results
# - Multi-pass response processing
# - Memory recall scores
# - Token counts and timing
#
# Enable via command line: python main.py --dev
# The AI is notified when dev mode is active.
DEV_MODE_ENABLED = False  # Set programmatically via --dev flag, not env var

# =============================================================================
# EMAIL GATEWAY CONFIGURATION
# =============================================================================
# Email sending via Gmail SMTP.
# Requires a Gmail account with an app password (not regular password).
#
# To create an app password:
# 1. Enable 2-Factor Authentication on your Google account
# 2. Go to https://myaccount.google.com/apppasswords
# 3. Generate a new app password for "Mail"
# 4. Use that password as APP_EMAIL_PASS
EMAIL_GATEWAY_ENABLED = False  # Disabled - Telegram is the primary communication channel
EMAIL_ADDRESS = os.getenv("APP_EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("APP_EMAIL_PASS", "")
EMAIL_DISPLAY_NAME = "Pattern Claude"
EMAIL_SMTP_HOST = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587

# Email whitelist - only these addresses can receive emails
# Empty list means all recipients blocked (since email is disabled)
EMAIL_WHITELIST = []  # Add addresses here when enabling email

# =============================================================================
# TELEGRAM BOT CONFIGURATION
# =============================================================================
# Telegram Bot API for bidirectional messaging.
# Create a bot via @BotFather to get your token.
#
# Setup:
# 1. Message @BotFather on Telegram, send /newbot
# 2. Choose a name and username for your bot
# 3. Copy the bot token to your environment variable
# 4. Start a chat with your bot and send any message
# 5. The chat_id will be auto-detected on first message
TELEGRAM_ENABLED = True
TELEGRAM_BOT_TOKEN = os.getenv("telegram_bot", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # Auto-detected if empty
TELEGRAM_POLL_INTERVAL = 2  # Seconds between polling for inbound messages

# =============================================================================
# COMMUNICATION RATE LIMITS
# =============================================================================
# Prevent abuse by limiting messages per hour
EMAIL_MAX_PER_HOUR = 20      # Maximum emails per hour (when enabled)
TELEGRAM_MAX_PER_HOUR = 30   # Maximum Telegram messages per hour

# =============================================================================
# WEB SEARCH CONFIGURATION
# =============================================================================
# Claude's native web search tool - searches happen server-side via Anthropic.
# Requires enabling in Anthropic Console (organization setting).
#
# Pricing: $10 per 1,000 searches + standard token costs (results are input tokens)
# Supported models: Claude 3.5 Sonnet, 3.5 Haiku, 3.7 Sonnet, and newer
#
# When enabled, Claude can autonomously search the web for current information.
# Results include citations (title, URL, cited_text) automatically.
WEB_SEARCH_ENABLED = True                       # Master toggle for web search
WEB_SEARCH_MAX_USES_PER_REQUEST = 3             # Max searches Claude can do per API call
WEB_SEARCH_TOTAL_ALLOWED_PER_DAY = 30           # Daily budget (resets at midnight)
