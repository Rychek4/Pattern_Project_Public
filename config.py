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
# LLM CONFIGURATION
# =============================================================================
# Anthropic (Claude)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-5-20251101")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))

# KoboldCpp (Local)
KOBOLD_API_URL = os.getenv("KOBOLD_API_URL", "http://127.0.0.1:5001")
KOBOLD_MAX_CONTEXT = int(os.getenv("KOBOLD_MAX_CONTEXT", "4096"))
KOBOLD_MAX_LENGTH = int(os.getenv("KOBOLD_MAX_LENGTH", "512"))

# Routing
LLM_PRIMARY_PROVIDER = os.getenv("LLM_PRIMARY_PROVIDER", "anthropic")  # 'anthropic' or 'kobold'
LLM_EXTRACTION_PROVIDER = "kobold"  # Always use local for extraction
LLM_FALLBACK_ENABLED = True  # Fall back to kobold if anthropic fails

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
MEMORY_EXTRACTION_THRESHOLD = 10  # Turns before triggering extraction
MEMORY_EXTRACTION_INTERVAL = 60  # Seconds between extraction checks
MEMORY_MAX_PER_QUERY = 10  # Max memories to retrieve per query
MEMORY_FRESHNESS_HALF_LIFE_DAYS = 30  # Decay rate for freshness scoring

# Scoring weights
MEMORY_SEMANTIC_WEIGHT = 0.6
MEMORY_FRESHNESS_WEIGHT = 0.3
MEMORY_ACCESS_WEIGHT = 0.1

# =============================================================================
# SESSION CONFIGURATION
# =============================================================================
SESSION_IDLE_WARNING_SECONDS = 600  # 10 minutes
SESSION_AUTO_EXTRACT_ON_END = True

# =============================================================================
# AGENCY CONFIGURATION
# =============================================================================
AGENCY_ENABLED = True
AGENCY_CHECK_INTERVAL = 300  # 5 minutes
AGENCY_IDLE_TRIGGER_SECONDS = 900  # 15 minutes before AI initiates

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
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_TO_FILE = True
LOG_TO_CONSOLE = True

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

# =============================================================================
# RELATIONSHIP CONFIGURATION
# =============================================================================
RELATIONSHIP_ANALYSIS_INTERVAL = 120  # Seconds between relationship analysis
RELATIONSHIP_MIN_TURNS = 4  # Minimum turns before analysis
RELATIONSHIP_MAX_DELTA = 0.1  # Maximum change per analysis

# =============================================================================
# VISUAL CAPTURE CONFIGURATION
# =============================================================================
VISUAL_ENABLED = os.getenv("VISUAL_ENABLED", "false").lower() == "true"
VISUAL_CAPTURE_INTERVAL = int(os.getenv("VISUAL_CAPTURE_INTERVAL", "30"))
VISUAL_SCREENSHOT_ENABLED = True
VISUAL_WEBCAM_ENABLED = True
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
