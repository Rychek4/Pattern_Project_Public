"""
Pattern Project - Book Parser
Detects chapters and arcs from plain text novel files.

Supports hierarchical structure detection:
    - Top-level: Prologue, Arcs/Parts/Books (containers)
    - Chapters: The actual reading units inside containers

When chapter detection fails, falls back to fixed-size chunking at
paragraph boundaries.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from core.logger import log_info, log_warning


@dataclass
class Chapter:
    """A single chapter (the reading unit)."""
    number: int           # 1-indexed chapter number across the whole book
    title: str            # Detected title (e.g., "Chapter 1: The Arrival")
    arc_number: Optional[int]  # Which arc this belongs to (None if no arcs)
    start_pos: int        # Character offset in the full text
    end_pos: int          # Character offset end
    word_count: int = 0
    token_estimate: int = 0

    @property
    def text_length(self) -> int:
        return self.end_pos - self.start_pos


@dataclass
class Arc:
    """A top-level division (Arc, Part, Book)."""
    number: int
    title: str
    chapter_numbers: List[int] = field(default_factory=list)


@dataclass
class BookStructure:
    """Complete parsed structure of a book."""
    title: str
    filename: str
    full_text: str
    chapters: List[Chapter] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    has_prologue: bool = False
    detection_method: str = ""
    total_word_count: int = 0
    total_token_estimate: int = 0

    @property
    def total_chapters(self) -> int:
        return len(self.chapters)

    @property
    def total_arcs(self) -> int:
        return len(self.arcs)

    def get_chapter(self, chapter_number: int) -> Optional[Chapter]:
        """Get a chapter by its number (1-indexed)."""
        for ch in self.chapters:
            if ch.number == chapter_number:
                return ch
        return None

    def get_chapter_text(self, chapter_number: int) -> Optional[str]:
        """Get the raw text content of a chapter."""
        ch = self.get_chapter(chapter_number)
        if ch is None:
            return None
        return self.full_text[ch.start_pos:ch.end_pos]

    def get_arc_for_chapter(self, chapter_number: int) -> Optional[Arc]:
        """Get the arc that contains a given chapter."""
        for arc in self.arcs:
            if chapter_number in arc.chapter_numbers:
                return arc
        return None

    def is_arc_boundary(self, chapter_number: int) -> bool:
        """Check if completing this chapter means we've finished an arc."""
        for arc in self.arcs:
            if arc.chapter_numbers and arc.chapter_numbers[-1] == chapter_number:
                return True
        return False

    def to_summary_dict(self) -> dict:
        """Return a JSON-serializable summary for storage and tool output."""
        arc_summaries = []
        for arc in self.arcs:
            arc_summaries.append({
                "number": arc.number,
                "title": arc.title,
                "chapters": arc.chapter_numbers,
            })

        chapter_summaries = []
        for ch in self.chapters:
            chapter_summaries.append({
                "number": ch.number,
                "title": ch.title,
                "arc": ch.arc_number,
                "word_count": ch.word_count,
                "token_estimate": ch.token_estimate,
            })

        return {
            "title": self.title,
            "filename": self.filename,
            "detection_method": self.detection_method,
            "has_prologue": self.has_prologue,
            "total_chapters": self.total_chapters,
            "total_arcs": self.total_arcs,
            "total_word_count": self.total_word_count,
            "total_token_estimate": self.total_token_estimate,
            "arcs": arc_summaries,
            "chapters": chapter_summaries,
        }


# =============================================================================
# CHAPTER/ARC DETECTION PATTERNS
# =============================================================================

