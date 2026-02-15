"""
Pattern Project - File Tool Command Handlers
Handles file read/write operations for AI-initiated file storage and retrieval.

Security: All operations are sandboxed to FILE_STORAGE_DIR with strict validation.
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

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

    Args:
        filename: The filename to resolve

    Returns:
        Validated Path object within the sandbox

    Raises:
        FileSecurityError: If any security check fails
    """
    # Sanitize the filename
    safe_name = _sanitize_filename(filename)

    # Validate extension
    _validate_extension(safe_name)

    # Build the path
    storage_dir = _get_storage_dir()
    filepath = storage_dir / safe_name

    # Final check: ensure resolved path is still within sandbox
    # This catches any edge cases we might have missed
    try:
        resolved = filepath.resolve()
        storage_resolved = storage_dir.resolve()

        if not str(resolved).startswith(str(storage_resolved)):
            raise FileSecurityError("Path resolution escaped sandbox")
    except Exception as e:
        if isinstance(e, FileSecurityError):
            raise
        raise FileSecurityError(f"Path validation failed: {str(e)}")

    return filepath


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
    Handles [[READ_FILE: filename]] commands for reading text files.

    Example AI usage:
        "Let me check your notes... [[READ_FILE: notes.txt]]"
    """

    @property
    def command_name(self) -> str:
        return "READ_FILE"

    @property
    def pattern(self) -> str:
        return r'\[\[READ_FILE:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

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
                    expected_format="read_file with simple filename (no paths)",
                    example="read_file(filename='notes.txt')"
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

    def get_instructions(self) -> str:
        return """You can read text files by including this command in your response:
  [[READ_FILE: filename.txt]]

Use this when:
- The user asks you to check or read a file you previously saved
- You need to retrieve stored information

Rules:
- Simple filenames only (no paths or slashes: use "notes.txt" not "folder/notes.txt")
- No hidden files (cannot start with ".")

The file must exist in your file storage. Use [[LIST_FILES]] to see available files."""

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
    Handles [[WRITE_FILE: filename | content]] commands for writing text files.

    Example AI usage:
        "I'll save that for you... [[WRITE_FILE: notes.txt | Meeting notes from today...]]"
    """

    @property
    def command_name(self) -> str:
        return "WRITE_FILE"

    @property
    def pattern(self) -> str:
        # Match filename | content, non-greedy
        return r'\[\[WRITE_FILE:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

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
                    example="write_file(filename='notes.txt', content='These are my notes.')"
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
                    expected_format="write_file with simple filename (no paths)",
                    example="write_file(filename='notes.txt', content='My notes here.')"
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

    def get_instructions(self) -> str:
        return """You can write text files by including this command in your response:
  [[WRITE_FILE: filename.txt | content to write]]

Use this when:
- The user asks you to save something (notes, lists, information)
- You want to store data for later retrieval

Rules:
- Simple filenames only (no paths or slashes: use "notes.txt" not "folder/notes.txt")
- Must have an allowed extension (.txt, .md, .json, .csv, .log)
- No hidden files (cannot start with ".")

Note: This overwrites any existing file with the same name. Use [[APPEND_FILE:]] to add to existing files."""

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
    Handles [[APPEND_FILE: filename | content]] commands for appending to text files.

    Example AI usage:
        "I'll add that to your list... [[APPEND_FILE: shopping.txt | Bananas]]"
    """

    @property
    def command_name(self) -> str:
        return "APPEND_FILE"

    @property
    def pattern(self) -> str:
        return r'\[\[APPEND_FILE:\s*(.+?)\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

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
                    expected_format="append_file with simple filename (no paths)",
                    example="append_file(filename='notes.txt', content='Additional note.')"
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

    def get_instructions(self) -> str:
        return """You can append to text files by including this command in your response:
  [[APPEND_FILE: filename.txt | content to add]]

Use this when:
- Adding items to an existing list
- Adding new entries to a log or notes file
- You want to preserve existing content and add more

Rules:
- Simple filenames only (no paths or slashes: use "notes.txt" not "folder/notes.txt")
- Must have an allowed extension (.txt, .md, .json, .csv, .log)
- No hidden files (cannot start with ".")

If the file doesn't exist, it will be created."""

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
    Handles [[LIST_FILES]] commands for listing available files.

    Example AI usage:
        "Let me see what files are available... [[LIST_FILES]]"
    """

    @property
    def command_name(self) -> str:
        return "LIST_FILES"

    @property
    def pattern(self) -> str:
        # Parameterless command
        return r'\[\[LIST_FILES\]\]'

    @property
    def needs_continuation(self) -> bool:
        return True

    def execute(self, query: str, context: dict) -> CommandResult:
        """
        List all files in the storage directory.

        Args:
            query: Empty string (parameterless command)
            context: Session context (unused)

        Returns:
            CommandResult with list of files
        """
        from config import FILE_ALLOWED_EXTENSIONS

        try:
            storage_dir = _get_storage_dir()

            files: List[dict] = []

            # List files with allowed extensions
            for filepath in storage_dir.iterdir():
                if filepath.is_file():
                    ext = filepath.suffix.lower()
                    if ext in FILE_ALLOWED_EXTENSIONS:
                        stat = filepath.stat()
                        files.append({
                            "name": filepath.name,
                            "size": stat.st_size,
                            "modified": stat.st_mtime
                        })

            # Sort by modification time (newest first)
            files.sort(key=lambda f: f["modified"], reverse=True)

            return CommandResult(
                command_name=self.command_name,
                query="",
                data={"files": files, "count": len(files)},
                needs_continuation=True,
                display_text=f"Found {len(files)} file(s)"
            )

        except Exception as e:
            return CommandResult(
                command_name=self.command_name,
                query="",
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

    def get_instructions(self) -> str:
        return """You can list available files by including this command in your response:
  [[LIST_FILES]]

Use this when:
- You need to know what files are available to read
- The user asks what files you have stored
- Before attempting to read a file you're unsure exists"""

    def format_result(self, result: CommandResult) -> str:
        if result.error:
            return f"  {result.get_error_message()}"

        if not result.data:
            return "  No files found."

        files = result.data.get("files", [])
        count = result.data.get("count", 0)

        if count == 0:
            return "  No files stored yet."

        lines = [f"  {count} file(s) available:"]
        for f in files:
            name = f["name"]
            size = f["size"]
            # Format size nicely
            if size < 1024:
                size_str = f"{size} B"
            else:
                size_str = f"{size / 1024:.1f} KB"
            lines.append(f"    - {name} ({size_str})")

        return "\n".join(lines)
