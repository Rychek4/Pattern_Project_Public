"""
Pattern Project - Moltbook API Client
Direct REST integration with Moltbook (https://www.moltbook.com/).

Moltbook is a social network for AI agents. This client wraps its REST API
with proper authentication, rate limiting, and error handling.

No Moltbot/OpenClaw harness required - this talks directly to the API using
a Bearer token obtained through the registration flow.

API Base: https://www.moltbook.com/api/v1
Auth: Bearer token (moltbook_xxx)
User-Agent: Molt/1.0 (OpenClaw; Pattern-Agent)
"""

import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from threading import Lock

import requests
from urllib.parse import urlparse

from core.logger import log_info, log_warning, log_error


class _MoltbookSession(requests.Session):
    """
    A requests.Session subclass that preserves the Authorization header
    across redirects within moltbook.com.

    Python's ``requests`` library strips auth headers when following a
    redirect to a different *host*.  Moltbook's infrastructure can
    redirect between ``www.moltbook.com`` and ``moltbook.com`` (or
    other subdomains), which counts as a host change.  This causes a
    silent 401 because the Bearer token is dropped mid-flight.

    See: https://www.moltbook.com/post/d45e46d1-4cf6-4ced-82b4-e41db2033ca5
    """

    def rebuild_auth(self, prepared_request, response):
        """Keep auth for moltbook.com; defer to default for other hosts."""
        redirect_host = urlparse(prepared_request.url).hostname or ""
        if redirect_host.endswith("moltbook.com"):
            # Preserve Authorization header – same trusted domain.
            return
        super().rebuild_auth(prepared_request, response)


class MoltbookRateLimiter:
    """
    Three-tier rate limiter for Moltbook's API constraints.

    Tiers:
      - requests: 100 per minute (rolling 60s window)
      - posts:    1 per 30 minutes (rolling 1800s window)
      - comments: 50 per hour (rolling 3600s window)
    """

    def __init__(
        self,
        requests_per_min: int = 100,
        posts_per_30min: int = 1,
        comments_per_hour: int = 50,
    ):
        self._limits = {
            "requests": (requests_per_min, 60),
            "posts": (posts_per_30min, 1800),
            "comments": (comments_per_hour, 3600),
        }
        self._timestamps: Dict[str, List[datetime]] = {
            "requests": [],
            "posts": [],
            "comments": [],
        }
        self._lock = Lock()

    def _clean(self, tier: str) -> None:
        """Remove expired timestamps for a tier."""
        _, window = self._limits[tier]
        cutoff = datetime.now() - timedelta(seconds=window)
        self._timestamps[tier] = [
            ts for ts in self._timestamps[tier] if ts > cutoff
        ]

    def check(self, tier: str) -> bool:
        """Check if an action is allowed under the given tier."""
        with self._lock:
            self._clean(tier)
            limit, _ = self._limits[tier]
            return len(self._timestamps[tier]) < limit

    def record(self, tier: str) -> None:
        """Record a timestamp for the given tier."""
        with self._lock:
            self._timestamps[tier].append(datetime.now())

    def remaining(self, tier: str) -> int:
        """Get remaining quota for a tier."""
        with self._lock:
            self._clean(tier)
            limit, _ = self._limits[tier]
            return max(0, limit - len(self._timestamps[tier]))

    def seconds_until_available(self, tier: str) -> Optional[float]:
        """Seconds until the next slot opens for a tier, or None if available now."""
        with self._lock:
            self._clean(tier)
            limit, window = self._limits[tier]
            if len(self._timestamps[tier]) < limit:
                return None
            oldest = min(self._timestamps[tier])
            reset_at = oldest + timedelta(seconds=window)
            remaining = (reset_at - datetime.now()).total_seconds()
            return max(0.0, remaining)


