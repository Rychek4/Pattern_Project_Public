"""
Pattern Project - File Tool Command Handlers
Handles file read/write/move/directory operations for AI-initiated file storage.

Security: All operations are sandboxed to FILE_STORAGE_DIR with strict validation.
Paths may contain forward slashes for subdirectories but each segment is validated
independently to prevent traversal attacks.
"""

import os
import re
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agency.commands.handlers.base import CommandHandler, CommandResult
from agency.commands.errors import ToolError, ToolErrorType


class FileSecurityError(Exception):
    """Raised when a file operation violates security constraints."""
    pass


def _get_storage_dir() -> Path:
    """
    Get the file storage directory, creating it if needed.

    Returns:
        Path to the sandboxed file storage directory
    """
    from config import FILE_STORAGE_DIR

    storage_dir = Path(FILE_STORAGE_DIR)
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def _sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename to prevent security issues.

    Args:
        filename: The raw filename from user/AI input

    Returns:
        Sanitized filename

    Raises:
        FileSecurityError: If filename contains dangerous patterns
    """
    # Strip whitespace
    filename = filename.strip()

    if not filename:
        raise FileSecurityError("Filename cannot be empty")

    # Check for path traversal attempts
    if ".." in filename:
        raise FileSecurityError("Path traversal detected: '..' not allowed in filename")

    # Check for path separators (both Unix and Windows)
    if "/" in filename or "\\" in filename:
        raise FileSecurityError("Path separators not allowed in filename")

    # Check for null bytes
    if "\x00" in filename:
        raise FileSecurityError("Null bytes not allowed in filename")

    # Reject hidden files (starting with .)
    if filename.startswith("."):
        raise FileSecurityError("Hidden files (starting with '.') not allowed")

    # Sanitize: only allow alphanumeric, dash, underscore, dot
    # This is a secondary defense - the above checks should catch issues first
    sanitized = re.sub(r'[^\w\-.]', '_', filename)

    return sanitized


def _validate_path_segment(segment: str) -> None:
    """
    Validate a single path segment (directory name or filename).

    Args:
        segment: A single component of a path (no slashes)

    Raises:
        FileSecurityError: If segment contains dangerous patterns
    """
    if not segment:
        raise FileSecurityError("Path segment cannot be empty")

    if segment in (".", ".."):
        raise FileSecurityError("Path traversal not allowed: '.' and '..' are forbidden")

    if segment.startswith("."):
        raise FileSecurityError(f"Hidden files/directories not allowed: '{segment}'")

    # Null byte check
    if "\x00" in segment:
        raise FileSecurityError("Null bytes not allowed in path")

    # Only allow word characters (letters, digits, underscore), dash, and dot
    if not re.match(r'^[\w\-.]+$', segment):
        raise FileSecurityError(
            f"Invalid characters in '{segment}'. "
            "Allowed: letters, numbers, dash, underscore, dot"
        )


def _resolve_safe_path(path_str: str, require_extension: bool = True) -> Path:
    """
    Resolve a relative path to a safe absolute path within the sandbox.

    Validates each segment independently and ensures the resolved path
    stays within the sandboxed storage directory. Supports subdirectories
    via forward slashes (e.g., "projects/notes.txt").

    Args:
        path_str: Relative path (e.g., "projects/notes.txt" or "projects")
        require_extension: If True, validate the final segment has an allowed extension

    Returns:
        Validated absolute Path within the sandbox

    Raises:
        FileSecurityError: If any security check fails
    """
    path_str = path_str.strip()

    if not path_str:
        raise FileSecurityError("Path cannot be empty")

    # Reject backslashes (Windows path separators)
    if "\\" in path_str:
        raise FileSecurityError("Backslash not allowed in path — use forward slash")

    # Split into segments, filtering empty ones (handles leading/trailing/double slashes)
    segments = [s for s in path_str.split("/") if s]

    if not segments:
        raise FileSecurityError("Path cannot be empty")

    # Validate each segment independently
    for segment in segments:
        _validate_path_segment(segment)

    # Validate extension on the final segment (for file operations)
    if require_extension:
        _validate_extension(segments[-1])

    # Build the absolute path
    storage_dir = _get_storage_dir()
    target_path = storage_dir
    for segment in segments:
        target_path = target_path / segment

    # Final sandbox escape check using resolved paths
    try:
        resolved = target_path.resolve()
        storage_resolved = storage_dir.resolve()

        if not str(resolved).startswith(str(storage_resolved) + os.sep) and resolved != storage_resolved:
            raise FileSecurityError("Path resolution escaped sandbox")
    except FileSecurityError:
        raise
    except Exception as e:
        raise FileSecurityError(f"Path validation failed: {str(e)}")

    return target_path


def _validate_extension(filename: str) -> None:
    """
    Validate that the file has an allowed extension.

    Args:
        filename: The filename to check

    Raises:
        FileSecurityError: If extension is not in whitelist
    """
    from config import FILE_ALLOWED_EXTENSIONS

    ext = Path(filename).suffix.lower()

    if not ext:
        raise FileSecurityError(
            f"File must have an extension. Allowed: {', '.join(sorted(FILE_ALLOWED_EXTENSIONS))}"
        )

    if ext not in FILE_ALLOWED_EXTENSIONS:
        raise FileSecurityError(
            f"Extension '{ext}' not allowed. Allowed: {', '.join(sorted(FILE_ALLOWED_EXTENSIONS))}"
        )


def _validate_content_size(content: str) -> None:
    """
    Validate that content doesn't exceed size limit.

    Args:
        content: The content to write

    Raises:
        FileSecurityError: If content exceeds size limit
    """
    from config import FILE_MAX_SIZE_BYTES

    size = len(content.encode('utf-8'))
    if size > FILE_MAX_SIZE_BYTES:
        raise FileSecurityError(
            f"Content size ({size} bytes) exceeds limit ({FILE_MAX_SIZE_BYTES} bytes)"
        )


def _get_safe_filepath(filename: str) -> Path:
    """
    Get a safe, validated filepath within the sandbox.

    Supports paths with subdirectories (e.g., "projects/notes.txt").

    Args:
        filename: The filename or relative path to resolve

    Returns:
        Validated Path object within the sandbox

    Raises:
        FileSecurityError: If any security check fails
    """
    return _resolve_safe_path(filename, require_extension=True)


def _parse_write_command(query: str) -> Tuple[str, str]:
    """
    Parse a write command query into filename and content.

    Args:
        query: The full query string (filename | content)

    Returns:
        Tuple of (filename, content)

    Raises:
        ValueError: If query format is invalid
    """
    if "|" not in query:
        raise ValueError("Write command requires format: filename | content")

    # Split on first pipe only (content may contain pipes)
    parts = query.split("|", 1)

    if len(parts) != 2:
        raise ValueError("Write command requires format: filename | content")

    filename = parts[0].strip()
    content = parts[1].strip()

    if not filename:
        raise ValueError("Filename cannot be empty")

    if not content:
        raise ValueError("Content cannot be empty")

    return filename, content


class ReadFileHandler(CommandHandler):
    """
    Handles file reading via the read_file native tool.

    Called by ToolExecutor when the AI invokes the read_file tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Read content from a file.

        Args:
            query: The filename to read
            context: Session context (unused)

        Returns:
            CommandResult with file content or error
        """
        from config import FILE_MAX_SIZE_BYTES

        filename = query.strip()

        try:
            # Get validated filepath
            filepath = _get_safe_filepath(filename)

            # Check if file exists
            if not filepath.exists():
                return CommandResult(
                    command_name=self.command_name,
                    query=filename,
                    data=None,
                    needs_continuation=True,
                    display_text=f"File not found: {filename}",
                    error=ToolError(
                        error_type=ToolErrorType.INVALID_INPUT,
                        message=f"File '{filename}' does not exist. Use list_files to see available files.",
                        expected_format="read_file with filename parameter",
                        example="read_file(filename='notes.txt')"
                    )
                )

            # Check file size before reading
            file_size = filepath.stat().st_size
            if file_size > FILE_MAX_SIZE_BYTES:
                return CommandResult(
                    command_name=self.command_name,
                    query=filename,
                    data=None,
                    needs_continuation=True,
                    display_text=f"File too large: {filename}",
                    error=ToolError(
                        error_type=ToolErrorType.INVALID_INPUT,
                        message=f"File size ({file_size} bytes) exceeds limit ({FILE_MAX_SIZE_BYTES} bytes)",
                        expected_format=None,
                        example=None
                    )
                )

            # Read the file
            content = filepath.read_text(encoding='utf-8')

            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data={"filename": filename, "content": content, "size": len(content)},
                needs_continuation=True,
                display_text=f"Reading file: {filename}"
            )

        except FileSecurityError as e:
            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data=None,
                needs_continuation=True,
                display_text=f"Security error: {filename}",
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message=f"Security check failed: {str(e)}",
                    expected_format="read_file with filename or path",
                    example="read_file(filename='projects/notes.txt')"
                )
            )
        except UnicodeDecodeError:
            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data=None,
                needs_continuation=True,
                display_text=f"Cannot read binary file: {filename}",
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message="File contains binary data and cannot be read as text",
                    expected_format=None,
                    example=None
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data=None,
                needs_continuation=True,
                display_text=f"Error reading file: {filename}",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to read file: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  File is empty."

        data = result.data
        content = data.get("content", "")
        filename = data.get("filename", "unknown")
        size = data.get("size", 0)

        # Optionally truncate content (0 = no limit, returns full file)
        from config import FILE_READ_MAX_CHARS
        max_chars = FILE_READ_MAX_CHARS
        if max_chars > 0 and len(content) > max_chars:
            content = content[:max_chars] + f"\n... [truncated, showing {max_chars} of {size} chars]"

        return f"  File: {filename}\n  Content:\n{content}"


class WriteFileHandler(CommandHandler):
    """
    Handles file writing via the write_file native tool.

    Called by ToolExecutor when the AI invokes the write_file tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Write content to a file (overwrites if exists).

        Args:
            query: "filename | content" format
            context: Session context (unused)

        Returns:
            CommandResult with success/failure info
        """
        try:
            # Parse the command
            filename, content = _parse_write_command(query)

            # Validate content size
            _validate_content_size(content)

            # Get validated filepath
            filepath = _get_safe_filepath(filename)

            # Check if we're overwriting
            existed = filepath.exists()

            # Auto-create parent directories if writing to a subdirectory
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Write the file
            filepath.write_text(content, encoding='utf-8')

            action = "Updated" if existed else "Created"

            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data={
                    "filename": filename,
                    "action": action.lower(),
                    "size": len(content),
                    "existed": existed
                },
                needs_continuation=True,
                display_text=f"{action} file: {filename}"
            )

        except ValueError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Invalid write command format",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message=str(e),
                    expected_format="write_file with filename and content parameters",
                    example="write_file(filename='projects/notes.txt', content='These are my notes.')"
                )
            )
        except FileSecurityError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Security error in write command",
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message=f"Security check failed: {str(e)}",
                    expected_format="write_file with filename or path",
                    example="write_file(filename='projects/notes.txt', content='My notes here.')"
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Error writing file",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to write file: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Write operation completed."

        data = result.data
        filename = data.get("filename", "unknown")
        action = data.get("action", "saved")
        size = data.get("size", 0)

        return f"  Successfully {action} '{filename}' ({size} characters)"


class AppendFileHandler(CommandHandler):
    """
    Handles file appending via the append_file native tool.

    Called by ToolExecutor when the AI invokes the append_file tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        Append content to a file (creates if doesn't exist).

        Args:
            query: "filename | content" format
            context: Session context (unused)

        Returns:
            CommandResult with success/failure info
        """
        from config import FILE_MAX_SIZE_BYTES

        try:
            # Parse the command
            filename, content = _parse_write_command(query)

            # Get validated filepath
            filepath = _get_safe_filepath(filename)

            # Check existing size + new content
            existing_size = filepath.stat().st_size if filepath.exists() else 0
            new_content_size = len(content.encode('utf-8'))
            total_size = existing_size + new_content_size + 1  # +1 for newline

            if total_size > FILE_MAX_SIZE_BYTES:
                return CommandResult(
                    command_name=self.command_name,
                    query=query,
                    data=None,
                    needs_continuation=True,
                    display_text=f"File would exceed size limit: {filename}",
                    error=ToolError(
                        error_type=ToolErrorType.INVALID_INPUT,
                        message=f"Appending would exceed size limit ({total_size} > {FILE_MAX_SIZE_BYTES} bytes)",
                        expected_format=None,
                        example=None
                    )
                )

            # Check if we're creating or appending
            existed = filepath.exists()

            # Auto-create parent directories if appending to a file in a subdirectory
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Append to the file (with newline separator if file exists)
            with open(filepath, 'a', encoding='utf-8') as f:
                if existed and filepath.stat().st_size > 0:
                    f.write('\n')
                f.write(content)

            action = "Appended to" if existed else "Created"

            return CommandResult(
                command_name=self.command_name,
                query=filename,
                data={
                    "filename": filename,
                    "action": action.lower(),
                    "added_size": new_content_size,
                    "existed": existed
                },
                needs_continuation=True,
                display_text=f"{action} file: {filename}"
            )

        except ValueError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Invalid append command format",
                error=ToolError(
                    error_type=ToolErrorType.FORMAT_ERROR,
                    message=str(e),
                    expected_format="append_file with filename and content parameters",
                    example="append_file(filename='shopping.txt', content='Bananas')"
                )
            )
        except FileSecurityError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Security error in append command",
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message=f"Security check failed: {str(e)}",
                    expected_format="append_file with filename or path",
                    example="append_file(filename='projects/log.txt', content='Additional note.')"
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query,
                data=None,
                needs_continuation=True,
                display_text="Error appending to file",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to append to file: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  Append operation completed."

        data = result.data
        filename = data.get("filename", "unknown")
        action = data.get("action", "appended to")
        added_size = data.get("added_size", 0)

        return f"  Successfully {action} '{filename}' (+{added_size} characters)"


class ListFilesHandler(CommandHandler):
    """
    Handles file/directory listing via the list_files native tool.

    Lists the immediate contents of a directory (non-recursive), showing both
    subdirectories and files with [DIR] and [FILE] prefixes.

    Called by ToolExecutor when the AI invokes the list_files tool.
    """

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        List files and directories in a storage directory.

        Args:
            query: Optional relative path to list (empty = root storage dir)
            context: Session context (unused)

        Returns:
            CommandResult with list of files and directories
        """
        from config import FILE_ALLOWED_EXTENSIONS

        try:
            path_str = query.strip() if query else ""

            # Determine the target directory
            if path_str:
                target_dir = _resolve_safe_path(path_str, require_extension=False)
                if not target_dir.exists():
                    return CommandResult(
                        command_name=self.command_name,
                        query=path_str,
                        data=None,
                        needs_continuation=True,
                        display_text=f"Directory not found: {path_str}",
                        error=ToolError(
                            error_type=ToolErrorType.INVALID_INPUT,
                            message=f"Directory '{path_str}' does not exist.",
                            expected_format="list_files with optional path parameter",
                            example="list_files(path='projects')"
                        )
                    )
                if not target_dir.is_dir():
                    return CommandResult(
                        command_name=self.command_name,
                        query=path_str,
                        data=None,
                        needs_continuation=True,
                        display_text=f"Not a directory: {path_str}",
                        error=ToolError(
                            error_type=ToolErrorType.INVALID_INPUT,
                            message=f"'{path_str}' is not a directory.",
                            expected_format="list_files with a directory path",
                            example="list_files(path='projects')"
                        )
                    )
                display_path = path_str.rstrip("/") + "/"
            else:
                target_dir = _get_storage_dir()
                display_path = "/"

            directories: List[dict] = []
            files: List[dict] = []

            # List immediate children (non-recursive)
            for entry in target_dir.iterdir():
                if entry.name.startswith("."):
                    continue  # Skip hidden entries

                if entry.is_dir():
                    directories.append({"name": entry.name})
                elif entry.is_file():
                    ext = entry.suffix.lower()
                    if ext in FILE_ALLOWED_EXTENSIONS:
                        stat = entry.stat()
                        files.append({
                            "name": entry.name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime
                        })

            # Sort: directories alphabetically, files by modification time (newest first)
            directories.sort(key=lambda d: d["name"])
            files.sort(key=lambda f: f["modified"], reverse=True)

            return CommandResult(
                command_name=self.command_name,
                query=path_str,
                data={
                    "path": display_path,
                    "directories": directories,
                    "files": files,
                    "dir_count": len(directories),
                    "file_count": len(files),
                },
                needs_continuation=True,
                display_text=f"Listing {display_path}: {len(directories)} dir(s), {len(files)} file(s)"
            )

        except FileSecurityError as e:
            return CommandResult(
                command_name=self.command_name,
                query=query or "",
                data=None,
                needs_continuation=True,
                display_text="Security error listing files",
                error=ToolError(
                    error_type=ToolErrorType.INVALID_INPUT,
                    message=f"Security check failed: {str(e)}",
                    expected_format="list_files with optional path parameter",
                    example="list_files(path='projects')"
                )
            )
        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query=query or "",
                data=None,
                needs_continuation=True,
                display_text="Error listing files",
                error=ToolError(
                    error_type=ToolErrorType.SYSTEM_ERROR,
                    message=f"Failed to list files: {str(e)}",
                    expected_format=None,
                    example=None
                )
            )

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  No files found."

        data = result.data
        display_path = data.get("path", "/")
        directories = data.get("directories", [])
        files = data.get("files", [])
        dir_count = data.get("dir_count", 0)
        file_count = data.get("file_count", 0)

        if dir_count == 0 and file_count == 0:
            return f"  Listing: {display_path}\n  (empty)"

        lines = [f"  Listing: {display_path}"]

        for d in directories:
            lines.append(f"  [DIR]  {d['name']}/")

        for f in files:
            size = f["size"]
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1048576:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / 1048576:.1f} MB"
            lines.append(f"  [FILE] {f['name']} ({size_str})")

        return "\n".join(lines)


