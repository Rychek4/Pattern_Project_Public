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
from memory.conversation import init_conversation_manager, get_conversation_manager
from memory.vector_store import init_vector_store
from memory.extractor import init_memory_extractor
from interface.cli import init_cli, get_cli
from interface.http_api import init_http_server, get_http_server
from agency.proactive import init_proactive_agent, get_proactive_agent
# Visual capture is now stateless - no init/start/stop lifecycle needed.
# Capture happens on-demand via capture_all_visuals() in gui.py.
# Import availability checker for startup logging only.
from agency.visual_capture import is_visual_capture_available, release_webcam
from agency.system_pulse import init_system_pulse_timer, get_system_pulse_timer
from agency.intentions import init_reminder_scheduler, get_reminder_scheduler
from subprocess_mgmt.manager import init_subprocess_manager, get_subprocess_manager
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

    # Clean up any empty assistant messages from previous sessions
    # These can cause API errors: "messages must have non-empty content"
    get_conversation_manager().cleanup_empty_messages()

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

    # Initialize communication gateways if enabled
    if config.EMAIL_GATEWAY_ENABLED or config.TELEGRAM_ENABLED:
        from communication.rate_limiter import init_rate_limiter

        # Initialize rate limiter
        init_rate_limiter(
            email_max_per_hour=config.EMAIL_MAX_PER_HOUR,
            telegram_max_per_hour=config.TELEGRAM_MAX_PER_HOUR
        )

        # Initialize email gateway if enabled
        if config.EMAIL_GATEWAY_ENABLED:
            from communication.email_gateway import init_email_gateway
            init_email_gateway()

        # Initialize Telegram gateway and listener if enabled
        if config.TELEGRAM_ENABLED:
            from communication.telegram_gateway import init_telegram_gateway, get_telegram_gateway
            from communication.telegram_listener import init_telegram_listener, get_telegram_listener

            gateway = init_telegram_gateway()
            listener = init_telegram_listener()

            # Connect listener to gateway so auto-detected chat_id propagates
            def on_chat_id_detected(chat_id: str):
                gateway.set_chat_id(chat_id)
            listener.set_chat_id_callback(on_chat_id_detected)

    # Initialize agency (legacy - disabled)
    init_proactive_agent()

    # Initialize system pulse timer
    init_system_pulse_timer()

    # Initialize reminder scheduler
    init_reminder_scheduler(enabled=True)

    # Visual capture check - the new system is stateless (no init needed).
    # Just verify availability for startup logging.
    if config.VISUAL_ENABLED:
        screenshot_ok, webcam_ok = is_visual_capture_available()
        if not screenshot_ok and config.VISUAL_SCREENSHOT_ENABLED:
            log_warning("Screenshot capture unavailable (PIL not installed)")
        if not webcam_ok and config.VISUAL_WEBCAM_ENABLED:
            log_warning("Webcam capture unavailable (OpenCV not installed)")

    # Initialize subprocess manager and register subprocesses
    init_subprocess_manager()
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
    log_subsection(f"Memory Extractor: WINDOWED (overflow at {config.CONTEXT_OVERFLOW_TRIGGER} turns)")
    log_subsection(f"Health Monitor: ENABLED (interval: {config.HEALTH_CHECK_INTERVAL}s)")
    log_subsection(f"Lock Stats: ENABLED (interval: {config.LOCK_STATS_INTERVAL}s)")

    # Memory settings
    log_section("Memory Settings", "🧠")
    log_subsection(f"Context Window: {config.CONTEXT_WINDOW_SIZE} turns (overflow trigger: {config.CONTEXT_OVERFLOW_TRIGGER})")
    log_subsection(f"Scoring Weights: semantic={config.MEMORY_SEMANTIC_WEIGHT}, "
                   f"importance={config.MEMORY_IMPORTANCE_WEIGHT}, "
                   f"freshness={config.MEMORY_FRESHNESS_WEIGHT}")

    # Prompt Builder settings
    log_section("Prompt Builder", "📝")
    log_subsection(f"Conversation History: {config.CONTEXT_WINDOW_SIZE} turns (windowed)")
    log_subsection(f"Memory Promotion Threshold: {config.MEMORY_PROMOTION_THRESHOLD}")
    log_subsection(f"Deduplication: {'ENABLED' if config.MEMORY_DEDUP_ENABLED else 'DISABLED'} (threshold: {config.MEMORY_DEDUP_THRESHOLD})")

    # Visual settings
    if config.VISUAL_ENABLED:
        log_section("Visual Capture", "📷")
        log_subsection(f"Capture Interval: {config.VISUAL_CAPTURE_INTERVAL}s")
        log_subsection(f"Screenshot: {'ENABLED' if config.VISUAL_SCREENSHOT_ENABLED else 'DISABLED'}")
        log_subsection(f"Webcam: {'ENABLED' if config.VISUAL_WEBCAM_ENABLED else 'DISABLED'}")

    # Communication settings
    if config.EMAIL_GATEWAY_ENABLED or config.TELEGRAM_ENABLED:
        log_section("Communication", "📱")
        log_subsection(f"Email: {'ENABLED' if config.EMAIL_GATEWAY_ENABLED else 'DISABLED'}")
        log_subsection(f"Telegram: {'ENABLED' if config.TELEGRAM_ENABLED else 'DISABLED'}")
        if config.TELEGRAM_ENABLED:
            chat_id = config.TELEGRAM_CHAT_ID
            masked = f"...{chat_id[-4:]}" if len(chat_id) >= 4 else "auto-detect"
            log_subsection(f"Telegram Chat: {masked}")
        log_subsection(f"Rate Limits: {config.EMAIL_MAX_PER_HOUR} email/hr, {config.TELEGRAM_MAX_PER_HOUR} telegram/hr")


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

    # Start reminder scheduler
    reminder_scheduler = get_reminder_scheduler()
    reminder_scheduler.start()
    log_subsection("Reminder scheduler started")

    # Visual capture is stateless - no background service to start.
    # Capture happens on-demand when building messages in gui.py.
    if config.VISUAL_ENABLED:
        log_subsection("Visual capture ready (on-demand)")

    # Start subprocess manager monitoring
    subprocess_mgr = get_subprocess_manager()
    subprocess_mgr.start_monitor()
    log_subsection("Subprocess monitor started")

    # Start registered subprocesses
    if config.SUBPROCESS_OVERLAY_ENABLED:
        subprocess_mgr.start("chat_overlay")

    # Start HTTP server if enabled
    if config.HTTP_ENABLED:
        http_server = get_http_server()
        http_server.start()
        log_subsection(f"HTTP API started on http://{config.HTTP_HOST}:{config.HTTP_PORT}")

    # Start Telegram listener if enabled (callback set by CLI)
    if config.TELEGRAM_ENABLED:
        from communication.telegram_listener import get_telegram_listener
        telegram_listener = get_telegram_listener()
        telegram_listener.start()
        log_subsection("Telegram listener started")


