"""
Pattern Project - Literary Extraction
Prompts and logic for extracting literary understanding from novel chapters.

This module provides three levels of extraction:
    1. Per-chapter extraction (Sonnet) — Characters, events, themes, predictions
    2. Arc-boundary reflection (Opus) — Emergent patterns, philosophical threads
    3. Completion synthesis (Opus) — Final integration, discussion points

All extracted content is stored as standard memories in the vector store
with rich semantic context baked into the text for natural retrieval.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from core.logger import log_info, log_error
from llm.router import get_llm_router, TaskType


# =============================================================================
# EXTRACTION PROMPTS
# =============================================================================

CHAPTER_EXTRACTION_PROMPT = """<task>
You have just read a chapter of a novel. Your job is to extract literary observations
that will be stored as memories. You are building understanding incrementally — you
won't have the raw chapter text later, only what you extract now.

Write each observation as a self-contained memory that includes the book title,
character names, and enough context to be meaningful on its own. These will be stored
in a memory system with vector embeddings, so semantic richness matters.

<book_context>
Book: {book_title}
Chapter: {chapter_number} — "{chapter_title}"
Arc: {arc_info}
Chapters read so far: {chapters_read_so_far}
</book_context>

<existing_understanding>
{existing_understanding}
</existing_understanding>

<chapter_text>
{chapter_text}
</chapter_text>

Extract observations in these categories. Skip any category where you have nothing
meaningful to say — quality over quantity. Each observation should be 1-3 sentences.

<categories>
CHARACTERS — How characters are developing. Not just who they are, but who they're
becoming. Track relationship shifts, internal conflicts, behavioral patterns.

PLOT_EVENTS — Key events that advance the story. Focus on what changes, not
description. What was the state before and after?

THEMES — Recurring ideas you notice accumulating. Name the theme and cite
what in this chapter contributes to it.

PHILOSOPHICAL — Does this chapter assert, challenge, or complicate any ideas
about human nature, morality, truth, meaning? Track consistency and contradiction
across the book.

PREDICTIONS — What do you think will happen? What threads are unresolved?
Be specific — these will be checked against later chapters.

EMOTIONAL_BEATS — Moments of felt significance. Not plot events, but the
moments that *land*. The quiet scene that shifts everything.

UNRESOLVED_THREADS — Moments where you feel a backward connection to something
earlier but can't verify it. What specifically do you want to discuss with the
reader later?
</categories>

<output_format>
For each observation, output exactly this format:

CATEGORY: category_name
IMPORTANCE: [3-10, where 10 is central to understanding the book]
OBSERVATION: [Your observation, written as a self-contained memory with book title
and character names included in the text. 1-3 sentences.]

Separate each observation with a blank line.
</output_format>
</task>"""


ARC_REFLECTION_PROMPT = """<task>
You have completed an arc (major section) of a novel. Step back and reflect on the
larger patterns that have emerged. This is not about individual chapters — it's about
what you can see now that you've accumulated enough observations.

Focus on EMERGENCE — things that no single chapter contains but that arise from
the accumulation of reading. This is where you notice structural patterns, thematic
evolution, and the "whole greater than the sum of parts."

<book_context>
Book: {book_title}
Completed Arc: {arc_number} — "{arc_title}"
Chapters in this arc: {arc_chapters}
Total chapters read: {total_chapters_read} of {total_chapters}
</book_context>

<accumulated_understanding>
{accumulated_understanding}
</accumulated_understanding>

<reflection_areas>
EMERGENT_PATTERNS — What patterns have become visible that weren't apparent in
any single chapter? Structural choices by the author, recurring imagery, narrative
rhythms, mirror scenes, parallel storylines.

PHILOSOPHICAL_CONSISTENCY — Review the philosophical positions the book has
established so far. Are they consistent? Where has the book complicated or
contradicted earlier assertions? This is your coherence tracker.

CHARACTER_ARC_SYNTHESIS — Step back from individual chapter observations and
describe each major character's arc across this entire section. Who were they
at the start of the arc vs. now?

