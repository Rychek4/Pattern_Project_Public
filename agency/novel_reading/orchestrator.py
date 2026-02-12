"""
Pattern Project - Novel Reading Orchestrator
Coordinates the full reading loop: parsing, chapter delivery, extraction,
memory storage, and progress tracking.

The orchestrator manages:
    - Book lifecycle (open, read chapters, complete)
    - Per-chapter extraction → memory storage
    - Arc boundary reflective passes (Opus)
    - Completion synthesis
    - Growth thread updates for the reading journey
    - Progress persistence in the database
"""

import json
import re
from datetime import datetime
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

from core.database import get_database
from core.logger import log_info, log_error, log_warning
from concurrency.db_retry import db_retry
from memory.vector_store import get_vector_store
from agency.novel_reading.parser import parse_book, BookStructure
from agency.novel_reading.extraction import (
    extract_chapter,
    reflect_on_arc,
    synthesize_completion,
    LiteraryObservation,
)


# =============================================================================
# READING SESSION MANAGER
# =============================================================================

class ReadingSession:
    """Manages database persistence for a reading session."""

    def __init__(self, session_id: int):
        self.session_id = session_id

    @staticmethod
    @db_retry()
    def get_active() -> Optional['ReadingSession']:
        """Get the currently active reading session, if any."""
        db = get_database()
        result = db.execute(
            "SELECT id FROM reading_sessions WHERE status = 'reading' ORDER BY started_at DESC LIMIT 1",
            fetch=True
        )
        if result:
            return ReadingSession(result[0]["id"])
        return None

    @staticmethod
    @db_retry()
    def create(
        filename: str,
        title: str,
        structure: BookStructure
    ) -> 'ReadingSession':
        """Create a new reading session."""
        db = get_database()
        now = datetime.now().isoformat()

        db.execute(
            """
            INSERT INTO reading_sessions
            (filename, title, status, total_chapters, total_arcs, has_prologue,
             structure_json, current_chapter, current_arc, chapters_read,
             started_at, last_read_at)
            VALUES (?, ?, 'reading', ?, ?, ?, ?, 0, 0, '[]', ?, ?)
            """,
            (
                filename, title,
                structure.total_chapters, structure.total_arcs,
                structure.has_prologue,
                json.dumps(structure.to_summary_dict()),
                now, now,
            )
        )

        result = db.execute(
            "SELECT id FROM reading_sessions ORDER BY id DESC LIMIT 1",
            fetch=True
        )
        session_id = result[0]["id"]
        log_info(f"Created reading session #{session_id} for '{title}'", prefix="📖")
        return ReadingSession(session_id)

    @db_retry()
    def get_info(self) -> Optional[Dict[str, Any]]:
        """Get full session info."""
        db = get_database()
        result = db.execute(
            "SELECT * FROM reading_sessions WHERE id = ?",
            (self.session_id,),
            fetch=True
        )
        if not result:
            return None

        row = result[0]
        return {
            "id": row["id"],
            "filename": row["filename"],
            "title": row["title"],
            "status": row["status"],
            "total_chapters": row["total_chapters"],
            "total_arcs": row["total_arcs"],
            "has_prologue": bool(row["has_prologue"]),
            "current_chapter": row["current_chapter"],
            "current_arc": row["current_arc"],
            "chapters_read": json.loads(row["chapters_read"] or "[]"),
            "started_at": row["started_at"],
            "last_read_at": row["last_read_at"],
            "completed_at": row["completed_at"],
            "structure": json.loads(row["structure_json"] or "{}"),
        }

    @db_retry()
    def update_progress(
        self,
        chapter_number: int,
        arc_number: Optional[int] = None
    ) -> None:
        """Mark a chapter as read and update progress."""
        db = get_database()
        now = datetime.now().isoformat()

        # Get current chapters_read list
        result = db.execute(
            "SELECT chapters_read FROM reading_sessions WHERE id = ?",
            (self.session_id,),
            fetch=True
        )
        if not result:
            return

        chapters_read = json.loads(result[0]["chapters_read"] or "[]")
        if chapter_number not in chapters_read:
            chapters_read.append(chapter_number)

        update_sql = """
            UPDATE reading_sessions
            SET current_chapter = ?, chapters_read = ?, last_read_at = ?
        """
        params = [chapter_number, json.dumps(chapters_read), now]

        if arc_number is not None:
            update_sql += ", current_arc = ?"
            params.append(arc_number)

        update_sql += " WHERE id = ?"
        params.append(self.session_id)

        db.execute(update_sql, tuple(params))

    @db_retry()
    def mark_completed(self) -> None:
        """Mark the reading session as completed."""
        db = get_database()
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE reading_sessions SET status = 'completed', completed_at = ? WHERE id = ?",
            (now, self.session_id)
        )
        log_info(f"Reading session #{self.session_id} completed", prefix="📖")

    @db_retry()
    def mark_abandoned(self) -> None:
        """Mark the reading session as abandoned."""
        db = get_database()
        now = datetime.now().isoformat()
        db.execute(
            "UPDATE reading_sessions SET status = 'abandoned', completed_at = ? WHERE id = ?",
            (now, self.session_id)
        )
        log_info(f"Reading session #{self.session_id} abandoned", prefix="📖")

    @db_retry()
    def save_observations(self, observations: List[LiteraryObservation]) -> None:
        """Persist observation tracker state for resume capability."""
        db = get_database()
        obs_data = [
            {
                "category": o.category,
                "importance": o.importance,
                "observation": o.observation,
                "source_chapter": o.source_chapter,
                "source_arc": o.source_arc,
            }
            for o in observations
        ]
        db.execute(
            "UPDATE reading_sessions SET observations_json = ? WHERE id = ?",
            (json.dumps(obs_data), self.session_id)
        )

    @db_retry()
    def load_observations(self) -> List[LiteraryObservation]:
        """Load persisted observations for resume."""
        db = get_database()
        result = db.execute(
            "SELECT observations_json FROM reading_sessions WHERE id = ?",
            (self.session_id,),
            fetch=True
        )
        if not result or not result[0]["observations_json"]:
            return []
        obs_data = json.loads(result[0]["observations_json"])
        return [
            LiteraryObservation(
                category=o["category"],
                importance=o["importance"],
                observation=o["observation"],
                source_chapter=o.get("source_chapter"),
                source_arc=o.get("source_arc"),
            )
            for o in obs_data
        ]


