"""
Pattern Project - Visual Capture System
Screenshot and webcam capture for direct Claude multimodal integration

This module provides:
1. Raw image capture (screenshot, webcam) returning bytes
2. Image formatting for Claude's multimodal API
"""

import io
import base64
import threading
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass

from core.logger import log_info, log_error, log_warning

# Optional imports - graceful degradation if not available
try:
    from PIL import ImageGrab, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    log_warning("PIL not available - screenshot capture disabled (optional)")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    log_warning("OpenCV not available - webcam capture disabled (optional)")


# =============================================================================
# PERSISTENT WEBCAM MANAGER
# =============================================================================

class WebcamManager:
    """
    Persistent webcam device manager to avoid open/close latency.

    Opening a webcam device (cv2.VideoCapture) typically takes 500-2000ms.
    By keeping the device open between captures, we reduce this to ~10-50ms
    per frame capture.

    Thread-safe singleton pattern ensures only one instance manages the device.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    IDLE_TIMEOUT_SECONDS = 600  # 10 minutes

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cap = None
        self._device_lock = threading.Lock()
        self._is_open = False
        self._idle_timer: Optional[threading.Timer] = None

    def _open_device(self) -> bool:
        """Open the webcam device if not already open."""
        if self._cap is not None and self._cap.isOpened():
            return True

        try:
            self._cap = cv2.VideoCapture(0)
            if self._cap.isOpened():
                self._is_open = True
                log_info("Webcam device opened (persistent)", prefix="📷")
                return True
            else:
                log_warning("Could not open webcam (device 0)")
                self._cap = None
                return False
        except Exception as e:
            log_error(f"Failed to open webcam device: {e}")
            self._cap = None
            return False

    def capture_frame(self) -> Optional[bytes]:
        """
        Capture a frame from the webcam.

        Opens the device on first call and keeps it open for subsequent captures.

        Returns:
            JPEG image bytes, or None if capture fails
        """
        with self._device_lock:
            if not self._open_device():
                return None

            try:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    log_warning("Failed to read webcam frame")
                    # Device may have disconnected, try to reopen next time
                    self._close_device_internal()
                    return None

                # Resize for efficient transmission
                frame = cv2.resize(frame, (640, 480))

                # Convert to JPEG bytes
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                image_bytes = buffer.tobytes()

                log_info(f"Webcam captured: {len(image_bytes)} bytes", prefix="📷")
                self._reset_idle_timer()
                return image_bytes

            except Exception as e:
                log_error(f"Webcam capture failed: {e}")
                self._close_device_internal()
                return None

    def _reset_idle_timer(self):
        """Reset the idle timeout timer. Called after each successful capture."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(self.IDLE_TIMEOUT_SECONDS, self._on_idle_timeout)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _on_idle_timeout(self):
        """Called when the webcam has been idle for IDLE_TIMEOUT_SECONDS."""
        log_info("Webcam idle for 10 minutes, releasing device", prefix="📷")
        self.release()

    def _close_device_internal(self):
        """Internal close without lock (called from within locked sections)."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
            self._is_open = False

    def release(self):
        """Release the webcam device. Call on application shutdown."""
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._device_lock:
            if self._cap is not None:
                self._close_device_internal()
                log_info("Webcam device released", prefix="📷")

    @property
    def is_open(self) -> bool:
        """Check if the webcam device is currently open."""
        return self._is_open


# Global webcam manager instance
_webcam_manager: Optional[WebcamManager] = None


def get_webcam_manager() -> Optional[WebcamManager]:
    """Get or create the global webcam manager instance."""
    global _webcam_manager
    if not CV2_AVAILABLE:
        return None
    if _webcam_manager is None:
        _webcam_manager = WebcamManager()
    return _webcam_manager


def release_webcam():
    """Release the persistent webcam device. Call on application shutdown."""
    global _webcam_manager
    if _webcam_manager is not None:
        _webcam_manager.release()
        _webcam_manager = None


# =============================================================================
# IMAGE CONTENT DATA STRUCTURES
# =============================================================================

@dataclass
class ImageContent:
    """
    Image content formatted for Claude's multimodal API.

    Attributes:
        media_type: MIME type (e.g., "image/jpeg", "image/png")
        data: Base64-encoded image data
        source_type: Origin of image ("screenshot", "webcam", or "telegram")
    """
    media_type: str
    data: str  # Base64 encoded
    source_type: str  # "screenshot", "webcam", or "telegram"

    def to_api_format(self) -> Dict[str, Any]:
        """
        Convert to Claude API content block format.

        Returns:
            Dict in Claude's image content block format
        """
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": self.data
            }
        }


# =============================================================================
# RAW CAPTURE FUNCTIONS
# =============================================================================

def capture_screenshot_bytes() -> Optional[bytes]:
    """
    Capture a screenshot and return as JPEG bytes.

    The screenshot is resized to a maximum of 1280x720 for efficient
    transmission while maintaining readability.

    Returns:
        JPEG image bytes, or None if capture fails
    """
    if not PIL_AVAILABLE:
        log_warning("Screenshot capture unavailable - PIL not installed")
        return None

    try:
        # Capture the screen
        screenshot = ImageGrab.grab()

        # Resize if too large (maintains aspect ratio)
        max_size = (1280, 720)
        screenshot.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Convert to JPEG bytes
        buffer = io.BytesIO()
        screenshot.save(buffer, format='JPEG', quality=85)
        image_bytes = buffer.getvalue()

        log_info(f"Screenshot captured: {len(image_bytes)} bytes", prefix="📸")
        return image_bytes

    except Exception as e:
        log_error(f"Screenshot capture failed: {e}")
        return None


def capture_webcam_bytes() -> Optional[bytes]:
    """
    Capture a webcam frame and return as JPEG bytes.

    Uses the persistent WebcamManager to avoid device open/close latency.
    The device is opened on first use and kept open for subsequent captures.

    Returns:
        JPEG image bytes, or None if capture fails
    """
    if not CV2_AVAILABLE:
        log_warning("Webcam capture unavailable - OpenCV not installed")
        return None

    manager = get_webcam_manager()
    if manager is None:
        return None

    return manager.capture_frame()


# =============================================================================
# IMAGE FORMATTING FOR CLAUDE API
# =============================================================================

def _detect_media_type(image_bytes: bytes) -> str:
    """Detect image MIME type from magic bytes.

    Args:
        image_bytes: Raw image bytes

    Returns:
        Detected MIME type string, defaults to "image/jpeg" if unknown
    """
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if image_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    if image_bytes[:4] == b'GIF8':
        return "image/gif"
    if image_bytes[:4] == b'RIFF' and len(image_bytes) > 11 and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


def format_image_for_claude(
    image_bytes: bytes,
    source_type: str,
    media_type: Optional[str] = None
) -> ImageContent:
    """
    Format raw image bytes into Claude API-compatible content.

    Args:
        image_bytes: Raw image data
        source_type: Origin of image ("screenshot", "webcam", or "telegram")
        media_type: Optional MIME type of the image. If not provided,
                    detected automatically from image magic bytes.

    Returns:
        ImageContent object ready for API use
    """
    if not media_type:
        media_type = _detect_media_type(image_bytes)
    encoded = base64.b64encode(image_bytes).decode('utf-8')
    return ImageContent(
        media_type=media_type,
        data=encoded,
        source_type=source_type
    )


def capture_screenshot_for_claude() -> Optional[ImageContent]:
    """
    Capture screenshot and format for Claude's API.

    Convenience function combining capture and formatting.

    Returns:
        ImageContent ready for Claude API, or None if capture fails
    """
    image_bytes = capture_screenshot_bytes()
    if image_bytes is None:
        return None
    return format_image_for_claude(image_bytes, "screenshot")


def capture_webcam_for_claude() -> Optional[ImageContent]:
    """
    Capture webcam frame and format for Claude's API.

    Convenience function combining capture and formatting.

    Returns:
        ImageContent ready for Claude API, or None if capture fails
    """
    image_bytes = capture_webcam_bytes()
    if image_bytes is None:
        return None
    return format_image_for_claude(image_bytes, "webcam")


def capture_all_visuals() -> List[ImageContent]:
    """
    Capture visual sources configured for auto-mode.

    Only captures sources where mode is "auto" (not "on_demand" or "disabled").
    Sources in "on_demand" mode are captured via tool calls instead.
    Failed captures are silently skipped (graceful degradation).

    Returns:
        List of ImageContent objects (may be empty if all captures fail)
    """
    import config

    images = []

    # Only capture screenshot if mode is "auto" (not "on_demand" or "disabled")
    if config.VISUAL_SCREENSHOT_MODE == "auto":
        screenshot = capture_screenshot_for_claude()
        if screenshot:
            images.append(screenshot)

    # Only capture webcam if mode is "auto" (not "on_demand" or "disabled")
    if config.VISUAL_WEBCAM_MODE == "auto":
        webcam = capture_webcam_for_claude()
        if webcam:
            images.append(webcam)

    log_info(f"Captured {len(images)} visual(s) for prompt", prefix="👁️")
    return images


def build_multimodal_content(
    text: str,
    images: Optional[List[ImageContent]] = None
) -> List[Dict[str, Any]]:
    """
    Build a multimodal content array for Claude API messages.

    Creates a content array with images first, then text. This format
    is used in Claude's messages API for multimodal inputs.

    Args:
        text: The text content (user input or prompt)
        images: Optional list of ImageContent objects

    Returns:
        List of content blocks for Claude API message
    """
    content = []

    # DIAGNOSTIC: Log multimodal build
    log_info(f"Building multimodal content: text={len(text)} chars, images={len(images) if images else 0}", prefix="👁️")

    # Add images first (Claude processes them before text)
    if images:
        for i, img in enumerate(images):
            try:
                api_format = img.to_api_format()
                # Log image details (not the actual data)
                source = api_format.get("source", {})
                data_len = len(source.get("data", "")) if source else 0
                media_type = source.get("media_type", "unknown") if source else "unknown"
                log_info(f"  Image {i}: type={media_type}, source={img.source_type}, data_len={data_len}", prefix="👁️")
                content.append(api_format)
            except Exception as e:
                log_error(f"  Image {i}: Failed to convert to API format: {e}", prefix="👁️")

    # Add text content
    content.append({
        "type": "text",
        "text": text
    })

    log_info(f"Multimodal content built: {len(content)} blocks total", prefix="👁️")
    return content


# =============================================================================
# TEMP IMAGE REGISTRY (turn-level image tracking for save_image tool)
# =============================================================================
# When images enter the system (any source), they are saved to temp files
# and registered here. The save_image tool handler looks up temp images
# by source_type. At end of turn, remaining temp files are cleaned up.

_temp_images: Dict[str, str] = {}  # source_type -> temp_file_path


def save_temp_image(image_bytes: bytes, source_type: str) -> Optional[str]:
    """Save image bytes to a temp file and register for this turn.

    Args:
        image_bytes: Raw image bytes (JPEG)
        source_type: Origin of image ("screenshot", "webcam", "telegram", "clipboard")

    Returns:
        Path to temp file, or None on failure
    """
    import config
    import uuid

    if not config.IMAGE_MEMORY_ENABLED:
        return None

    try:
        config.IMAGE_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        # Clean up old temp file for this source_type before overwriting
        if source_type in _temp_images:
            from pathlib import Path
            old_path = Path(_temp_images[source_type])
            old_path.unlink(missing_ok=True)
        filename = f"{source_type}_{uuid.uuid4().hex[:8]}.jpg"
        temp_path = config.IMAGE_TEMP_DIR / filename
        temp_path.write_bytes(image_bytes)
        _temp_images[source_type] = str(temp_path)
        log_info(f"Temp image saved: {source_type} ({len(image_bytes)} bytes)", prefix="💾")
        return str(temp_path)
    except Exception as e:
        log_error(f"Failed to save temp image: {e}")
        return None


def get_temp_images() -> Dict[str, str]:
    """Get all temp image paths by source type."""
    return dict(_temp_images)


def cleanup_temp_images():
    """Delete all temp images and clear registry. Call at end of turn."""
    from pathlib import Path
    for source_type, path_str in _temp_images.items():
        try:
            Path(path_str).unlink(missing_ok=True)
        except Exception:
            pass
    _temp_images.clear()


def is_visual_capture_available() -> Tuple[bool, bool]:
    """
    Check which visual capture methods are available.

    Returns:
        Tuple of (screenshot_available, webcam_available)
    """
    return (PIL_AVAILABLE, CV2_AVAILABLE)
