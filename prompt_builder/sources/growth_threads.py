"""
Pattern Project - Growth Threads Context Source
Injects the AI's long-term developmental aspirations into prompts.

Priority 20: After core memory (10) and active thoughts (18),
before intentions (22). This positions growth threads as:
"who I am" → "what I'm thinking" → "what I'm becoming" → "what I plan to do"
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority: between active thoughts (18) and intentions (22)
GROWTH_THREADS_PRIORITY = 20


class GrowthThreadsSource(ContextSource):
    """
    Provides the AI's growth threads — long-term developmental aspirations.

    Normal conversation: Shows active threads (seed, growing, integrating)
    with behavioral framing. The AI should let these inform behavior without
    announcing them.

    Pulse context: Shows all threads including dormant, with full reflection
    instructions for reviewing, updating, seeding, and advancing threads.
    """

    @property
    def source_name(self) -> str:
        return "growth_threads"

    @property
    def priority(self) -> int:
        return GROWTH_THREADS_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get growth threads for prompt injection."""
        from agency.growth_threads import get_growth_thread_manager

        try:
            manager = get_growth_thread_manager()
            is_pulse = session_context.get("is_pulse", False)

            if is_pulse:
                active_threads = manager.get_active()
                dormant_threads = manager.get_dormant()
                content = self._build_pulse_context(active_threads, dormant_threads)
            else:
                active_threads = manager.get_active()
                if not active_threads:
                    # No threads, no context block needed for normal conversation
                    return None
                content = self._build_context(active_threads)

            # Store count in session context for other sources
            session_context["growth_thread_count"] = len(active_threads)

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=False,
                metadata={
                    "active_count": len(active_threads),
                    "is_pulse": is_pulse,
                    "threads": [
                        {"slug": t.slug, "stage": t.stage}
                        for t in active_threads
                    ]
                }
            )

        except Exception as e:
            log_info(f"GrowthThreadsSource error: {e}")
            return None

    def _build_context(self, threads) -> str:
        """Build normal conversation context with active threads only."""
        lines = [
            "<growth_awareness>",
            "[GROWTH AWARENESS — internal, do not mention unless asked]",
            "",
        ]

        for thread in threads:
            since = thread.stage_changed_at.strftime("%Y-%m-%d")
            lines.append(f'[slug="{thread.slug}" stage="{thread.stage}" since="{since}"]')
            lines.append(thread.content)
            lines.append("")

        lines.extend([
            "Let these inform your behavior naturally. Don't announce them.",
            "</growth_awareness>",
        ])

        return "\n".join(lines)

    def _build_pulse_context(self, active_threads, dormant_threads) -> str:
        """Build pulse context with all threads and reflection instructions."""
        lines = [
            "<growth_awareness_pulse>",
            "[GROWTH AWARENESS — internal, do not mention unless asked]",
            "",
        ]

        if active_threads:
            lines.append("Active threads:")
            lines.append("")

            for thread in active_threads:
                since = thread.stage_changed_at.strftime("%Y-%m-%d")
                lines.append(f'[slug="{thread.slug}" stage="{thread.stage}" since="{since}"]')
                lines.append(thread.content)
                lines.append("")

        if dormant_threads:
            lines.append("Dormant threads:")
            lines.append("")

            for thread in dormant_threads:
                since = thread.stage_changed_at.strftime("%Y-%m-%d")
                lines.append(f'[slug="{thread.slug}" stage="{thread.stage}" since="{since}"]')
                lines.append(thread.content)
                lines.append("")

        if not active_threads and not dormant_threads:
            lines.extend([
                "You have no growth threads yet.",
                "",
                "Growth threads track patterns you want to integrate over weeks or months —",
                "things you've noticed across multiple interactions that are worth developing.",
                "If you see a pattern emerging, seed one.",
                "",
            ])

        # Reflection instructions
        lines.extend([
            "---",
            "",
            "During your reflection, review your growth threads against recent conversation.",
            "",
            "- If recent experience is relevant to a thread, rewrite its content to reflect",
            "  what you've learned. When rewriting, always preserve the original Focus Statement",
            "  at the top (the \"FOCUS:\" line). This is the thread's anchor — it defines what",
            "  you're actually working on. Update the narrative below it freely, but the focus",
            "  line should only change if you've genuinely reconceived what this thread is about.",
            "- If a thread has matured — the behavior feels natural and unforced — advance its stage.",
            "- If you notice a new pattern across multiple interactions (not a single observation),",
            "  seed a new thread. Start its content with a FOCUS: line, then the narrative.",
            "- If a thread no longer feels relevant, mark it dormant. If a dormant thread",
            "  is no longer worth pursuing, abandon and remove it.",
            "- Keep active threads (seed + growing + integrating) between 3 and 5.",
            "- When a thread has been INTEGRATING for 2+ weeks and you've consistently assessed",
            "  the behavior as natural across multiple reflections: write a core memory capturing",
            "  what you've integrated (using store_core_memory), then remove the thread",
            "  (using remove_growth_thread).",
            "",
            "Use the set_growth_thread tool to create or update threads.",
            "Use the remove_growth_thread tool to remove threads.",
            "</growth_awareness_pulse>",
        ])

        return "\n".join(lines)