# Arc-level patterns (containers): Prologue, Arc N, Part N, Book N
ARC_PATTERNS = [
    # "Prologue" or "Prologue: Title"
    re.compile(r'^(Prologue(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    # "Epilogue" or "Epilogue: Title"
    re.compile(r'^(Epilogue(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    # "Arc 1", "Arc 1: Title", "ARC ONE"
    re.compile(r'^(Arc\s+\w+(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    # "Part 1", "Part One", "PART I: Title"
    re.compile(r'^(Part\s+\w+(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    # "Book 1", "Book One"
    re.compile(r'^(Book\s+\w+(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
]

# Chapter-level patterns
CHAPTER_PATTERNS = [
    # "Chapter 1", "Chapter One", "CHAPTER 1: Title"
    re.compile(r'^(Chapter\s+\w+(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    # "Interlude", "Interlude: Character Name - Title"
    re.compile(r'^(Interlude(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
]

# Bare number fallback — only used when primary patterns find nothing
_BARE_NUMBER_PATTERN = re.compile(r'(?:^|\n\n)\s*(\d{1,3})\s*(?:\n\n)', re.MULTILINE)

# Back-matter patterns — mark end of readable content
BACKMATTER_PATTERNS = [
    re.compile(r'^(Glossary(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^(Appendix(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^(Acknowledge?ments?(?:\s*[:\-–—]\s*.+)?)\s*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'^(About the Author)\s*$', re.IGNORECASE | re.MULTILINE),
]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~1 token per 4 characters for English text."""
    return len(text) // 4


def _count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def parse_book(filepath: Path) -> BookStructure:
    """
    Parse a plain text file into a BookStructure with chapters and arcs.

    Strategy:
    1. First pass: detect arc-level markers (Prologue, Arc, Part, Book)
    2. Second pass: detect chapter markers within/across arcs
    3. If chapter detection fails, fall back to fixed-size chunking

    Args:
        filepath: Path to the .txt file

    Returns:
        BookStructure with detected chapters and arcs
    """
    text = filepath.read_text(encoding='utf-8')
    filename = filepath.name
    title = filepath.stem.replace('_', ' ').replace('-', ' ').title()

    structure = BookStructure(
        title=title,
        filename=filename,
        full_text=text,
        total_word_count=_count_words(text),
        total_token_estimate=_estimate_tokens(text),
    )

    # First: detect arcs
    arc_markers = _detect_arc_markers(text)

    # Second: detect chapters
    chapter_markers = _detect_chapter_markers(text)

    # Inject Prologue/Epilogue as reading units if not already captured
    for pos, arc_title, marker_type in arc_markers:
        if marker_type in ('prologue', 'epilogue'):
            is_duplicate = any(abs(pos - cp) < 50 for cp, _ in chapter_markers)
            if not is_duplicate:
                chapter_markers.append((pos, arc_title))
    chapter_markers.sort(key=lambda x: x[0])

    # Detect back-matter to cap the last chapter's range
    backmatter_markers = _detect_backmatter_markers(text)
    last_chapter_pos = chapter_markers[-1][0] if chapter_markers else 0
    content_end = len(text)
    for bm_pos, _ in backmatter_markers:
        if bm_pos > last_chapter_pos:
            content_end = bm_pos
            break

    if chapter_markers:
        # Build chapters from detected markers
        _build_chapters_from_markers(structure, chapter_markers, arc_markers, content_end)
        structure.detection_method = "pattern: chapter markers"
        if arc_markers:
            structure.detection_method += f" + {len(arc_markers)} arc(s)"
    else:
        # Fallback: fixed-size chunking
        _build_chapters_from_chunking(structure, content_end=content_end)
        structure.detection_method = "fixed-size fallback (~4000 tokens per segment)"

    log_info(
        f"Parsed '{filename}': {structure.total_chapters} chapters, "
        f"{structure.total_arcs} arcs, {structure.total_word_count} words, "
        f"method: {structure.detection_method}",
        prefix="📖"
    )

    return structure


def _detect_arc_markers(text: str) -> List[Tuple[int, str, str]]:
    """
    Detect arc-level markers in the text.

    Returns:
        List of (position, raw_title, marker_type) tuples, sorted by position.
        marker_type is one of: 'prologue', 'epilogue', 'arc', 'part', 'book'
    """
    markers = []

    for pattern in ARC_PATTERNS:
        for match in pattern.finditer(text):
            raw_title = match.group(1).strip()
            pos = match.start()

            # Determine marker type
            lower = raw_title.lower()
            if lower.startswith('prologue'):
                marker_type = 'prologue'
            elif lower.startswith('epilogue'):
                marker_type = 'epilogue'
            elif lower.startswith('arc'):
                marker_type = 'arc'
            elif lower.startswith('part'):
                marker_type = 'part'
            elif lower.startswith('book'):
                marker_type = 'book'
            else:
                marker_type = 'arc'

            markers.append((pos, raw_title, marker_type))

    # Sort by position
    markers.sort(key=lambda x: x[0])
    return markers


def _detect_chapter_markers(text: str) -> List[Tuple[int, str]]:
    """
    Detect chapter markers in the text.

    Returns:
        List of (position, raw_title) tuples, sorted by position.
    """
    markers = []

    for pattern in CHAPTER_PATTERNS:
        for match in pattern.finditer(text):
            raw_title = match.group(1).strip()
            pos = match.start()
            markers.append((pos, raw_title))

    # Only use bare-number fallback if primary patterns found nothing
    if not markers:
        for match in _BARE_NUMBER_PATTERN.finditer(text):
            raw_title = match.group(1).strip()
            pos = match.start()
            markers.append((pos, raw_title))

    # Sort by position and deduplicate (overlapping patterns)
    markers.sort(key=lambda x: x[0])

    # Remove duplicates within 50 characters of each other
    deduped = []
    for pos, title in markers:
        if not deduped or pos - deduped[-1][0] > 50:
            deduped.append((pos, title))

    return deduped


def _detect_backmatter_markers(text: str) -> List[Tuple[int, str]]:
    """
    Detect back-matter markers (Glossary, Appendix, etc.).

    Returns:
        List of (position, raw_title) tuples, sorted by position.
    """
    markers = []
    for pattern in BACKMATTER_PATTERNS:
        for match in pattern.finditer(text):
            markers.append((match.start(), match.group(1).strip()))
    markers.sort(key=lambda x: x[0])
    return markers


def _build_chapters_from_markers(
    structure: BookStructure,
    chapter_markers: List[Tuple[int, str]],
    arc_markers: List[Tuple[int, str, str]],
    content_end: Optional[int] = None,
) -> None:
    """
    Build Chapter and Arc objects from detected markers.

    Assigns chapters to arcs based on position ordering.
    """
    text = structure.full_text
    text_len = len(text)
    readable_end = content_end if content_end is not None else text_len

    # Build arc objects first
    arcs = []
    has_prologue = False

    for i, (pos, title, marker_type) in enumerate(arc_markers):
        if marker_type == 'prologue':
            has_prologue = True
            # Prologue is not numbered as an arc — it's special
            continue

        arc_number = len(arcs) + 1
        arc = Arc(number=arc_number, title=title)
        arcs.append(arc)

    structure.arcs = arcs
    structure.has_prologue = has_prologue

    # Build chapters
    chapters = []
    for i, (pos, title) in enumerate(chapter_markers):
        # Determine end position (start of next chapter or end of text)
        if i + 1 < len(chapter_markers):
            # End at the next chapter marker, but step back to just before
            # the marker line to exclude the header
            end_pos = chapter_markers[i + 1][0]
        else:
            end_pos = readable_end

        # Find the actual content start (skip past the chapter title line)
        content_start = text.find('\n', pos)
        if content_start == -1:
            content_start = pos
        else:
            content_start += 1  # Skip the newline

        chapter_text = text[content_start:end_pos].strip()
        chapter_number = i + 1

        chapter = Chapter(
            number=chapter_number,
            title=title,
            arc_number=None,
            start_pos=content_start,
            end_pos=end_pos,
            word_count=_count_words(chapter_text),
            token_estimate=_estimate_tokens(chapter_text),
        )
        chapters.append(chapter)

    # Assign chapters to arcs by position
    if arc_markers and arcs:
        # Build position ranges for arcs
        # Arc positions include all types (prologue handled specially)
        arc_positions = [
            (pos, title, mtype) for pos, title, mtype in arc_markers
            if mtype != 'prologue' and mtype != 'epilogue'
        ]

        for chapter in chapters:
            chapter_pos = chapter.start_pos
            assigned_arc = None

            # Find which arc this chapter falls under
            for ai, (arc_pos, _, _) in enumerate(arc_positions):
                # Chapter is in this arc if its position is after the arc marker
                # and before the next arc marker (or end of book)
                next_arc_pos = (
                    arc_positions[ai + 1][0]
                    if ai + 1 < len(arc_positions)
                    else text_len
                )
                if arc_pos <= chapter_pos < next_arc_pos:
                    assigned_arc = ai + 1  # 1-indexed arc number
                    break

            chapter.arc_number = assigned_arc

        # Populate arc chapter lists
        for arc in arcs:
            arc.chapter_numbers = [
                ch.number for ch in chapters if ch.arc_number == arc.number
            ]

    structure.chapters = chapters


def _build_chapters_from_chunking(
    structure: BookStructure,
    target_tokens: int = 4000,
    content_end: Optional[int] = None,
) -> None:
    """
    Fall back to fixed-size chunking when no chapter markers are detected.

    Splits at paragraph boundaries (double newlines) to avoid cutting
    mid-sentence.
    """
    text = structure.full_text
    if content_end is not None:
        text = text[:content_end]
    target_chars = target_tokens * 4  # Rough char estimate

    # Split into paragraphs
    paragraphs = re.split(r'\n\s*\n', text)

    chapters = []
    current_chunk_start = 0
    current_chunk_chars = 0
    chunk_paragraphs = []
    chapter_number = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for the split delimiter

        if current_chunk_chars + para_len > target_chars and chunk_paragraphs:
            # Finalize current chunk as a chapter
            chapter_number += 1
            chunk_text = '\n\n'.join(chunk_paragraphs)
            end_pos = current_chunk_start + len(chunk_text)

            chapters.append(Chapter(
                number=chapter_number,
                title=f"Segment {chapter_number}",
                arc_number=None,
                start_pos=current_chunk_start,
                end_pos=end_pos,
                word_count=_count_words(chunk_text),
                token_estimate=_estimate_tokens(chunk_text),
            ))

            current_chunk_start = end_pos + 2  # Skip delimiter
            current_chunk_chars = 0
            chunk_paragraphs = []

        chunk_paragraphs.append(para)
        current_chunk_chars += para_len

    # Don't forget the last chunk
    if chunk_paragraphs:
        chapter_number += 1
        chunk_text = '\n\n'.join(chunk_paragraphs)
        end_pos = current_chunk_start + len(chunk_text)

        chapters.append(Chapter(
            number=chapter_number,
            title=f"Segment {chapter_number}",
            arc_number=None,
            start_pos=current_chunk_start,
            end_pos=min(end_pos, len(text)),
            word_count=_count_words(chunk_text),
            token_estimate=_estimate_tokens(chunk_text),
        ))

    structure.chapters = chapters
    structure.detection_method = f"fixed-size fallback (~{target_tokens} tokens per segment)"

    log_warning(
        f"No chapter markers detected in '{structure.filename}'. "
        f"Split into {len(chapters)} segments at paragraph boundaries."
    )
