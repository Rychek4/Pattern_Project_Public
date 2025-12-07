"""
Pattern Project - Audio Player Subprocess
Placeholder for text-to-speech audio playback
"""

from pathlib import Path
from typing import Optional

from subprocess_mgmt.manager import ProcessConfig, get_subprocess_manager
from core.logger import log_info


# Default configuration
AUDIO_PLAYER_CONFIG = ProcessConfig(
    name="audio_player",
    command=["python", "audio_player_server.py"],
    working_dir=None,
    health_url="http://127.0.0.1:5003/health",
    health_timeout=5.0,
    startup_timeout=30.0,
    max_restart_attempts=3,
    enabled=False  # Disabled by default until implemented
)


def register_audio_player(
    script_path: Optional[Path] = None,
    port: int = 5003,
    enabled: bool = False
) -> None:
    """
    Register the audio player subprocess.

    Args:
        script_path: Path to the audio player script
        port: Port for the audio player HTTP server
        enabled: Whether to enable the audio player
    """
    config = ProcessConfig(
        name="audio_player",
        command=["python", str(script_path)] if script_path else ["python", "audio_player_server.py"],
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
        log_info(f"Audio player registered on port {port}", prefix="🔊")
    else:
        log_info("Audio player: DISABLED (not configured)", prefix="🔊")


def start_audio_player() -> bool:
    """Start the audio player subprocess."""
    manager = get_subprocess_manager()
    return manager.start("audio_player")


def stop_audio_player() -> bool:
    """Stop the audio player subprocess."""
    manager = get_subprocess_manager()
    return manager.stop("audio_player")


# ============================================================================
# PLACEHOLDER: Audio Player Server
# ============================================================================
# When implemented, create a separate file: audio_player_server.py
#
# The audio player server should:
# 1. Run a Flask server on the configured port
# 2. Accept POST requests to /play_audio with audio data
# 3. Provide a /health endpoint for health checks
# 4. Support TTS via Google Cloud, ElevenLabs, or local synthesis
#
# Example API:
#   POST /play_audio
#   Body: {"text": "Hello world", "voice": "default"}
#
#   GET /health
#   Response: {"status": "healthy"}
#
# For implementation reference, see the WoW proxy project's audio_player.py
# ============================================================================