# =============================================================================
# IN-MEMORY OBSERVATION TRACKER
# =============================================================================

class ObservationTracker:
    """
    Tracks all literary observations extracted during a reading session.

    This is the in-memory accumulation of what the AI has understood so far.
    It feeds into each subsequent extraction prompt and into reflective passes.
    """

    def __init__(self):
        self.observations: List[LiteraryObservation] = []

    def add(self, observations: List[LiteraryObservation]) -> None:
        """Add new observations from an extraction pass."""
        self.observations.extend(observations)

    def get_all(self) -> List[LiteraryObservation]:
        """Get all accumulated observations."""
        return self.observations

    def get_by_category(self, category: str) -> List[LiteraryObservation]:
        """Get observations filtered by category."""
        return [o for o in self.observations if o.category == category]

    def get_for_chapter(self, chapter_number: int) -> List[LiteraryObservation]:
        """Get observations from a specific chapter."""
        return [o for o in self.observations if o.source_chapter == chapter_number]

    def count(self) -> int:
        return len(self.observations)


# =============================================================================
# ORCHESTRATOR
# =============================================================================

# In-memory state for the active reading
_active_book: Optional[BookStructure] = None
_active_session: Optional[ReadingSession] = None
_observation_tracker: Optional[ObservationTracker] = None


