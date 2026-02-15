"""
Pygame-based TTS player with multiprocessing isolation.

Architecture:
- Main Process: Coordinates ElevenLabs API calls and queues audio
- Worker Process: Dedicated pygame playback (isolated from main app)
- Watchdog Thread: Monitors worker heartbeat, auto-restarts if frozen

Audio Pipeline:
  ElevenLabs MP3 -> pygame (direct playback)
"""

import io
import os
import re
import struct
import threading
import time
import multiprocessing
from multiprocessing import Process, Queue, Value
from typing import Optional
from ctypes import c_double

import numpy as np

import config
from core.logger import log_info, log_warning, log_error


# =============================================================================
# CONFIGURATION
# =============================================================================
ELEVENLABS_PCM_SAMPLE_RATE = 44100  # ElevenLabs pcm_44100 format
ELEVENLABS_PCM_24K_SAMPLE_RATE = 24000  # For streaming (pcm_24000)
PYGAME_SAMPLE_RATE = 44100
PYGAME_CHANNELS = 1
PYGAME_BUFFER = 512

TARGET_DBFS = -16.0  # Broadcast standard
FADE_IN_MS = 10
FADE_OUT_MS = 5
MASTER_VOLUME = 0.4

WATCHDOG_TIMEOUT = 30.0  # Seconds before considering worker frozen
HEARTBEAT_INTERVAL = 1.0  # Worker heartbeat frequency

# Audio type markers for worker process
AUDIO_TYPE_MP3 = "mp3"
AUDIO_TYPE_PCM = "pcm"


# =============================================================================
# TEXT SANITIZATION
# =============================================================================
def _sanitize_for_tts(text: str) -> str:
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


# =============================================================================
# AUDIO NORMALIZATION PIPELINE
# =============================================================================
def normalize_audio(pcm_data: bytes, sample_rate: int = ELEVENLABS_PCM_SAMPLE_RATE) -> io.BytesIO:
    """
    Process raw PCM audio: DC offset removal, normalization, fades, WAV export.

    Args:
        pcm_data: Raw 16-bit signed PCM audio bytes
        sample_rate: Sample rate of the PCM data

    Returns:
        BytesIO containing normalized WAV data ready for pygame
    """
    # Convert bytes to numpy array (16-bit signed integers)
    samples = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32)

    if len(samples) == 0:
        # Return empty WAV
        return _create_wav_buffer(np.array([], dtype=np.int16), sample_rate)

    # 1. DC Offset Removal - removes constant bias to prevent clicks
    dc_offset = np.mean(samples)
    samples = samples - dc_offset

    # 2. Normalize to target dBFS (-16 dBFS broadcast standard)
    max_amplitude = np.max(np.abs(samples))
    if max_amplitude > 0:
        # Calculate current dBFS
        current_dbfs = 20 * np.log10(max_amplitude / 32767.0)
        # Calculate gain needed
        gain_db = TARGET_DBFS - current_dbfs
        gain_linear = 10 ** (gain_db / 20)
        # Apply gain (with headroom protection)
        samples = samples * min(gain_linear, 10.0)  # Cap at +20dB gain

    # 3. Fade In - smooth ramp from silence to prevent start clicks
    fade_in_samples = int(sample_rate * FADE_IN_MS / 1000)
    if fade_in_samples > 0 and len(samples) > fade_in_samples:
        fade_in_curve = np.linspace(0, 1, fade_in_samples)
        samples[:fade_in_samples] = samples[:fade_in_samples] * fade_in_curve

    # 4. Fade Out - smooth ramp to silence to prevent end clicks
    fade_out_samples = int(sample_rate * FADE_OUT_MS / 1000)
    if fade_out_samples > 0 and len(samples) > fade_out_samples:
        fade_out_curve = np.linspace(1, 0, fade_out_samples)
        samples[-fade_out_samples:] = samples[-fade_out_samples:] * fade_out_curve

    # 5. Clip and convert back to int16
    samples = np.clip(samples, -32767, 32767).astype(np.int16)

    return _create_wav_buffer(samples, sample_rate)


