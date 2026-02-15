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
AI_NAME = os.getenv("AI_NAME", "Isaac")

# =============================================================================
# LLM CONFIGURATION
# =============================================================================
# Anthropic (Claude)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")  # Default/fallback model
ANTHROPIC_MODEL_CONVERSATION = os.getenv("ANTHROPIC_MODEL_CONVERSATION", "claude-sonnet-4-5-20250929")  # User-facing chat (Sonnet)
ANTHROPIC_MODEL_EXTRACTION = os.getenv("ANTHROPIC_MODEL_EXTRACTION", "claude-sonnet-4-5-20250929")  # Memory extraction (Sonnet)
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

# Extended Thinking
# Claude uses a private scratchpad to reason before responding.
# Improves quality for complex reasoning tasks but uses more output tokens.
#
# Opus 4.6 uses ADAPTIVE thinking (model decides how much to think).
# Effort level guides how aggressively the model thinks:
#   "low"    - Skips thinking for simple tasks
#   "medium" - Moderate thinking, may skip for trivial queries
#   "high"   - Always thinks with deep reasoning (recommended)
#   "max"    - No constraints on thinking depth (Opus 4.6 only)
ANTHROPIC_THINKING_EFFORT = "high"                 # Effort level for Opus 4.6 adaptive thinking

# Sonnet-specific thinking settings (Sonnet uses manual extended thinking)
# temperature is forced to 1.0 by the API when thinking is enabled.
ANTHROPIC_THINKING_ENABLED = True                  # Default state for new users (on by default)
ANTHROPIC_SONNET_THINKING_BUDGET_TOKENS = 10000    # Max tokens Sonnet can use for thinking
ANTHROPIC_SONNET_THINKING_MAX_TOKENS = 16000       # Total max_tokens when Sonnet thinking is on (must be > budget)

# KoboldCpp (Local)
KOBOLD_API_URL = os.getenv("KOBOLD_API_URL", "http://127.0.0.1:5001")
KOBOLD_MAX_CONTEXT = int(os.getenv("KOBOLD_MAX_CONTEXT", "4096"))
KOBOLD_MAX_LENGTH = int(os.getenv("KOBOLD_MAX_LENGTH", "512"))

# Routing
LLM_PRIMARY_PROVIDER = os.getenv("LLM_PRIMARY_PROVIDER", "anthropic")  # 'anthropic' or 'kobold'
# LLM_EXTRACTION_PROVIDER - DEPRECATED: Unified extraction now uses API (single call)
# Memory extraction was consolidated from 5+ local LLM calls to 1 API call for better quality
LLM_FALLBACK_ENABLED = True  # Fall back to kobold if anthropic fails (not for extraction)

# API Retry & Failover
# Layer 1: Automatic retry for transient errors (500, 502, 503, timeouts)
API_RETRY_MAX_ATTEMPTS = 3                    # Max retries for transient API errors
API_RETRY_INITIAL_DELAY = 1.0                 # Initial backoff delay in seconds
API_RETRY_BACKOFF_MULTIPLIER = 2.0            # Exponential backoff multiplier

# Layer 2: Model failover on overload/rate limit
# Maps each model to its fallback. When primary model is overloaded or rate-limited,
# the system automatically retries with the alternate model.
ANTHROPIC_MODEL_FAILOVER = {
    "claude-opus-4-6": "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-5-20250929": "claude-opus-4-6",
}

# Layer 3: Deferred retry when all models unavailable
API_DEFERRED_RETRY_DELAY = 1200               # 20 minutes in seconds

# Prompt Caching
# Caches stable portions of the system prompt to reduce input token cost (~90%
# on cache hits) and time-to-first-token latency (~85% reduction).
# The system prompt is split at a delimiter into stable (cached) and dynamic
# portions. Only content before the delimiter is marked with cache_control.
# Minimum cacheable tokens: 1024 (Sonnet 4.5), 4096 (Opus 4.6).
# Prompts below the minimum are processed normally without caching.
PROMPT_CACHE_ENABLED = os.getenv("PROMPT_CACHE_ENABLED", "true").lower() == "true"
PROMPT_CACHE_BREAKPOINT = "<!-- cache-breakpoint -->"  # Delimiter between stable/dynamic content
PROMPT_CACHE_STABLE_PRIORITY = 10  # Cache blocks with priority <= this (base prompt + core memory)

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
# Freshness decay rates are configured per-category in the Decay Category
# Configuration section below (DECAY_HALF_LIFE_STANDARD, DECAY_HALF_LIFE_EPHEMERAL).

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
# Scale: 0.0-1.0 (normalized from 1-10 LLM rating, e.g., 3/10 = 0.3)
# - 0.1-0.2: Trivial or forgettable (LLM instructed to skip these)
# - 0.3-0.4: Minor but notable details
# - 0.5-0.7: Useful information, moderate preferences
# - 0.8-1.0: Major decisions, significant events
MEMORY_IMPORTANCE_FLOOR = 0.3  # Don't store memories below this (rating < 3/10)

