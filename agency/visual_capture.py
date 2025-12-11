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
# IMAGE CONTENT DATA STRUCTURES
# =============================================================================

@dataclass
class ImageContent:
    """
    Image content formatted for Claude's multimodal API.

    Attributes:
        media_type: MIME type (e.g., "image/jpeg", "image/png")
        data: Base64-encoded image data
        source_type: Origin of image ("screenshot" or "webcam")
    """
    media_type: str
    data: str  # Base64 encoded
    source_type: str

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

    Opens the default webcam (device 0), captures a single frame,
    resizes to 640x480, and returns as JPEG.

    Returns:
        JPEG image bytes, or None if capture fails
    """
    if not CV2_AVAILABLE:
        log_warning("Webcam capture unavailable - OpenCV not installed")
        return None

    try:
        # Open webcam
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            log_warning("Could not open webcam (device 0)")
            return None

        try:
            # Capture a frame
            ret, frame = cap.read()
            if not ret or frame is None:
                log_warning("Failed to read webcam frame")
                return None

            # Resize for efficient transmission
            frame = cv2.resize(frame, (640, 480))

            # Convert to JPEG bytes
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_bytes = buffer.tobytes()

            log_info(f"Webcam captured: {len(image_bytes)} bytes", prefix="📷")
            return image_bytes

        finally:
            cap.release()

    except Exception as e:
        log_error(f"Webcam capture failed: {e}")
        return None


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
        source_type: Origin of image ("screenshot" or "webcam")
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
    Capture all enabled visual sources for auto-mode.

    Captures screenshot and webcam based on config settings.
    Failed captures are silently skipped (graceful degradation).

    Returns:
        List of ImageContent objects (may be empty if all captures fail)
    """
    import config

    images = []

    if config.VISUAL_SCREENSHOT_ENABLED:
        screenshot = capture_screenshot_for_claude()
        if screenshot:
            images.append(screenshot)

    if config.VISUAL_WEBCAM_ENABLED:
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

    # Add images first (Claude processes them before text)
    if images:
        for img in images:
            content.append(img.to_api_format())

    # Add text content
    content.append({
        "type": "text",
        "text": text
    })

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

    This class is DISABLED by default and kept only for potential future
    fallback scenarios. The new system sends images directly to Claude.

    To use: Set VISUAL_CAPTURE_MODE to "legacy" (not currently implemented)
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
