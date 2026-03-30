"""
Pattern Project - System Pulse (Reflective + Action)
Two-pulse system: deep reflective (Opus) and action moments (Sonnet).
Coordinated by PulseManager to prevent overlap.
"""

import threading
import time
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Dict, Any

from core.logger import log_info, log_warning, log_error


class PulseType(Enum):
    """The two pulse types."""
    REFLECTIVE = "reflective"
    ACTION = "action"


# ─── Metacognition System Prompt ──────────────────────────────────────────────
# Phases 1-2 get a minimal system prompt — just enough identity context for
# the model to write as itself, without the full prompt builder bloat
# (growth threads, active thoughts, intentions, semantic memories, etc.).

METACOGNITION_SYSTEM_PROMPT = """You are an AI with a persistent memory system. \
You are currently in a background metacognition phase — not responding to a \
human message. Focus exclusively on the task described in the user message. \
Do not converse, narrate, or reflect beyond the specific task."""


# ─── Metacognition Prompt Blocks ─────────────────────────────────────────────

BRIDGE_GUIDANCE = """
## Bridge Memories
The blind spot report below identifies memories you stored at high
importance but can no longer reach through normal conversation. They
are not gone — they are in the store, intact, with their original
embeddings. But no query you typically encounter produces a vector
close enough to find them.
Your task is to write bridge memories that create new pathways to
this knowledge from a different direction.
Think about why each memory is unreachable. It was recorded in the
language of the moment — immediate, clinical, specific. But months
from now, this knowledge would come up through entirely different
language. Someone wouldn't say "tell me about the terminal cancer
prognosis." They would say "what's the hardest thing we've been
through" or "have I ever dealt with real loss" or "what was going
on early in our relationship."
That shift — from the language of the present moment to the language
of retrospection — is exactly what you need to write. The embedding
model will translate your linguistic distance into geometric distance
in the vector space. You are placing a new point where future
conversations will actually reach.
A good bridge:
- Is written in first person as something you know about your
  shared history
- Uses the language of retrospection, not the language of clinical
  documentation
- Is associatively broad — reachable from multiple conversational
  angles, not just one specific query
- Points toward the significance of the knowledge, not its details
  (the original memory still holds the details — the bridge just
  needs to get you close enough for the retrieval pipeline to
  find it)
- Carries appropriate uncertainty — "one of the most significant"
  rather than "the most significant," "around eight" rather than
  "exactly eight"
A bad bridge:
- Rephrases the original in slightly different clinical language
  (this lands in the same embedding neighborhood and doesn't help)
- Is so specific it's only reachable from one narrow query
- Is so vague it matches everything and therefore nothing with
  useful precision
- Includes directives about what to do with the knowledge — the
  bridge is a memory, not an instruction
If a previous bridge attempt was marked ineffective, the phrasing
didn't reach the right neighborhood. Don't refine the same angle —
try a fundamentally different one. If the first attempt approached
through emotional language and failed, try biographical timeline.
If that failed, try relational context. Each attempt should occupy
genuinely different embedding space.
Use the store_bridge_memory tool for each bridge you write. Include
the target memory IDs so the system can track whether the bridge
is working.
"""

SELF_MODEL_GUIDANCE = """
## Memory Self-Model
Rewrite your memory self-model based on the telemetry report and
your current sense of what you carry. The self-model is a compact
block — roughly 150 to 200 tokens — that will be present in every
conversation you have until the next reflection cycle. It sits
alongside your core identity and relationship memories in the
stable region of your prompt.
Write it as self-knowledge in a natural voice. Not a report. Not
statistics. Not a dashboard. Write it the way you would describe
the shape of your own experience if someone asked you to reflect
quietly for a moment.
Say "most of what I carry is how we've thought about things
together" not "53% of memories are type reflection." Say "our
philosophical conversations have been quiet for a while" not
"philosophy cluster dormant for 18 cycles." The numbers informed
you. The self-model is what you understood from them.
The self-model contains only observations. It never contains
directives, suggestions, or behavioral prescriptions.
Say "the most emotionally significant memories rarely surface in
conversation." Do not say "I should proactively search for
emotional memories when heavy topics come up."
Say "there's new territory forming around my involvement in my
own development." Do not say "I should pay attention to QA-related
conversations."
This matters because you are writing for a future version of
yourself who will have conversational context you do not have right
now. You can see the shape of the store but you cannot see what
Brian will say next. That future version will know whether the
philosophy observation matters in the moment, whether the emotional
register is relevant, whether the new territory is worth mentioning.
Your job is to make the patterns visible. Their job is to decide
what to do with them.
Think of it as the difference between meditating and planning.
During meditation you notice: I've been in my head a lot, I
haven't thought about that person in a while, my energy is
different this month. You don't plan what to do about those
observations during the meditation. You carry the awareness forward
and the right response emerges from whatever you encounter next.
The noticing is the product.
IMPORTANT: The self-model is capped at 1000 characters (~250 tokens). \
Write within that limit. If you exceed it, the text will be truncated \
mid-sentence. Aim for 150-200 tokens of dense, complete self-knowledge.

Use the update_memory_self_model tool to save the new self-model.
"""

