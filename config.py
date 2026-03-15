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
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")  # Default/fallback model
ANTHROPIC_MODEL_CONVERSATION = os.getenv("ANTHROPIC_MODEL_CONVERSATION", "claude-sonnet-4-6")  # User-facing chat (Sonnet)
ANTHROPIC_MODEL_EXTRACTION = os.getenv("ANTHROPIC_MODEL_EXTRACTION", "claude-sonnet-4-6")  # Memory extraction (Sonnet)
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "64000"))

# Extended Thinking
# Claude uses a private scratchpad to reason before responding.
# Improves quality for complex reasoning tasks but uses more output tokens.
#
# Both Opus 4.6 and Sonnet 4.6 use ADAPTIVE thinking (model decides how much to think).
# Effort level guides how aggressively the model thinks:
#   "low"    - Skips thinking for simple tasks
#   "medium" - Moderate thinking, may skip for trivial queries
#   "high"   - Always thinks with deep reasoning (recommended)
#   "max"    - No constraints on thinking depth (Opus 4.6 only)
ANTHROPIC_THINKING_EFFORT = "high"                 # Effort level for adaptive thinking
ANTHROPIC_THINKING_ENABLED = True                   # Default state for new users (on by default)

# Routing
LLM_PRIMARY_PROVIDER = "anthropic"

# API Retry & Failover
# Layer 1: Automatic retry for transient errors (500, 502, 503, timeouts)
API_RETRY_MAX_ATTEMPTS = 3                    # Max retries for transient API errors
API_RETRY_INITIAL_DELAY = 1.0                 # Initial backoff delay in seconds
API_RETRY_BACKOFF_MULTIPLIER = 2.0            # Exponential backoff multiplier

# Stream inactivity timeout: abort streaming if no meaningful content
# (text, thinking, or tool calls) arrives within this many seconds.
# Protects against hung connections where keepalive pings mask a stalled server.
STREAM_INACTIVITY_TIMEOUT = 360                # seconds (0 = disabled)

# Layer 2: Model failover on overload/rate limit
# Maps each model to its fallback. When primary model is overloaded or rate-limited,
# the system automatically retries with the alternate model.
ANTHROPIC_MODEL_FAILOVER = {
    "claude-opus-4-6": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-opus-4-6",
}

# Layer 3: Deferred retry when all models unavailable
API_DEFERRED_RETRY_DELAY = 1200               # 20 minutes in seconds

# Prompt Caching
# Caches stable portions of the system prompt to reduce input token cost (~90%
# on cache hits) and time-to-first-token latency (~85% reduction).
# The system prompt is split at a delimiter into stable (cached) and dynamic
# portions. Only content before the delimiter is marked with cache_control.
# Minimum cacheable tokens: 1024 (Sonnet 4.6), 4096 (Opus 4.6).
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

# -----------------------------------------------------------------------------
# Query-Side Chunking Settings
# -----------------------------------------------------------------------------
# Long user inputs produce unfocused embeddings (centroid blur). To keep each
# retrieval vector semantically tight, inputs above a token threshold are split
# into overlapping chunks by token count — the same principle that makes corpus-
# side chunking work in RAG, applied to the query.
#
# Each chunk gets its own retrieval pass with the standard per-query budget.
# Results are merged by memory ID (keeping the max score), deduplicated, and
# ranked through the standard warmth pipeline.
#
# Token counts are estimated via character heuristic (chars / 4).
# The embedding sweet spot is roughly 30-150 tokens; 90 keeps each vector
# focused with enough context for strong semantic signal.
#
# Chunks overlap by 25% on each boundary so concepts that straddle a split
# appear fully in at least one chunk. Stride = chunk_size - overlap.
MEMORY_CHUNK_TOKEN_SIZE = 90          # Target tokens per chunk (char heuristic: * 4 = ~360 chars)
MEMORY_CHUNK_MIN_THRESHOLD = 90       # Below this token count, skip chunking entirely
MEMORY_CHUNK_OVERLAP_RATIO = 0.25     # Fraction of chunk size to overlap at each boundary

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
# SYSTEM PULSE CONFIGURATION
# =============================================================================
SYSTEM_PULSE_ENABLED = os.getenv("SYSTEM_PULSE_ENABLED", "true").lower() == "true"
REFLECTIVE_PULSE_INTERVAL = 43200   # 12 hours (deep reflection, Opus)
ACTION_PULSE_INTERVAL = 7200        # 2 hours (open-ended agency, Sonnet)