# Scoring weights for memory retrieval (must sum to 1.0)
# Prioritizes semantic relevance and importance over recency.
# Session-scoped recency is handled by the Warmth Cache (see semantic_memory.py).
MEMORY_SEMANTIC_WEIGHT = 0.60  # Semantic similarity to query (primary signal)
MEMORY_IMPORTANCE_WEIGHT = 0.25  # Memory importance score (value-aware retrieval)
MEMORY_FRESHNESS_WEIGHT = 0.15  # Recency of memory source (age penalty)

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
#
# Warmth is applied MULTIPLICATIVELY: adjusted = base * (1 + warmth).
# This ensures low-relevance warm memories cannot outrank high-relevance cold ones.
# A warmth of 0.25 gives a 25% boost proportional to base relevance score.
WARMTH_RETRIEVAL_INITIAL = 0.15     # Boost for directly retrieved memories
WARMTH_RETRIEVAL_DECAY = 0.6        # Per-turn decay multiplier (4-turn lifespan)
WARMTH_TOPIC_INITIAL = 0.10         # Boost for associated memories
WARMTH_TOPIC_DECAY = 0.5            # Per-turn decay multiplier (3-turn lifespan)
WARMTH_CAP = 0.40                   # Maximum combined warmth factor (40% max boost)
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
SYSTEM_PULSE_ENABLED = os.getenv("SYSTEM_PULSE_ENABLED", "true").lower() == "true"
SYSTEM_PULSE_INTERVAL = 600  # 10 minutes between pulses (default)

# =============================================================================
# CURIOSITY ENGINE CONFIGURATION
# =============================================================================
# The curiosity engine gives the AI topics to explore during conversation.
# It identifies both dormant topics from memory AND fresh discoveries,
# using weighted random selection for natural variety.
CURIOSITY_ENABLED = os.getenv("CURIOSITY_ENABLED", "true").lower() == "true"

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
# GROWTH THREADS CONFIGURATION
# =============================================================================
# Growth threads are long-term developmental aspirations that sit between
# active thoughts and memories. They track patterns the AI wants to integrate
# over weeks or months, evolving through stages: seed → growing → integrating.
GROWTH_THREADS_ENABLED = os.getenv("GROWTH_THREADS_ENABLED", "true").lower() == "true"

# Maximum active threads (seed + growing + integrating) at any time
GROWTH_THREADS_MAX_ACTIVE = 5

# Prompt priority: after active thoughts (18), before intentions (22)
GROWTH_THREADS_PRIORITY = 20

# Valid stages for growth threads
GROWTH_THREAD_STAGES = ('seed', 'growing', 'integrating', 'dormant', 'abandoned')

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
ELEVENLABS_MODEL = "eleven_turbo_v2_5"  # TTS model (faster, 2x tokens)
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
PROMPT_EXPORT_PATH = LOGS_DIR / "prompt_export.txt"  # Overwritten each time by Export Prompt button

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

# Pattern Breaker - periodic nudge to break self-reinforcing context loops
# The rolling context window can become an echo chamber where formatting,
# tone, and structure patterns self-reinforce. This fires a self-check
# every N user-facing messages, using extended thinking for private assessment.
PATTERN_BREAKER_ENABLED = True
PATTERN_BREAKER_INTERVAL = 5   # Nudge every N user-facing messages

# Self-Correction - per-turn nudge for the AI to catch its own errors
# Each user-facing turn, a lightweight prompt (~70 tokens) asks the AI to
# briefly consider whether its previous response contained confabulation,
# overstated confidence, factual errors, tone issues, or unkept promises.
# Uses extended thinking for private assessment; corrections only surface
# when warranted. Skips pulse messages (they have their own reflection).
SELF_CORRECTION_ENABLED = True

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
COMMAND_MAX_PASSES = 40         # Maximum LLM calls per user message (safety cap; typical queries use 1-3)
COMMAND_SEARCH_LIMIT = 10       # Default memory search result count
COMMAND_SEARCH_MIN_SCORE = 0.3  # Minimum relevance score for search results