# =============================================================================
# DIRECTORY AND FILE MANAGEMENT FUNCTIONS
# =============================================================================
# These functions are called directly from the tool executor rather than
# going through the CommandHandler pattern (which is vestigial for native tools).


def create_directory(path: str) -> Dict[str, object]:
    """
    Create a directory (and any parent directories) within the sandbox.

    Args:
        path: Relative directory path (e.g., "projects" or "notes/2026/feb")

    Returns:
        Dict with operation results

    Raises:
        FileSecurityError: If path validation fails
    """
    dir_path = _resolve_safe_path(path, require_extension=False)

    if dir_path.exists() and not dir_path.is_dir():
        raise FileSecurityError(f"Path exists but is not a directory: {path}")

    already_existed = dir_path.is_dir()

    dir_path.mkdir(parents=True, exist_ok=True)

    return {
        "path": path,
        "created": not already_existed,
        "already_existed": already_existed,
    }


def move_file(source: str, destination: str) -> Dict[str, object]:
    """
    Move (or rename) a file within the sandbox.

    The destination must be a full file path including filename and extension.
    Parent directories at the destination are created automatically.

    Args:
        source: Relative path to the source file (e.g., "notes.txt")
        destination: Relative path for the destination (e.g., "archive/notes.txt")

    Returns:
        Dict with operation results

    Raises:
        FileSecurityError: If path validation fails or files don't exist
    """
    source_path = _resolve_safe_path(source, require_extension=True)
    dest_path = _resolve_safe_path(destination, require_extension=True)

    if not source_path.exists():
        raise FileSecurityError(f"Source file not found: {source}")

    if not source_path.is_file():
        raise FileSecurityError(f"Source is not a file: {source}")

    if dest_path.exists():
        raise FileSecurityError(f"Destination already exists: {destination}")

    # Auto-create parent directories at destination
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.move(str(source_path), str(dest_path))

    return {
        "source": source,
        "destination": destination,
        "moved": True,
    }
