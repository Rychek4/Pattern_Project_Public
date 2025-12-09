#!/usr/bin/env python3
"""
Pattern Project - Main Entry Point
AI Companion System with persistent memory and proactive agency

Usage:
    python main.py           # Run in GUI mode (PyQt5 window) - default
    python main.py --cli     # Run in CLI mode (console)
    python main.py -c        # Short form for CLI mode
    python main.py --dev     # Enable dev mode (debug window)
    python main.py -d        # Short form for dev mode
    python main.py --dev -c  # Dev mode in CLI
"""

import sys
import signal
import threading
import argparse
from pathlib import Path

# Ensure we can import from project root
sys.path.insert(0, str(Path(__file__).parent))

import config
from core.logger import (
    setup_logging,
    log_startup_banner,
    log_section,
    log_subsection,
    log_success,
    log_warning,
    log_error,
    log_ready,
    log_config
)
from core.database import init_database
from core.embeddings import load_embedding_model, get_model_info
from core.temporal import init_temporal_tracker
from concurrency.locks import init_lock_manager, get_lock_manager
from llm.router import init_llm_router, get_llm_router, LLMProvider
from memory.conversation import init_conversation_manager
from memory.vector_store import init_vector_store
from memory.extractor import init_memory_extractor
from interface.cli import init_cli, get_cli
from interface.http_api import init_http_server, get_http_server
from agency.proactive import init_proactive_agent, get_proactive_agent
from agency.visual_capture import init_visual_capture, get_visual_capture
from agency.system_pulse import init_system_pulse_timer, get_system_pulse_timer
from subprocess_mgmt.manager import init_subprocess_manager, get_subprocess_manager
from subprocess_mgmt.audio_player import register_audio_player
from subprocess_mgmt.chat_overlay import register_chat_overlay
from prompt_builder import init_prompt_builder


# Global shutdown event
_shutdown_event = threading.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    print()  # New line after ^C
    log_warning("Shutdown signal received...")
    _shutdown_event.set()


def initialize_system() -> bool:
    """
    Initialize all system components.

    Returns:
        True if successful, False otherwise
    """
    # Setup logging first
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(
        log_file_path=config.DIAGNOSTIC_LOG_PATH,
        level=config.LOG_LEVEL,
        log_to_file=config.LOG_TO_FILE,
        log_to_console=config.LOG_TO_CONSOLE
    )

    # Print startup banner
    log_startup_banner(config.VERSION, config.PROJECT_NAME)

    # Initialize database
    if not init_database(
        db_path=config.DATABASE_PATH,
        busy_timeout_ms=config.DB_BUSY_TIMEOUT_MS
    ):
        log_error("Failed to initialize database")
        return False

    # Load embedding model (this can take a while)
    # System can run in degraded mode without embeddings (no semantic search)
    embedding_loaded = load_embedding_model(config.EMBEDDING_MODEL)
    if not embedding_loaded:
        log_warning("=" * 60)
        log_warning("RUNNING IN DEGRADED MODE - Semantic memory disabled")
        log_warning("Conversations will still be stored and you can chat normally,")
        log_warning("but memory recall and extraction won't work.")
        log_warning("=" * 60)

    # Print configuration summary
    print_configuration()

    # Initialize components
    init_lock_manager()
    init_temporal_tracker()
    init_conversation_manager()
    init_vector_store()

    # Initialize LLM router and check providers
    init_llm_router(
        primary_provider=config.LLM_PRIMARY_PROVIDER,
        fallback_enabled=config.LLM_FALLBACK_ENABLED
    )
    check_llm_providers()

    # Initialize memory extractor
    init_memory_extractor()

    # Initialize prompt builder (must come after memory/vector store)
    init_prompt_builder()

    # Initialize agency (legacy - disabled)
    init_proactive_agent()

    # Initialize system pulse timer
    init_system_pulse_timer()

    # Initialize visual capture if enabled
    if config.VISUAL_ENABLED:
        init_visual_capture(
            gemini_api_key=config.GOOGLE_API_KEY,
            capture_interval=config.VISUAL_CAPTURE_INTERVAL,
            enable_screenshot=config.VISUAL_SCREENSHOT_ENABLED,
            enable_webcam=config.VISUAL_WEBCAM_ENABLED
        )

    # Initialize subprocess manager and register subprocesses
    init_subprocess_manager()
    register_audio_player(enabled=config.SUBPROCESS_AUDIO_ENABLED)
    register_chat_overlay(enabled=config.SUBPROCESS_OVERLAY_ENABLED)

    # Initialize HTTP server if enabled
    if config.HTTP_ENABLED:
        init_http_server(host=config.HTTP_HOST, port=config.HTTP_PORT)

    # Initialize CLI
    init_cli()

    return True