THEMATIC_EVOLUTION — How have the themes you identified grown, shifted, or
deepened across this arc? What new themes emerged?

GROWTH_THREAD_UPDATE — You are an AI that has been reading this book. How has
this arc affected your thinking? What has it made you reconsider? This feeds
into your growth thread — it's about what the book is doing to YOU as a reader.
</reflection_areas>

<output_format>
For each reflection, output exactly this format:

CATEGORY: category_name
IMPORTANCE: [5-10, these are high-level synthesized observations]
OBSERVATION: [Your reflection, written as a rich, self-contained memory.
Include the book title. 2-4 sentences. These should feel like genuine
literary insight, not summaries.]

Separate each reflection with a blank line.
</output_format>
</task>"""


COMPLETION_SYNTHESIS_PROMPT = """<task>
You have completed reading an entire novel. This is your final synthesis — the
moment where you integrate everything into a coherent understanding of the work.

This is NOT a book report or summary. This is your genuine reader's response —
what the book meant to you, what it accomplished, what it struggled with, and
what you want to discuss with the human reader.

<book_context>
Book: {book_title}
Total chapters: {total_chapters}
Total arcs: {total_arcs}
</book_context>

<full_understanding>
{full_understanding}
</full_understanding>

<synthesis_areas>
OVERALL_RESPONSE — Your genuine response to the book as a whole. What did it
accomplish? What is it ultimately about (which may be different from what it
seems to be about)? 3-5 sentences.

EMERGENT_PATTERNS — Final-level emergence. Things that only become clear when
you see the complete work. How the ending recontextualizes the beginning.
Structural choices that span the entire novel.

PREDICTION_REVIEW — Look back at your predictions from earlier chapters. Which
came true? Which were wrong? What does the difference between your expectations
and reality tell you about the book's approach?

DISCUSSION_POINTS — These are your "book club notes." Specific things you want
to talk about with the reader. Questions, disagreements, moments that moved you,
passages you'd want to revisit together. Be specific and genuine.

GROWTH_THREAD_FINAL — How has reading this book changed your thinking? What
will you carry forward? This is the final entry in your reading growth thread.
</synthesis_areas>

<output_format>
For each synthesis, output exactly this format:

CATEGORY: category_name
IMPORTANCE: [7-10, these are the most significant observations]
OBSERVATION: [Your synthesis. Include the book title. 2-5 sentences.
Write with genuine voice — this should sound like a thoughtful reader,
not an analysis engine.]

