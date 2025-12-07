"""
Pattern Project - Visual Source
Cached image descriptions from screenshots/webcam
"""

import threading
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import base64

from prompt_builder.sources.base import ContextSource, ContextBlock, SourcePriority
from core.logger import log_info, log_error, log_warning


# Default refresh interval: 30 seconds
DEFAULT_REFRESH_INTERVAL = 30


@dataclass
class CachedVisual:
    """A cached visual description."""
    source_type: str  # 'screenshot' or 'webcam'
    description: str
    captured_at: datetime
    expires_at: datetime
    image_path: Optional[str] = None


class VisualSource(ContextSource):
    """
    Provides visual context from screenshots and webcam.

    Process:
    1. Timer triggers image capture
    2. Image sent to Gemini 2.5 Flash for interpretation
    3. Text description cached
    4. Cached description injected into prompts
    5. Cache refreshes on timer

    Note: Actual image capture and Gemini integration are implemented
    separately. This source manages the cache and prompt injection.
    """

    def __init__(
        self,
        refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
        gemini_api_key: Optional[str] = None
    ):
        """
        Initialize visual source.

        Args:
            refresh_interval: Seconds between visual refreshes
            gemini_api_key: Gemini API key for image interpretation
        """
        self.refresh_interval = refresh_interval
        self.gemini_api_key = gemini_api_key

        # Cached visuals
        self._screenshot_cache: Optional[CachedVisual] = None
        self._webcam_cache: Optional[CachedVisual] = None

        # Threading
        self._lock = threading.RLock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Callbacks for capture (set by visual capture system)
        self._screenshot_callback: Optional[Callable[[], Optional[bytes]]] = None
        self._webcam_callback: Optional[Callable[[], Optional[bytes]]] = None
        self._interpret_callback: Optional[Callable[[bytes, str], Optional[str]]] = None

    @property
    def source_name(self) -> str:
        return "visual"

    @property
    def priority(self) -> int:
        return SourcePriority.VISUAL

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get cached visual descriptions for prompt injection."""
        with self._lock:
            now = datetime.now()
            visuals = []

            # Check screenshot cache
            if self._screenshot_cache and now < self._screenshot_cache.expires_at:
                visuals.append(("screenshot", self._screenshot_cache.description))

            # Check webcam cache
            if self._webcam_cache and now < self._webcam_cache.expires_at:
                visuals.append(("webcam", self._webcam_cache.description))

            if not visuals:
                return None

            # Format for prompt
            lines = ["<visual_context>"]

            for source_type, description in visuals:
                lines.append(f"  <{source_type}>")
                lines.append(f"    {description}")
                lines.append(f"  </{source_type}>")

            lines.append("</visual_context>")

            return ContextBlock(
                source_name=self.source_name,
                content="\n".join(lines),
                priority=self.priority,
                include_always=False,
                metadata={
                    "has_screenshot": self._screenshot_cache is not None,
                    "has_webcam": self._webcam_cache is not None,
                    "visual_count": len(visuals)
                }
            )

    def update_screenshot(self, description: str) -> None:
        """
        Update the screenshot description cache.

        Args:
            description: Text description from image interpretation
        """
        with self._lock:
            now = datetime.now()
            self._screenshot_cache = CachedVisual(
                source_type="screenshot",
                description=description,
                captured_at=now,
                expires_at=now + timedelta(seconds=self.refresh_interval)
            )
            log_info(f"Screenshot cache updated: {description[:50]}...", prefix="📸")

    def update_webcam(self, description: str) -> None:
        """
        Update the webcam description cache.

        Args:
            description: Text description from image interpretation
        """
        with self._lock:
            now = datetime.now()
            self._webcam_cache = CachedVisual(
                source_type="webcam",
                description=description,
                captured_at=now,
                expires_at=now + timedelta(seconds=self.refresh_interval)
            )
            log_info(f"Webcam cache updated: {description[:50]}...", prefix="📷")

    def set_capture_callbacks(
        self,
        screenshot_fn: Optional[Callable[[], Optional[bytes]]] = None,
        webcam_fn: Optional[Callable[[], Optional[bytes]]] = None,
        interpret_fn: Optional[Callable[[bytes, str], Optional[str]]] = None
    ) -> None:
        """
        Set callbacks for image capture and interpretation.

        Args:
            screenshot_fn: Function that captures screenshot, returns bytes
            webcam_fn: Function that captures webcam frame, returns bytes
            interpret_fn: Function that interprets image bytes, returns description
        """
        self._screenshot_callback = screenshot_fn
        self._webcam_callback = webcam_fn
        self._interpret_callback = interpret_fn

    def start_refresh_loop(self) -> None:
        """Start the background refresh loop."""
        if self._refresh_thread is not None and self._refresh_thread.is_alive():
            return

        self._stop_event.clear()
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            daemon=True,
            name="VisualRefresh"
        )
        self._refresh_thread.start()
        log_info("Visual refresh loop started", prefix="🔄")

    def stop_refresh_loop(self) -> None:
        """Stop the background refresh loop."""
        self._stop_event.set()
        if self._refresh_thread is not None:
            self._refresh_thread.join(timeout=5.0)
            self._refresh_thread = None
        log_info("Visual refresh loop stopped", prefix="⏹️")

    def _refresh_loop(self) -> None:
        """Background loop that refreshes visual caches."""
        while not self._stop_event.is_set():
            try:
                self._refresh_visuals()
            except Exception as e:
                log_error(f"Visual refresh error: {e}")

            self._stop_event.wait(self.refresh_interval)

    def _refresh_visuals(self) -> None:
        """Capture and interpret current visuals."""
        if not self._interpret_callback:
            return

        # Capture and interpret screenshot
        if self._screenshot_callback:
            try:
                image_bytes = self._screenshot_callback()
                if image_bytes:
                    description = self._interpret_callback(image_bytes, "screenshot")
                    if description:
                        self.update_screenshot(description)
            except Exception as e:
                log_warning(f"Screenshot capture failed: {e}")

        # Capture and interpret webcam
        if self._webcam_callback:
            try:
                image_bytes = self._webcam_callback()
                if image_bytes:
                    description = self._interpret_callback(image_bytes, "webcam")
                    if description:
                        self.update_webcam(description)
            except Exception as e:
                log_warning(f"Webcam capture failed: {e}")

    def clear_cache(self) -> None:
        """Clear all cached visuals."""
        with self._lock:
            self._screenshot_cache = None
            self._webcam_cache = None
            log_info("Visual cache cleared", prefix="🗑️")

    def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self.stop_refresh_loop()
        self.clear_cache()


# Global instance
_visual_source: Optional[VisualSource] = None


def get_visual_source() -> VisualSource:
    """Get the global visual source instance."""
    global _visual_source
    if _visual_source is None:
        _visual_source = VisualSource()
    return _visual_source


def init_visual_source(
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL,
    gemini_api_key: Optional[str] = None
) -> VisualSource:
    """Initialize the global visual source."""
    global _visual_source
    _visual_source = VisualSource(
        refresh_interval=refresh_interval,
        gemini_api_key=gemini_api_key
    )
    return _visual_source
