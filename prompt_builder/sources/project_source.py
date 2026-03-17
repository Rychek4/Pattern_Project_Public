"""
Pattern Project - Projects Context Source
Injects the AI's active project state into prompts.

Priority 21: After growth threads (20), before intentions (22).
This positions projects as: "what I'm becoming" → "what I'm building" → "what I plan to do"
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock
from core.logger import log_info


# Priority: between growth threads (20) and intentions (22)
PROJECTS_PRIORITY = 21


class ProjectSource(ContextSource):
    """
    Provides the AI's active project state for prompt injection.

    Normal conversation: Shows active project with progress and next actions.
    Compact format to minimize token usage.

    Pulse context: Also shows paused projects for review.
    """

    @property
    def source_name(self) -> str:
        return "projects"

    @property
    def priority(self) -> int:
        return PROJECTS_PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Get project state for prompt injection."""
        from agency.projects import get_project_manager

        try:
            manager = get_project_manager()
            is_pulse = session_context.get("is_pulse", False)

            active = manager.get_active()
            paused = manager.get_paused() if is_pulse else []

            if not active and not paused:
                return None

            if is_pulse:
                content = self._build_pulse_context(active, paused)
            else:
                if not active:
                    return None
                content = self._build_context(active)

            # Store in session context for other sources
            session_context["has_active_project"] = active is not None
            if active:
                session_context["active_project_id"] = active.id
                session_context["active_project_name"] = active.name

            return ContextBlock(
                source_name=self.source_name,
                content=content,
                priority=self.priority,
                include_always=False,
                metadata={
                    "has_active": active is not None,
                    "paused_count": len(paused),
                }
            )

        except Exception as e:
            log_info(f"ProjectSource error: {e}")
            return None

    def _build_context(self, project) -> str:
        """Build normal conversation context with active project."""
        total = len(project.actions)
        completed = sum(1 for a in project.actions if a.status == 'completed')

        lines = [
            "<active_project>",
            f"[PROJECT: {project.name}] ({completed}/{total} actions complete)",
            project.description,
            "",
        ]

        # Show next pending/in-progress actions
        remaining = [a for a in project.actions if a.status != 'completed']
        if remaining:
            lines.append("Next:")
            for a in remaining[:4]:  # Show at most 4 upcoming
                marker = "~" if a.status == "in_progress" else " "
                line = f"  [{marker}] {a.description}"
                if a.notes:
                    line += f" — {a.notes}"
                lines.append(line)
            if len(remaining) > 4:
                lines.append(f"  ... and {len(remaining) - 4} more")
        else:
            lines.append("All actions complete — consider completing the project.")

        # Compact completed summary
        if completed > 0:
            completed_actions = [a for a in project.actions if a.status == 'completed']
            completed_names = ", ".join(a.description[:40] for a in completed_actions[-3:])
            if completed > 3:
                lines.append(f"Done: ...{completed_names} ({completed} total)")
            else:
                lines.append(f"Done: {completed_names}")

        lines.append("</active_project>")
        return "\n".join(lines)

    def _build_pulse_context(self, active, paused) -> str:
        """Build pulse context showing active and paused projects."""
        lines = ["<project_awareness_pulse>"]

        if active:
            total = len(active.actions)
            completed = sum(1 for a in active.actions if a.status == 'completed')

            lines.extend([
                f"Active project: {active.name} (id={active.id})",
                active.description,
                f"Progress: {completed}/{total} actions complete",
                "",
            ])

            for a in active.actions:
                status_icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}[a.status]
                line = f"  {status_icon} (id={a.id}) {a.description}"
                if a.notes:
                    line += f" — {a.notes}"
                lines.append(line)

            lines.append("")
        else:
            lines.extend([
                "No active project.",
                "",
            ])

        if paused:
            lines.append("Paused projects:")
            for p in paused:
                p_total = len(p.actions)
                p_done = sum(1 for a in p.actions if a.status == 'completed')
                lines.append(f"  - {p.name} (id={p.id}, {p_done}/{p_total} done)")
            lines.append("")

        lines.extend([
            "Review your project state. Consider:",
            "- Is the active project still the right priority?",
            "- Are any actions stale or need updating?",
            "- Should a paused project be resumed?",
            "</project_awareness_pulse>",
        ])

        return "\n".join(lines)