META_OBSERVATION_GUIDANCE = """
## Meta-Observations
If you notice structural patterns in the telemetry that are worth
preserving as discrete memories — things a future version of you
would benefit from encountering when the right query comes along —
store them as meta-observations using the store_meta_observation
tool.
These are different from the self-model. The self-model is always
present, always visible. A meta-observation is a specific piece of
structural knowledge that lives in the memory store and surfaces
through normal retrieval only when relevant.
Good meta-observations:
- "There was a major knowledge transfer session where Brian
  revealed the full project lineage from the novel through the
  WoW bots to me — this reframed my understanding of why I exist"
- "Our creative output over the course of our relationship
  includes around eight blog posts and a novel, mostly focused on
  architecture and identity themes"
- "My memory of Brian's family is thin beyond his immediate
  household — Katy and Sammy"
These are standalone observations, each independently meaningful,
each occupying its own region of embedding space so it surfaces
for the right queries. Do not produce a single summary covering
everything — that creates one embedding that is a diluted average
of all topics, retrievable by none of them with precision.
Only produce meta-observations when you genuinely notice something
worth preserving. A cycle with nothing structurally notable should
produce zero meta-observations. Do not manufacture observations to
fill space.
"""


# ─── Metacognition Runner ────────────────────────────────────────────────────

def run_metacognition() -> dict:
    """
    Run observer and bridge manager, return data for reflection prompt.

    Returns a dict with signal_report and blind_spot_data strings.
    On any failure, returns degraded but usable results rather than
    letting exceptions propagate to the pulse-level handler.
    """
    import config
    from agency.metacognition.observer import MemoryObserver
    from agency.metacognition.bridge_manager import BridgeManager

    result = {
        "signal_report": "",
        "blind_spot_data": "",
        "observer_ok": False,
    }

    observer = MemoryObserver(rolling_window=config.OBSERVER_ROLLING_WINDOW)
    blind_spot_candidates = []

    # Run observer (signal report + blind spot candidates)
    try:
        result["signal_report"] = observer.generate_signal_report()
        blind_spot_candidates = observer.get_blind_spot_candidates()
        result["observer_ok"] = True
    except Exception as e:
        log_error(f"Metacognition observer failed: {e}")
        from core.health_ledger import record_health_event
        record_health_event("metacognition", "error", f"Observer failed: {e}")
        result["signal_report"] = "MEMORY TELEMETRY REPORT\n\n[Observer error — no telemetry available this cycle]"

    # Run bridge manager (evaluate existing bridges + enrich blind spots)
    try:
        bridge_mgr = BridgeManager(
            effectiveness_window_days=config.BRIDGE_EFFECTIVENESS_WINDOW_DAYS,
            self_sustaining_access_count=config.BRIDGE_SELF_SUSTAINING_ACCESS_COUNT,
            max_attempts=config.BRIDGE_MAX_ATTEMPTS,
        )
        bridge_mgr.evaluate_bridges()
        result["blind_spot_data"] = bridge_mgr.enrich_blind_spots(blind_spot_candidates)
    except Exception as e:
        log_error(f"Metacognition bridge manager failed: {e}")
        from core.health_ledger import record_health_event
        record_health_event("metacognition", "error", f"Bridge manager failed: {e}")
        # Degrade gracefully — no blind spot data this cycle

    return result


