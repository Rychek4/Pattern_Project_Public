# ESP32-S3 Voice Pipeline Implementation Plan

## Overview

Replace the legacy PC-audio TTS pipeline with a dedicated ESP32-S3R8 voice terminal for Isaac. Add Push-to-Talk (PTT) with local Whisper STT. The ESP32 becomes the sole audio I/O for Isaac — no PC speakers, no PC mic.

---

## Architecture (After)

```
┌────────────────────────┐         WiFi/HTTP          ┌──────────────────────────────┐
│     ESP32-S3R8         │ ◄──────────────────────────►│     Pattern Project Server   │
│                        │                             │                              │
│  [PTT Button] ─► Mic  │  POST /voice/stt            │  faster-whisper STT          │
│  Record I2S audio      │  ─────────────────────────► │  (in-process, like embeds)   │
│                        │                             │         │                    │
│                        │                             │         ▼                    │
│  [Speaker] ◄── I2S    │  GET /voice/tts/stream      │  Isaac (Claude API)          │
│  Play audio response   │  ◄───────────────────────── │         │                    │
│                        │                             │         ▼                    │
│  [Status LED]          │                             │  OpenAI TTS                  │
│  WiFi/recording state  │                             │  (tts-1 / tts-1-hd)         │
└────────────────────────┘                             └──────────────────────────────┘
```

---

## Phase 1: Settings & Configuration Consolidation

### 1A. Expand `core/user_settings.py`

Replace the flat `TTSSettings` with a structured `VoiceSettings` dataclass:

```python
@dataclass
class VoiceSettings:
    """Consolidated voice pipeline settings."""
    pipeline_enabled: bool = False     # Master on/off for entire voice system
    tts_enabled: bool = True           # TTS output (can disable for silent STT-only mode)
    stt_enabled: bool = True           # STT input
    voice_id: str = ""                 # ElevenLabs voice ID (empty = default)
    ptt_key: str = ""                  # PTT key binding (empty = ESP32-only, no keyboard PTT)
    stt_model_size: str = "small"      # faster-whisper model: tiny, base, small
```

- `pipeline_enabled = False` means the whole system is dormant: no Whisper model loaded, no ESP32 endpoints active
- `tts_enabled` / `stt_enabled` are sub-toggles under the master switch
- Backward-compatible: old `user_settings.json` files with `tts.enabled` get migrated to the new shape on first load

**Migration path**: The `_load()` method checks for the old `tts` key and maps `tts.enabled` → `voice.pipeline_enabled + voice.tts_enabled`, `tts.voice_id` → `voice.voice_id`. Old key is removed on next save.

**Files changed:**
- `core/user_settings.py` — new dataclass, migration logic, new properties
- `config.py` — add `WHISPER_MODEL_DEFAULT = "small"`, `VOICE_ENDPOINT_PORT` (or reuse HTTP_PORT)

### 1B. Update GUI Settings Dialog

**File:** `interface/gui.py` → `SettingsDialog` class (line ~3073)

Replace the current TTS section with a "Voice" section:

```
Voice Pipeline
  [x] Enable voice pipeline          ← master toggle
      [x] Enable TTS (Isaac speaks)  ← sub-toggle, grayed out if master off
      [x] Enable STT (Push-to-Talk)  ← sub-toggle, grayed out if master off
      Voice ID: [____________]        ← existing field
      PTT Key:  [____________]        ← new field (key capture widget)
      STT Model: [tiny|base|small ▼]  ← dropdown
```

The sub-toggles are only interactive when the master toggle is checked. Standard Qt `setEnabled()` wiring.

### 1C. Update all existing TTS consumers

Every place that currently calls `is_tts_enabled()` needs to check the new `pipeline_enabled AND tts_enabled` logic. Currently these are:

- `interface/gui.py:1304` — `_trigger_tts()`
- `interface/gui.py:1771` — streaming sentence buffer init
- `interface/gui.py:1809` — during-stream TTS queueing

The `is_tts_enabled()` convenience function in `core/user_settings.py` gets updated internally so callers don't change:
```python
def is_tts_enabled() -> bool:
    mgr = get_user_settings()
    return mgr.voice_pipeline_enabled and mgr.tts_enabled
```

---

## Phase 2: STT Integration (faster-whisper)

### 2A. New module: `stt/transcriber.py`

Lightweight module following the same pattern as `core/embeddings.py`:

```python
"""
Speech-to-text using faster-whisper.
Lazy-loaded on first use. Model stays resident in RAM.
"""

_model = None

def load_stt_model(model_size: str = "small") -> bool:
    """Load the Whisper model. ~500MB RAM for 'small'."""
    global _model
    from faster_whisper import WhisperModel
    _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return True

def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw PCM audio bytes to text."""
    # Convert bytes to numpy, write temp WAV or use in-memory
    # faster-whisper accepts file paths or file-like objects
    ...

def is_stt_available() -> bool:
    """Check if faster-whisper is installed."""
    ...

def unload_stt_model():
    """Free memory when voice pipeline is disabled."""
    global _model
    _model = None
```