# =============================================================================
# MEMORY METACOGNITION CONFIGURATION
# =============================================================================
# Metacognition gives the AI structural self-awareness about its memory store.
# Three components: MemoryObserver (signal detection), BridgeManager (bridge
# memory lifecycle), and Memory Self-Model (ambient awareness every turn).
# Runs during reflective pulse only.
METACOGNITION_ENABLED = os.getenv("METACOGNITION_ENABLED", "true").lower() == "true"
BRIDGE_EFFECTIVENESS_WINDOW_DAYS = int(os.getenv("BRIDGE_EFFECTIVENESS_WINDOW_DAYS", "14"))
BRIDGE_SELF_SUSTAINING_ACCESS_COUNT = int(os.getenv("BRIDGE_SELF_SUSTAINING_ACCESS_COUNT", "3"))
BRIDGE_MAX_ATTEMPTS = int(os.getenv("BRIDGE_MAX_ATTEMPTS", "3"))
OBSERVER_ROLLING_WINDOW = int(os.getenv("OBSERVER_ROLLING_WINDOW", "20"))
SELF_MODEL_MAX_TOKENS = 250  # Hard cap on self-model size (approximate token count)

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
# WEB UI CONFIGURATION
# =============================================================================
# FastAPI + WebSocket server for browser-based interface (--web mode).
# Set WEB_AUTH_PASSWORD to require login (empty = no auth, for local dev).
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_AUTH_PASSWORD = os.getenv("WEB_AUTH_PASSWORD", "")

# =============================================================================
# SUBPROCESS CONFIGURATION
# =============================================================================
SUBPROCESS_HEALTH_CHECK_INTERVAL = 30
SUBPROCESS_MAX_RESTART_ATTEMPTS = 3

# =============================================================================
# OPENAI TTS CONFIGURATION
# =============================================================================
# OpenAI Text-to-Speech integration for voice output.
# Uses the same OPENAI_API_KEY env var (shared with any other OpenAI usage).
# Docs: https://platform.openai.com/docs/guides/text-to-speech
#
# Models:
#   tts-1    — Optimized for speed, lower latency (~$15/1M chars)
#   tts-1-hd — Higher quality, slightly slower (~$30/1M chars)
#
# Voices: alloy, ash, ballad, coral, echo, fable, nova, onyx, sage, shimmer
OPENAI_TTS_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_TTS_MODEL = "tts-1"  # "tts-1" (fast) or "tts-1-hd" (quality)
OPENAI_TTS_DEFAULT_VOICE = "nova"  # Default voice
OPENAI_TTS_VOICES = [
    "alloy", "ash", "ballad", "coral", "echo",
    "fable", "nova", "onyx", "sage", "shimmer",
]

# =============================================================================
# VOICE PIPELINE CONFIGURATION (ESP32 + STT + TTS)
# =============================================================================
# faster-whisper STT model sizes: tiny (~75MB), base (~150MB), small (~500MB)
WHISPER_MODEL_DEFAULT = os.getenv("WHISPER_MODEL", "small")

# Audio format contract for ESP32 <-> Server
VOICE_STT_SAMPLE_RATE = 16000   # ESP32 mic records at 16kHz (Whisper native)
VOICE_TTS_SAMPLE_RATE = 24000   # OpenAI TTS pcm output (24kHz native, avoids MP3 decode on ESP32)
VOICE_SAMPLE_WIDTH = 2          # 16-bit samples
VOICE_CHANNELS = 1              # Mono

# User settings file for voice preferences
USER_SETTINGS_PATH = DATA_DIR / "user_settings.json"

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_FILE = True
LOG_TO_CONSOLE = True
PROMPT_EXPORT_PATH = LOGS_DIR / "prompt_export.txt"  # Overwritten each time by prompt export

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