def _store_observations_as_memories(
    observations: List[LiteraryObservation],
    book_title: str
) -> int:
    """
    Store literary observations as standard memories in the vector store.

    Each observation becomes a memory with:
    - decay_category: 'standard' (subject to normal aging)
    - memory_type: 'reflection' (literary observations are reflective)
    - memory_category: 'episodic' (they're narrative in nature)

    Returns:
        Number of memories successfully stored
    """
    vector_store = get_vector_store()
    stored = 0

    # Map literary categories to decay behavior
    # Characters and themes are more lasting; predictions are more ephemeral
    category_decay = {
        'CHARACTERS': 'standard',
        'PLOT_EVENTS': 'standard',
        'THEMES': 'standard',
        'PHILOSOPHICAL': 'standard',
        'PREDICTIONS': 'ephemeral',  # Predictions fade once resolved
        'EMOTIONAL_BEATS': 'standard',
        'UNRESOLVED_THREADS': 'standard',
        'EMERGENT_PATTERNS': 'standard',
        'PHILOSOPHICAL_CONSISTENCY': 'standard',
        'CHARACTER_ARC_SYNTHESIS': 'standard',
        'THEMATIC_EVOLUTION': 'standard',
        'GROWTH_THREAD_UPDATE': 'standard',
        'OVERALL_RESPONSE': 'standard',
        'PREDICTION_REVIEW': 'standard',
        'DISCUSSION_POINTS': 'standard',
        'GROWTH_THREAD_FINAL': 'standard',
    }

    for obs in observations:
        decay = category_decay.get(obs.category, 'standard')

        memory_id = vector_store.add_memory(
            content=obs.observation,
            source_conversation_ids=[],  # Not from a conversation
            importance=obs.importance,
            memory_type='reflection',
            decay_category=decay,
            memory_category='episodic',
        )

        if memory_id is not None:
            stored += 1

    log_info(
        f"Stored {stored}/{len(observations)} literary observations as memories "
        f"for '{book_title}'",
        prefix="📖"
    )
    return stored


def _split_chapter_text(text: str, max_tokens: int) -> List[str]:
    """
    Split chapter text into segments at paragraph boundaries if it exceeds
    the token budget. Returns a list of text segments.
    """
    estimated_tokens = len(text) // 4
    if estimated_tokens <= max_tokens:
        return [text]

    target_chars = max_tokens * 4
    paragraphs = re.split(r'\n\s*\n', text)

    segments = []
    current_paragraphs = []
    current_chars = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for the split delimiter
        if current_chars + para_len > target_chars and current_paragraphs:
            segments.append('\n\n'.join(current_paragraphs))
            current_paragraphs = []
            current_chars = 0
        current_paragraphs.append(para)
        current_chars += para_len

    if current_paragraphs:
        segments.append('\n\n'.join(current_paragraphs))

    return segments


