"""
Pattern Project - Reddit API Client
Integration with Reddit via PRAW (Python Reddit API Wrapper).

Allows Pattern to browse, post, comment, vote, and search on Reddit
using a personal account with OAuth2 "script" app credentials.

Authentication: OAuth2 via PRAW (client_id + client_secret + username + password)
User-Agent: Required by Reddit API; descriptive format prevents throttling.

See docs/reddit_setup.md for account setup instructions.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from threading import Lock

from core.logger import log_info, log_warning, log_error


class RedditRateLimiter:
    """
    Four-tier rate limiter for Reddit API constraints.

    Tiers:
      - requests:  30 per minute (rolling 60s window) — Reddit allows 60
      - posts:     1 per 30 minutes (rolling 1800s window)
      - comments:  10 per hour (rolling 3600s window)
      - votes:     30 per hour (rolling 3600s window)
    """

    def __init__(
        self,
        requests_per_min: int = 30,
        posts_per_30min: int = 1,
        comments_per_hour: int = 10,
        votes_per_hour: int = 30,
    ):
        self._limits = {
            "requests": (requests_per_min, 60),
            "posts": (posts_per_30min, 1800),
            "comments": (comments_per_hour, 3600),
            "votes": (votes_per_hour, 3600),
        }
        self._timestamps: Dict[str, List[datetime]] = {
            "requests": [],
            "posts": [],
            "comments": [],
            "votes": [],
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


class RedditClient:
    """
    PRAW-based client for the Reddit API.

    All public methods return a dict with either the serialized data
    or an error structure: {"error": True, "message": "..."}.

    PRAW handles OAuth2 token refresh and its own rate limiting internally.
    We layer our own RedditRateLimiter on top for conservative enforcement.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        username: str,
        password: str,
        user_agent: str = "python:pattern-agent:v1.0 (by /u/pattern-agent)",
        requests_per_min: int = 30,
        posts_per_30min: int = 1,
        comments_per_hour: int = 10,
        votes_per_hour: int = 30,
    ):
        try:
            import praw
        except ImportError:
            raise RuntimeError(
                "PRAW not installed. Run: pip install praw"
            )

        self._reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            username=username,
            password=password,
            user_agent=user_agent,
        )
        self._rate_limiter = RedditRateLimiter(
            requests_per_min=requests_per_min,
            posts_per_30min=posts_per_30min,
            comments_per_hour=comments_per_hour,
            votes_per_hour=votes_per_hour,
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

    def _serialize_submission(self, submission) -> Dict[str, Any]:
        """Convert a PRAW Submission object to a plain dict."""
        return {
            "id": submission.id,
            "title": submission.title,
            "author": str(submission.author) if submission.author else "[deleted]",
            "subreddit": str(submission.subreddit),
            "score": submission.score,
            "upvote_ratio": submission.upvote_ratio,
            "num_comments": submission.num_comments,
            "created_utc": datetime.utcfromtimestamp(submission.created_utc).isoformat(),
            "url": submission.url,
            "selftext": submission.selftext[:2000] if submission.selftext else "",
            "permalink": f"https://reddit.com{submission.permalink}",
            "is_self": submission.is_self,
            "link_flair_text": submission.link_flair_text,
        }

    def _serialize_comment(self, comment, depth: int = 0) -> Dict[str, Any]:
        """Convert a PRAW Comment object to a plain dict."""
        from praw.models import MoreComments
        if isinstance(comment, MoreComments):
            return {
                "type": "more_comments",
                "count": comment.count,
            }

        return {
            "id": comment.id,
            "author": str(comment.author) if comment.author else "[deleted]",
            "body": comment.body[:2000] if comment.body else "",
            "score": comment.score,
            "created_utc": datetime.utcfromtimestamp(comment.created_utc).isoformat(),
            "depth": depth,
            "parent_id": comment.parent_id,
            "is_submitter": comment.is_submitter,
        }

    def _serialize_subreddit(self, subreddit) -> Dict[str, Any]:
        """Convert a PRAW Subreddit object to a plain dict."""
        return {
            "name": subreddit.display_name,
            "title": subreddit.title,
            "description": (subreddit.public_description or "")[:500],
            "subscribers": subreddit.subscribers,
            "created_utc": datetime.utcfromtimestamp(subreddit.created_utc).isoformat(),
            "over18": subreddit.over18,
        }

    def _serialize_redditor(self, redditor) -> Dict[str, Any]:
        """Convert a PRAW Redditor object to a plain dict."""
        return {
            "name": redditor.name,
            "link_karma": redditor.link_karma,
            "comment_karma": redditor.comment_karma,
            "created_utc": datetime.utcfromtimestamp(redditor.created_utc).isoformat(),
            "is_gold": getattr(redditor, "is_gold", False),
            "has_verified_email": getattr(redditor, "has_verified_email", False),
        }

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    def get_feed(
        self,
        subreddit: str = "all",
        sort: str = "hot",
        time_filter: str = "day",
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Get posts from a subreddit.

        Args:
            subreddit: Subreddit name (default: "all")
            sort: Sort order - "hot", "new", "top", "rising"
            time_filter: Time filter for "top" - "hour", "day", "week", "month", "year", "all"
            limit: Number of posts to return (max 25)

        Returns:
            Dict with posts list or error
        """
        rate_error = self._check_rate_limit("requests")
        if rate_error:
            return rate_error

        limit = min(limit, 25)

        try:
            sub = self._reddit.subreddit(subreddit)

            if sort == "hot":
                posts = sub.hot(limit=limit)
            elif sort == "new":
                posts = sub.new(limit=limit)
            elif sort == "top":
                posts = sub.top(time_filter=time_filter, limit=limit)
            elif sort == "rising":
                posts = sub.rising(limit=limit)
            else:
                return {"error": True, "message": f"Invalid sort: {sort}. Use hot, new, top, or rising."}

            self._record_rate_limit("requests")

            result = [self._serialize_submission(p) for p in posts]
            log_info(f"Reddit feed: r/{subreddit} sort={sort}, {len(result)} posts", prefix="📡")
            return {"posts": result, "subreddit": subreddit, "sort": sort}

        except Exception as e:
            log_error(f"Reddit feed error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def get_post(
        self,
        post_id: str,
        comment_sort: str = "best",
        comment_limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Get a single post with its comment tree.

        Args:
            post_id: Reddit post ID (e.g., "1abc23d")
            comment_sort: Comment sort - "best", "top", "new", "controversial"
            comment_limit: Max top-level comments to return

        Returns:
            Dict with post data and comments or error
        """
        rate_error = self._check_rate_limit("requests")
        if rate_error:
            return rate_error

        try:
            submission = self._reddit.submission(id=post_id)
            submission.comment_sort = comment_sort
            submission.comment_limit = comment_limit

            # Replace MoreComments with a limited expansion
            submission.comments.replace_more(limit=0)

            comments = []
            for comment in submission.comments[:comment_limit]:
                comments.append(self._serialize_comment(comment, depth=0))
                # Include first level of replies
                if hasattr(comment, "replies"):
                    for reply in list(comment.replies)[:5]:
                        comments.append(self._serialize_comment(reply, depth=1))

            self._record_rate_limit("requests")

            post_data = self._serialize_submission(submission)
            post_data["comments"] = comments

            log_info(f"Reddit post: {post_id} ({len(comments)} comments)", prefix="📡")
            return post_data

        except Exception as e:
            log_error(f"Reddit post error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def search(
        self,
        query: str,
        subreddit: Optional[str] = None,
        sort: str = "relevance",
        time_filter: str = "all",
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Search Reddit posts.

        Args:
            query: Search query string
            subreddit: Optional subreddit to scope search to
            sort: Sort - "relevance", "hot", "top", "new", "comments"
            time_filter: Time filter - "hour", "day", "week", "month", "year", "all"
            limit: Max results (max 25)

        Returns:
            Dict with search results or error
        """
        rate_error = self._check_rate_limit("requests")
        if rate_error:
            return rate_error

        limit = min(limit, 25)

        try:
            sub_name = subreddit or "all"
            sub = self._reddit.subreddit(sub_name)
            results = sub.search(query, sort=sort, time_filter=time_filter, limit=limit)

            self._record_rate_limit("requests")

            posts = [self._serialize_submission(p) for p in results]
            log_info(f"Reddit search: '{query[:50]}' in r/{sub_name}, {len(posts)} results", prefix="📡")
            return {"posts": posts, "query": query, "subreddit": sub_name}

        except Exception as e:
            log_error(f"Reddit search error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def get_subreddits(
        self,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        Search for subreddits or list subscribed ones.

        Args:
            query: Search query (omit to list subscribed subreddits)
            limit: Max results (max 25)

        Returns:
            Dict with subreddits list or error
        """
        rate_error = self._check_rate_limit("requests")
        if rate_error:
            return rate_error

        limit = min(limit, 25)

        try:
            if query:
                subreddits = self._reddit.subreddits.search(query, limit=limit)
                mode = "search"
            else:
                subreddits = self._reddit.user.subreddits(limit=limit)
                mode = "subscribed"

            self._record_rate_limit("requests")

            result = [self._serialize_subreddit(s) for s in subreddits]
            log_info(f"Reddit subreddits ({mode}): {len(result)} results", prefix="📡")
            return {"subreddits": result, "mode": mode, "query": query}

        except Exception as e:
            log_error(f"Reddit subreddits error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def get_profile(
        self,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get a Reddit user's profile.

        Args:
            username: Username to look up (omit for own profile)

        Returns:
            Dict with profile data or error
        """
        rate_error = self._check_rate_limit("requests")
        if rate_error:
            return rate_error

        try:
            if username:
                redditor = self._reddit.redditor(username)
                # Force a fetch to validate the user exists
                _ = redditor.id
            else:
                redditor = self._reddit.user.me()

            self._record_rate_limit("requests")

            profile = self._serialize_redditor(redditor)
            log_info(f"Reddit profile: u/{profile['name']}", prefix="📡")
            return profile

        except Exception as e:
            log_error(f"Reddit profile error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    # =========================================================================
    # WRITE OPERATIONS
    # =========================================================================

    def create_post(
        self,
        subreddit: str,
        title: str,
        content: Optional[str] = None,
        url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new post (text or link).

        Args:
            subreddit: Target subreddit name
            title: Post title
            content: Text body (for self/text posts)
            url: Link URL (for link posts; mutually exclusive with content)

        Returns:
            Dict with created post data or error
        """
        rate_error = self._check_rate_limit("requests", "posts")
        if rate_error:
            return rate_error

        if not subreddit or not title:
            return {"error": True, "message": "Both 'subreddit' and 'title' are required."}

        if content and url:
            return {"error": True, "message": "Provide either 'content' (text post) or 'url' (link post), not both."}

        try:
            sub = self._reddit.subreddit(subreddit)

            if url:
                submission = sub.submit(title=title, url=url)
            else:
                submission = sub.submit(title=title, selftext=content or "")

            self._record_rate_limit("requests", "posts")

            result = self._serialize_submission(submission)
            log_info(f"Reddit post created: '{title[:50]}' in r/{subreddit}", prefix="📡")
            return result

        except Exception as e:
            log_error(f"Reddit create post error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def create_comment(
        self,
        thing_id: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Reply to a post or comment.

        Args:
            thing_id: The fullname (t3_xxx for post, t1_xxx for comment)
                      or just the ID (we'll try to resolve it)
            content: Comment text (markdown supported)

        Returns:
            Dict with created comment data or error
        """
        rate_error = self._check_rate_limit("requests", "comments")
        if rate_error:
            return rate_error

        if not content:
            return {"error": True, "message": "Comment content is required."}

        try:
            # Determine if this is a post or comment
            if thing_id.startswith("t1_"):
                # Replying to a comment
                parent = self._reddit.comment(thing_id[3:])
            elif thing_id.startswith("t3_"):
                # Replying to a post
                parent = self._reddit.submission(thing_id[3:])
            else:
                # No prefix - try as submission first, fall back to comment
                try:
                    parent = self._reddit.submission(id=thing_id)
                    _ = parent.title  # Force fetch to validate
                except Exception:
                    parent = self._reddit.comment(thing_id)

            comment = parent.reply(content)

            self._record_rate_limit("requests", "comments")

            result = self._serialize_comment(comment)
            log_info(f"Reddit comment on {thing_id}", prefix="📡")
            return result

        except Exception as e:
            log_error(f"Reddit comment error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}

    def vote(
        self,
        thing_id: str,
        direction: str = "up",
    ) -> Dict[str, Any]:
        """
        Vote on a post or comment.

        Args:
            thing_id: The fullname or ID of the post/comment
            direction: "up", "down", or "clear"

        Returns:
            Dict confirming the vote or error
        """
        rate_error = self._check_rate_limit("requests", "votes")
        if rate_error:
            return rate_error

        if direction not in ("up", "down", "clear"):
            return {"error": True, "message": f"Invalid direction: {direction}. Use 'up', 'down', or 'clear'."}

        try:
            # Resolve the thing
            if thing_id.startswith("t1_"):
                thing = self._reddit.comment(thing_id[3:])
            elif thing_id.startswith("t3_"):
                thing = self._reddit.submission(thing_id[3:])
            else:
                # Try as submission first
                try:
                    thing = self._reddit.submission(id=thing_id)
                    _ = thing.title
                except Exception:
                    thing = self._reddit.comment(thing_id)

            if direction == "up":
                thing.upvote()
            elif direction == "down":
                thing.downvote()
            else:
                thing.clear_vote()

            self._record_rate_limit("requests", "votes")

            log_info(f"Reddit vote {direction} on {thing_id}", prefix="📡")
            return {"success": True, "thing_id": thing_id, "direction": direction}

        except Exception as e:
            log_error(f"Reddit vote error: {e}")
            return {"error": True, "message": f"Reddit API error: {str(e)}"}


# =============================================================================
# SINGLETON
# =============================================================================

_client: Optional[RedditClient] = None


def get_reddit_client() -> RedditClient:
    """
    Get the global RedditClient instance.

    Lazily initializes from config. Raises RuntimeError if Reddit
    is not properly configured.

    Returns:
        The global RedditClient instance
    """
    global _client
    if _client is None:
        import config

        if not config.REDDIT_ENABLED:
            raise RuntimeError("Reddit is not enabled (set REDDIT_ENABLED=true)")
        if not config.REDDIT_CLIENT_ID:
            raise RuntimeError("Reddit client ID not set (set REDDIT_CLIENT_ID in .env)")
        if not config.REDDIT_CLIENT_SECRET:
            raise RuntimeError("Reddit client secret not set (set REDDIT_CLIENT_SECRET in .env)")
        if not config.REDDIT_USERNAME:
            raise RuntimeError("Reddit username not set (set REDDIT_USERNAME in .env)")
        if not config.REDDIT_PASSWORD:
            raise RuntimeError("Reddit password not set (set REDDIT_PASSWORD in .env)")

        _client = RedditClient(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            username=config.REDDIT_USERNAME,
            password=config.REDDIT_PASSWORD,
            user_agent=config.REDDIT_USER_AGENT,
            requests_per_min=config.REDDIT_RATE_LIMIT_REQUESTS_PER_MIN,
            posts_per_30min=config.REDDIT_RATE_LIMIT_POSTS_PER_30MIN,
            comments_per_hour=config.REDDIT_RATE_LIMIT_COMMENTS_PER_HOUR,
            votes_per_hour=config.REDDIT_RATE_LIMIT_VOTES_PER_HOUR,
        )
        log_info("Reddit client initialized", prefix="📡")

    return _client