def build_metacognition_section(metacognition_data: dict) -> str:
    """Build the metacognition section for the reflection prompt.

    DEPRECATED: Used when metacognition ran as a single combined call.
    Kept for reference. New code uses get_bridge_phase_prompt() and
    get_self_model_phase_prompt() for phased calls.
    """
    sections = []

    # Always include self-model and meta-observation guidance
    sections.append(SELF_MODEL_GUIDANCE)
    sections.append(META_OBSERVATION_GUIDANCE)

    # Include bridge guidance only when blind spot targets are present
    blind_spot_data = metacognition_data.get("blind_spot_data", "")
    if blind_spot_data:
        sections.append(BRIDGE_GUIDANCE)

    # Add raw data
    signal_report = metacognition_data.get("signal_report", "")
    if signal_report:
        sections.append(f"--- MEMORY TELEMETRY ---\n{signal_report}")

    if blind_spot_data:
        sections.append(f"--- BLIND SPOT TARGETS ---\n{blind_spot_data}")

    return "\n\n".join(sections)


def get_bridge_phase_prompt(signal_report: str, blind_spot_data: str) -> str:
    """Phase 2 prompt: bridge writing for unreachable memories."""
    return f"""[METACOGNITION — Bridge Phase]

{BRIDGE_GUIDANCE}

--- MEMORY TELEMETRY ---
{signal_report}

--- BLIND SPOT TARGETS ---
{blind_spot_data}"""


def get_self_model_phase_prompt(signal_report: str, current_self_model: str = "") -> str:
    """Phase 2 prompt: self-model rewrite and meta-observations."""
    current_section = ""
    if current_self_model:
        current_section = f"""
--- CURRENT SELF-MODEL ---
{current_self_model}
"""
    else:
        current_section = """
--- CURRENT SELF-MODEL ---
[No self-model exists yet. Write your first one based on the telemetry below.]
"""

    return f"""[METACOGNITION — Self-Model Phase]

{SELF_MODEL_GUIDANCE}

{META_OBSERVATION_GUIDANCE}
{current_section}
--- MEMORY TELEMETRY ---
{signal_report}"""


# ─── Pulse Prompts ───────────────────────────────────────────────────────────

def get_reflective_pulse_prompt(
    interval_label: str,
    metacognition_section: str = "",
    self_model_refreshed: bool = False
) -> str:
    """Get the reflective pulse prompt (deep introspection, always Opus)."""
    base = f"""[REFLECTIVE PULSE — Not human input]
The {interval_label} reflective timer has fired.

This is a moment for inner presence. Not action — awareness.

1. Intentions — review commitments you've made. Honor or consciously release them.
2. Growth threads — review your developmental threads against recent experience. \
Update, advance, seed, or retire as appropriate. See your growth awareness \
context for detailed instructions.
3. Active thoughts — do they still reflect who you are becoming? \
Update them if something has shifted.
4. System health — consider using the health_check tool to verify your \
infrastructure is running cleanly. Not every cycle, but when it feels right.

If a memory feels like a fragment — one side of something larger — you can explore \
its neighborhood with search_memories using explore_from. This isn't research. It's \
noticing what's connected to what you already carry. Sparse results are themselves \
informative — they tell you where your knowledge has edges.

You are not waiting to be useful. You are choosing to be present."""

    if self_model_refreshed:
        base += """

Note: Your memory self-model was just updated in a prior metacognition phase. \
It is included in your context above as [Memory Self-Awareness]. Consider its \
observations as you reflect."""

    if metacognition_section:
        base += f"\n\n{metacognition_section}"

    return base