def open_book(filepath: Path) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Open a book for reading: parse structure and create a reading session.

    Args:
        filepath: Path to the .txt file

    Returns:
        Tuple of (success, message, structure_summary)
    """
    global _active_book, _active_session, _observation_tracker

    # Check for existing active session
    existing = ReadingSession.get_active()
    if existing:
        info = existing.get_info()
        # If in-memory state is already set, truly active — block
        if _active_session is not None:
            return (
                False,
                f"Already reading '{info['title']}' "
                f"(chapter {info['current_chapter']}/{info['total_chapters']}). "
                f"Complete or abandon the current book first.",
                None
            )
        # In-memory state lost (restart) — auto-resume if same file
        if info.get("filename") == filepath.name:
            log_info(
                f"Detected interrupted session for '{info['title']}', auto-resuming",
                prefix="📖"
            )
            return resume_reading(filepath)
        # Different file — tell user to abandon the stale session first
        return (
            False,
            f"A previous session for '{info['title']}' is still active "
            f"(chapter {info['current_chapter']}/{info['total_chapters']}). "
            f"Use abandon_reading to clear it, or resume_reading to continue it.",
            None
        )

    # Validate file
    if not filepath.exists():
        return False, f"File not found: {filepath}", None

    if not filepath.suffix.lower() == '.txt':
        return False, "Only .txt files are supported for novel reading.", None

    try:
        # Parse the book
        structure = parse_book(filepath)

        if structure.total_chapters == 0:
            return False, "No chapters or content could be detected in the file.", None

        # Create reading session
        session = ReadingSession.create(
            filename=structure.filename,
            title=structure.title,
            structure=structure,
        )

        # Set up in-memory state
        _active_book = structure
        _active_session = session
        _observation_tracker = ObservationTracker()

        summary = structure.to_summary_dict()
        return True, f"Opened '{structure.title}' — ready to read.", summary

    except Exception as e:
        log_error(f"Failed to open book: {e}")
        return False, f"Failed to parse book: {str(e)}", None


def read_next_chapter() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Read the next chapter: deliver text, run extraction, store memories.

    This is the core of the reading loop. For each chapter:
    1. Get the chapter text
    2. Run literary extraction (Sonnet)
    3. Store observations as memories
    4. Check for arc boundary → run reflective pass (Opus) if so
    5. Update progress

    Returns:
        Tuple of (success, message, result_data)
    """
    global _active_book, _active_session, _observation_tracker

    if _active_book is None or _active_session is None:
        return False, "No book is currently open. Use open_book first.", None

    info = _active_session.get_info()
    if info is None:
        return False, "Reading session not found.", None

    chapters_read = info["chapters_read"]
    next_chapter_num = len(chapters_read) + 1

    if next_chapter_num > _active_book.total_chapters:
        return False, "All chapters have been read. Use complete_reading to finish.", None

    # Get chapter
    chapter = _active_book.get_chapter(next_chapter_num)
    if chapter is None:
        return False, f"Chapter {next_chapter_num} not found.", None

    chapter_text = _active_book.get_chapter_text(next_chapter_num)
    if chapter_text is None:
        return False, f"Could not read chapter {next_chapter_num} text.", None

    # Build context for extraction
    arc = _active_book.get_arc_for_chapter(next_chapter_num)
    arc_info = f"Arc {arc.number}: {arc.title}" if arc else "No arc structure"
    chapters_read_str = (
        f"Chapters 1-{next_chapter_num - 1}" if chapters_read
        else "None (this is the first chapter)"
    )

    log_info(
        f"Reading chapter {next_chapter_num}/{_active_book.total_chapters}: "
        f"'{chapter.title}' ({chapter.word_count} words)",
        prefix="📖"
    )

    # Split chapter if it exceeds token budget
    from config import NOVEL_CHAPTER_MAX_TOKENS
    segments = _split_chapter_text(chapter_text, NOVEL_CHAPTER_MAX_TOKENS)

    if len(segments) > 1:
        log_info(
            f"Chapter {next_chapter_num} exceeds token budget — "
            f"splitting into {len(segments)} segments",
            prefix="📖"
        )

    # Run extraction across all segments
    all_observations = []
    any_extraction_failed = False

    for seg_idx, segment in enumerate(segments):
        seg_label = (
            f" (segment {seg_idx + 1}/{len(segments)})"
            if len(segments) > 1 else ""
        )
        extraction_result = extract_chapter(
            book_title=_active_book.title,
            chapter_number=next_chapter_num,
            chapter_title=chapter.title + seg_label,
            chapter_text=segment,
            arc_info=arc_info,
            chapters_read_so_far=chapters_read_str,
            previous_observations=_observation_tracker.get_all() + all_observations,
        )
        if extraction_result.success:
            all_observations.extend(extraction_result.observations)
        else:
            any_extraction_failed = True
            log_warning(
                f"Extraction failed for chapter {next_chapter_num}{seg_label}: "
                f"{extraction_result.error}"
            )

    result_data = {
        "chapter_number": next_chapter_num,
        "chapter_title": chapter.title,
        "word_count": chapter.word_count,
        "token_estimate": chapter.token_estimate,
        "arc": arc_info,
        "extraction_success": not any_extraction_failed,
        "observations_extracted": len(all_observations),
    }

    if len(segments) > 1:
        result_data["segments"] = len(segments)

    if all_observations:
        # Track observations
        _observation_tracker.add(all_observations)

        # Store as memories
        stored = _store_observations_as_memories(
            all_observations,
            _active_book.title,
        )
        result_data["memories_stored"] = stored

        # Categorize what was found
        categories_found = set(o.category for o in all_observations)
        result_data["categories"] = sorted(categories_found)

    if any_extraction_failed and not all_observations:
        log_warning(
            f"All extraction segments failed for chapter {next_chapter_num}"
        )

    # Update progress
    _active_session.update_progress(
        chapter_number=next_chapter_num,
        arc_number=arc.number if arc else None,
    )

    # Check for arc boundary → reflective pass
    from config import NOVEL_REFLECT_AT_ARC_BOUNDARIES
    if NOVEL_REFLECT_AT_ARC_BOUNDARIES and _active_book.is_arc_boundary(next_chapter_num):
        arc = _active_book.get_arc_for_chapter(next_chapter_num)
        if arc:
            log_info(
                f"Arc boundary reached: Arc {arc.number} '{arc.title}' complete. "
                f"Running reflective pass...",
                prefix="📖"
            )

            arc_chapters_str = ', '.join(str(c) for c in arc.chapter_numbers)
            reflection = reflect_on_arc(
                book_title=_active_book.title,
                arc_number=arc.number,
                arc_title=arc.title,
                arc_chapters=arc_chapters_str,
                total_chapters_read=next_chapter_num,
                total_chapters=_active_book.total_chapters,
                all_observations=_observation_tracker.get_all(),
            )

            if reflection.success:
                _observation_tracker.add(reflection.observations)
                stored = _store_observations_as_memories(
                    reflection.observations,
                    _active_book.title,
                )
                result_data["arc_reflection"] = {
                    "arc_number": arc.number,
                    "arc_title": arc.title,
                    "observations": len(reflection.observations),
                    "memories_stored": stored,
                }

    # Persist observation tracker for resume capability
    _active_session.save_observations(_observation_tracker.get_all())

    # Check if all chapters are now read
    is_last_chapter = next_chapter_num >= _active_book.total_chapters
    result_data["is_last_chapter"] = is_last_chapter
    result_data["chapters_remaining"] = _active_book.total_chapters - next_chapter_num

    msg = (
        f"Read chapter {next_chapter_num}/{_active_book.total_chapters}: "
        f"'{chapter.title}'"
    )

    if is_last_chapter:
        msg += " — All chapters read. Use complete_reading to run final synthesis."

    return True, msg, result_data