Key decisions:
- `device="cpu"`, `compute_type="int8"` — no GPU needed, lowest memory footprint
- Model loads on first PTT press OR on startup if `pipeline_enabled=True`
- Model can be unloaded when master toggle is switched off (free ~500MB RAM)
- Audio input expected as 16kHz 16-bit mono PCM (Whisper's native format; ESP32 records at 16kHz and sends raw)

### 2B. New dependency

Add `faster-whisper` to `requirements.txt`. It pulls in `ctranslate2` and `tokenizers` — CPU-only, no CUDA needed.

---

## Phase 3: Voice API Endpoints

### 3A. New module: `voice/api.py`

A Flask blueprint that gets registered on the existing HTTP server (`interface/http_api.py`). Not a separate server — bolted onto the existing one.

**Endpoints:**

#### `POST /voice/stt`
- ESP32 sends raw PCM audio (16kHz, 16-bit, mono) in request body
- Server runs faster-whisper → returns transcribed text
- Optionally: feeds text directly to Isaac and returns response (see `/voice/talk` below)

```
Request:  Content-Type: application/octet-stream, body = raw PCM bytes
Response: {"text": "the transcribed words", "success": true}
```

#### `POST /voice/talk`
- The "full loop" endpoint: audio in → STT → Isaac → TTS → audio out
- ESP32 sends raw PCM audio
- Server: transcribe → chat with Isaac → ElevenLabs TTS → return audio bytes
- Response is chunked audio (WAV or raw PCM) that ESP32 plays directly

```
Request:  Content-Type: application/octet-stream, body = raw PCM bytes
Response: Content-Type: audio/wav (or audio/pcm), body = TTS audio bytes
          Header X-Transcription: "what the user said"
          Header X-Isaac-Text: "what Isaac said" (for logging/display)
```

This single-request design is simpler for the ESP32 firmware — one POST, one response, done. No state management on the microcontroller.

#### `GET /voice/health`
- ESP32 pings on boot to confirm server is reachable
- Returns pipeline status (STT model loaded, ElevenLabs available, etc.)

### 3B. Wire into existing HTTP server

In `interface/http_api.py` → `create_app()`, register the voice blueprint:

```python
from voice.api import voice_blueprint
app.register_blueprint(voice_blueprint, url_prefix="/voice")
```

The voice endpoints respect the `pipeline_enabled` setting — if disabled, they return 503.

### 3C. Reuse existing ElevenLabs client

The `tts/player.py` ElevenLabs API client code (`_get_client()`, API call logic, text sanitization, sentence splitting) gets refactored:

- **Keep**: ElevenLabs client init, `_sanitize_for_tts()`, API call logic, sentence buffer
- **Replace**: The pygame playback backend. Instead of queueing to a pygame worker, the voice endpoint collects the audio bytes and returns them in the HTTP response

Specifically, extract the ElevenLabs API-calling logic into a reusable function:

```python
# tts/synthesizer.py (new, extracted from tts/player.py)
def synthesize(text: str, voice_id: str = None) -> bytes:
    """Call ElevenLabs and return audio bytes. No playback."""
    ...
```

This is called by both:
- The new voice endpoint (returns bytes to ESP32)
- The GUI streaming path (if we want to keep optional PC playback later)

---

## Phase 4: Remove Legacy Audio Pipeline

### 4A. Delete files

- `subprocess_mgmt/audio_player_server.py` — Flask TTS microservice (currently disabled)
- `subprocess_mgmt/audio_player.py` — HTTP client for above

### 4B. Gut `tts/player.py`

Remove the entire pygame multiprocessing playback architecture:
- `_worker_process()` function
- `WorkerWatchdog` class
- `TTSPlayer` class (the pygame-based one)
- All pygame imports and config constants

What remains is the public API surface, now backed by `tts/synthesizer.py`:
- `play_tts()` → for any remaining local playback (or remove entirely)
- `queue_tts_sentence()` → keep for GUI streaming if desired, or redirect to synthesizer
- `shutdown_tts()` → simplified (no pygame worker to kill)

### 4C. Update `tts/__init__.py`

Update exports to match the new module structure.

### 4D. Clean up config

- Remove `ELEVENLABS_AUDIO_PORT` (no more audio subprocess)
- Remove `SUBPROCESS_AUDIO_ENABLED` placeholder

---

## Phase 5: ESP32-S3R8 Firmware

### 5A. Separate directory: `esp32/`

This is a standalone Arduino/PlatformIO project, not part of the Python codebase.

```
esp32/
├── platformio.ini          # Build config (ESP32-S3, Arduino framework)
├── src/
│   └── main.cpp            # Firmware entry point
├── include/
│   ├── config.h            # WiFi credentials, server URL, pin definitions
│   ├── audio.h             # I2S mic/speaker setup
│   ├── network.h           # HTTP client helpers
│   └── button.h            # PTT button debounce
└── README.md               # Wiring diagram, flash instructions
```

### 5B. Firmware behavior

```
Boot:
  1. Connect to WiFi
  2. GET /voice/health to confirm server is up
  3. Blink LED = ready

Main loop:
  1. Wait for PTT button press (GPIO interrupt)
  2. On press:  Start recording I2S mic → buffer in PSRAM (8MB available)
  3. On release: Stop recording
  4. POST /voice/talk with raw PCM body
  5. Receive audio response
  6. Play response through I2S speaker
  7. Return to waiting state
```

### 5C. Hardware requirements

| Component | Purpose |
|---|---|
| ESP32-S3R8 dev board | MCU + WiFi + 8MB PSRAM |
| INMP441 (or SPH0645) | I2S MEMS microphone |
| MAX98357A | I2S amplifier + speaker driver |
| Small speaker (3W) | Audio output |
| Momentary push button | PTT trigger |
| LED | Status indicator |

I2S bus is shared (or use two I2S peripherals — ESP32-S3 has two). Mic at 16kHz, speaker at 24kHz (or 44.1kHz depending on ElevenLabs format).

### 5D. Audio format contract

- **ESP32 → Server**: Raw PCM, 16kHz, 16-bit signed, mono (Whisper's native format)
- **Server → ESP32**: Raw PCM, 24kHz, 16-bit signed, mono (ElevenLabs pcm_24000 format, avoids MP3 decoding on ESP32)

---

## Phase 6: Integration & Polish

### 6A. GUI notification of ESP32 events

When a voice message comes in via the ESP32, it should appear in the GUI chat log (if GUI is running). The voice endpoint writes to the same conversation manager that the GUI uses. The GUI already polls/updates from conversation state.

### 6B. Startup integration

In `main.py` → `initialize_system()`:
```python
# Load STT model if voice pipeline is enabled
from core.user_settings import get_user_settings
if get_user_settings().voice_pipeline_enabled:
    from stt.transcriber import load_stt_model
    load_stt_model(get_user_settings().stt_model_size)
```

Similarly in `run_gui()` initialization.

### 6C. Shutdown integration

In `stop_background_services()`:
```python
from stt.transcriber import unload_stt_model
unload_stt_model()
```

---

## Implementation Order

| Step | What | Depends on | Risk |
|------|------|------------|------|
| 1 | Settings consolidation (1A, 1B, 1C) | Nothing | Low — pure refactor |
| 2 | STT module (2A, 2B) | Nothing | Low — standalone module |
| 3 | Extract synthesizer from player (part of 3C) | Nothing | Medium — refactor existing code |
| 4 | Voice API endpoints (3A, 3B) | Steps 2 + 3 | Medium — new integration point |
| 5 | Remove legacy audio (4A-4D) | Step 3 | Low — deletion |
| 6 | ESP32 firmware (5A-5D) | Step 4 | Medium — different toolchain |
| 7 | Integration polish (6A-6C) | Steps 1-5 | Low |

Steps 1, 2, and 3 can be done in parallel. Step 4 requires 2+3. Step 5 can happen after 3. Step 6 can start anytime but can't be tested end-to-end until step 4 is done.

---

## Files Summary

### New files
| File | Purpose |
|------|---------|
| `stt/__init__.py` | STT package |
| `stt/transcriber.py` | faster-whisper integration |
| `tts/synthesizer.py` | ElevenLabs API calls (extracted from player.py) |
| `voice/__init__.py` | Voice API package |
| `voice/api.py` | Flask blueprint for /voice/* endpoints |
| `esp32/` | Entire ESP32 firmware project (separate toolchain) |

### Modified files
| File | Change |
|------|--------|
| `core/user_settings.py` | New VoiceSettings dataclass, migration, properties |
| `config.py` | New voice/STT config constants, remove audio subprocess ones |
| `interface/gui.py` | SettingsDialog voice section, update TTS trigger calls |
| `interface/http_api.py` | Register voice blueprint |
| `tts/player.py` | Gut pygame playback, keep as thin wrapper over synthesizer |
| `tts/__init__.py` | Update exports |
| `main.py` | STT model loading on startup, shutdown cleanup |

### Deleted files
| File | Reason |
|------|--------|
| `subprocess_mgmt/audio_player_server.py` | Legacy Flask audio microservice (already disabled) |
| `subprocess_mgmt/audio_player.py` | Client for above |
