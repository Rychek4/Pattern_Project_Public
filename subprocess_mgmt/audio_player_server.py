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
from io import BytesIO

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, jsonify

app = Flask(__name__)

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
except ImportError:
    print("WARNING: elevenlabs package not installed. TTS will not work.")
    print("Install with: pip install elevenlabs")

try:
    import sounddevice  # elevenlabs uses this for streaming playback
    _audio_available = True
except ImportError:
    try:
        import pyaudio
        _audio_available = True
    except ImportError:
        print("WARNING: No audio backend available. Install sounddevice or pyaudio.")


def _get_client() -> "ElevenLabs | None":
    """Get an ElevenLabs client instance."""
    if not _elevenlabs_available:
        return None

    api_key = os.getenv("Eleven_Labs_API", "")
    if not api_key:
        print("WARNING: Eleven_Labs_API environment variable not set")
        return None

    return ElevenLabs(api_key=api_key)


def _play_audio_stream(text: str, voice_id: str, model: str):
    """
    Stream audio from ElevenLabs and play it.

    This runs in a separate thread to not block the HTTP response.
    """
    global _stop_requested

    try:
        client = _get_client()
        if not client:
            print("ERROR: Could not create ElevenLabs client")
            return

        # Generate streaming audio
        audio_stream = client.generate(
            text=text,
            voice=voice_id,
            model=model,
            stream=True
        )

        # Use elevenlabs built-in streaming playback
        # This handles chunked streaming automatically
        stream(audio_stream)

    except Exception as e:
        print(f"ERROR: Audio playback failed: {e}")
    finally:
        _stop_requested.clear()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    status = {
        "status": "healthy",
        "elevenlabs_available": _elevenlabs_available,
        "audio_available": _audio_available,
        "api_key_set": bool(os.getenv("Eleven_Labs_API", ""))
    }
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

    if not _elevenlabs_available:
        return jsonify({
            "success": False,
            "error": "elevenlabs package not installed"
        }), 503

    if not _audio_available:
        return jsonify({
            "success": False,
            "error": "No audio backend available (install sounddevice or pyaudio)"
        }), 503

    data = request.get_json() or {}
    text = data.get('text', '')

    if not text:
        return jsonify({
            "success": False,
            "error": "No text provided"
        }), 400

    # Get voice settings with defaults
    voice_id = data.get('voice_id', 'MKHH3pSZhHPPzypDhMoU')
    model = data.get('model', 'eleven_monolingual_v1')

    with _playback_lock:
        # Start playback in background thread
        _stop_requested.clear()
        _current_playback_thread = threading.Thread(
            target=_play_audio_stream,
            args=(text, voice_id, model),
            daemon=True
        )
        _current_playback_thread.start()

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