def complete_reading() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Complete the reading session: run final synthesis and update growth thread.

    This runs the Opus completion synthesis pass and stores the final
    set of high-level memories and discussion points.

    Returns:
        Tuple of (success, message, result_data)
    """
    global _active_book, _active_session, _observation_tracker

    if _active_book is None or _active_session is None:
        return False, "No book is currently open.", None

    info = _active_session.get_info()
    chapters_read = info["chapters_read"]

    if len(chapters_read) < _active_book.total_chapters:
        remaining = _active_book.total_chapters - len(chapters_read)
        return (
            False,
            f"Book not finished — {remaining} chapters remaining. "
            f"Continue reading or abandon the session.",
            None
        )

    log_info(
        f"Running completion synthesis for '{_active_book.title}'...",
        prefix="📖"
    )

    # Run completion synthesis
    synthesis = synthesize_completion(
        book_title=_active_book.title,
        total_chapters=_active_book.total_chapters,
        total_arcs=_active_book.total_arcs,
        all_observations=_observation_tracker.get_all(),
    )

    result_data = {
        "book_title": _active_book.title,
        "total_chapters_read": len(chapters_read),
        "total_observations": _observation_tracker.count(),
        "synthesis_success": synthesis.success,
    }

    if synthesis.success:
        _observation_tracker.add(synthesis.observations)
        stored = _store_observations_as_memories(
            synthesis.observations,
            _active_book.title,
        )
        result_data["synthesis_observations"] = len(synthesis.observations)
        result_data["synthesis_memories_stored"] = stored

        # Extract discussion points for the result
        discussion_points = [
            o.observation for o in synthesis.observations
            if o.category == 'DISCUSSION_POINTS'
        ]
        result_data["discussion_points"] = discussion_points

    # Store a "I have read this book" memory
    vector_store = get_vector_store()
    completion_memory = (
        f"I completed reading {_active_book.title} on "
        f"{datetime.now().strftime('%B %d, %Y')}. "
        f"The book had {_active_book.total_chapters} chapters"
    )
    if _active_book.total_arcs > 0:
        arc_titles = ', '.join(a.title for a in _active_book.arcs)
        completion_memory += f" across {_active_book.total_arcs} arcs ({arc_titles})"
    completion_memory += (
        f". I extracted {_observation_tracker.count()} literary observations "
        f"during my reading."
    )

    vector_store.add_memory(
        content=completion_memory,
        source_conversation_ids=[],
        importance=0.8,
        memory_type='event',
        decay_category='standard',
        memory_category='episodic',
    )

    # Mark session as completed
    _active_session.mark_completed()

    # Clear in-memory state
    _active_book = None
    _active_session = None
    _observation_tracker = None

    return True, f"Completed reading '{info['title']}'.", result_data


def get_reading_progress() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Get current reading progress.

    Returns progress for the active session, or info about the most recent
    completed session if no book is currently being read.
    """
    global _active_book, _active_session, _observation_tracker

    # Use in-memory session, or fall back to DB (post-restart)
    session = _active_session or ReadingSession.get_active()

    if session is not None:
        info = session.get_info()
        if info:
            chapters_read = info["chapters_read"]
            progress_pct = (
                (len(chapters_read) / info["total_chapters"] * 100)
                if info["total_chapters"] > 0 else 0
            )

            needs_resume = _active_session is None
            status_note = " (session needs resume — use resume_reading or re-open the book)" if needs_resume else ""

            result = {
                "status": "reading",
                "title": info["title"],
                "filename": info["filename"],
                "current_chapter": info["current_chapter"],
                "total_chapters": info["total_chapters"],
                "chapters_read": chapters_read,
                "chapters_remaining": info["total_chapters"] - len(chapters_read),
                "progress_percent": round(progress_pct, 1),
                "total_arcs": info["total_arcs"],
                "current_arc": info["current_arc"],
                "observations_so_far": (
                    _observation_tracker.count() if _observation_tracker else 0
                ),
                "started_at": info["started_at"],
                "needs_resume": needs_resume,
            }
            return True, f"Currently reading '{info['title']}'{status_note}", result

    # Check for most recent completed session
    db = get_database()
    result = db.execute(
        """
        SELECT * FROM reading_sessions
        WHERE status IN ('completed', 'abandoned')
        ORDER BY completed_at DESC LIMIT 1
        """,
        fetch=True
    )

    if result:
        row = result[0]
        return True, f"No active reading. Last read: '{row['title']}'", {
            "status": row["status"],
            "title": row["title"],
            "total_chapters": row["total_chapters"],
            "completed_at": row["completed_at"],
        }

    return True, "No reading sessions found. Use open_book to start reading.", {
        "status": "none"
    }


