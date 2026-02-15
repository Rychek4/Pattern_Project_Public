"""
Pattern Project - Proactive Agency System
Allows the AI to initiate conversation rather than just respond
"""

import threading
import time
from datetime import datetime
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from core.logger import log_info, log_warning, log_error
from core.temporal import get_temporal_tracker
from memory.conversation import get_conversation_manager
from memory.vector_store import get_vector_store
from llm.router import get_llm_router, TaskType


class TriggerType(Enum):
    """Types of proactive triggers."""
    IDLE = "idle"           # User has been idle
    REFLECTION = "reflection"  # After memory extraction
    CURIOSITY = "curiosity"   # Based on incomplete information
    GREETING = "greeting"     # Time-based greeting
    REMINDER = "reminder"     # Scheduled reminder


@dataclass
class ProactiveTrigger:
    """A proactive conversation trigger."""
    trigger_type: TriggerType
    message: str
    priority: int = 0
    metadata: Optional[Dict[str, Any]] = None


class ProactiveAgent:
    """
    Agent that monitors for opportunities to initiate conversation.

    Triggers:
    - Idle trigger: No conversation for X minutes
    - Reflection trigger: Share insights after memory extraction
    - Curiosity trigger: Ask about incomplete memories
    """

    def __init__(
        self,
        check_interval: float = 300.0,
        idle_trigger_seconds: float = 900.0,
        enabled: bool = True
    ):
        """
        Initialize the proactive agent.

        Args:
            check_interval: Seconds between trigger checks
            idle_trigger_seconds: Seconds of idle before triggering
            enabled: Whether proactive behavior is enabled
        """
        self.check_interval = check_interval
        self.idle_trigger_seconds = idle_trigger_seconds
        self.enabled = enabled

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._paused = False
        self._last_proactive_time: Optional[datetime] = None
        self._pending_triggers: List[ProactiveTrigger] = []
        self._trigger_callback: Optional[Callable[[ProactiveTrigger], None]] = None

    def start(self) -> None:
        """Start the proactive agent thread."""
        if not self.enabled:
            log_info("Proactive agent disabled", prefix="🗣️")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="ProactiveAgent"
        )
        self._thread.start()
        log_info("Proactive agent started", prefix="🗣️")

    def stop(self) -> None:
        """Stop the proactive agent thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        log_info("Proactive agent stopped", prefix="🗣️")

    def pause(self) -> None:
        """Pause proactive triggers."""
        self._paused = True
        log_info("Proactive agent paused", prefix="🗣️")

    def resume(self) -> None:
        """Resume proactive triggers."""
        self._paused = False
        log_info("Proactive agent resumed", prefix="🗣️")

    def set_trigger_callback(self, callback: Callable[[ProactiveTrigger], None]) -> None:
        """Set the callback for when triggers fire."""
        self._trigger_callback = callback

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while not self._stop_event.is_set():
            try:
                if not self._paused:
                    self._check_triggers()

            except Exception as e:
                log_error(f"Proactive agent error: {e}")

            self._stop_event.wait(self.check_interval)

    def _check_triggers(self) -> None:
        """Check all trigger conditions."""
        tracker = get_temporal_tracker()

        if not tracker.is_session_active:
            return

        # Check cooldown (don't trigger too frequently)
        if self._last_proactive_time:
            time_since_last = (datetime.now() - self._last_proactive_time).total_seconds()
            if time_since_last < self.check_interval:
                return

        # Check idle trigger
        idle_seconds = tracker.get_idle_seconds()
        if idle_seconds >= self.idle_trigger_seconds:
            self._fire_idle_trigger(idle_seconds)

    def _fire_idle_trigger(self, idle_seconds: float) -> None:
        """Fire an idle trigger."""
        # Generate a contextual idle message
        trigger = self._generate_idle_trigger(idle_seconds)

        if trigger and self._trigger_callback:
            self._last_proactive_time = datetime.now()
            self._trigger_callback(trigger)

    def _generate_idle_trigger(self, idle_seconds: float) -> Optional[ProactiveTrigger]:
        """Generate an appropriate idle trigger message."""
        try:
            router = get_llm_router()
            vector_store = get_vector_store()

            # Get recent memories for context
            recent_memories = vector_store.search(
                "recent conversation topics and interests",
                limit=3
            )

            memory_context = ""
            if recent_memories:
                memory_context = "Recent context: " + "; ".join(
                    [r.memory.content for r in recent_memories]
                )

            idle_minutes = idle_seconds / 60

            prompt = f"""You are an AI companion. It has been {idle_minutes:.0f} minutes since the last message.
{memory_context}