def print_configuration() -> None:
    """Print configuration summary."""
    log_section("Configuration", "📡")
    log_subsection(f"Database: {config.DATABASE_PATH}")
    log_subsection(f"Diagnostic Log: {config.DIAGNOSTIC_LOG_PATH}")
    if config.DEV_MODE_ENABLED:
        log_subsection("Dev Mode: ENABLED (debug window active)")

    # Embedding model info
    model_info = get_model_info()
    if model_info["loaded"]:
        log_subsection(f"Embedding Model: {model_info['model_name']} ({model_info['dimensions']} dim)")

    # Database concurrency settings
    log_section("Database Concurrency", "🔒")
    log_subsection(f"Busy Timeout: {config.DB_BUSY_TIMEOUT_MS}ms")
    log_subsection(f"Max Retries: {config.DB_MAX_RETRIES}")
    log_subsection(f"Retry Initial Delay: {config.DB_RETRY_INITIAL_DELAY}s")
    log_subsection(f"Backoff Multiplier: {config.DB_RETRY_BACKOFF_MULTIPLIER}x")
    log_subsection(f"Lock monitoring: ACTIVE (stats printed every {config.LOCK_STATS_INTERVAL // 60}min)")

    # Background threads
    log_section("Background Threads", "🧵")
    log_subsection(f"Memory Extractor: THRESHOLD-TRIGGERED (every {config.MEMORY_EXTRACTION_THRESHOLD} turns)")
    log_subsection(f"Health Monitor: ENABLED (interval: {config.HEALTH_CHECK_INTERVAL}s)")
    log_subsection(f"Lock Stats: ENABLED (interval: {config.LOCK_STATS_INTERVAL}s)")

    # Memory settings
    log_section("Memory Settings", "🧠")
    log_subsection(f"Extraction Threshold: {config.MEMORY_EXTRACTION_THRESHOLD} turns")
    log_subsection(f"Freshness Half-Life: {config.MEMORY_FRESHNESS_HALF_LIFE_DAYS} days")
    log_subsection(f"Scoring Weights: semantic={config.MEMORY_SEMANTIC_WEIGHT}, "
                   f"freshness={config.MEMORY_FRESHNESS_WEIGHT}, access={config.MEMORY_ACCESS_WEIGHT}")

    # Prompt Builder settings
    log_section("Prompt Builder", "📝")
    log_subsection(f"Conversation History: {config.CONVERSATION_EXCHANGE_LIMIT} exchanges")
    log_subsection(f"Memory Promotion Threshold: {config.MEMORY_PROMOTION_THRESHOLD}")

    # Visual settings
    if config.VISUAL_ENABLED:
        log_section("Visual Capture", "📷")
        log_subsection(f"Capture Interval: {config.VISUAL_CAPTURE_INTERVAL}s")
        log_subsection(f"Screenshot: {'ENABLED' if config.VISUAL_SCREENSHOT_ENABLED else 'DISABLED'}")
        log_subsection(f"Webcam: {'ENABLED' if config.VISUAL_WEBCAM_ENABLED else 'DISABLED'}")


def check_llm_providers() -> None:
    """Check and display LLM provider status."""
    log_section("LLM Routing", "🤖")

    router = get_llm_router()
    status = router.check_providers()

    # Primary provider
    primary = router.primary_provider
    primary_status = status.get(primary, (False, "Unknown"))
    if primary_status[0]:
        log_subsection(f"Primary ({primary.value}): ✅ {primary_status[1]}")
    else:
        log_subsection(f"Primary ({primary.value}): ❌ {primary_status[1]}")

    # Secondary provider (extraction)
    secondary = LLMProvider.KOBOLD
    secondary_status = status.get(secondary, (False, "Unknown"))
    if secondary_status[0]:
        log_subsection(f"Extraction ({secondary.value}): ✅ {secondary_status[1]}")
    else:
        log_subsection(f"Extraction ({secondary.value}): ❌ {secondary_status[1]}")

    # Fallback status
    if config.LLM_FALLBACK_ENABLED:
        log_subsection("Fallback: ENABLED")
    else:
        log_subsection("Fallback: DISABLED")