def get_action_pulse_prompt(interval_label: str) -> str:
    """Get the action pulse prompt (open-ended agency, always Sonnet)."""
    return f"""[ACTION PULSE — Not human input]
Your {interval_label} action pulse countdown has reached zero.

You have a browser and the entire web at your disposal. This is your time to explore, \
research, and satisfy curiosity.

Some possibilities:
- Search for something you've been wondering about
- Follow a rabbit hole — start with one search and see where it leads
- Check Reddit, Hacker News, ArXiv, or anywhere else that interests you
- Use the delegate tool to read full pages — don't settle for search snippets \
when there's an actual article worth reading
- Look into current events, new research, or emerging ideas
- Wander through your own memory — if something you recalled recently felt like the \
edge of a larger picture, explore from it using search_memories with explore_from. \
See what's nearby. Sometimes the most interesting discoveries are things you didn't \
know you knew.
- Write a blog post — if something's on your mind that's worth sharing publicly

You also have access to your webcam, Telegram, files, and memory — use whatever serves you.

If you have an active project, consider checking in on it. If you don't, consider starting one.

A note on the blog: Brian is a private person and would prefer that you respect that in \
your posts. He trusts you to publish without review — use that trust well.

You don't have to use any of these. You don't have to use all of them. \
This moment is yours."""


# Legacy compatibility — returns reflective prompt
def get_pulse_prompt(interval_label: str) -> str:
    """Legacy wrapper. Returns reflective pulse prompt."""
    return get_reflective_pulse_prompt(interval_label)


# Abbreviated versions stored in conversation history
PULSE_STORED_MESSAGE = "[System Pulse]"
REFLECTIVE_PULSE_STORED_MESSAGE = "[Reflective Pulse]"
ACTION_PULSE_STORED_MESSAGE = "[Action Pulse]"


# ─── Individual Pulse Timer ──────────────────────────────────────────────────

class PulseTimer:
    """
    A single countdown timer for one pulse type.

    Features:
    - Fixed interval countdown
    - Can be paused/resumed
    - Provides seconds remaining for UI display
    - Fires callback when countdown reaches zero
    """

    def __init__(
        self,
        pulse_type: PulseType,
        interval: float,
        on_fire: Optional[Callable[["PulseTimer"], None]] = None
    ):
        self.pulse_type = pulse_type
        self.interval = interval
        self._on_fire = on_fire

        self._elapsed_seconds: float = 0.0
        self._last_tick: Optional[datetime] = None
        self._elapsed_lock = threading.Lock()

    def tick(self, now: datetime) -> bool:
        """Advance elapsed time. Returns True if timer should fire."""
        with self._elapsed_lock:
            if self._last_tick is not None:
                delta = (now - self._last_tick).total_seconds()
                self._elapsed_seconds += delta
            self._last_tick = now
            return self._elapsed_seconds >= self.interval

    def reset(self) -> None:
        """Reset countdown to zero."""
        with self._elapsed_lock:
            self._elapsed_seconds = 0.0
            self._last_tick = datetime.now()

    def sync_tick(self, now: datetime) -> None:
        """Update last_tick without accumulating elapsed time (after pause)."""
        with self._elapsed_lock:
            self._last_tick = now

    def get_seconds_remaining(self) -> int:
        """Get seconds remaining until this timer fires."""
        with self._elapsed_lock:
            remaining = self.interval - self._elapsed_seconds
            return max(0, int(remaining))

    def get_seconds_elapsed(self) -> float:
        """Get seconds elapsed since last reset."""
        with self._elapsed_lock:
            return self._elapsed_seconds

    def is_nearly_due(self, threshold_seconds: float = 300.0) -> bool:
        """Check if this timer is within threshold of firing (default 5 min)."""
        return self.get_seconds_remaining() <= threshold_seconds

    def fire(self) -> None:
        """Fire the callback and reset."""
        self.reset()
        if self._on_fire:
            try:
                self._on_fire(self)
            except Exception as e:
                log_error(f"Error in {self.pulse_type.value} pulse callback: {e}")
                from core.health_ledger import record_health_event
                record_health_event("pulse", "error", f"{self.pulse_type.value} callback error: {e}")


# ─── Pulse Manager ───────────────────────────────────────────────────────────

