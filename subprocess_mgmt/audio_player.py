"""
Pattern Project - Audio Player Subprocess
ElevenLabs text-to-speech audio playback via subprocess
"""

from pathlib import Path
from typing import Optional

import config
from subprocess_mgmt.manager import ProcessConfig, get_subprocess_manager
from core.logger import log_info, log_warning


# Path to the audio player server script
AUDIO_PLAYER_SCRIPT = Path(__file__).parent / "audio_player_server.py"

# Default configuration
AUDIO_PLAYER_CONFIG = ProcessConfig(
    name="audio_player",
    command=["python", str(AUDIO_PLAYER_SCRIPT)],
    working_dir=Path(__file__).parent,
    health_url=f"http://127.0.0.1:{config.ELEVENLABS_AUDIO_PORT}/health",
    health_timeout=5.0,
    startup_timeout=30.0,
    max_restart_attempts=3,
    enabled=False  # Enabled dynamically based on user settings
)


def register_audio_player(
    script_path: Optional[Path] = None,
    port: Optional[int] = None,
    enabled: bool = False
) -> None:
    """
    Register the audio player subprocess.

    Args:
        script_path: Path to the audio player script (defaults to bundled server)
        port: Port for the audio player HTTP server (defaults to config)
        enabled: Whether to enable the audio player
    """
    if port is None:
        port = config.ELEVENLABS_AUDIO_PORT

    if script_path is None:
        script_path = AUDIO_PLAYER_SCRIPT

    proc_config = ProcessConfig(
        name="audio_player",
        command=["python", str(script_path)],
        working_dir=script_path.parent if script_path else None,
        health_url=f"http://127.0.0.1:{port}/health",
        health_timeout=5.0,
        startup_timeout=30.0,
        max_restart_attempts=3,
        enabled=enabled
    )

    manager = get_subprocess_manager()
    manager.register(proc_config)

    if enabled:
        log_info(f"Audio player registered on port {port}", prefix="🔊")
    else:
        log_info("Audio player: DISABLED (TTS not enabled)", prefix="🔊")


def start_audio_player() -> bool:
    """Start the audio player subprocess."""
    manager = get_subprocess_manager()
    return manager.start("audio_player")


def stop_audio_player() -> bool:
    """Stop the audio player subprocess."""
    manager = get_subprocess_manager()
    # Only attempt to stop if the process is registered
    if manager.get_status("audio_player") is None:
        return True  # Nothing to stop
    return manager.stop("audio_player")


def play_tts(text: str, voice_id: Optional[str] = None) -> bool:
    """
    Send text to the audio player for TTS playback.

    Args:
        text: The text to speak
        voice_id: Optional ElevenLabs voice ID (uses default if not specified)

    Returns:
        True if request was sent successfully, False otherwise
    """
    import requests

    port = config.ELEVENLABS_AUDIO_PORT
    url = f"http://127.0.0.1:{port}/play_audio"

    effective_voice_id = voice_id or config.ELEVENLABS_DEFAULT_VOICE_ID
    payload = {
        "text": text,
        "voice_id": effective_voice_id,
        "model": config.ELEVENLABS_MODEL
    }

    text_preview = text[:50] + "..." if len(text) > 50 else text
    log_info(f"TTS client: sending to {url}", prefix="🔊")
    log_info(f"TTS client: text='{text_preview}', voice={effective_voice_id}", prefix="🔊")

    try:
        response = requests.post(url, json=payload, timeout=5)
        log_info(f"TTS client: got response {response.status_code}", prefix="🔊")
        if response.status_code == 200:
            response_data = response.json()
            log_info(f"TTS client: success - {response_data}", prefix="🔊")
            return True
        else:
            log_warning(f"TTS client: request failed ({response.status_code}): {response.text}")
            return False
    except requests.exceptions.ConnectionError as e:
        log_warning(f"TTS client: audio player not running - {e}")
        return False
    except Exception as e:
        log_warning(f"TTS client: request error - {e}")
        return False