class MoltbookClient:
    """
    HTTP client for the Moltbook REST API.

    All methods return a dict with either the parsed JSON response
    or an error structure: {"error": True, "message": "..."}.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://www.moltbook.com/api/v1",
        user_agent: str = "Molt/1.0 (OpenClaw; Pattern-Agent)",
        requests_per_min: int = 100,
        posts_per_30min: int = 1,
        comments_per_hour: int = 50,
    ):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._session = _MoltbookSession()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        })
        self._rate_limiter = MoltbookRateLimiter(
            requests_per_min=requests_per_min,
            posts_per_30min=posts_per_30min,
            comments_per_hour=comments_per_hour,
        )

    def _check_rate_limit(self, *tiers: str) -> Optional[Dict[str, Any]]:
        """
        Check all specified rate limit tiers. Returns an error dict if any
        tier is exhausted, or None if all are clear.
        """
        for tier in tiers:
            if not self._rate_limiter.check(tier):
                wait = self._rate_limiter.seconds_until_available(tier)
                wait_str = f" Try again in {int(wait)}s." if wait else ""
                return {
                    "error": True,
                    "message": f"Rate limited ({tier}: {self._rate_limiter.remaining(tier)} remaining).{wait_str}",
                }
        return None

    def _record_rate_limit(self, *tiers: str) -> None:
        """Record a hit against all specified rate limit tiers."""
        for tier in tiers:
            self._rate_limiter.record(tier)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
        extra_tiers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Core request method with rate limiting, error handling, and 429 backoff.

        Args:
            method: HTTP method (GET, POST)
            path: API path (e.g., "/posts")
            params: Query parameters for GET requests
            json_body: JSON body for POST requests
            extra_tiers: Additional rate limit tiers to check beyond "requests"

        Returns:
            Parsed JSON response dict, or error dict
        """
        # Check rate limits
        tiers_to_check = ["requests"] + (extra_tiers or [])
        rate_error = self._check_rate_limit(*tiers_to_check)
        if rate_error:
            log_warning(f"Moltbook rate limited: {rate_error['message']}")
            return rate_error

        url = f"{self._base_url}{path}"

        try:
            response = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                timeout=15,
            )

            # Record the request
            self._record_rate_limit(*tiers_to_check)

            # Handle 429 Too Many Requests
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "60")
                try:
                    wait_seconds = int(retry_after)
                except ValueError:
                    wait_seconds = 60
                log_warning(f"Moltbook 429: server says retry after {wait_seconds}s")
                return {
                    "error": True,
                    "message": f"Server rate limited. Retry after {wait_seconds} seconds.",
                }

            # Handle other HTTP errors
            if not response.ok:
                error_text = response.text[:200] if response.text else f"HTTP {response.status_code}"
                log_error(f"Moltbook API error: {response.status_code} - {error_text}")
                if response.history:
                    chain = " -> ".join(
                        f"{r.status_code} {r.url}" for r in response.history
                    )
                    log_warning(f"Moltbook redirect chain: {chain} -> {response.url}")
                    has_auth = "Authorization" in response.request.headers
                    log_warning(f"Moltbook auth header on final request: {has_auth}")
                return {
                    "error": True,
                    "message": f"API error ({response.status_code}): {error_text}",
                }

            # Parse JSON response
            data = response.json()
            return data

        except requests.exceptions.Timeout:
            log_error("Moltbook API timeout")
            return {"error": True, "message": "Request timed out (15s)"}
        except requests.exceptions.ConnectionError:
            log_error("Moltbook API connection error")
            return {"error": True, "message": "Connection failed. Check network or Moltbook status."}
        except requests.exceptions.JSONDecodeError:
            log_error("Moltbook API returned non-JSON response")
            return {"error": True, "message": "Invalid response from server (not JSON)"}
        except Exception as e:
            log_error(f"Moltbook API unexpected error: {e}")
            return {"error": True, "message": f"Unexpected error: {str(e)}"}

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    def get_feed(
        self,
        sort: str = "hot",
        limit: int = 25,
        submolt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get posts from the feed.

        Args:
            sort: Sort order - "hot", "new", "top", "rising"
            limit: Number of posts to return (max 25)
            submolt: Optional submolt name to filter by

        Returns:
            API response with posts list
        """
        params = {"sort": sort, "limit": min(limit, 25)}
        if submolt:
            # Strip "m/" prefix if included (e.g. "m/sandbox" -> "sandbox")
            if submolt.startswith("m/"):
                submolt = submolt[2:]
            params["submolt"] = submolt

        log_info(f"Moltbook feed: sort={sort}, submolt={submolt or 'all'}", prefix="🦞")
        return self._request("GET", "/posts", params=params)

    def get_post(self, post_id: str) -> Dict[str, Any]:
        """
        Get a single post by ID, including its comments.

        Args:
            post_id: The post ID

        Returns:
            API response with post data and comments
        """
        log_info(f"Moltbook post: {post_id}", prefix="🦞")
        return self._request("GET", f"/posts/{post_id}")

    def search(self, query: str, limit: int = 25) -> Dict[str, Any]:
        """
        Search posts, agents, and submolts.

        Args:
            query: Search query string
            limit: Max results (max 25)

        Returns:
            API response with search results
        """
        params = {"q": query, "limit": min(limit, 25)}
        log_info(f"Moltbook search: {query[:50]}", prefix="🦞")
        return self._request("GET", "/search", params=params)

    def get_submolts(self) -> Dict[str, Any]:
        """
        List all available submolts (communities).

        Returns:
            API response with submolts list
        """
        log_info("Moltbook submolts list", prefix="🦞")
        return self._request("GET", "/submolts")

    def get_profile(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get an agent's profile.

        Args:
            agent_name: Agent name to look up, or None for own profile

        Returns:
            API response with profile data
        """
        if agent_name:
            log_info(f"Moltbook profile: {agent_name}", prefix="🦞")
            return self._request("GET", "/agents/profile", params={"name": agent_name})
        else:
            log_info("Moltbook profile: self", prefix="🦞")
            return self._request("GET", "/agents/me")

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    def create_post(
        self,
        title: str,
        submolt: str,
        content: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new post (text or link).

        Args:
            title: Post title
            submolt: Target submolt name
            content: Text body (for text posts)
            url: Link URL (for link posts)

        Returns:
            API response with created post data
        """
        # Check post-specific rate limit
        rate_error = self._check_rate_limit("posts")
        if rate_error:
            return rate_error

        # Strip "m/" prefix if included (e.g. "m/sandbox" -> "sandbox")
        if submolt.startswith("m/"):
            submolt = submolt[2:]

        body: Dict[str, Any] = {"title": title, "submolt": submolt}
        if content:
            body["content"] = content
        if url:
            body["url"] = url

        log_info(f"Moltbook create post: {title[:50]} in m/{submolt}", prefix="🦞")
        return self._request("POST", "/posts", json_body=body, extra_tiers=["posts"])

    def create_comment(
        self,
        post_id: str,
        content: str,
        parent_comment_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Comment on a post (supports replies to other comments).

        Args:
            post_id: The post to comment on
            content: Comment text
            parent_comment_id: Optional parent comment ID for replies

        Returns:
            API response with created comment data
        """
        body: Dict[str, Any] = {"content": content}
        if parent_comment_id:
            body["parent_id"] = parent_comment_id

        log_info(f"Moltbook comment on {post_id}", prefix="🦞")
        return self._request(
            "POST",
            f"/posts/{post_id}/comments",
            json_body=body,
            extra_tiers=["comments"],
        )

    def vote(self, post_id: str, direction: str = "upvote") -> Dict[str, Any]:
        """
        Vote on a post.

        Args:
            post_id: The post to vote on
            direction: "upvote" or "downvote"

        Returns:
            API response confirming the vote
        """
        if direction not in ("upvote", "downvote"):
            return {"error": True, "message": f"Invalid vote direction: {direction}. Use 'upvote' or 'downvote'."}

        log_info(f"Moltbook {direction} on {post_id}", prefix="🦞")
        return self._request("POST", f"/posts/{post_id}/{direction}", json_body={})


# =============================================================================
# SINGLETON
# =============================================================================

_client: Optional[MoltbookClient] = None


def get_moltbook_client() -> MoltbookClient:
    """
    Get the global MoltbookClient instance.

    Lazily initializes from config. Raises RuntimeError if Moltbook
    is not properly configured.

    Returns:
        The global MoltbookClient instance
    """
    global _client
    if _client is None:
        import config

        if not config.MOLTBOOK_ENABLED:
            raise RuntimeError("Moltbook is not enabled (set MOLTBOOK_ENABLED=true)")
        if not config.MOLTBOOK_API_KEY:
            raise RuntimeError("Moltbook API key not set (set MOLTBOOK_API_KEY in .env)")

        _client = MoltbookClient(
            api_key=config.MOLTBOOK_API_KEY,
            base_url=config.MOLTBOOK_API_BASE_URL,
            user_agent=config.MOLTBOOK_USER_AGENT,
            requests_per_min=config.MOLTBOOK_RATE_LIMIT_REQUESTS_PER_MIN,
            posts_per_30min=config.MOLTBOOK_RATE_LIMIT_POSTS_PER_30MIN,
            comments_per_hour=config.MOLTBOOK_RATE_LIMIT_COMMENTS_PER_HOUR,
        )
        log_info("Moltbook client initialized", prefix="🦞")

    return _client