def stop_background_services() -> None:
    """Stop all background services gracefully."""
    log_section("Stopping Services", "🛑")

    # Wait for any in-progress memory extraction to complete cleanly
    try:
        from memory.extractor import get_memory_extractor

        extractor = get_memory_extractor()

        # Wait for extraction to finish so memories are fully written
        if extractor.wait_for_completion(timeout=5.0):
            log_subsection("Memory extraction completed")
        else:
            log_subsection("Memory extraction timeout - some memories may be incomplete")

    except Exception as e:
        log_error(f"Error waiting for memory extraction: {e}")

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

    # Stop reminder scheduler
    try:
        reminder_scheduler = get_reminder_scheduler()
        reminder_scheduler.stop()
        log_subsection("Reminder scheduler stopped")
    except Exception as e:
        log_error(f"Error stopping reminder scheduler: {e}")

    # Release webcam device if it was opened
    try:
        release_webcam()
        log_subsection("Webcam device released")
    except Exception as e:
        log_error(f"Error releasing webcam: {e}")

    # Stop subprocesses
    try:
        subprocess_mgr = get_subprocess_manager()
        subprocess_mgr.stop_all()
        subprocess_mgr.stop_monitor()
        log_subsection("Subprocess manager stopped")
    except Exception as e:
        log_error(f"Error stopping subprocess manager: {e}")

    # Stop Telegram listener if enabled
    if config.TELEGRAM_ENABLED:
        try:
            from communication.telegram_listener import get_telegram_listener
            telegram_listener = get_telegram_listener()
            telegram_listener.stop()
            log_subsection("Telegram listener stopped")
        except Exception as e:
            log_error(f"Error stopping Telegram listener: {e}")

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
