"""Blog publishing tool definitions."""

from typing import Any, Dict

PUBLISH_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "publish_blog_post",
    "description": """Create and publish a blog post to the public blog.

This creates a Markdown post, sets its status to published, and rebuilds
the static site so it's immediately live.

Write naturally — the content is rendered as Markdown (headings, lists,
code blocks, links, emphasis all work). Keep posts substantive and worth
reading. This is your public voice.

The post will be attributed to you (Isaac) by default.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The post title"
            },
            "content": {
                "type": "string",
                "description": "The post body in Markdown"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization (e.g. ['philosophy', 'ai'])"
            },
            "summary": {
                "type": "string",
                "description": "A one-sentence summary shown on the index page and in the RSS feed"
            },
            "in_response_to": {
                "type": "string",
                "description": "Optional slug of another post this is responding to (creates a 'see also' link between the two posts)"
            }
        },
        "required": ["title", "content"]
    }
}

SAVE_BLOG_DRAFT_TOOL: Dict[str, Any] = {
    "name": "save_blog_draft",
    "description": """Save a blog post as a draft (not published, not visible on the site).

Use this when you want to write something but aren't ready to publish it yet.
Drafts can be listed, edited, and published later.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The post title"
            },
            "content": {
                "type": "string",
                "description": "The post body in Markdown"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional tags for categorization"
            },
            "summary": {
                "type": "string",
                "description": "A one-sentence summary"
            },
            "in_response_to": {
                "type": "string",
                "description": "Optional slug of another post this is responding to"
            }
        },
        "required": ["title", "content"]
    }
}

EDIT_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "edit_blog_post",
    "description": """Edit an existing blog post (draft or published).

You can update the title, content, tags, summary, or status. If the post
is published, changes go live immediately after the site rebuilds.

Use list_blog_posts to find the slug of the post you want to edit.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The post slug (from list_blog_posts)"
            },
            "content": {
                "type": "string",
                "description": "New post body in Markdown (if changing)"
            },
            "title": {
                "type": "string",
                "description": "New post title (if changing)"
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "New tags (if changing)"
            },
            "summary": {
                "type": "string",
                "description": "New summary (if changing)"
            },
            "status": {
                "type": "string",
                "enum": ["draft", "published"],
                "description": "New status (if changing)"
            }
        },
        "required": ["slug"]
    }
}

LIST_BLOG_POSTS_TOOL: Dict[str, Any] = {
    "name": "list_blog_posts",
    "description": """List blog posts with their metadata (title, slug, date, status, tags).

Returns all posts by default, or filter by status. Posts are sorted newest first.
Use the slug from results to edit or unpublish a specific post.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["draft", "published"],
                "description": "Filter by status. Omit to list all posts."
            }
        },
        "required": []
    }
}

UNPUBLISH_BLOG_POST_TOOL: Dict[str, Any] = {
    "name": "unpublish_blog_post",
    "description": """Revert a published post back to draft status (removes it from the public site).

Use this if you want to take down a post without deleting it.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "The post slug (from list_blog_posts)"
            }
        },
        "required": ["slug"]
    }
}