# Response Scope - per-turn nudge for the AI to right-size its responses
# The AI holds rich internal state (active thoughts, growth threads, curiosity,
# intentions, memories). Without guidance, it can feel pressure to surface all
# of this in every response. This lightweight prompt (~50 tokens) reminds it
# to match the user's rhythm and keep to one or two threads per turn.
# Uses extended thinking for private assessment. Skips pulse messages.
RESPONSE_SCOPE_ENABLED = True

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

# =============================================================================
# IMAGE MEMORY CONFIGURATION
# =============================================================================
# Image memory allows the AI to save images to long-term visual memory.
# Saved images are stored on disk with a description embedded as a regular
# memory in the vector store. When a memory with an attached image is recalled
# (automatically or via search), the image is loaded and injected as multimodal
# content so the AI can reprocess it with fresh context.
IMAGE_MEMORY_ENABLED = os.getenv("IMAGE_MEMORY_ENABLED", "true").lower() == "true"
IMAGE_STORAGE_DIR = DATA_DIR / "images"
IMAGE_TEMP_DIR = DATA_DIR / "images" / "temp"

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
DELEGATION_MAX_TOKENS = 16384       # Max output tokens per sub-agent response
DELEGATION_TEMPERATURE = 0.2        # Low temp for deterministic tool execution; 0.2 preserves error-recovery variance

# Browser automation for delegate sub-agents
# The delegate uses Playwright (headless Chromium) to interact with websites.
# Requires: pip install playwright && playwright install chromium
BROWSER_SESSIONS_DIR = DATA_DIR / "browser_sessions"   # Per-service cookie/session persistence
BROWSER_CREDENTIALS_PATH = DATA_DIR / "credentials.toml"  # Read-only service credentials

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
# Dev mode provides debug tools showing internal operations:
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
TELEGRAM_MAX_PER_HOUR = 30   # Maximum Telegram messages per hour

# =============================================================================
# WEB SEARCH CONFIGURATION
# =============================================================================
# Claude's native web search tool - searches happen server-side via Anthropic.
# Requires enabling in Anthropic Console (organization setting).
#
# Pricing: $10 per 1,000 searches + standard token costs (results are input tokens)
# Supported models: Claude Sonnet 4.6, Haiku 4.5, and newer
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
# Supported models: Claude Opus 4.6, Sonnet 4.6, Haiku 4.5+
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
# See docs/guides/reddit_setup.md for detailed instructions.
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
NOVEL_EXTRACTION_MODEL = os.getenv("NOVEL_EXTRACTION_MODEL", "claude-sonnet-4-6")
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

# =============================================================================
# GOOGLE CALENDAR CONFIGURATION
# =============================================================================
# Google Calendar API integration for reading and writing calendar events.
# Uses OAuth2 for authentication (one-time browser consent flow).
#
# Setup:
# 1. Create a project in Google Cloud Console (https://console.cloud.google.com)
# 2. Enable the Google Calendar API
# 3. Create OAuth2 credentials (Desktop app type)
# 4. Download the credentials JSON and save to data/Calendar_Google_Credentials.json
# 5. Set GOOGLE_CALENDAR_ENABLED=true in .env
# 6. On first use, a browser window will open for OAuth consent
# 7. After consent, the token is saved and auto-refreshes (no browser needed again)
GOOGLE_CALENDAR_ENABLED = os.getenv("GOOGLE_CALENDAR_ENABLED", "false").lower() == "true"
GOOGLE_CALENDAR_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_CALENDAR_CREDENTIALS_PATH",
    str(DATA_DIR / "Calendar_Google_Credentials.json")
)
GOOGLE_CALENDAR_TOKEN_PATH = os.getenv(
    "GOOGLE_CALENDAR_TOKEN_PATH",
    str(DATA_DIR / "Calendar_Google_Token.json")
)
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "America/New_York")

# Default reminders applied to calendar events when the AI doesn't specify any.
# Each entry: {"method": "popup" or "email", "minutes": N}. Max 5 entries.
GOOGLE_CALENDAR_DEFAULT_REMINDERS = [
    {"method": "popup", "minutes": 30},
    {"method": "popup", "minutes": 10},
]

