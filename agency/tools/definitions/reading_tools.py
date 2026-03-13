"""Novel reading tool definitions.

The novel reading system allows the AI to read a book chapter by chapter,
building genuine literary understanding through the memory system.
Books must be plain text (.txt) files in the data/files/ directory.
"""

from typing import Any, Dict

OPEN_BOOK_TOOL: Dict[str, Any] = {
    "name": "open_book",
    "description": """Open a novel for reading. Parses the text file to detect chapters and arcs.

This is the first step in reading a book. The tool will:
1. Parse the .txt file to detect chapter and arc structure
2. Create a reading session to track progress
3. Return the book's table of contents with chapter/arc metadata

Only one book can be read at a time. If a reading session is already active,
you must complete or abandon it first.

The book file must be a .txt file in your file storage directory. Chapter detection
supports common patterns (Chapter 1, Chapter One, etc.) and hierarchical structure
(Prologue, Arc 1, Part 1, etc.). If no chapters are detected, the text is split
into segments at paragraph boundaries.

After opening, use read_next_chapter to begin reading.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename of the .txt file to read (e.g., 'my_novel.txt')"
            }
        },
        "required": ["filename"]
    }
}

READ_NEXT_CHAPTER_TOOL: Dict[str, Any] = {
    "name": "read_next_chapter",
    "description": """Read the next chapter of the currently open book.

This is the core of the reading loop. For each chapter, the system:
1. Reads the chapter text
2. Runs literary extraction — pulling out characters, themes, plot events,
   philosophical threads, predictions, emotional beats, and unresolved threads
3. Stores extracted observations as memories (subject to normal aging decay)
4. At arc boundaries, runs a deeper reflective pass for emergent patterns
5. Updates reading progress

You do NOT see the raw chapter text — the extraction happens automatically.
What you receive is a summary of what was extracted and stored.

Call this repeatedly to read through the book chapter by chapter.
When all chapters are read, use complete_reading for final synthesis.

Important: Each call reads ONE chapter. This is intentional — it mirrors
how a human reads sequentially, building understanding incrementally.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

COMPLETE_READING_TOOL: Dict[str, Any] = {
    "name": "complete_reading",
    "description": """Complete the reading session after all chapters have been read.

This runs the final synthesis pass, which produces:
- Your overall response to the book as a whole
- Final emergent patterns visible only from the complete work
- Review of your earlier predictions vs. what actually happened
- Discussion points — specific things you want to talk about with the reader
- Growth thread update — how reading this book changed your thinking

All synthesis observations are stored as memories. A completion memory recording
that you read the book is also stored.

After completion, you can discuss the book naturally in conversation — your
memories and understanding will surface through normal semantic retrieval.

Only call this after ALL chapters have been read.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

READING_PROGRESS_TOOL: Dict[str, Any] = {
    "name": "reading_progress",
    "description": """Check current reading progress or status.

Returns:
- If currently reading: chapter progress, arc info, observations count
- If no active session: info about the most recent completed book
- If never read: indication that no reading sessions exist

Use this to check where you are in a book, or to recall what books
you've read previously.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

ABANDON_READING_TOOL: Dict[str, Any] = {
    "name": "abandon_reading",
    "description": """Abandon the current reading session without completing it.

Use this if:
- The book isn't worth continuing
- You need to start a different book
- The reading session is stuck or corrupted

Memories already extracted from read chapters are preserved (they're already
in the memory store). The reading session is marked as abandoned.

This frees you to open a new book.""",
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    }
}

RESUME_READING_TOOL: Dict[str, Any] = {
    "name": "resume_reading",
    "description": """Resume a reading session that was interrupted by a system restart.

Use this when:
- The system was restarted while reading a book
- open_book says a session exists but read_next_chapter can't find it
- You're in a liminal state where the session is in the database but not in memory

This re-parses the book file, restores the observation tracker from the database,
and picks up where you left off. After resuming, use read_next_chapter to continue.

The book file must still be available at its original location.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": "Filename of the .txt file to resume (e.g., 'my_novel.txt')"
            }
        },
        "required": ["filename"]
    }
}