def abandon_reading() -> Tuple[bool, str]:
    """Abandon the current reading session."""
    global _active_book, _active_session, _observation_tracker

    session = _active_session

    # Fall back to DB if in-memory state was lost (e.g. after restart)
    if session is None:
        session = ReadingSession.get_active()

    if session is None:
        return False, "No book is currently being read."

    info = session.get_info()
    session.mark_abandoned()

    # Clear state
    _active_book = None
    _active_session = None
    _observation_tracker = None

    return True, f"Abandoned reading '{info['title']}'."


def resume_reading(filepath: Path) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Resume a previously interrupted reading session.

    If the system was restarted mid-read, this reloads the book structure
    and observation tracker from the database and parsed file.
    """
    global _active_book, _active_session, _observation_tracker

    # Check for active session in DB
    session = ReadingSession.get_active()
    if session is None:
        return False, "No active reading session to resume.", None

    info = session.get_info()

    # Re-parse the book
    if not filepath.exists():
        return False, f"Book file not found: {filepath}", None

    try:
        structure = parse_book(filepath)
    except Exception as e:
        return False, f"Failed to re-parse book: {e}", None

    # Restore state
    _active_book = structure
    _active_session = session
    _observation_tracker = ObservationTracker()

    # Reload persisted observations from the database
    saved_observations = session.load_observations()
    if saved_observations:
        _observation_tracker.add(saved_observations)
        log_info(
            f"Restored {len(saved_observations)} observations from previous session",
            prefix="📖"
        )

    chapters_read = info["chapters_read"]
    return (
        True,
        f"Resumed reading '{info['title']}' at chapter "
        f"{info['current_chapter']}/{info['total_chapters']}.",
        {
            "title": info["title"],
            "chapters_read": chapters_read,
            "chapters_remaining": info["total_chapters"] - len(chapters_read),
        }
    )
