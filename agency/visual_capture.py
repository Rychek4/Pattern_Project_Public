"""
Pattern Project - Visual Capture System
Screenshot and webcam capture with Gemini 2.5 Flash interpretation
"""

import os
import io
import base64
import threading
from typing import Optional, Callable
from datetime import datetime
from pathlib import Path

from prompt_builder.sources.visual import get_visual_source
from core.logger import log_info, log_error, log_warning

# Optional imports - graceful degradation if not available
try:
    from PIL import ImageGrab, Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    # Optional - only needed for screenshot capture
    log_warning("PIL not available - screenshot capture disabled (optional)")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    # Optional - only needed for webcam capture
    log_warning("OpenCV not available - webcam capture disabled (optional)")

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    # This is an optional feature - not a problem if missing
    log_warning("Google Generative AI not available - visual features disabled (optional)")


# Interpretation prompts
SCREENSHOT_PROMPT = """Describe what you see in this screenshot concisely.
Focus on:
- Active application/window
- Key content visible (text, images, code)
- User's apparent activity

Keep response under 100 words. Be factual, not interpretive."""

WEBCAM_PROMPT = """Describe what you see in this webcam image concisely.
Focus on:
- Person present (if any) - general appearance, expression, posture
- Environment/background
- Lighting conditions

Keep response under 75 words. Respect privacy - no identifying details."""


class VisualCaptureSystem:
    """
    Captures screenshots and webcam images, interprets with Gemini.

    Process:
    1. Timer triggers capture
    2. Image captured (screenshot or webcam)
    3. Image sent to Gemini 2.5 Flash for description
    4. Description cached in VisualSource
    5. Cache used for prompt injection
    """

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        capture_interval: int = 30,
        enable_screenshot: bool = True,
        enable_webcam: bool = True
    ):
        """
        Initialize the visual capture system.

        Args:
            gemini_api_key: Google API key for Gemini
            capture_interval: Seconds between captures
            enable_screenshot: Enable screenshot capture
            enable_webcam: Enable webcam capture
        """
        self.api_key = gemini_api_key or os.getenv("GOOGLE_API_KEY", "")
        self.capture_interval = capture_interval
        self.enable_screenshot = enable_screenshot and PIL_AVAILABLE
        self.enable_webcam = enable_webcam and CV2_AVAILABLE

        self._model = None
        self._webcam: Optional[cv2.VideoCapture] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # Initialize Gemini if available
        if GEMINI_AVAILABLE and self.api_key:
            self._init_gemini()

    def _init_gemini(self) -> bool:
        """Initialize the Gemini model."""
        try:
            genai.configure(api_key=self.api_key)
            self._model = genai.GenerativeModel('gemini-2.5-flash-preview-05-20')
            log_info("Gemini 2.5 Flash initialized", prefix="🤖")
            return True
        except Exception as e:
            log_error(f"Failed to initialize Gemini: {e}")
            return False

    def start(self) -> None:
        """Start the visual capture system."""
        if self._running:
            return

        if not self._model:
            log_warning("Gemini not initialized - visual capture disabled")
            return

        # Initialize webcam if enabled
        if self.enable_webcam and CV2_AVAILABLE:
            try:
                self._webcam = cv2.VideoCapture(0)
                if not self._webcam.isOpened():
                    log_warning("Could not open webcam")
                    self._webcam = None
            except Exception as e:
                log_warning(f"Webcam initialization failed: {e}")
                self._webcam = None

        # Register callbacks with visual source
        visual_source = get_visual_source()
        visual_source.set_capture_callbacks(
            screenshot_fn=self._capture_screenshot if self.enable_screenshot else None,
            webcam_fn=self._capture_webcam if self.enable_webcam else None,
            interpret_fn=self._interpret_image
        )

        # Start the visual source refresh loop
        visual_source.refresh_interval = self.capture_interval
        visual_source.start_refresh_loop()

        self._running = True
        log_info("Visual capture system started", prefix="📷")

    def stop(self) -> None:
        """Stop the visual capture system."""
        self._running = False

        # Stop visual source refresh
        visual_source = get_visual_source()
        visual_source.stop_refresh_loop()

        # Release webcam
        if self._webcam:
            self._webcam.release()
            self._webcam = None

        log_info("Visual capture system stopped", prefix="⏹️")

    def _capture_screenshot(self) -> Optional[bytes]:
        """Capture a screenshot and return as bytes."""
        if not PIL_AVAILABLE:
            return None

        try:
            # Capture screen
            screenshot = ImageGrab.grab()

            # Resize if too large (for faster processing)
            max_size = (1280, 720)
            screenshot.thumbnail(max_size, Image.Resampling.LANCZOS)

            # Convert to bytes
            buffer = io.BytesIO()
            screenshot.save(buffer, format='JPEG', quality=85)
            return buffer.getvalue()

        except Exception as e:
            log_warning(f"Screenshot capture failed: {e}")
            return None

    def _capture_webcam(self) -> Optional[bytes]:
        """Capture a webcam frame and return as bytes."""
        if not self._webcam or not CV2_AVAILABLE:
            return None

        try:
            with self._lock:
                ret, frame = self._webcam.read()
                if not ret:
                    return None

                # Resize for faster processing
                frame = cv2.resize(frame, (640, 480))

                # Convert to JPEG bytes
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return buffer.tobytes()

        except Exception as e:
            log_warning(f"Webcam capture failed: {e}")
            return None

    def _interpret_image(
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
            Text description of the image
        """
        if not self._model:
            return None

        try:
            # Select prompt based on source type
            prompt = SCREENSHOT_PROMPT if source_type == "screenshot" else WEBCAM_PROMPT

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
            log_warning(f"Image interpretation failed: {e}")
            return None

    def capture_screenshot_now(self) -> Optional[str]:
        """
        Capture and interpret a screenshot immediately.

        Returns:
            Text description of the screenshot
        """
        image_bytes = self._capture_screenshot()
        if not image_bytes:
            return None

        description = self._interpret_image(image_bytes, "screenshot")
        if description:
            visual_source = get_visual_source()
            visual_source.update_screenshot(description)

        return description

    def capture_webcam_now(self) -> Optional[str]:
        """
        Capture and interpret a webcam frame immediately.

        Returns:
            Text description of the webcam image
        """
        image_bytes = self._capture_webcam()
        if not image_bytes:
            return None

        description = self._interpret_image(image_bytes, "webcam")
        if description:
            visual_source = get_visual_source()
            visual_source.update_webcam(description)

        return description

    @property
    def is_available(self) -> bool:
        """Check if visual capture is available."""
        return self._model is not None and (self.enable_screenshot or self.enable_webcam)


# Global instance
_visual_capture: Optional[VisualCaptureSystem] = None


def get_visual_capture() -> VisualCaptureSystem:
    """Get the global visual capture instance."""
    global _visual_capture
    if _visual_capture is None:
        _visual_capture = VisualCaptureSystem()
    return _visual_capture


def init_visual_capture(
    gemini_api_key: Optional[str] = None,
    capture_interval: int = 30,
    enable_screenshot: bool = True,
    enable_webcam: bool = True
) -> VisualCaptureSystem:
    """Initialize and start the global visual capture system."""
    global _visual_capture
    _visual_capture = VisualCaptureSystem(
        gemini_api_key=gemini_api_key,
        capture_interval=capture_interval,
        enable_screenshot=enable_screenshot,
        enable_webcam=enable_webcam
    )
    _visual_capture.start()
    return _visual_capture
