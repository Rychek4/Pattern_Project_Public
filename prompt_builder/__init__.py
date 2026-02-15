"""
Pattern Project - Prompt Builder
Modular context assembly for rich, self-contained prompts
"""

from prompt_builder.builder import PromptBuilder, get_prompt_builder, init_prompt_builder
from prompt_builder.sources.base import ContextSource, ContextBlock

__all__ = [
    "PromptBuilder",
    "get_prompt_builder",
    "init_prompt_builder",
    "ContextSource",
    "ContextBlock",
]
