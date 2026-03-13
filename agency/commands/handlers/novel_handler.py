"""
Pattern Project - Novel Reading Tool Handlers
Handles open_book, read_next_chapter, complete_reading, reading_progress,
abandon_reading, and resume_reading.

Extracted from agency/tools/executor.py for modularity.
"""

from typing import Any, Dict

import config


def exec_open_book(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Open a novel for reading."""
    from pathlib import Path
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import open_book
    from agency.commands.handlers.file_handler import _sanitize_filename, FileSecurityError

    tool_name = "open_book"
    filename = input.get("filename", "")
    if not filename:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="No filename provided",
            is_error=True
        )

    try:
        filename = _sanitize_filename(filename)
    except FileSecurityError as e:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Invalid filename: {e}",
            is_error=True
        )

    filepath = Path(config.NOVEL_BOOKS_DIR) / filename

    success, message, summary = open_book(filepath)

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=message,
            is_error=True
        )

    # Format the structure summary for the AI
    result_parts = [message, ""]
    if summary:
        result_parts.append(f"Title: {summary.get('title', 'Unknown')}")
        result_parts.append(f"Detection: {summary.get('detection_method', 'unknown')}")
        result_parts.append(f"Total words: {summary.get('total_word_count', 0):,}")
        result_parts.append(f"Estimated tokens: {summary.get('total_token_estimate', 0):,}")
        result_parts.append(f"Chapters: {summary.get('total_chapters', 0)}")
        result_parts.append(f"Arcs: {summary.get('total_arcs', 0)}")

        if summary.get('has_prologue'):
            result_parts.append("Has prologue: yes")

        if summary.get('arcs'):
            result_parts.append("\nStructure:")
            for arc in summary['arcs']:
                ch_range = arc.get('chapters', [])
                ch_str = f"chapters {ch_range[0]}-{ch_range[-1]}" if ch_range else "no chapters"
                result_parts.append(f"  {arc['title']} ({ch_str})")

        result_parts.append("\nUse read_next_chapter to begin reading.")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content="\n".join(result_parts)
    )


def exec_read_next_chapter(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Read the next chapter of the current book."""
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import read_next_chapter

    tool_name = "read_next_chapter"

    success, message, result_data = read_next_chapter()

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=message,
            is_error=True
        )

    # Format result for the AI
    parts = [message, ""]
    if result_data:
        parts.append(f"Words: {result_data.get('word_count', 0):,}")
        parts.append(f"Arc: {result_data.get('arc', 'N/A')}")
        parts.append(f"Extraction: {'success' if result_data.get('extraction_success') else 'failed'}")
        parts.append(f"Observations extracted: {result_data.get('observations_extracted', 0)}")
        parts.append(f"Memories stored: {result_data.get('memories_stored', 0)}")

        categories = result_data.get('categories', [])
        if categories:
            parts.append(f"Categories found: {', '.join(categories)}")

        arc_reflection = result_data.get('arc_reflection')
        if arc_reflection:
            parts.append(f"\nArc boundary reflection (Arc {arc_reflection['arc_number']}: {arc_reflection['arc_title']}):")
            parts.append(f"  Reflective observations: {arc_reflection['observations']}")
            parts.append(f"  Memories stored: {arc_reflection['memories_stored']}")

        remaining = result_data.get('chapters_remaining', 0)
        if remaining > 0:
            parts.append(f"\nChapters remaining: {remaining}")
        else:
            parts.append("\nAll chapters read. Use complete_reading for final synthesis.")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content="\n".join(parts)
    )


def exec_complete_reading(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Complete the reading session with final synthesis."""
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import complete_reading

    tool_name = "complete_reading"

    success, message, result_data = complete_reading()

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=message,
            is_error=True
        )

    parts = [message, ""]
    if result_data:
        parts.append(f"Total chapters read: {result_data.get('total_chapters_read', 0)}")
        parts.append(f"Total observations accumulated: {result_data.get('total_observations', 0)}")
        parts.append(f"Synthesis observations: {result_data.get('synthesis_observations', 0)}")
        parts.append(f"Synthesis memories stored: {result_data.get('synthesis_memories_stored', 0)}")

        discussion_points = result_data.get('discussion_points', [])
        if discussion_points:
            parts.append("\nDiscussion points for the reader:")
            for i, point in enumerate(discussion_points, 1):
                parts.append(f"  {i}. {point}")

        parts.append("\nYour literary memories are now part of your memory system.")
        parts.append("They will surface naturally in relevant conversations.")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content="\n".join(parts)
    )


def exec_reading_progress(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Get current reading progress."""
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import get_reading_progress

    tool_name = "reading_progress"

    success, message, result_data = get_reading_progress()

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=message,
            is_error=True
        )

    parts = [message]
    if result_data:
        status = result_data.get('status', 'none')
        if status == 'reading':
            parts.append(f"\nProgress: {result_data.get('progress_percent', 0)}%")
            parts.append(f"Chapter: {result_data.get('current_chapter', 0)}/{result_data.get('total_chapters', 0)}")
            parts.append(f"Chapters remaining: {result_data.get('chapters_remaining', 0)}")
            parts.append(f"Observations so far: {result_data.get('observations_so_far', 0)}")
            if result_data.get('total_arcs', 0) > 0:
                parts.append(f"Current arc: {result_data.get('current_arc', 0)}/{result_data.get('total_arcs', 0)}")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content="\n".join(parts)
    )


def exec_abandon_reading(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Abandon the current reading session."""
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import abandon_reading

    success, message = abandon_reading()

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name="abandon_reading",
        content=message,
        is_error=not success
    )


def exec_resume_reading(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Resume an interrupted reading session."""
    from pathlib import Path
    from agency.tools.executor import ToolResult
    from agency.novel_reading.orchestrator import resume_reading
    from agency.commands.handlers.file_handler import _sanitize_filename, FileSecurityError

    tool_name = "resume_reading"
    filename = input.get("filename", "")
    if not filename:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content="No filename provided",
            is_error=True
        )

    try:
        filename = _sanitize_filename(filename)
    except FileSecurityError as e:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=f"Invalid filename: {e}",
            is_error=True
        )

    filepath = Path(config.NOVEL_BOOKS_DIR) / filename

    success, message, result_data = resume_reading(filepath)

    if not success:
        return ToolResult(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            content=message,
            is_error=True
        )

    parts = [message, ""]
    if result_data:
        parts.append(f"Title: {result_data.get('title', 'Unknown')}")
        chapters_read = result_data.get('chapters_read', [])
        parts.append(f"Chapters already read: {len(chapters_read)}")
        parts.append(f"Chapters remaining: {result_data.get('chapters_remaining', 0)}")
        parts.append("\nUse read_next_chapter to continue reading.")

    return ToolResult(
        tool_use_id=tool_use_id,
        tool_name=tool_name,
        content="\n".join(parts)
    )