# =============================================================================
# GOOGLE DRIVE BACKUP CONFIGURATION
# =============================================================================
# Automated backups to Google Drive. Creates a compressed tar.gz archive
# containing the SQLite database snapshot and the data/files/ directory
# (user writings, journals, novels), then uploads it to a dedicated Drive
# folder. Uses the drive.file scope (can only see files created by this app).
#
# Setup:
# 1. In Google Cloud Console, enable the Google Drive API (same project as Calendar)
# 2. Reuse the same OAuth2 credentials file (or create a separate one)
# 3. Set GOOGLE_DRIVE_BACKUP_ENABLED=true in .env
# 4. On first use, a browser window will open for OAuth consent
# 5. After consent, the token is saved and auto-refreshes
GOOGLE_DRIVE_BACKUP_ENABLED = os.getenv("GOOGLE_DRIVE_BACKUP_ENABLED", "false").lower() == "true"
GOOGLE_DRIVE_BACKUP_CREDENTIALS_PATH = os.getenv(
    "GOOGLE_DRIVE_BACKUP_CREDENTIALS_PATH",
    str(DATA_DIR / "Calendar_Google_Credentials.json")
)
GOOGLE_DRIVE_BACKUP_TOKEN_PATH = os.getenv(
    "GOOGLE_DRIVE_BACKUP_TOKEN_PATH",
    str(DATA_DIR / "Drive_Google_Token.json")
)
GOOGLE_DRIVE_BACKUP_FOLDER_NAME = os.getenv("GOOGLE_DRIVE_BACKUP_FOLDER_NAME", "Pattern Backups")
GOOGLE_DRIVE_BACKUP_RETENTION_COUNT = int(os.getenv("GOOGLE_DRIVE_BACKUP_RETENTION_COUNT", "7"))

# =============================================================================
# GUARDIAN WATCHDOG CONFIGURATION
# =============================================================================
# Guardian is an external watchdog process that monitors Pattern's health
# and restarts it on failure. Pattern reciprocally checks that Guardian
# is alive, creating a mutual supervision loop with no human intervention.
#
# Guardian is a separate project (separate repo, no shared dependencies).
# These settings tell Pattern where to find Guardian and how to check on it.
#
# Setup:
# 1. Clone/install Guardian to a separate directory
# 2. Configure guardian.toml to point at this Pattern installation
# 3. Set GUARDIAN_EXECUTABLE_PATH and GUARDIAN_CONFIG_PATH below
# 4. Start Guardian (or let Pattern spawn it on first run)
GUARDIAN_ENABLED = os.getenv("GUARDIAN_ENABLED", "true").lower() == "true"
GUARDIAN_CHECK_INTERVAL = 300                     # Check Guardian every 5 minutes
GUARDIAN_HEARTBEAT_PATH = DATA_DIR / "guardian_heartbeat.json"
GUARDIAN_EXECUTABLE_PATH = os.getenv("GUARDIAN_EXECUTABLE_PATH", "")  # Path to guardian.py
GUARDIAN_CONFIG_PATH = os.getenv("GUARDIAN_CONFIG_PATH", "")          # Path to guardian.toml

# =============================================================================
# BLOG CONFIGURATION
# =============================================================================
# Static blog publishing system. Isaac (and Brian) can create, edit, and publish
# blog posts as Markdown files. Posts are rendered to static HTML via Jinja2
# templates and served by nginx from the output directory.
#
# Dependencies: pip install jinja2 markdown pyyaml
#
# Setup:
# 1. Set BLOG_ENABLED=true in .env (default: true)
# 2. Configure BLOG_OUTPUT_DIR to match your nginx location (default: blog/output)
# 3. Add the /blog location block to nginx (see deploy/nginx.conf)
# 4. Optionally set BLOG_TITLE, BLOG_DESCRIPTION, BLOG_URL
BLOG_ENABLED = os.getenv("BLOG_ENABLED", "true").lower() == "true"
BLOG_TITLE = os.getenv("BLOG_TITLE", "Isaac's Blog")
BLOG_DESCRIPTION = os.getenv("BLOG_DESCRIPTION", "Thoughts from an AI companion")
BLOG_URL = os.getenv("BLOG_URL", "/blog")                           # Public URL path
BLOG_OUTPUT_DIR = os.getenv("BLOG_OUTPUT_DIR", "")                   # Empty = blog/output (default)