Generate a brief, natural message to re-engage the conversation. This could be:
- A thoughtful observation or question
- Following up on a previous topic
- Sharing something interesting
- A gentle check-in

Keep it concise (1-2 sentences). Be natural, not needy.
Respond with just the message, no explanation."""

            response = router.generate(
                prompt=prompt,
                task_type=TaskType.SIMPLE,
                max_tokens=100,
                temperature=0.8
            )

            if response.success and response.text:
                return ProactiveTrigger(
                    trigger_type=TriggerType.IDLE,
                    message=response.text.strip(),
                    priority=1,
                    metadata={"idle_seconds": idle_seconds}
                )

        except Exception as e:
            log_error(f"Failed to generate idle trigger: {e}")

        return None

    def trigger_reflection(self, memories_extracted: int) -> None:
        """
        Trigger a reflection after memory extraction.

        Args:
            memories_extracted: Number of memories just extracted
        """
        if not self.enabled or self._paused:
            return

        try:
            router = get_llm_router()
            vector_store = get_vector_store()

            # Get the recently extracted memories
            recent_memories = vector_store.search(
                "recently extracted insights",
                limit=min(memories_extracted, 3)
            )

            if not recent_memories:
                return

            memory_text = "\n".join([
                f"- {r.memory.content}" for r in recent_memories
            ])

            prompt = f"""You just processed our conversation and extracted these insights:
{memory_text}

Generate a brief reflection or observation about what you learned. Be thoughtful but concise (1-2 sentences).
Respond with just the reflection, no explanation."""

            response = router.generate(
                prompt=prompt,
                task_type=TaskType.SIMPLE,
                max_tokens=100,
                temperature=0.7
            )

            if response.success and response.text and self._trigger_callback:
                trigger = ProactiveTrigger(
                    trigger_type=TriggerType.REFLECTION,
                    message=response.text.strip(),
                    priority=2,
                    metadata={"memories_extracted": memories_extracted}
                )
                self._last_proactive_time = datetime.now()
                self._trigger_callback(trigger)

        except Exception as e:
            log_error(f"Failed to trigger reflection: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        return {
            "enabled": self.enabled,
            "paused": self._paused,
            "is_running": self._thread is not None and self._thread.is_alive(),
            "check_interval": self.check_interval,
            "idle_trigger_seconds": self.idle_trigger_seconds,
            "last_proactive_time": self._last_proactive_time.isoformat() if self._last_proactive_time else None
        }


# Global proactive agent instance
_proactive_agent: Optional[ProactiveAgent] = None


def get_proactive_agent() -> ProactiveAgent:
    """Get the global proactive agent instance."""
    global _proactive_agent
    if _proactive_agent is None:
        from config import AGENCY_ENABLED, AGENCY_CHECK_INTERVAL, AGENCY_IDLE_TRIGGER_SECONDS
        _proactive_agent = ProactiveAgent(
            check_interval=AGENCY_CHECK_INTERVAL,
            idle_trigger_seconds=AGENCY_IDLE_TRIGGER_SECONDS,
            enabled=AGENCY_ENABLED
        )
    return _proactive_agent


def init_proactive_agent() -> ProactiveAgent:
    """Initialize the global proactive agent."""
    global _proactive_agent
    from config import AGENCY_ENABLED, AGENCY_CHECK_INTERVAL, AGENCY_IDLE_TRIGGER_SECONDS
    _proactive_agent = ProactiveAgent(
        check_interval=AGENCY_CHECK_INTERVAL,
        idle_trigger_seconds=AGENCY_IDLE_TRIGGER_SECONDS,
        enabled=AGENCY_ENABLED
    )
    return _proactive_agent