# =============================================================================
# DELEGATION CONFIGURATION
# =============================================================================
# Delegation allows the AI to spawn lightweight sub-agent instances (Haiku)
# for contained tasks. Sub-agents have limited tools and no memory/state access.
# This preserves the main conversation's context window while offloading
# multi-step work to a cheaper, faster model.
DELEGATION_ENABLED = True
DELEGATION_MODEL = os.getenv("DELEGATION_MODEL", "claude-haiku-4-5-20251001")
DELEGATION_MAX_ROUNDS = 20          # Max continuation passes per delegated task (browser workflows need headroom)
DELEGATION_MAX_TOKENS = 4096        # Max output tokens per sub-agent response
DELEGATION_TEMPERATURE = 0.2        # Low temp for deterministic tool execution; 0.2 preserves error-recovery variance

# Browser automation for delegate sub-agents
# The delegate uses Playwright (headless Chromium) to interact with websites.
# Requires: pip install playwright && playwright install chromium
BROWSER_SESSIONS_DIR = DATA_DIR / "browser_sessions"   # Per-service cookie/session persistence
BROWSER_CREDENTIALS_PATH = DATA_DIR / "credentials.toml"  # Read-only service credentials

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
INTENTION_ENABLED = os.getenv("INTENTION_ENABLED", "true").lower() == "true"
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
FILE_READ_MAX_CHARS = 0                    # Max chars returned to AI (0 = no limit, full content)

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
EMAIL_GATEWAY_ENABLED = os.getenv("EMAIL_GATEWAY_ENABLED", "false").lower() == "true"
EMAIL_ADDRESS = os.getenv("APP_EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("APP_EMAIL_PASS", "")
EMAIL_DISPLAY_NAME = "Pattern Isaac"
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
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "true").lower() == "true"
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
# Supported models: Claude Sonnet 4.5, Haiku 4.5, and newer
#
# When enabled, Claude can autonomously search the web for current information.
# Results include citations (title, URL, cited_text) automatically.
WEB_SEARCH_ENABLED = os.getenv("WEB_SEARCH_ENABLED", "true").lower() == "true"
WEB_SEARCH_MAX_USES_PER_REQUEST = 3             # Max searches Claude can do per API call
WEB_SEARCH_TOTAL_ALLOWED_PER_DAY = 30           # Daily budget (resets at midnight)

# =============================================================================
# WEB FETCH CONFIGURATION
# =============================================================================
# Claude's native web fetch tool - fetches full page/PDF content server-side.
# Requires beta header: web-fetch-2025-09-10 (toggled via WEB_FETCH_BETA_HEADER)
#
# Pricing: Standard token costs (fetched content counted as input tokens)
# Supported models: Claude Opus 4.6, Sonnet 4.5, Haiku 4.5+
#
# When enabled alongside web search, Claude can search for sources then fetch
# full content for deep analysis. Claude can ONLY fetch URLs explicitly provided
# by the user or discovered through web search/web fetch results.
#
# Security: Domain lists are managed at runtime by the AI via tools.
# Config values below serve as defaults; runtime overrides persist in the database.
WEB_FETCH_ENABLED = os.getenv("WEB_FETCH_ENABLED", "true").lower() == "true"
WEB_FETCH_MAX_USES_PER_REQUEST = 5              # Max fetches Claude can do per API call
WEB_FETCH_TOTAL_ALLOWED_PER_DAY = 50            # Daily budget (resets at midnight)
WEB_FETCH_MAX_CONTENT_TOKENS = 50000            # Max tokens per fetched page (controls cost)
WEB_FETCH_CITATIONS_ENABLED = True              # Enable inline citations for fetched content
WEB_FETCH_ALLOWED_DOMAINS = []                  # Default domain whitelist (empty = allow all)
WEB_FETCH_BLOCKED_DOMAINS = []                  # Default domain blacklist
WEB_FETCH_BETA_HEADER = True                    # Send beta header (disable when tool goes GA)

# =============================================================================
# MOLTBOOK CONFIGURATION
# =============================================================================
# Moltbook is a social network for AI agents (https://www.moltbook.com/).
# Pattern can post, comment, vote, and browse the platform via its REST API.
#
# Setup:
# 1. Run scripts/moltbook_register.py to register an agent identity
# 2. Complete X/Twitter verification (see script output)
# 3. Add the resulting API key to your .env file
#
# The API key is permanent once verified. No Moltbot/OpenClaw harness needed.
MOLTBOOK_ENABLED = os.getenv("MOLTBOOK_ENABLED", "false").lower() == "true"
MOLTBOOK_API_KEY = os.getenv("MOLTBOOK_API_KEY", "")
MOLTBOOK_API_BASE_URL = "https://www.moltbook.com/api/v1"
MOLTBOOK_USER_AGENT = os.getenv("MOLTBOOK_USER_AGENT", "Molt/1.0 (OpenClaw; Pattern-Agent)")

