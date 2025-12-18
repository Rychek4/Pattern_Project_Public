"""
Pattern Project - Visual Capture System
Screenshot and webcam capture for direct Claude multimodal integration

This module provides:
1. Raw image capture (screenshot, webcam) returning bytes
2. Image formatting for Claude's multimodal API
3. Legacy Gemini interpretation support (disabled by default, kept for fallback)
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

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cap = None
        self._device_lock = threading.Lock()
        self._is_open = False

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
                return image_bytes

            except Exception as e:
                log_error(f"Webcam capture failed: {e}")
                self._close_device_internal()
                return None

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

def format_image_for_claude(
    image_bytes: bytes,
    source_type: str,
    media_type: str = "image/jpeg"
) -> ImageContent:
    """
    Format raw image bytes into Claude API-compatible content.

    Args:
        image_bytes: Raw image data
        source_type: Origin of image ("screenshot", "webcam", or "telegram")
        media_type: MIME type of the image

    Returns:
        ImageContent object ready for API use
    """
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


def is_visual_capture_available() -> Tuple[bool, bool]:
    """
    Check which visual capture methods are available.

    Returns:
        Tuple of (screenshot_available, webcam_available)
    """
    return (PIL_AVAILABLE, CV2_AVAILABLE)


# =============================================================================
# LEGACY GEMINI INTERPRETATION (Disabled, kept for fallback)
# =============================================================================

# Gemini imports - only needed for legacy fallback mode
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


class LegacyVisualCaptureSystem:
    """
    Legacy visual capture system using Gemini for interpretation.

    This class is DISABLED and kept only for potential future fallback
    scenarios. The new system sends images directly to Claude via multimodal.
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        capture_interval: int = 30,
        enable_screenshot: bool = True,
        enable_webcam: bool = True
    ):
        """
        Initialize the legacy visual capture system.

        Args:
            gemini_api_key: Google API key for Gemini
            capture_interval: Seconds between captures (legacy timer mode)
            enable_screenshot: Enable screenshot capture
            enable_webcam: Enable webcam capture
        """
        import os
        self.api_key = gemini_api_key or os.getenv("GOOGLE_API_KEY", "")
        self.capture_interval = capture_interval
        self.enable_screenshot = enable_screenshot and PIL_AVAILABLE
        self.enable_webcam = enable_webcam and CV2_AVAILABLE

        self._model = None
        self._running = False
        self._lock = threading.RLock()

        # Initialize Gemini if available
        if GEMINI_AVAILABLE and self.api_key:
            self._init_gemini()

    def _init_gemini(self) -> bool:
        """Initialize the Gemini model."""
        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
            log_info("Legacy Gemini interpreter initialized", prefix="🤖")
            return True
        except Exception as e:
            log_error(f"Failed to initialize Gemini: {e}")
            return False

    def interpret_image(
        self,
        image_bytes: bytes,
        source_type: str
    ) -> Optional[str]:
        """
        Interpret image using Gemini 2.5 Flash.

        Args:
            image_bytes: JPEG image data
            source_type: 'screenshot' or 'webcam'

        Returns:
            Text description of the image, or None on failure
        """
        if not self._model:
            return None

        try:
            # Select prompt based on source type
            if source_type == "screenshot":
                prompt = """Describe what you see in this screenshot concisely.
Focus on: Active application/window, key content visible, user's apparent activity.
Keep response under 100 words. Be factual, not interpretive."""
            else:
                prompt = """Describe what you see in this webcam image concisely.
Focus on: Person present (if any), environment/background, lighting conditions.
Keep response under 75 words. Respect privacy - no identifying details."""

            # Create image part for Gemini
            image_part = {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(image_bytes).decode('utf-8')
            }

            # Generate description
            response = self._model.generate_content([prompt, image_part])

            if response.text:
                return response.text.strip()
            return None

        except Exception as e:
            log_warning(f"Gemini interpretation failed: {e}")
            return None

    @property
    def is_available(self) -> bool:
        """Check if legacy system is available."""
        return self._model is not None


# Global legacy instance (not initialized by default)
_legacy_capture: Optional[LegacyVisualCaptureSystem] = None


def get_legacy_capture() -> Optional[LegacyVisualCaptureSystem]:
    """Get the legacy capture system (initializes on first call if needed)."""
    global _legacy_capture
    # Only initialize if explicitly needed (not implemented yet)
    return _legacy_capture