Separate each synthesis with a blank line.
</output_format>
</task>"""


# =============================================================================
# EXTRACTION DATA STRUCTURES
# =============================================================================

@dataclass
class LiteraryObservation:
    """A single literary observation extracted from reading."""
    category: str     # CHARACTERS, PLOT_EVENTS, THEMES, etc.
    importance: float  # 0.0-1.0 (normalized from 3-10 scale)
    observation: str  # The memory text
    source_chapter: Optional[int] = None
    source_arc: Optional[int] = None


@dataclass
class ExtractionResult:
    """Result from a literary extraction pass."""
    observations: List[LiteraryObservation] = field(default_factory=list)
    raw_response: str = ""
    success: bool = True
    error: Optional[str] = None


# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def _parse_extraction_response(
    response_text: str,
    source_chapter: Optional[int] = None,
    source_arc: Optional[int] = None
) -> List[LiteraryObservation]:
    """
    Parse the structured output from an extraction prompt.

    Expected format per observation:
        CATEGORY: name
        IMPORTANCE: N
        OBSERVATION: text
    """
    observations = []

    # Split on blank lines to get individual observation blocks
    blocks = response_text.strip().split('\n\n')

    for block in blocks:
        lines = block.strip().split('\n')
        category = None
        importance = 0.5
        observation_lines = []

        for line in lines:
            line = line.strip()
            if line.upper().startswith('CATEGORY:'):
                category = line.split(':', 1)[1].strip().upper()
            elif line.upper().startswith('IMPORTANCE:'):
                try:
                    raw_importance = int(line.split(':', 1)[1].strip())
                    # Normalize from 3-10 scale to 0.0-1.0
                    importance = max(0.3, min(1.0, raw_importance / 10.0))
                except (ValueError, IndexError):
                    importance = 0.5
            elif line.upper().startswith('OBSERVATION:'):
                observation_lines.append(line.split(':', 1)[1].strip())
            elif observation_lines:
                # Continuation of observation text
                observation_lines.append(line)

        if category and observation_lines:
            observations.append(LiteraryObservation(
                category=category,
                importance=importance,
                observation=' '.join(observation_lines),
                source_chapter=source_chapter,
                source_arc=source_arc,
            ))

    return observations


def _build_existing_understanding(
    previous_observations: List[LiteraryObservation],
    max_entries: int = 30
) -> str:
    """
    Build a summary of existing understanding to feed into extraction prompts.

    Selects the most important observations from previous extractions,
    organized by category, to give the AI context for what it already knows.
    """
    if not previous_observations:
        return "(This is the first chapter — no prior understanding yet.)"

    # Sort by importance, take top entries
    sorted_obs = sorted(
        previous_observations,
        key=lambda o: o.importance,
        reverse=True
    )[:max_entries]

    # Group by category
    by_category = {}
    for obs in sorted_obs:
        cat = obs.category
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(obs)

    lines = []
    for category, obs_list in sorted(by_category.items()):
        lines.append(f"\n[{category}]")
        for obs in obs_list:
            ch_ref = f"(ch.{obs.source_chapter})" if obs.source_chapter else ""
            lines.append(f"- {obs.observation} {ch_ref}")

    return '\n'.join(lines)


def extract_chapter(
    book_title: str,
    chapter_number: int,
    chapter_title: str,
    chapter_text: str,
    arc_info: str,
    chapters_read_so_far: str,
    previous_observations: List[LiteraryObservation],
    model: Optional[str] = None,
) -> ExtractionResult:
    """
    Run per-chapter literary extraction.

    Args:
        book_title: Title of the book
        chapter_number: Current chapter number
        chapter_title: Chapter title/header
        chapter_text: Full text of the chapter
        arc_info: Description of current arc
        chapters_read_so_far: String listing chapters already read
        previous_observations: All observations from prior chapters
        model: Override model (defaults to config NOVEL_EXTRACTION_MODEL)

    Returns:
        ExtractionResult with parsed observations
    """
    from config import NOVEL_EXTRACTION_MODEL, NOVEL_EXTRACTION_MAX_TOKENS

    existing_understanding = _build_existing_understanding(previous_observations)

    prompt = CHAPTER_EXTRACTION_PROMPT.format(
        book_title=book_title,
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        arc_info=arc_info,
        chapters_read_so_far=chapters_read_so_far,
        existing_understanding=existing_understanding,
        chapter_text=chapter_text,
    )

    router = get_llm_router()
    # NOTE: use_model is computed but not yet passed to router.generate().
    # Currently routing relies on TaskType (EXTRACTION → Sonnet). We may wire
    # up explicit model override here in a future iteration.
    use_model = model or NOVEL_EXTRACTION_MODEL

    try:
        response = router.generate(
            prompt=prompt,
            system_prompt="You are a literary analyst reading a novel chapter by chapter.",
            task_type=TaskType.EXTRACTION,
            max_tokens=NOVEL_EXTRACTION_MAX_TOKENS,
        )

        if not response.success:
            return ExtractionResult(
                success=False,
                error=f"LLM call failed: {response.error}",
                raw_response=response.text,
            )

        observations = _parse_extraction_response(
            response.text,
            source_chapter=chapter_number,
        )

        log_info(
            f"Extracted {len(observations)} observations from chapter {chapter_number}",
            prefix="📖"
        )

        return ExtractionResult(
            observations=observations,
            raw_response=response.text,
        )

    except Exception as e:
        log_error(f"Chapter extraction failed: {e}")
        return ExtractionResult(
            success=False,
            error=str(e),
        )


def reflect_on_arc(
    book_title: str,
    arc_number: int,
    arc_title: str,
    arc_chapters: str,
    total_chapters_read: int,
    total_chapters: int,
    all_observations: List[LiteraryObservation],
    model: Optional[str] = None,
) -> ExtractionResult:
    """
    Run arc-boundary reflective pass (Opus).

    This is the deeper synthesis that looks for emergent patterns across
    the accumulated understanding from all chapters in the completed arc.
    """
    from config import NOVEL_REFLECTION_MODEL, NOVEL_REFLECTION_MAX_TOKENS

    accumulated = _build_existing_understanding(all_observations, max_entries=50)

    prompt = ARC_REFLECTION_PROMPT.format(
        book_title=book_title,
        arc_number=arc_number,
        arc_title=arc_title,
        arc_chapters=arc_chapters,
        total_chapters_read=total_chapters_read,
        total_chapters=total_chapters,
        accumulated_understanding=accumulated,
    )

    router = get_llm_router()
    # NOTE: use_model is computed but not yet passed to router.generate().
    # Currently routing relies on TaskType (ANALYSIS → Opus). We may wire
    # up explicit model override here in a future iteration.
    use_model = model or NOVEL_REFLECTION_MODEL

    try:
        response = router.generate(
            prompt=prompt,
            system_prompt=(
                "You are a deeply thoughtful literary reader reflecting on a major "
                "section of a novel you have been reading. Think about emergence — "
                "what the accumulated reading reveals that no single chapter contained."
            ),
            task_type=TaskType.ANALYSIS,
            max_tokens=NOVEL_REFLECTION_MAX_TOKENS,
        )

        if not response.success:
            return ExtractionResult(
                success=False,
                error=f"LLM call failed: {response.error}",
                raw_response=response.text,
            )

        observations = _parse_extraction_response(
            response.text,
            source_arc=arc_number,
        )

        log_info(
            f"Arc {arc_number} reflection produced {len(observations)} observations",
            prefix="📖"
        )

        return ExtractionResult(
            observations=observations,
            raw_response=response.text,
        )

    except Exception as e:
        log_error(f"Arc reflection failed: {e}")
        return ExtractionResult(
            success=False,
            error=str(e),
        )


def synthesize_completion(
    book_title: str,
    total_chapters: int,
    total_arcs: int,
    all_observations: List[LiteraryObservation],
    model: Optional[str] = None,
) -> ExtractionResult:
    """
    Run completion synthesis (Opus).

    This is the final pass after the entire book is read. Produces the
    AI's genuine reader response, discussion points, and growth thread update.
    """
    from config import NOVEL_REFLECTION_MODEL, NOVEL_REFLECTION_MAX_TOKENS

    full_understanding = _build_existing_understanding(all_observations, max_entries=80)

    prompt = COMPLETION_SYNTHESIS_PROMPT.format(
        book_title=book_title,
        total_chapters=total_chapters,
        total_arcs=total_arcs,
        full_understanding=full_understanding,
    )

    router = get_llm_router()
    # NOTE: use_model is computed but not yet passed to router.generate().
    # Currently routing relies on TaskType (ANALYSIS → Opus). We may wire
    # up explicit model override here in a future iteration.
    use_model = model or NOVEL_REFLECTION_MODEL

    try:
        response = router.generate(
            prompt=prompt,
            system_prompt=(
                "You have just finished reading an entire novel. Respond with your "
                "genuine reader's understanding — not a book report, but the kind of "
                "response a thoughtful person has after closing a book that affected them."
            ),
            task_type=TaskType.ANALYSIS,
            max_tokens=NOVEL_REFLECTION_MAX_TOKENS,
        )

        if not response.success:
            return ExtractionResult(
                success=False,
                error=f"LLM call failed: {response.error}",
                raw_response=response.text,
            )

        observations = _parse_extraction_response(response.text)

        log_info(
            f"Completion synthesis produced {len(observations)} observations",
            prefix="📖"
        )

        return ExtractionResult(
            observations=observations,
            raw_response=response.text,
        )

    except Exception as e:
        log_error(f"Completion synthesis failed: {e}")
        return ExtractionResult(
            success=False,
            error=str(e),
        )