def _create_wav_buffer(samples: np.ndarray, sample_rate: int) -> io.BytesIO:
    """Create a WAV file in memory from numpy samples."""
    buffer = io.BytesIO()

    # WAV header
    num_samples = len(samples)
    bytes_per_sample = 2  # 16-bit
    num_channels = 1
    data_size = num_samples * bytes_per_sample

    # RIFF header
    buffer.write(b'RIFF')
    buffer.write(struct.pack('<I', 36 + data_size))  # File size - 8
    buffer.write(b'WAVE')

    # fmt chunk
    buffer.write(b'fmt ')
    buffer.write(struct.pack('<I', 16))  # Chunk size
    buffer.write(struct.pack('<H', 1))   # Audio format (PCM)
    buffer.write(struct.pack('<H', num_channels))
    buffer.write(struct.pack('<I', sample_rate))
    buffer.write(struct.pack('<I', sample_rate * num_channels * bytes_per_sample))  # Byte rate
    buffer.write(struct.pack('<H', num_channels * bytes_per_sample))  # Block align
    buffer.write(struct.pack('<H', 16))  # Bits per sample

    # data chunk
    buffer.write(b'data')
    buffer.write(struct.pack('<I', data_size))
    buffer.write(samples.tobytes())

    buffer.seek(0)
    return buffer


# =============================================================================
# WORKER PROCESS
# =============================================================================
def _worker_process(audio_queue: Queue, heartbeat: Value, shutdown_event):
    """
    Dedicated pygame playback process.

    Isolated from main process to prevent pygame hangs from affecting the app.
    Handles both MP3 (legacy) and PCM (streaming) audio formats.
    """
    import pygame

    try:
        pygame.mixer.init(
            frequency=PYGAME_SAMPLE_RATE,
            size=-16,  # 16-bit signed
            channels=PYGAME_CHANNELS,
            buffer=PYGAME_BUFFER
        )
        log_info("Pygame mixer initialized in worker process", prefix="[TTS-Worker]")
    except Exception as e:
        log_error(f"Failed to initialize pygame mixer: {e}", prefix="[TTS-Worker]")
        return

    while not shutdown_event.is_set():
        try:
            # Update heartbeat
            heartbeat.value = time.time()

            # Check for audio in queue (non-blocking with timeout)
            try:
                queue_item = audio_queue.get(timeout=HEARTBEAT_INTERVAL)
            except:
                # Queue empty, loop continues (heartbeat updated)
                continue

            if queue_item is None:
                # Shutdown signal
                break

            # Determine audio type
            if isinstance(queue_item, tuple) and len(queue_item) == 2:
                audio_type, audio_data = queue_item
            else:
                # Legacy format: raw audio data (MP3)
                audio_type = AUDIO_TYPE_MP3
                audio_data = queue_item

            try:
                if audio_type == AUDIO_TYPE_PCM:
                    # PCM audio: use pygame.mixer.Sound for direct playback
                    # Audio data is already WAV-wrapped from normalize_audio()
                    sound = pygame.mixer.Sound(audio_data)
                    sound.set_volume(MASTER_VOLUME)
                    channel = sound.play()

                    # Wait for playback to complete
                    while channel and channel.get_busy():
                        heartbeat.value = time.time()
                        pygame.time.wait(50)  # Shorter wait for more responsive streaming

                        if shutdown_event.is_set():
                            channel.stop()
                            break

                else:
                    # MP3 audio: use pygame.mixer.music (legacy path)
                    audio_buffer = io.BytesIO(audio_data)
                    pygame.mixer.music.load(audio_buffer)
                    pygame.mixer.music.set_volume(MASTER_VOLUME)
                    pygame.mixer.music.play()

                    # Wait for playback to complete
                    while pygame.mixer.music.get_busy():
                        heartbeat.value = time.time()
                        pygame.time.wait(100)

                        if shutdown_event.is_set():
                            pygame.mixer.music.stop()
                            break

            except Exception as e:
                log_error(f"Playback error: {e}", prefix="[TTS-Worker]")

        except Exception as e:
            log_error(f"Worker loop error: {e}", prefix="[TTS-Worker]")

    # Cleanup
    try:
        pygame.mixer.quit()
    except:
        pass
    log_info("Worker process shutdown complete", prefix="[TTS-Worker]")


