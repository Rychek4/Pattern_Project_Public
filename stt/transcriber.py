"""
Speech-to-text using faster-whisper.

Lazy-loaded on first use. Model stays resident in RAM until explicitly
unloaded. Follows the same pattern as core/embeddings.py.

Audio input expected as 16kHz 16-bit mono PCM (Whisper's native format).
"""

import io
import struct
import tempfile
from typing import Optional

import numpy as np

from core.logger import log_info, log_warning, log_error

_model = None
_model_size: Optional[str] = None


def load_stt_model(model_size: str = "small") -> bool:
    """
    Load the faster-whisper model into memory.

    Args:
        model_size: Model size - "tiny" (~75MB), "base" (~150MB), "small" (~500MB)

    Returns:
        True if model loaded successfully
    """
    global _model, _model_size

    if _model is not None:
        if _model_size == model_size:
            log_info(f"STT model already loaded ({model_size})", prefix="[STT]")
            return True
        # Different size requested — unload first
        unload_stt_model()

    try:
        from faster_whisper import WhisperModel

        log_info(f"Loading faster-whisper model '{model_size}' (CPU, int8)...", prefix="[STT]")
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        _model_size = model_size
        log_info(f"STT model loaded: {model_size}", prefix="[STT]")
        return True

    except ImportError:
        log_error("faster-whisper not installed. Run: pip install faster-whisper", prefix="[STT]")
        return False
    except Exception as e:
        log_error(f"Failed to load STT model: {e}", prefix="[STT]")
        return False


def unload_stt_model():
    """Free the model from memory."""
    global _model, _model_size
    if _model is not None:
        log_info("Unloading STT model", prefix="[STT]")
    _model = None
    _model_size = None


def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """
    Transcribe raw PCM audio bytes to text.

    Args:
        audio_bytes: Raw 16-bit signed mono PCM audio
        sample_rate: Sample rate of the audio (default 16kHz)

    Returns:
        Transcribed text, or empty string on failure
    """
    if _model is None:
        log_error("STT model not loaded — call load_stt_model() first", prefix="[STT]")
        return ""

    if not audio_bytes:
        return ""

    try:
        # Convert raw PCM to WAV in memory (faster-whisper accepts file paths)
        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate)

        # Write to temp file (faster-whisper needs a file path or ndarray)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            tmp.write(wav_bytes)
            tmp.flush()

            segments, info = _model.transcribe(
                tmp.name,
                beam_size=5,
                language="en",
                vad_filter=True,
            )

            # Collect all segment texts
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            result = " ".join(text_parts).strip()
            duration = len(audio_bytes) / (sample_rate * 2)  # 16-bit = 2 bytes/sample
            log_info(f"STT: {duration:.1f}s audio → {len(result)} chars", prefix="[STT]")
            return result

    except Exception as e:
        log_error(f"Transcription failed: {e}", prefix="[STT]")
        return ""


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM bytes in a WAV header."""
    num_channels = 1
    bits_per_sample = 16
    bytes_per_sample = bits_per_sample // 8
    data_size = len(pcm_bytes)

    buf = io.BytesIO()
    # RIFF header
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    # fmt chunk
    buf.write(b'fmt ')
    buf.write(struct.pack('<I', 16))
    buf.write(struct.pack('<H', 1))  # PCM
    buf.write(struct.pack('<H', num_channels))
    buf.write(struct.pack('<I', sample_rate))
    buf.write(struct.pack('<I', sample_rate * num_channels * bytes_per_sample))
    buf.write(struct.pack('<H', num_channels * bytes_per_sample))
    buf.write(struct.pack('<H', bits_per_sample))
    # data chunk
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(pcm_bytes)
    return buf.getvalue()


def is_stt_available() -> bool:
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def is_stt_loaded() -> bool:
    """Check if a model is currently loaded."""
    return _model is not None
