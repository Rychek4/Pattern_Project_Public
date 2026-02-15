"""
Pattern Project - Audio Player Server (ElevenLabs TTS)

A Flask microservice that handles text-to-speech using ElevenLabs API.
Runs as a subprocess managed by the subprocess manager.

Endpoints:
  POST /play_audio - Convert text to speech and play it
  GET /health - Health check endpoint
  POST /stop - Stop current audio playback
"""

import os
import sys
import threading
import queue
import logging
from io import BytesIO
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify

app = Flask(__name__)

# Configure logging to stderr so subprocess manager can capture it
logging.basicConfig(
    level=logging.INFO,
    format='[AUDIO_SERVER %(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def log_server(msg: str, level: str = "info"):
    """Log a message with timestamp."""
    timestamp = datetime.now().strftime("%H:%M:%S")
    # Print to stdout for immediate visibility
    print(f"[AUDIO_SERVER {timestamp}] {msg}", flush=True)
    # Also log via logger
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)

# Audio playback state
_playback_lock = threading.Lock()
_current_playback_thread: threading.Thread | None = None
_stop_requested = threading.Event()

# Check for required dependencies
_elevenlabs_available = False
_audio_available = False

try:
    from elevenlabs import stream
    from elevenlabs.client import ElevenLabs
    _elevenlabs_available = True
    log_server("✓ elevenlabs package available")
except ImportError:
    log_server("✗ elevenlabs package NOT installed - TTS will not work", "error")

try:
    import sounddevice  # elevenlabs uses this for streaming playback
    _audio_available = True
    log_server("✓ sounddevice audio backend available")
except ImportError:
    try:
        import pyaudio
        _audio_available = True
        log_server("✓ pyaudio audio backend available")
    except ImportError:
        log_server("✗ No audio backend available - install sounddevice or pyaudio", "error")


def _get_client() -> "ElevenLabs | None":
    """Get an ElevenLabs client instance."""
    if not _elevenlabs_available:
        log_server("Cannot create client - elevenlabs not available", "error")
        return None

    api_key = os.getenv("Eleven_Labs_API", "")
    if not api_key:
        log_server("Cannot create client - Eleven_Labs_API env var not set", "error")
        return None

    log_server(f"Creating ElevenLabs client (API key: {api_key[:8]}...)")
    return ElevenLabs(api_key=api_key)


def _play_audio_stream(text: str, voice_id: str, model: str):
    """
    Stream audio from ElevenLabs and play it.

    This runs in a separate thread to not block the HTTP response.
    """
    global _stop_requested

    text_preview = text[:50] + "..." if len(text) > 50 else text
    log_server(f"Starting audio stream for: '{text_preview}'")
    log_server(f"Voice: {voice_id}, Model: {model}")

    try:
        client = _get_client()
        if not client:
            log_server("Could not create ElevenLabs client - aborting", "error")
            return

        log_server("Calling ElevenLabs API to generate audio...")
        # Generate streaming audio (ElevenLabs SDK 1.0+ API)
        audio_stream = client.text_to_speech.stream(
            text=text,
            voice_id=voice_id,
            model_id=model,
        )
        log_server("Got audio stream from ElevenLabs, starting playback...")

        # Use elevenlabs built-in streaming playback
        # This handles chunked streaming automatically
        stream(audio_stream)
        log_server("Audio playback completed successfully")

    except Exception as e:
        log_server(f"Audio playback failed: {type(e).__name__}: {e}", "error")
        import traceback
        log_server(f"Traceback: {traceback.format_exc()}", "error")
    finally:
        _stop_requested.clear()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    api_key_set = bool(os.getenv("Eleven_Labs_API", ""))

    # Determine if truly healthy (all required components available)
    is_healthy = _elevenlabs_available and _audio_available and api_key_set

    status = {
        "status": "healthy" if is_healthy else "degraded",
        "elevenlabs_available": _elevenlabs_available,
        "audio_available": _audio_available,
        "api_key_set": api_key_set,
        "ready_for_tts": is_healthy
    }

    # Return 503 if not fully functional
    if not is_healthy:
        missing = []
        if not _elevenlabs_available:
            missing.append("elevenlabs package")
        if not _audio_available:
            missing.append("audio backend (sounddevice/pyaudio)")
        if not api_key_set:
            missing.append("Eleven_Labs_API env var")
        status["missing"] = missing
        return jsonify(status), 503

    return jsonify(status)


@app.route('/play_audio', methods=['POST'])
def play_audio():
    """
    Play text as speech using ElevenLabs.

    Request body:
    {
        "text": "Text to speak",
        "voice_id": "optional voice ID",
        "model": "optional model ID"
    }
    """
    global _current_playback_thread

    log_server("Received /play_audio request")

    if not _elevenlabs_available:
        log_server("Rejecting request - elevenlabs not available", "error")
        return jsonify({
            "success": False,
            "error": "elevenlabs package not installed"
        }), 503

    if not _audio_available:
        log_server("Rejecting request - no audio backend", "error")
        return jsonify({
            "success": False,
            "error": "No audio backend available (install sounddevice or pyaudio)"
        }), 503

    data = request.get_json() or {}
    text = data.get('text', '')

    if not text:
        log_server("Rejecting request - no text provided", "warning")
        return jsonify({
            "success": False,
            "error": "No text provided"
        }), 400

    # Get voice settings with defaults
    voice_id = data.get('voice_id', 'MKHH3pSZhHPPzypDhMoU')
    model = data.get('model', 'eleven_turbo_v2_5')

    text_preview = text[:50] + "..." if len(text) > 50 else text
    log_server(f"Starting TTS for {len(text)} chars: '{text_preview}'")
    log_server(f"Voice: {voice_id}, Model: {model}")

    with _playback_lock:
        # Start playback in background thread
        _stop_requested.clear()
        _current_playback_thread = threading.Thread(
            target=_play_audio_stream,
            args=(text, voice_id, model),
            daemon=True
        )
        _current_playback_thread.start()
        log_server(f"Playback thread started: {_current_playback_thread.name}")

    return jsonify({
        "success": True,
        "message": "Audio playback started",
        "text_length": len(text)
    })


@app.route('/stop', methods=['POST'])
def stop_audio():
    """Stop current audio playback."""
    _stop_requested.set()
    return jsonify({
        "success": True,
        "message": "Stop requested"
    })


if __name__ == '__main__':
    port = int(os.getenv('AUDIO_PLAYER_PORT', '5003'))
    print(f"Starting Audio Player Server on port {port}")
    print(f"ElevenLabs available: {_elevenlabs_available}")
    print(f"Audio backend available: {_audio_available}")
    print(f"API key set: {bool(os.getenv('Eleven_Labs_API', ''))}")

    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)
