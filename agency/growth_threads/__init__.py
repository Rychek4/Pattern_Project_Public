"""
Pattern Project - Growth Threads
Long-term developmental aspirations that sit between active thoughts and memories.

Growth threads track patterns the AI wants to integrate over weeks/months.
They evolve through stages: seed → growing → integrating → (core memory + removal)
"""

from agency.growth_threads.manager import (
    GrowthThread,
    GrowthThreadManager,
    get_growth_thread_manager
)

__all__ = [
    'GrowthThread',
    'GrowthThreadManager',
    'get_growth_thread_manager',
]