# =============================================================================
# WATCHDOG THREAD
# =============================================================================
class WorkerWatchdog(threading.Thread):
    """Monitors worker heartbeat and restarts if frozen."""

    def __init__(self, player: 'TTSPlayer'):
        super().__init__(daemon=True)
        self._player = player
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            time.sleep(HEARTBEAT_INTERVAL)

            if self._player._worker_process is None:
                continue

            if not self._player._worker_process.is_alive():
                log_warning("Worker process died, restarting...", prefix="[TTS-Watchdog]")
                self._player._restart_worker()
                continue

            # Check heartbeat
            last_heartbeat = self._player._heartbeat.value
            if last_heartbeat > 0:
                elapsed = time.time() - last_heartbeat
                if elapsed > WATCHDOG_TIMEOUT:
                    log_warning(f"Worker frozen ({elapsed:.1f}s since heartbeat), restarting...",
                               prefix="[TTS-Watchdog]")
                    self._player._restart_worker()

    def stop(self):
        self._stop_event.set()


# =============================================================================
# MAIN TTS PLAYER CLASS
# =============================================================================
class TTSPlayer:
    """
    Multiprocessing TTS player using ElevenLabs and pygame.

    Architecture:
    - ElevenLabs API calls happen in background threads
    - Audio is normalized and queued
    - Separate worker process handles pygame playback
    - Watchdog monitors worker health
    """

    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

        # Rate limiting for ElevenLabs API (max 5 concurrent)
        self._api_semaphore = threading.Semaphore(5)

        # Sequence tracking for ordered playback
        # Ensures sentences play in the order they were queued, not the order
        # they return from the API (shorter sentences return faster)
        self._sequence_lock = threading.Lock()
        self._sequence_counter = 0  # Assigned when sentence is queued
        self._next_expected_seq = 0  # Next sequence number to release to playback
        self._reorder_buffer: dict = {}  # {seq_num: (audio_type, audio_data)}
        self._sequence_timestamps: dict = {}  # {seq_num: queue_time} for timeout
        self._sequence_timeout = 12.0  # Seconds before skipping a hung sequence

        # Multiprocessing components (lazy initialized)
        self._worker_process: Optional[Process] = None
        self._audio_queue: Optional[Queue] = None
        self._heartbeat: Optional[Value] = None
        self._shutdown_event = None
        self._watchdog: Optional[WorkerWatchdog] = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization of multiprocessing components."""
        if self._initialized:
            return True

        with self._lock:
            if self._initialized:
                return True

            try:
                # Set spawn method for Windows compatibility
                try:
                    multiprocessing.set_start_method('spawn', force=False)
                except RuntimeError:
                    pass  # Already set

                self._audio_queue = Queue()
                self._heartbeat = Value(c_double, time.time())
                self._shutdown_event = multiprocessing.Event()

                # Start worker process
                self._worker_process = Process(
                    target=_worker_process,
                    args=(self._audio_queue, self._heartbeat, self._shutdown_event),
                    daemon=True
                )
                self._worker_process.start()
                log_info("TTS worker process started", prefix="[TTS]")

                # Start watchdog
                self._watchdog = WorkerWatchdog(self)
                self._watchdog.start()
                log_info("TTS watchdog started", prefix="[TTS]")

                self._initialized = True
                return True

            except Exception as e:
                log_error(f"Failed to initialize TTS system: {e}", prefix="[TTS]")
                return False

    def _restart_worker(self):
        """Restart the worker process (called by watchdog)."""
        with self._lock:
            # Terminate old process
            if self._worker_process is not None:
                try:
                    self._worker_process.terminate()
                    self._worker_process.join(timeout=2)
                except:
                    pass

            # Clear the queue
            try:
                while not self._audio_queue.empty():
                    self._audio_queue.get_nowait()
            except:
                pass

            # Reset shutdown event
            self._shutdown_event.clear()

            # Start new worker
            self._heartbeat.value = time.time()
            self._worker_process = Process(
                target=_worker_process,
                args=(self._audio_queue, self._heartbeat, self._shutdown_event),
                daemon=True
            )
            self._worker_process.start()
            log_info("TTS worker restarted", prefix="[TTS]")

    def _get_client(self):
        """Lazy-load ElevenLabs client."""
        if self._client is None:
            api_key = os.getenv("Eleven_Labs_API")
            if api_key:
                try:
                    from elevenlabs.client import ElevenLabs
                    self._client = ElevenLabs(api_key=api_key)
                    log_info("ElevenLabs client initialized", prefix="[TTS]")
                except ImportError:
                    log_error("elevenlabs package not installed", prefix="[TTS]")
            else:
                log_warning("Eleven_Labs_API environment variable not set", prefix="[TTS]")
        return self._client

    def play(self, text: str, voice_id: Optional[str] = None) -> bool:
        """
        Play text as speech. Non-blocking.

        Args:
            text: Text to speak
            voice_id: Optional voice ID (uses default from config if not specified)

        Returns:
            True if playback started, False if failed
        """
        client = self._get_client()
        if not client:
            return False

        if not self._ensure_initialized():
            return False

        voice = voice_id or config.ELEVENLABS_DEFAULT_VOICE_ID

        # Sanitize text: remove *action* blocks before speaking
        sanitized_text = _sanitize_for_tts(text)
        if not sanitized_text:
            log_info("TTS skipped: no text after removing actions", prefix="[TTS]")
            return True  # Not an error, just nothing to say

        # Run API call and audio processing in background thread
        thread = threading.Thread(
            target=self._fetch_and_queue_audio,
            args=(sanitized_text, voice),
            daemon=True
        )
        thread.start()

        return True

    def _fetch_and_queue_audio(self, text: str, voice_id: str):
        """Background thread: Fetch audio from ElevenLabs and queue for playback."""
        try:
            preview = text[:50] + "..." if len(text) > 50 else text
            log_info(f"TTS fetching: {preview}", prefix="[TTS]")

            # Get MP3 audio from ElevenLabs (PCM formats require Pro tier)
            from elevenlabs import VoiceSettings
            audio_generator = self._client.text_to_speech.convert(
                text=text,
                voice_id=voice_id,
                model_id=config.ELEVENLABS_MODEL,
                output_format="mp3_44100_128",
                voice_settings=VoiceSettings(
                    stability=0.5,
                    similarity_boost=0.75,
                    style=0.5,
                    use_speaker_boost=True,
                ),
            )

            # Collect all chunks
            mp3_data = b''.join(chunk for chunk in audio_generator)

            if not mp3_data:
                log_warning("ElevenLabs returned empty audio", prefix="[TTS]")
                return

            # Queue MP3 directly for playback (pygame handles MP3 natively)
            self._audio_queue.put(mp3_data)
            log_info("TTS audio queued for playback", prefix="[TTS]")

        except Exception as e:
            log_error(f"TTS fetch/process failed: {e}", prefix="[TTS]")

    def queue_sentence(self, sentence: str, voice_id: Optional[str] = None) -> bool:
        """
        Queue a single sentence for TTS playback using PCM streaming format.

        This is the streaming-optimized method that uses PCM format for
        lower latency compared to MP3. Sentences are guaranteed to play
        in the order they were queued, even if shorter sentences return
        from the API faster.

        Args:
            sentence: Single sentence to speak
            voice_id: Optional voice ID (uses default if not specified)

        Returns:
            True if sentence was queued, False if failed
        """
        client = self._get_client()
        if not client:
            return False

        if not self._ensure_initialized():
            return False

        voice = voice_id or config.ELEVENLABS_DEFAULT_VOICE_ID

        # Sanitize text
        sanitized = _sanitize_for_tts(sentence)
        if not sanitized:
            return True  # Not an error, just nothing to say

        # Assign sequence number (atomic under lock)
        with self._sequence_lock:
            seq_num = self._sequence_counter
            self._sequence_counter += 1
            self._sequence_timestamps[seq_num] = time.time()

        # Fetch and queue in background thread with sequence number
        thread = threading.Thread(
            target=self._fetch_and_queue_pcm,
            args=(sanitized, voice, seq_num),
            daemon=True
        )
        thread.start()

        return True

    def _fetch_and_queue_pcm(self, text: str, voice_id: str, seq_num: int):
        """Background thread: Fetch PCM audio from ElevenLabs and queue for playback."""
        from elevenlabs import VoiceSettings

        # Use semaphore to limit concurrent API requests (ElevenLabs limit is 5)
        with self._api_semaphore:
            max_retries = 3
            backoff_seconds = [1.0, 2.0, 4.0]  # Exponential backoff

            for attempt in range(max_retries):
                try:
                    # Use PCM format for streaming (24kHz, 16-bit)
                    audio_generator = self._client.text_to_speech.convert(
                        text=text,
                        voice_id=voice_id,
                        model_id=config.ELEVENLABS_MODEL,
                        output_format="pcm_24000",  # 24kHz PCM for streaming
                        voice_settings=VoiceSettings(
                            stability=0.5,
                            similarity_boost=0.75,
                            style=0.5,
                            use_speaker_boost=True,
                        ),
                    )

                    # Collect PCM chunks
                    pcm_data = b''.join(chunk for chunk in audio_generator)

                    if not pcm_data:
                        log_warning(f"ElevenLabs returned empty audio for seq={seq_num}", prefix="[TTS]")
                        # Mark as failed so we don't block subsequent sentences
                        self._deliver_in_order(seq_num, None)
                        return

                    # Normalize and convert to WAV format for pygame
                    wav_buffer = normalize_audio(pcm_data, sample_rate=ELEVENLABS_PCM_24K_SAMPLE_RATE)

                    # Deliver to reorder buffer for sequenced playback
                    self._deliver_in_order(seq_num, (AUDIO_TYPE_PCM, wav_buffer))
                    return  # Success, exit retry loop

                except Exception as e:
                    error_str = str(e)
                    # Check for rate limit error (429)
                    is_rate_limit = "429" in error_str or "too_many_concurrent_requests" in error_str.lower()

                    if is_rate_limit and attempt < max_retries - 1:
                        wait_time = backoff_seconds[attempt]
                        log_warning(f"TTS rate limited seq={seq_num}, retrying in {wait_time}s (attempt {attempt + 1}/{max_retries})", prefix="[TTS]")
                        time.sleep(wait_time)
                        continue
                    else:
                        log_error(f"TTS streaming failed seq={seq_num}: {e}", prefix="[TTS]")
                        # Mark as failed so we don't block subsequent sentences
                        self._deliver_in_order(seq_num, None)
                        return

    def _deliver_in_order(self, seq_num: int, audio_data: Optional[tuple]):
        """
        Buffer audio and release to playback queue in sequence order.

        This ensures sentences are played in the order they were queued,
        even if shorter sentences return from the API faster than longer ones.

        Args:
            seq_num: Sequence number assigned when sentence was queued
            audio_data: (AUDIO_TYPE_PCM, wav_buffer) tuple, or None if failed
        """
        with self._sequence_lock:
            # Add to reorder buffer
            self._reorder_buffer[seq_num] = audio_data

            # Check for timed-out sequences that are blocking the queue
            current_time = time.time()
            while self._next_expected_seq in self._sequence_timestamps:
                queue_time = self._sequence_timestamps[self._next_expected_seq]
                elapsed = current_time - queue_time

                if self._next_expected_seq in self._reorder_buffer:
                    # This sequence is ready - release it
                    item = self._reorder_buffer.pop(self._next_expected_seq)
                    self._sequence_timestamps.pop(self._next_expected_seq, None)

                    if item is not None:
                        self._audio_queue.put(item)
                    else:
                        log_info(f"TTS skipped failed seq={self._next_expected_seq}", prefix="[TTS]")

                    self._next_expected_seq += 1

                elif elapsed > self._sequence_timeout:
                    # This sequence has timed out - skip it
                    log_warning(f"TTS timeout: skipping seq={self._next_expected_seq} after {elapsed:.1f}s", prefix="[TTS]")
                    self._sequence_timestamps.pop(self._next_expected_seq, None)
                    self._next_expected_seq += 1

                else:
                    # Still waiting for this sequence, and it hasn't timed out
                    break

    def stop(self):
        """Stop current playback and reset sequence state."""
        # Reset sequence tracking to start fresh
        with self._sequence_lock:
            self._sequence_counter = 0
            self._next_expected_seq = 0
            self._reorder_buffer.clear()
            self._sequence_timestamps.clear()

        if self._audio_queue is not None:
            # Clear the queue
            try:
                while not self._audio_queue.empty():
                    self._audio_queue.get_nowait()
            except:
                pass

        # Signal worker to stop current playback (it will handle pygame.mixer.music.stop())
        # We do this by restarting the worker (cleanest way to interrupt playback)
        if self._initialized and self._worker_process is not None:
            self._restart_worker()

    def shutdown(self):
        """Full shutdown of TTS system."""
        with self._lock:
            if not self._initialized:
                return

            # Stop watchdog
            if self._watchdog is not None:
                self._watchdog.stop()

            # Signal worker to shutdown
            if self._shutdown_event is not None:
                self._shutdown_event.set()

            # Send None to wake up worker from queue.get()
            if self._audio_queue is not None:
                try:
                    self._audio_queue.put(None)
                except:
                    pass

            # Wait for worker to finish
            if self._worker_process is not None:
                self._worker_process.join(timeout=3)
                if self._worker_process.is_alive():
                    self._worker_process.terminate()

            self._initialized = False
            log_info("TTS system shutdown complete", prefix="[TTS]")

    @staticmethod
    def is_available() -> bool:
        """Check if TTS dependencies are available."""
        # Check for elevenlabs
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError:
            return False

        # Check for pygame
        try:
            import pygame
        except ImportError:
            return False

        # Check for numpy (used in normalization)
        try:
            import numpy
        except ImportError:
            return False

        # Check for API key
        if not os.getenv("Eleven_Labs_API"):
            return False

        return True


# =============================================================================
# GLOBAL INSTANCE AND PUBLIC API
# =============================================================================
_player: Optional[TTSPlayer] = None


def get_tts_player() -> TTSPlayer:
    """Get the global TTS player instance."""
    global _player
    if _player is None:
        _player = TTSPlayer()
    return _player


def play_tts(text: str, voice_id: Optional[str] = None) -> bool:
    """
    Play text as speech. Main entry point.

    Args:
        text: Text to speak
        voice_id: Optional voice ID

    Returns:
        True if playback started
    """
    return get_tts_player().play(text, voice_id)


def stop_tts():
    """Stop current TTS playback."""
    get_tts_player().stop()


def queue_tts_sentence(sentence: str, voice_id: Optional[str] = None) -> bool:
    """
    Queue a single sentence for TTS playback (streaming-optimized).

    This uses PCM format for lower latency. Sentences are played
    sequentially in the order they're queued.

    Args:
        sentence: Single sentence to speak
        voice_id: Optional voice ID

    Returns:
        True if queued successfully
    """
    return get_tts_player().queue_sentence(sentence, voice_id)


def is_tts_available() -> bool:
    """Check if TTS is available (dependencies + API key)."""
    return TTSPlayer.is_available()


def shutdown_tts():
    """Shutdown TTS system (call on app exit)."""
    global _player
    if _player is not None:
        _player.shutdown()
        _player = None