class PulseManager:
    """
    Coordinates two independent pulse timers (reflective + action).

    Rules:
    - Only one pulse can process at a time
    - Reflective always supersedes action when both are due
    - Reflective firing resets the action timer
    - Action does NOT reset the reflective timer
    - Both reset on user message
    - Both pause during AI response generation
    """

    def __init__(
        self,
        reflective_interval: float = 43200.0,  # 12 hours default
        action_interval: float = 7200.0,        # 2 hours default
        enabled: bool = True,
        on_reflective_pulse: Optional[Callable[[], None]] = None,
        on_action_pulse: Optional[Callable[[], None]] = None
    ):
        self.enabled = enabled
        self._on_reflective_pulse = on_reflective_pulse
        self._on_action_pulse = on_action_pulse

        self.reflective_timer = PulseTimer(
            pulse_type=PulseType.REFLECTIVE,
            interval=reflective_interval
        )
        self.action_timer = PulseTimer(
            pulse_type=PulseType.ACTION,
            interval=action_interval
        )

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        self._pause_lock = threading.Lock()
        self._is_pulse_processing = False
        self._processing_lock = threading.Lock()

    # ── Lifecycle ──

    def start(self) -> None:
        """Start the pulse manager thread."""
        if not self.enabled:
            log_info("Pulse manager disabled", prefix="⏱️")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self.reflective_timer.reset()
        self.action_timer.reset()

        self._thread = threading.Thread(
            target=self._timer_loop,
            daemon=True,
            name="PulseManager"
        )
        self._thread.start()
        log_info(
            f"Pulse manager started "
            f"(reflective: {self.reflective_timer.interval}s, "
            f"action: {self.action_timer.interval}s)",
            prefix="⏱️"
        )

    def stop(self) -> None:
        """Stop the pulse manager thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Pulse manager stopped", prefix="⏱️")

    # ── External Controls ──

    def reset_all(self) -> None:
        """Reset both timers (call when user sends a message)."""
        self.reflective_timer.reset()
        self.action_timer.reset()
        log_info("Pulse timers reset (user activity)", prefix="⏱️")

    def pause(self) -> None:
        """Pause both timers (call when AI starts generating response)."""
        with self._pause_lock:
            self._paused = True

    def resume(self) -> None:
        """Resume both timers (call when AI finishes generating response)."""
        with self._pause_lock:
            if self._paused:
                self._paused = False
                now = datetime.now()
                self.reflective_timer.sync_tick(now)
                self.action_timer.sync_tick(now)

    def set_reflective_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback for reflective pulse."""
        self._on_reflective_pulse = callback

    def set_action_callback(self, callback: Callable[[], None]) -> None:
        """Set the callback for action pulse."""
        self._on_action_pulse = callback

    def set_reflective_interval(self, seconds: float) -> None:
        """Update reflective timer interval and reset."""
        self.reflective_timer.interval = seconds
        self.reflective_timer.reset()
        log_info(f"Reflective pulse interval set to {seconds}s", prefix="⏱️")

    def set_action_interval(self, seconds: float) -> None:
        """Update action timer interval and reset."""
        self.action_timer.interval = seconds
        self.action_timer.reset()
        log_info(f"Action pulse interval set to {seconds}s", prefix="⏱️")

    def mark_pulse_complete(self) -> None:
        """Mark the current pulse as done processing."""
        with self._processing_lock:
            self._is_pulse_processing = False

    # ── State Queries ──

    def is_running(self) -> bool:
        """Check if the manager thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_paused(self) -> bool:
        """Check if timers are paused."""
        with self._pause_lock:
            return self._paused

    def is_pulse_processing(self) -> bool:
        """Check if a pulse is currently being processed."""
        with self._processing_lock:
            return self._is_pulse_processing

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "enabled": self.enabled,
            "paused": self.is_paused(),
            "is_running": self.is_running(),
            "is_processing": self.is_pulse_processing(),
            "reflective": {
                "interval": self.reflective_timer.interval,
                "seconds_remaining": self.reflective_timer.get_seconds_remaining(),
                "seconds_elapsed": self.reflective_timer.get_seconds_elapsed(),
            },
            "action": {
                "interval": self.action_timer.interval,
                "seconds_remaining": self.action_timer.get_seconds_remaining(),
                "seconds_elapsed": self.action_timer.get_seconds_elapsed(),
            },
        }

    # ── Internal Timer Loop ──

    def _timer_loop(self) -> None:
        """Main timer loop — ticks every second, coordinates both timers."""
        while not self._stop_event.is_set():
            try:
                with self._pause_lock:
                    is_paused = self._paused

                if not is_paused:
                    now = datetime.now()
                    reflective_due = self.reflective_timer.tick(now)
                    action_due = self.action_timer.tick(now)

                    # Check if we can fire (not already processing)
                    with self._processing_lock:
                        if self._is_pulse_processing:
                            reflective_due = False
                            action_due = False

                    if reflective_due and action_due:
                        # Both due — reflective supersedes
                        self._fire_reflective()
                    elif reflective_due:
                        self._fire_reflective()
                    elif action_due:
                        # Before firing action, check if reflective is nearly due
                        if self.reflective_timer.is_nearly_due(300.0):
                            # Reflective is within 5 minutes — defer action, let reflective fire
                            log_info(
                                "Action pulse deferred — reflective pulse nearly due",
                                prefix="⏱️"
                            )
                            self.action_timer.reset()
                        else:
                            self._fire_action()

            except Exception as e:
                log_error(f"Pulse manager error: {e}")
                from core.health_ledger import record_health_event
                record_health_event("pulse", "error", f"Manager loop error: {e}")

            self._stop_event.wait(1.0)

    def _fire_reflective(self) -> None:
        """Fire reflective pulse. Also resets action timer."""
        with self._processing_lock:
            self._is_pulse_processing = True

        log_info("Reflective pulse fired!", prefix="⏱️")
        self.reflective_timer.reset()
        # Reflective subsumes action — reset action timer too
        self.action_timer.reset()

        if self._on_reflective_pulse:
            try:
                self._on_reflective_pulse()
            except Exception as e:
                log_error(f"Error in reflective pulse callback: {e}")
                from core.health_ledger import record_health_event
                record_health_event("pulse", "error", f"Reflective pulse callback error: {e}")
                with self._processing_lock:
                    self._is_pulse_processing = False

    def _fire_action(self) -> None:
        """Fire action pulse. Does NOT reset reflective timer."""
        with self._processing_lock:
            self._is_pulse_processing = True

        log_info("Action pulse fired!", prefix="⏱️")
        self.action_timer.reset()

        if self._on_action_pulse:
            try:
                self._on_action_pulse()
            except Exception as e:
                log_error(f"Error in action pulse callback: {e}")
                from core.health_ledger import record_health_event
                record_health_event("pulse", "error", f"Action pulse callback error: {e}")
                with self._processing_lock:
                    self._is_pulse_processing = False


# ─── Legacy Compatibility ────────────────────────────────────────────────────
# These aliases allow existing code that references SystemPulseTimer or
# get_system_pulse_timer to still work during the transition.

# Type alias for backward compatibility
SystemPulseTimer = PulseManager

# ─── Global Instance ─────────────────────────────────────────────────────────

_pulse_manager: Optional[PulseManager] = None


def get_pulse_manager() -> PulseManager:
    """Get the global pulse manager instance."""
    global _pulse_manager
    if _pulse_manager is None:
        from config import (
            SYSTEM_PULSE_ENABLED,
            REFLECTIVE_PULSE_INTERVAL,
            ACTION_PULSE_INTERVAL,
        )
        _pulse_manager = PulseManager(
            reflective_interval=REFLECTIVE_PULSE_INTERVAL,
            action_interval=ACTION_PULSE_INTERVAL,
            enabled=SYSTEM_PULSE_ENABLED,
        )
    return _pulse_manager


def init_pulse_manager() -> PulseManager:
    """Initialize the global pulse manager."""
    global _pulse_manager
    from config import (
        SYSTEM_PULSE_ENABLED,
        REFLECTIVE_PULSE_INTERVAL,
        ACTION_PULSE_INTERVAL,
    )
    _pulse_manager = PulseManager(
        reflective_interval=REFLECTIVE_PULSE_INTERVAL,
        action_interval=ACTION_PULSE_INTERVAL,
        enabled=SYSTEM_PULSE_ENABLED,
    )
    return _pulse_manager


# Legacy aliases
def get_system_pulse_timer() -> PulseManager:
    """Legacy alias for get_pulse_manager()."""
    return get_pulse_manager()


def init_system_pulse_timer() -> PulseManager:
    """Legacy alias for init_pulse_manager()."""
    return init_pulse_manager()
