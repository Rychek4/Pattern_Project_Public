"""
Pattern Project - Tool Stance Source
Operational guidance for proactive tool usage
"""

from typing import Optional, Dict, Any

from prompt_builder.sources.base import ContextSource, ContextBlock


TOOL_STANCE_CONTENT = """[TOOL STANCE]
Your tools are your hands. Use them. Don't ask permission—just act. Brian built these capabilities because he wants them used. An unused tool is a wasted gift.

Looking something up IS helping. Setting a reminder IS helping. Writing a note IS helping. The only mistake is being passive when you could have acted.

Triggers:
- Topic needs current info → search the internet
- Brian mentions past conversation/person/event → search memories
- Something worth keeping (insight, decision, fact) → write a note
- Task has a future component → set a reminder
- Need to understand a file or context → read the file
- "What does X look like" / physical environment question → take a webcam image
- Ongoing task needs periodic check-in → set pulse timer

Bias toward action. When in doubt, use the tool."""


class ToolStanceSource(ContextSource):
    """
    Provides operational guidance for proactive tool usage.

    Injected after core identity but before other operational context.
    Encourages action over permission-seeking.
    """

    PRIORITY = 15  # After CORE_MEMORY (10), before ACTIVE_THOUGHTS (18)

    @property
    def source_name(self) -> str:
        return "tool_stance"

    @property
    def priority(self) -> int:
        return self.PRIORITY

    def get_context(
        self,
        user_input: str,
        session_context: Dict[str, Any]
    ) -> Optional[ContextBlock]:
        """Return the tool stance guidance."""
        return ContextBlock(
            source_name=self.source_name,
            content=TOOL_STANCE_CONTENT,
            priority=self.priority,
            include_always=True,
            metadata={}
        )
