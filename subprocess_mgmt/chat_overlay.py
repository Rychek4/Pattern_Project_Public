"""
Pattern Project - Chat Overlay Subprocess
Placeholder for visual chat display overlay
"""

from pathlib import Path
from typing import Optional

from subprocess_mgmt.manager import ProcessConfig, get_subprocess_manager
from core.logger import log_info


# Default configuration
CHAT_OVERLAY_CONFIG = ProcessConfig(
    name="chat_overlay",
    command=["python", "chat_overlay_server.py"],
    working_dir=None,
    health_url="http://127.0.0.1:5004/health",
    health_timeout=5.0,
    startup_timeout=30.0,
    max_restart_attempts=3,
    enabled=False  # Disabled by default until implemented
)


def register_chat_overlay(
    script_path: Optional[Path] = None,
    port: int = 5004,
    enabled: bool = False
) -> None:
    """
    Register the chat overlay subprocess.

    Args:
        script_path: Path to the chat overlay script
        port: Port for the chat overlay HTTP server
        enabled: Whether to enable the chat overlay
    """
    config = ProcessConfig(
        name="chat_overlay",
        command=["python", str(script_path)] if script_path else ["python", "chat_overlay_server.py"],
        working_dir=script_path.parent if script_path else None,
        health_url=f"http://127.0.0.1:{port}/health",
        health_timeout=5.0,
        startup_timeout=30.0,
        max_restart_attempts=3,
        enabled=enabled
    )

    manager = get_subprocess_manager()
    manager.register(config)

    if enabled:
        log_info(f"Chat overlay registered on port {port}", prefix="🎨")
    else:
        log_info("Chat overlay: DISABLED (not configured)", prefix="🎨")


def start_chat_overlay() -> bool:
    """Start the chat overlay subprocess."""
    manager = get_subprocess_manager()
    return manager.start("chat_overlay")


def stop_chat_overlay() -> bool:
    """Stop the chat overlay subprocess."""
    manager = get_subprocess_manager()
    return manager.stop("chat_overlay")


# ============================================================================
# PLACEHOLDER: Chat Overlay Server
# ============================================================================
# When implemented, create a separate file: chat_overlay_server.py
#
# The chat overlay server should:
# 1. Run a Flask server on the configured port
# 2. Serve a web page with the chat overlay UI
# 3. Accept POST requests to /chat with new messages
# 4. Provide a /health endpoint for health checks
# 5. Use WebSockets or SSE for real-time updates
#
# Example API:
#   POST /chat
#   Body: {"sender": "AI", "message": "Hello!", "timestamp": "..."}
#
#   GET /health
#   Response: {"status": "healthy"}
#
#   GET /
#   Response: HTML page with overlay UI (can be embedded in OBS, etc.)
#
# For implementation reference, see the WoW proxy project's chat_overlay.py
# ============================================================================
