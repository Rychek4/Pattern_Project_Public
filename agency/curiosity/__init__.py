"""
Pattern Project - Curiosity Engine
AI-driven exploration of dormant topics and knowledge gaps.

This module provides curiosity-driven conversation direction by:
1. Analyzing memory state to identify dormant/interesting topics
2. Selecting goals via weighted random for natural exploration
3. Tracking exploration history to prevent repetition
4. Injecting curiosity context into all AI responses

The curiosity engine is always active (when enabled) - it influences
both idle pulses and regular conversation responses.
"""

from typing import Optional

import config
from core.logger import log_info


def is_curiosity_enabled() -> bool:
    """Check if curiosity system is enabled."""
    return getattr(config, 'CURIOSITY_ENABLED', True)


# Lazy-loaded engine instance
_curiosity_engine: Optional["CuriosityEngine"] = None


def get_curiosity_engine() -> "CuriosityEngine":
    """
    Get the global CuriosityEngine instance.

    Returns:
        The initialized CuriosityEngine

    Raises:
        RuntimeError: If curiosity is disabled
    """
    global _curiosity_engine

    if not is_curiosity_enabled():
        raise RuntimeError("Curiosity engine is disabled. Enable CURIOSITY_ENABLED in config.")

    if _curiosity_engine is None:
        from agency.curiosity.engine import CuriosityEngine
        _curiosity_engine = CuriosityEngine()
        log_info("Curiosity engine initialized", prefix="🔍")

    return _curiosity_engine


def init_curiosity_engine() -> Optional["CuriosityEngine"]:
    """
    Initialize the curiosity engine.

    Returns:
        The CuriosityEngine if enabled, None otherwise
    """
    if not is_curiosity_enabled():
        log_info("Curiosity engine disabled", prefix="🔍")
        return None

    return get_curiosity_engine()
