"""
Pattern Project - Browser Engine for Delegate Sub-Agents

Manages the Playwright browser lifecycle:
- Lazy initialization (browser only starts on first tool use)
- Headless-only operation (no GUI window)
- Per-service session persistence (cookies/storage survive across delegations)
- Clean shutdown when delegation completes

Usage:
    engine = BrowserEngine(sessions_dir=Path("data/browser_sessions"))

    # Lazy — browser starts on first call
    page = await engine.get_page()
    await page.goto("https://example.com")

    # Load saved session for a service before navigating to login
    await engine.load_session("reddit")

    # Save session after login succeeds
    await engine.save_session("reddit")

    # Cleanup when delegation is done
    await engine.close()
"""

import json
from pathlib import Path
from typing import Optional

from core.logger import log_info, log_warning, log_error


class BrowserEngine:
    """
    Manages a single Playwright browser instance for a delegation task.

    The browser is lazy-initialized on first use and runs headless.
    Session data (cookies, local storage) can be saved/loaded per service
    to avoid re-authenticating on every delegation.
    """

    def __init__(self, sessions_dir: Path):
        """
        Initialize the browser engine.

        Args:
            sessions_dir: Directory for per-service session persistence.
                          Each service gets a subdirectory with cookies.json
                          and storage.json files.
        """
        self._sessions_dir = sessions_dir
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._initialized = False
        self._current_service: Optional[str] = None

    async def _ensure_initialized(self) -> None:
        """Lazy-initialize Playwright and browser on first use."""
        if self._initialized:
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            )

        log_info("Starting headless browser for delegation task", prefix="🌐")

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ]
        )

        # Create a fresh browser context
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        self._page = await self._context.new_page()
        self._initialized = True

        log_info("Headless browser ready", prefix="🌐")

    async def get_page(self):
        """
        Get the active Playwright Page, initializing the browser if needed.

        Returns:
            Playwright Page object
        """
        await self._ensure_initialized()
        return self._page

    @property
    def is_initialized(self) -> bool:
        """Check if the browser has been started."""
        return self._initialized

    # =========================================================================
    # SESSION PERSISTENCE
    # =========================================================================

    def _service_session_dir(self, service: str) -> Path:
        """Get the session directory for a specific service."""
        return self._sessions_dir / service

    async def load_session(self, service: str) -> bool:
        """
        Load saved cookies and storage state for a service.

        Call this BEFORE navigating to a service's login page.
        If a saved session exists, the browser will have those cookies
        and the login may be skipped entirely.

        Args:
            service: Service name (e.g., "reddit", "twitter")

        Returns:
            True if a session was loaded, False if none existed
        """
        await self._ensure_initialized()

        session_dir = self._service_session_dir(service)
        cookies_path = session_dir / "cookies.json"

        if not cookies_path.exists():
            log_info(f"No saved session for '{service}'", prefix="🌐")
            return False

        try:
            with open(cookies_path, "r") as f:
                cookies = json.load(f)

            if cookies:
                await self._context.add_cookies(cookies)
                self._current_service = service
                log_info(
                    f"Loaded session for '{service}' ({len(cookies)} cookies)",
                    prefix="🌐"
                )
                return True
            return False

        except Exception as e:
            log_warning(f"Failed to load session for '{service}': {e}")
            return False

    async def save_session(self, service: str) -> bool:
        """
        Save current cookies and storage state for a service.

        Call this AFTER a successful login so future delegations
        can skip the login flow.

        Args:
            service: Service name (e.g., "reddit", "twitter")

        Returns:
            True if session was saved successfully
        """
        if not self._initialized or not self._context:
            return False

        session_dir = self._service_session_dir(service)
        session_dir.mkdir(parents=True, exist_ok=True)
        cookies_path = session_dir / "cookies.json"

        try:
            cookies = await self._context.cookies()

            with open(cookies_path, "w") as f:
                json.dump(cookies, f, indent=2)

            self._current_service = service
            log_info(
                f"Saved session for '{service}' ({len(cookies)} cookies)",
                prefix="🌐"
            )
            return True

        except Exception as e:
            log_warning(f"Failed to save session for '{service}': {e}")
            return False

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def close(self) -> None:
        """
        Shut down the browser and clean up resources.

        Called when a delegation task completes. If a service session
        is active, it's automatically saved before shutdown.
        """
        if not self._initialized:
            return

        # Auto-save session if we have an active service
        if self._current_service:
            try:
                await self.save_session(self._current_service)
            except Exception as e:
                log_warning(f"Failed to auto-save session on close: {e}")

        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()

            log_info("Headless browser shut down", prefix="🌐")
        except Exception as e:
            log_error(f"Error closing browser: {e}")
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._playwright = None
            self._initialized = False
            self._current_service = None
