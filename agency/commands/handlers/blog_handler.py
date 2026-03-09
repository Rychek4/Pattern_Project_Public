"""
Pattern Project - Blog Command Handlers
Handles blog post CRUD via native tool calls.
"""

import json
from typing import List

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class PublishBlogPostHandler(CommandHandler):
    """Create and immediately publish a blog post."""

    @property
    def command_name(self) -> str:
        return "PUBLISH_BLOG_POST"

    @property
    def pattern(self) -> str:
        return r""

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        from blog.blog_manager import create_post

        params = context.get("blog_params", {})
        title = params.get("title", "").strip()
        content = params.get("content", "").strip()
        tags = params.get("tags", [])
        summary = params.get("summary", "")

        if not title:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Title is required", None, None),
            )
        if not content:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Content is required", None, None),
            )

        result = create_post(
            title=title, content=content, author="Isaac",
            tags=tags, summary=summary, status="published",
        )

        if "error" in result:
            return CommandResult(
                command_name=self.command_name, query=title,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.SYSTEM_ERROR, result["error"], None, None),
            )

        return CommandResult(
            command_name=self.command_name, query=title,
            data=result, needs_continuation=True,
            display_text=f"Blog post published: {title}",
        )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return result.get_error_message()
        d = result.data
        return f"Published: \"{result.query}\" (slug: {d['slug']})"


class SaveBlogDraftHandler(CommandHandler):
    """Save a blog post as a draft."""

    @property
    def command_name(self) -> str:
        return "SAVE_BLOG_DRAFT"

    @property
    def pattern(self) -> str:
        return r""

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        from blog.blog_manager import create_post

        params = context.get("blog_params", {})
        title = params.get("title", "").strip()
        content = params.get("content", "").strip()
        tags = params.get("tags", [])
        summary = params.get("summary", "")

        if not title:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Title is required", None, None),
            )
        if not content:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Content is required", None, None),
            )

        result = create_post(
            title=title, content=content, author="Isaac",
            tags=tags, summary=summary, status="draft",
        )

        if "error" in result:
            return CommandResult(
                command_name=self.command_name, query=title,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.SYSTEM_ERROR, result["error"], None, None),
            )

        return CommandResult(
            command_name=self.command_name, query=title,
            data=result, needs_continuation=True,
            display_text=f"Blog draft saved: {title}",
        )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return result.get_error_message()
        d = result.data
        return f"Draft saved: \"{result.query}\" (slug: {d['slug']})"


class EditBlogPostHandler(CommandHandler):
    """Edit an existing blog post."""

    @property
    def command_name(self) -> str:
        return "EDIT_BLOG_POST"

    @property
    def pattern(self) -> str:
        return r""

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        from blog.blog_manager import edit_post

        params = context.get("blog_params", {})
        slug = params.get("slug", "").strip()

        if not slug:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Slug is required", None, None),
            )

        result = edit_post(
            slug=slug,
            content=params.get("content"),
            title=params.get("title"),
            tags=params.get("tags"),
            summary=params.get("summary"),
            status=params.get("status"),
        )

        if "error" in result:
            return CommandResult(
                command_name=self.command_name, query=slug,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.SYSTEM_ERROR, result["error"], None, None),
            )

        return CommandResult(
            command_name=self.command_name, query=slug,
            data=result, needs_continuation=True,
            display_text=f"Blog post edited: {slug}",
        )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return result.get_error_message()
        d = result.data
        return f"Edited: {d['slug']} (status: {d['status']})"


class ListBlogPostsHandler(CommandHandler):
    """List blog posts."""

    @property
    def command_name(self) -> str:
        return "LIST_BLOG_POSTS"

    @property
    def pattern(self) -> str:
        return r""

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        from blog.blog_manager import list_posts

        params = context.get("blog_params", {})
        status = params.get("status")

        posts = list_posts(status=status)

        return CommandResult(
            command_name=self.command_name, query=query,
            data=posts, needs_continuation=True,
            display_text=f"Found {len(posts)} blog post(s)",
        )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return result.get_error_message()
        posts = result.data
        if not posts:
            return "No blog posts found."
        lines = []
        for p in posts:
            tags_str = ", ".join(p["tags"]) if p["tags"] else ""
            status_mark = "[published]" if p["status"] == "published" else "[draft]"
            line = f"  {status_mark} {p['date']} — {p['title']} (slug: {p['slug']})"
            if tags_str:
                line += f" [{tags_str}]"
            lines.append(line)
        return f"{len(posts)} post(s):\n" + "\n".join(lines)


class UnpublishBlogPostHandler(CommandHandler):
    """Revert a published post to draft."""

    @property
    def command_name(self) -> str:
        return "UNPUBLISH_BLOG_POST"

    @property
    def pattern(self) -> str:
        return r""

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        from blog.blog_manager import unpublish_post

        params = context.get("blog_params", {})
        slug = params.get("slug", "").strip()

        if not slug:
            return CommandResult(
                command_name=self.command_name, query=query,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.FORMAT_ERROR, "Slug is required", None, None),
            )

        result = unpublish_post(slug)

        if "error" in result:
            return CommandResult(
                command_name=self.command_name, query=slug,
                data=None, needs_continuation=True,
                error=ToolError(ToolErrorType.SYSTEM_ERROR, result["error"], None, None),
            )

        return CommandResult(
            command_name=self.command_name, query=slug,
            data=result, needs_continuation=True,
            display_text=f"Blog post unpublished: {slug}",
        )

    def get_instructions(self) -> str:
        return ""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return result.get_error_message()
        d = result.data
        return f"Unpublished: {d['slug']} (now draft)"
