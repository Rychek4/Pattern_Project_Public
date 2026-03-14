"""File operation tool definitions."""

from typing import Any, Dict

READ_FILE_TOOL: Dict[str, Any] = {
    "name": "read_file",
    "description": """Read content from a text file in your sandboxed storage.

Use when:
- The user asks you to check or read a file you previously saved
- You need to retrieve stored information
- Looking up notes, lists, or data you've saved

Supports subdirectory paths (e.g., 'projects/notes.txt').""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with extension (e.g., 'notes.txt', 'projects/readme.md')"
            }
        },
        "required": ["filename"]
    }
}

WRITE_FILE_TOOL: Dict[str, Any] = {
    "name": "write_file",
    "description": """Write content to a text file (creates new or overwrites existing).

Use when:
- The user asks you to save something (notes, lists, information)
- You want to store data for later retrieval
- Creating a new file or completely replacing an existing one

Allowed extensions: .txt, .md, .json, .csv
Supports subdirectory paths — parent directories are created automatically.
Note: This overwrites existing files — use append_file to add to existing content.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with allowed extension (e.g., 'notes.txt', 'projects/readme.md')"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["filename", "content"]
    }
}

APPEND_FILE_TOOL: Dict[str, Any] = {
    "name": "append_file",
    "description": """Append content to an existing file (creates file if it doesn't exist).

Use when:
- Adding items to an existing list
- Adding new entries to a log or notes file
- You want to preserve existing content and add more

Supports subdirectory paths — parent directories are created automatically.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename or path with allowed extension (e.g., 'log.txt', 'projects/notes.md')"
            },
            "content": {
                "type": "string",
                "description": "Content to append (will be added on a new line)"
            }
        },
        "required": ["filename", "content"]
    }
}

LIST_FILES_TOOL: Dict[str, Any] = {
    "name": "list_files",
    "description": """List files and directories in your sandboxed storage.

Lists the immediate contents of a directory (non-recursive), showing both
subdirectories ([DIR]) and files ([FILE]). Call without a path to see the
root level, then drill into subdirectories as needed.

Use when:
- You need to know what files and directories are available
- The user asks what files you have stored
- Before attempting to read a file you're unsure exists
- Exploring the directory structure""",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional subdirectory to list (e.g., 'projects'). Omit to list the root storage directory."
            }
        },
        "required": []
    }
}

CREATE_DIRECTORY_TOOL: Dict[str, Any] = {
    "name": "create_directory",
    "description": """Create a new directory (and any parent directories) in your sandboxed storage.

Use when:
- Organizing files into categories or projects
- Setting up a directory structure before writing files
- The user asks you to create folders for organization

Parent directories are created automatically (e.g., 'notes/2026/feb' creates
all three levels at once). Directory names follow the same rules as filenames:
letters, numbers, dashes, underscores, and dots only.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path to create (e.g., 'projects', 'notes/2026/feb')"
            }
        },
        "required": ["path"]
    }
}

MOVE_FILE_TOOL: Dict[str, Any] = {
    "name": "move_file",
    "description": """Move or rename a file within your sandboxed storage.

Use when:
- Organizing files into directories
- Renaming a file
- Archiving old files into a subdirectory

The destination must be a full file path including filename and extension.
Parent directories at the destination are created automatically.
Cannot overwrite existing files — the destination must not already exist.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "description": "Current path of the file (e.g., 'notes.txt', 'old/data.csv')"
            },
            "destination": {
                "type": "string",
                "description": "New path for the file (e.g., 'archive/notes.txt', 'renamed.txt')"
            }
        },
        "required": ["source", "destination"]
    }
}