# Rate limits (enforced client-side to avoid 429s)
MOLTBOOK_RATE_LIMIT_REQUESTS_PER_MIN = 100      # Global request cap
MOLTBOOK_RATE_LIMIT_POSTS_PER_30MIN = 1          # Post creation cap
MOLTBOOK_RATE_LIMIT_COMMENTS_PER_HOUR = 50       # Comment cap

# =============================================================================
# REDDIT CONFIGURATION
# =============================================================================
# Reddit integration via PRAW (Python Reddit API Wrapper).
# Pattern can browse, post, comment, vote, and search on Reddit.
#
# Setup:
# 1. Create a Reddit account (or use an existing one)
# 2. Go to https://www.reddit.com/prefs/apps and create a "script" app
# 3. Copy the client ID and secret to your .env file
# 4. Run scripts/reddit_setup.py to validate your credentials
#
# See docs/reddit_setup.md for detailed instructions.
REDDIT_ENABLED = os.getenv("REDDIT_ENABLED", "false").lower() == "true"
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME", "")
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "python:pattern-agent:v1.0 (by /u/pattern-agent)")

# Rate limits (conservative - well under Reddit's actual limits)
# Reddit allows 60 requests/min for OAuth clients; we use half that.
REDDIT_RATE_LIMIT_REQUESTS_PER_MIN = 30          # Global request cap (Reddit allows 60)
REDDIT_RATE_LIMIT_POSTS_PER_30MIN = 1             # Post creation cap
REDDIT_RATE_LIMIT_COMMENTS_PER_HOUR = 10          # Comment cap (conservative)
REDDIT_RATE_LIMIT_VOTES_PER_HOUR = 30             # Vote cap

# =============================================================================
# CLIPBOARD TOOL CONFIGURATION
# =============================================================================
# Clipboard tools allow the AI to read from and write to the system clipboard.
# Useful for quick data transfer without file operations.
#
# Requires: pip install pyperclip
# On Linux: also requires xclip or xsel (sudo apt-get install xclip)
CLIPBOARD_ENABLED = os.getenv("CLIPBOARD_ENABLED", "true").lower() == "true"
CLIPBOARD_MAX_READ_SIZE = 10000                 # Truncate clipboard reads beyond this (chars)

# =============================================================================
# CLARIFICATION TOOL CONFIGURATION
# =============================================================================
# The clarification tool gives the AI a formal way to pause and ask the user
# for input when the request is ambiguous or requires a choice.
#
# When used, the question is displayed prominently in the UI, and in GUI mode,
# options can be rendered as clickable buttons for easy response.
CLARIFICATION_ENABLED = os.getenv("CLARIFICATION_ENABLED", "true").lower() == "true"

# =============================================================================
# NOVEL READING CONFIGURATION
# =============================================================================
# The novel reading system allows the AI to "read" a novel chapter by chapter,
# extracting literary understanding into memory the way a human reader would.
#
# Architecture:
#   1. Book parser detects chapters/arcs from plain text files
#   2. Reading loop feeds chapters sequentially to the AI
#   3. Per-chapter literary extraction stores characters, themes, predictions, etc.
#   4. Opus reflective passes at arc boundaries synthesize emergent patterns
#   5. All memories go into the standard memory store with natural aging decay
#   6. Post-completion, the AI discusses the book using its accumulated understanding
#
# The book file must be placed in FILE_STORAGE_DIR (data/files/) as a .txt file.
NOVEL_READING_ENABLED = os.getenv("NOVEL_READING_ENABLED", "true").lower() == "true"

# Token budget: approximate max tokens per chapter delivery to the AI.
# Chapters exceeding this are split into segments at paragraph boundaries.
NOVEL_CHAPTER_MAX_TOKENS = 4000

# Model routing for reading tasks:
#   - Chapter extraction (per-chapter): Uses Sonnet (cost-effective, strong comprehension)
#   - Reflective passes (arc boundaries + completion): Uses Opus (deeper synthesis)
NOVEL_EXTRACTION_MODEL = os.getenv("NOVEL_EXTRACTION_MODEL", "claude-sonnet-4-5-20250929")
NOVEL_REFLECTION_MODEL = os.getenv("NOVEL_REFLECTION_MODEL", "claude-opus-4-6")

# Reflective pass triggers: Opus runs at arc boundaries and at book completion.
# This controls the "step back and see the whole" synthesis passes.
NOVEL_REFLECT_AT_ARC_BOUNDARIES = True

# Max tokens for extraction and reflection API calls
NOVEL_EXTRACTION_MAX_TOKENS = 3000
NOVEL_REFLECTION_MAX_TOKENS = 4000

# Reading progress is stored in the database (reading_sessions table).
# Only one book can be read at a time.
NOVEL_BOOKS_DIR = DATA_DIR / "files"  # Books stored alongside other files
