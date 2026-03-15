"""
OpenAI TTS synthesizer — API calls only, no playback.

Provides synthesis functions for both the ESP32 voice endpoint
(raw PCM for direct I2S playback) and any future local playback needs.

OpenAI TTS outputs 24kHz 16-bit mono PCM by default, which matches
the ESP32 audio contract exactly.
"""

import os
import re
from typing import Optional

import config
from core.logger import log_info, log_warning, log_error

_client = None


def _get_client():
    """Lazy-load OpenAI client."""
    global _client
    if _client is None:
        api_key = config.OPENAI_TTS_API_KEY
        if api_key:
            try:
                from openai import OpenAI
                _client = OpenAI(api_key=api_key)
                log_info("OpenAI TTS client initialized", prefix="[TTS-Synth]")
            except ImportError:
                log_error("openai package not installed", prefix="[TTS-Synth]")
        else:
            log_warning("OPENAI_API_KEY environment variable not set", prefix="[TTS-Synth]")
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
    voice: Optional[str] = None,
    **kwargs,
) -> Optional[bytes]:
    """
    Call OpenAI TTS and return raw PCM audio bytes (no playback).

    OpenAI's PCM output is 24kHz, 16-bit, mono — matching the ESP32
    audio contract exactly (config.VOICE_TTS_SAMPLE_RATE = 24000).

    Args:
        text: Text to synthesize (will be sanitized)
        voice: OpenAI voice name (uses default from config if None).
               Valid voices: alloy, ash, ballad, coral, echo, fable,
               nova, onyx, sage, shimmer
        **kwargs: Accepted for backward compatibility (output_format, voice_id)

    Returns:
        Raw PCM bytes (24kHz 16-bit mono), or None on failure
    """
    client = _get_client()
    if not client:
        return None

    # Backward compatibility: accept voice_id kwarg from old call sites
    if voice is None:
        voice = kwargs.get("voice_id")
    voice = voice or config.OPENAI_TTS_DEFAULT_VOICE

    # Validate voice name
    if voice not in config.OPENAI_TTS_VOICES:
        log_warning(
            f"Unknown voice '{voice}', falling back to {config.OPENAI_TTS_DEFAULT_VOICE}",
            prefix="[TTS-Synth]"
        )
        voice = config.OPENAI_TTS_DEFAULT_VOICE

    # Sanitize
    sanitized = sanitize_for_tts(text)
    if not sanitized:
        log_info("TTS skipped: no text after sanitization", prefix="[TTS-Synth]")
        return b""  # Not an error, just nothing to say

    try:
        preview = sanitized[:50] + "..." if len(sanitized) > 50 else sanitized
        log_info(f"Synthesizing: {preview}", prefix="[TTS-Synth]")

        response = client.audio.speech.create(
            model=config.OPENAI_TTS_MODEL,
            voice=voice,
            input=sanitized,
            response_format="pcm",
        )

        pcm_data = response.content

        if not pcm_data:
            log_warning("OpenAI TTS returned empty audio", prefix="[TTS-Synth]")
            return None

        log_info(f"Synthesized {len(pcm_data)} bytes", prefix="[TTS-Synth]")
        return pcm_data

    except Exception as e:
        log_error(f"Synthesis failed: {e}", prefix="[TTS-Synth]")
        from core.health_ledger import record_health_event
        record_health_event("tts", "error", f"PCM synthesis failed: {e}")
        return None


def synthesize_mp3(
    text: str,
    voice: Optional[str] = None,
) -> Optional[bytes]:
    """
    Call OpenAI TTS and return MP3 audio bytes.

    Args:
        text: Text to synthesize (will be sanitized)
        voice: OpenAI voice name

    Returns:
        MP3 bytes, or None on failure
    """
    client = _get_client()
    if not client:
        return None

    voice = voice or config.OPENAI_TTS_DEFAULT_VOICE

    # Validate voice name
    if voice not in config.OPENAI_TTS_VOICES:
        voice = config.OPENAI_TTS_DEFAULT_VOICE

    sanitized = sanitize_for_tts(text)
    if not sanitized:
        return b""

    try:
        response = client.audio.speech.create(
            model=config.OPENAI_TTS_MODEL,
            voice=voice,
            input=sanitized,
            response_format="mp3",
        )
        return response.content

    except Exception as e:
        log_error(f"MP3 synthesis failed: {e}", prefix="[TTS-Synth]")
        from core.health_ledger import record_health_event
        record_health_event("tts", "error", f"MP3 synthesis failed: {e}")
        return None


def is_synthesizer_available() -> bool:
    """Check if OpenAI TTS synthesis is possible (package + API key)."""
    try:
        from openai import OpenAI  # noqa: F401
    except ImportError:
        return False

    if not config.OPENAI_TTS_API_KEY:
        return False

    return True
