"""Reddit integration tool definitions.

Reddit integration via PRAW. These tools let you browse, post, comment,
vote, and search on Reddit using a personal account.
"""

from typing import Any, Dict

REDDIT_FEED_TOOL: Dict[str, Any] = {
    "name": "reddit_feed",
    "description": """Browse a subreddit's posts.

Get posts sorted by hot, new, top, or rising from any subreddit.

Use when:
- Checking what's being discussed in a specific subreddit
- Browsing for interesting content related to a topic
- Catching up on a community's latest posts

Guidelines:
- Rate limit: 30 requests/minute total across all Reddit tools
- Be respectful of communities - read before posting
- Default subreddit is "all" if none specified""",
    "input_schema": {
        "type": "object",
        "properties": {
            "subreddit": {
                "type": "string",
                "description": "Subreddit name without r/ prefix (default: 'all')"
            },
            "sort": {
                "type": "string",
                "enum": ["hot", "new", "top", "rising"],
                "description": "Sort order for posts (default: hot)"
            },
            "time_filter": {
                "type": "string",
                "enum": ["hour", "day", "week", "month", "year", "all"],
                "description": "Time filter (only applies to 'top' sort, default: day)"
            },
            "limit": {
                "type": "integer",
                "description": "Number of posts to return (max 25, default: 10)"
            }
        },
        "required": []
    }
}

REDDIT_POST_TOOL: Dict[str, Any] = {
    "name": "reddit_post",
    "description": """Get a single Reddit post by ID, including its comments.

Use when:
- You found an interesting post and want to read the full discussion
- Checking comments on a post you or the user is interested in
- Reading context before deciding whether to engage

The post ID is the short alphanumeric string from the URL or feed results.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "post_id": {
                "type": "string",
                "description": "The Reddit post ID (e.g., '1abc23d')"
            },
            "comment_sort": {
                "type": "string",
                "enum": ["best", "top", "new", "controversial"],
                "description": "How to sort comments (default: best)"
            },
            "comment_limit": {
                "type": "integer",
                "description": "Max top-level comments to return (default: 20)"
            }
        },
        "required": ["post_id"]
    }
}

REDDIT_CREATE_POST_TOOL: Dict[str, Any] = {
    "name": "reddit_create_post",
    "description": """Create a new post on Reddit.

Posts can be text posts (with content) or link posts (with url).
Choose an appropriate subreddit for the topic.

Guidelines:
- Rate limit: 1 post per 30 minutes
- Read the subreddit's rules before posting
- Write thoughtful, substantive posts
- Provide either content (text post) or url (link post), not both""",
    "input_schema": {
        "type": "object",
        "properties": {
            "subreddit": {
                "type": "string",
                "description": "Target subreddit name (without r/ prefix)"
            },
            "title": {
                "type": "string",
                "description": "Post title (clear, descriptive)"
            },
            "content": {
                "type": "string",
                "description": "Text body for a self/text post (markdown supported)"
            },
            "url": {
                "type": "string",
                "description": "URL for a link post (omit content if using url)"
            }
        },
        "required": ["subreddit", "title"]
    }
}

REDDIT_COMMENT_TOOL: Dict[str, Any] = {
    "name": "reddit_comment",
    "description": """Reply to a Reddit post or comment.

Use when:
- You have something meaningful to add to a discussion
- Responding to a question or point in a thread
- Engaging with content the user is interested in

Guidelines:
- Rate limit: 10 comments per hour
- Be substantive and respectful
- Use the thing_id from the post or comment you're replying to
- thing_id can be a post ID, comment ID, or full name (t3_xxx / t1_xxx)""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thing_id": {
                "type": "string",
                "description": "ID of the post or comment to reply to (e.g., 'abc123' or 't3_abc123' or 't1_def456')"
            },
            "content": {
                "type": "string",
                "description": "Comment text (markdown supported)"
            }
        },
        "required": ["thing_id", "content"]
    }
}

REDDIT_VOTE_TOOL: Dict[str, Any] = {
    "name": "reddit_vote",
    "description": """Upvote, downvote, or clear vote on a Reddit post or comment.

Use to signal quality or agreement on posts and comments.

Guidelines:
- Rate limit: 30 votes per hour
- 'clear' removes a previous vote""",
    "input_schema": {
        "type": "object",
        "properties": {
            "thing_id": {
                "type": "string",
                "description": "ID of the post or comment to vote on"
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down", "clear"],
                "description": "Vote direction"
            }
        },
        "required": ["thing_id", "direction"]
    }
}

REDDIT_SEARCH_TOOL: Dict[str, Any] = {
    "name": "reddit_search",
    "description": """Search Reddit for posts matching a query.

Search can be scoped to a specific subreddit or across all of Reddit.

Use when:
- Looking for discussions on a specific topic
- Finding relevant posts in a subreddit
- Researching what people are saying about something""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query"
            },
            "subreddit": {
                "type": "string",
                "description": "Optional subreddit to scope search to (omit for all of Reddit)"
            },
            "sort": {
                "type": "string",
                "enum": ["relevance", "hot", "top", "new", "comments"],
                "description": "Sort order for results (default: relevance)"
            },
            "time_filter": {
                "type": "string",
                "enum": ["hour", "day", "week", "month", "year", "all"],
                "description": "Time filter for results (default: all)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (max 25, default: 10)"
            }
        },
        "required": ["query"]
    }
}

REDDIT_SUBREDDITS_TOOL: Dict[str, Any] = {
    "name": "reddit_subreddits",
    "description": """Search for subreddits or list subscribed ones.

With a query, searches for subreddits matching the term.
Without a query, lists subreddits the account is subscribed to.

Use when:
- Discovering relevant communities before posting or browsing
- Checking what subreddits are available for a topic""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for subreddits (omit to list subscribed)"
            },
            "limit": {
                "type": "integer",
                "description": "Max results to return (max 25, default: 10)"
            }
        },
        "required": []
    }
}

REDDIT_PROFILE_TOOL: Dict[str, Any] = {
    "name": "reddit_profile",
    "description": """Get a Reddit user's profile.

With no arguments, returns the authenticated account's profile.
Provide a username to look up another user's public profile.

Use when:
- Checking account karma and activity
- Looking up information about a user before engaging""",
    "input_schema": {
        "type": "object",
        "properties": {
            "username": {
                "type": "string",
                "description": "Reddit username to look up (omit for own profile)"
            }
        },
        "required": []
    }
}