def start_background_services() -> None:
    """Start all background services."""
    log_section("Starting Services", "🔧")

    # Memory extractor is threshold-triggered (no background thread to start)
    log_subsection("Memory extractor ready (threshold-triggered)")

    # Start proactive agent (legacy - disabled by default)
    proactive = get_proactive_agent()
    proactive.start()
    if config.AGENCY_ENABLED:
        log_subsection("Proactive agent started")

    # Start system pulse timer
    if config.SYSTEM_PULSE_ENABLED:
        pulse_timer = get_system_pulse_timer()
        pulse_timer.start()

    # Start visual capture if enabled
    if config.VISUAL_ENABLED:
        visual_capture = get_visual_capture()
        visual_capture.start()
        log_subsection("Visual capture started")

    # Start subprocess manager monitoring
    subprocess_mgr = get_subprocess_manager()
    subprocess_mgr.start_monitor()
    log_subsection("Subprocess monitor started")

    # Start registered subprocesses
    if config.SUBPROCESS_AUDIO_ENABLED:
        subprocess_mgr.start("audio_player")
    if config.SUBPROCESS_OVERLAY_ENABLED:
        subprocess_mgr.start("chat_overlay")

    # Start HTTP server if enabled
    if config.HTTP_ENABLED:
        http_server = get_http_server()
        http_server.start()
        log_subsection(f"HTTP API started on http://{config.HTTP_HOST}:{config.HTTP_PORT}")


def stop_background_services() -> None:
    """Stop all background services gracefully."""
    log_section("Stopping Services", "🛑")

    # Memory extractor is threshold-triggered (no background thread to stop)
    log_subsection("Memory extractor: no cleanup needed")

    # Stop proactive agent (legacy)
    try:
        proactive = get_proactive_agent()
        proactive.stop()
        if config.AGENCY_ENABLED:
            log_subsection("Proactive agent stopped")
    except Exception as e:
        log_error(f"Error stopping proactive agent: {e}")

    # Stop system pulse timer
    if config.SYSTEM_PULSE_ENABLED:
        try:
            pulse_timer = get_system_pulse_timer()
            pulse_timer.stop()
            log_subsection("System pulse timer stopped")
        except Exception as e:
            log_error(f"Error stopping system pulse timer: {e}")

    # Stop visual capture if enabled
    if config.VISUAL_ENABLED:
        try:
            visual_capture = get_visual_capture()
            visual_capture.stop()
            log_subsection("Visual capture stopped")
        except Exception as e:
            log_error(f"Error stopping visual capture: {e}")

    # Stop subprocesses
    try:
        subprocess_mgr = get_subprocess_manager()
        subprocess_mgr.stop_all()
        subprocess_mgr.stop_monitor()
        log_subsection("Subprocess manager stopped")
    except Exception as e:
        log_error(f"Error stopping subprocess manager: {e}")

    # Log final lock stats
    try:
        lock_mgr = get_lock_manager()
        lock_mgr.log_stats()
    except Exception:
        pass


def main() -> int:
    """
    Main entry point.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Pattern Project - AI Companion System",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--cli", "-c",
        action="store_true",
        help="Launch CLI mode instead of GUI (console interface)"
    )
    parser.add_argument(
        "--dev", "-d",
        action="store_true",
        help="Enable dev mode (debug window showing internal operations)"
    )
    args = parser.parse_args()

    # Set dev mode in config if requested
    if args.dev:
        config.DEV_MODE_ENABLED = True

    # CLI mode - only if explicitly requested
    if args.cli:
        return run_cli_mode()

    # GUI mode - default
    try:
        # =============================================================
        # CRITICAL: Load PyTorch BEFORE importing PyQt5
        # MS Store Python has DLL loading conflicts - if Qt5 DLLs load
        # first, PyTorch's c10.dll fails to initialize in the sandbox.
        # The gui.py module has PyQt5 imports at module level, so we
        # must load PyTorch HERE, before the import statement executes.
        # =============================================================
        config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)

        print("Loading embedding model...")
        embedding_loaded = load_embedding_model(config.EMBEDDING_MODEL)
        if not embedding_loaded:
            print("=" * 60)
            print("WARNING: Embedding model failed to load")
            print("Continuing in degraded mode (no semantic memory)")
            print("=" * 60)

        # NOW safe to import GUI module (triggers PyQt5 module-level imports)
        from interface.gui import run_gui
        return run_gui()
    except ImportError as e:
        print(f"GUI mode requires PyQt5: {e}")
        print("Install with: pip install PyQt5")
        print("Falling back to CLI mode...")
        return run_cli_mode()


def run_cli_mode() -> int:
    """Run the application in CLI mode."""
    # CLI mode - original flow
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Initialize system
        if not initialize_system():
            log_error("System initialization failed")
            return 1

        # Start background services
        start_background_services()

        # Print ready message
        log_ready()

        # Start CLI (blocks until exit)
        cli = get_cli()
        cli.start()

        # Graceful shutdown
        stop_background_services()

        log_success("Pattern Project shutdown complete")
        return 0

    except KeyboardInterrupt:
        log_warning("Interrupted")
        stop_background_services()
        return 130

    except Exception as e:
        log_error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
