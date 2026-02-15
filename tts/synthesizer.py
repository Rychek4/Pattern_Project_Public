"""
ElevenLabs TTS synthesizer — API calls only, no playback.

Extracted from tts/player.py so both the GUI streaming pipeline and
the ESP32 voice endpoint can share the same synthesis logic.
"""

import os
import re
from typing import Optional

import config
from core.logger import log_info, log_warning, log_error

_client = None


def _get_client():
    """Lazy-load ElevenLabs client."""
    global _client
    if _client is None:
        api_key = os.getenv("Eleven_Labs_API")
        if api_key:
            try:
                from elevenlabs.client import ElevenLabs
                _client = ElevenLabs(api_key=api_key)
                log_info("ElevenLabs client initialized", prefix="[TTS-Synth]")
            except ImportError:
                log_error("elevenlabs package not installed", prefix="[TTS-Synth]")
        else:
            log_warning("Eleven_Labs_API environment variable not set", prefix="[TTS-Synth]")
    return _client


def sanitize_for_tts(text: str) -> str:
    """
    Remove content that should be displayed but not spoken.

    Removes:
    - *action* blocks: LLM emoted actions like *smiles warmly*
    - (Just now): Temporal context marker echoed by the LLM

    Note: **bold** text (double asterisks) is preserved.
    """
    # Remove *action* blocks (but not **bold**)
    pattern = r'(?<!\*)\*(?!\*)([^*]+)\*(?!\*)'
    sanitized = re.sub(pattern, '', text)

    # Remove temporal context marker the LLM may echo
    sanitized = sanitized.replace("(Just now)", "")

    # Clean up any double spaces left behind
    sanitized = re.sub(r'  +', ' ', sanitized)
    return sanitized.strip()


def synthesize_pcm(
    text: str,
    voice_id: Optional[str] = None,
    output_format: str = "pcm_24000",
) -> Optional[bytes]:
    """
    Call ElevenLabs and return raw PCM audio bytes (no playback).

    Args:
        text: Text to synthesize (will be sanitized)
        voice_id: ElevenLabs voice ID (uses default from config if None)
        output_format: ElevenLabs output format string

    Returns:
        Raw PCM bytes, or None on failure
    """
    client = _get_client()
    if not client:
        return None

    voice = voice_id or config.ELEVENLABS_DEFAULT_VOICE_ID

    # Sanitize
    sanitized = sanitize_for_tts(text)
    if not sanitized:
        log_info("TTS skipped: no text after sanitization", prefix="[TTS-Synth]")
        return b""  # Not an error, just nothing to say

    try:
        from elevenlabs import VoiceSettings

        preview = sanitized[:50] + "..." if len(sanitized) > 50 else sanitized
        log_info(f"Synthesizing: {preview}", prefix="[TTS-Synth]")

        audio_generator = client.text_to_speech.convert(
            text=sanitized,
            voice_id=voice,
            model_id=config.ELEVENLABS_MODEL,
            output_format=output_format,
            voice_settings=VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
                style=0.5,
                use_speaker_boost=True,
            ),
        )

        pcm_data = b''.join(chunk for chunk in audio_generator)

        if not pcm_data:
            log_warning("ElevenLabs returned empty audio", prefix="[TTS-Synth]")
            return None

        log_info(f"Synthesized {len(pcm_data)} bytes", prefix="[TTS-Synth]")
        return pcm_data

    except Exception as e:
        log_error(f"Synthesis failed: {e}", prefix="[TTS-Synth]")
        return None


def synthesize_mp3(
    text: str,
    voice_id: Optional[str] = None,
) -> Optional[bytes]:
    """
    Call ElevenLabs and return MP3 audio bytes.

    Used by the GUI pygame playback path (pygame handles MP3 natively).

    Args:
        text: Text to synthesize (will be sanitized)
        voice_id: ElevenLabs voice ID

    Returns:
        MP3 bytes, or None on failure
    """
    return synthesize_pcm(text, voice_id, output_format="mp3_44100_128")


def is_synthesizer_available() -> bool:
    """Check if ElevenLabs synthesis is possible (package + API key)."""
    try:
        from elevenlabs.client import ElevenLabs  # noqa: F401
    except ImportError:
        return False

    if not os.getenv("Eleven_Labs_API"):
        return False

    return True
