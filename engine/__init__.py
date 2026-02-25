"""
Pattern Project - Chat Engine Package

UI-agnostic message processing engine shared by GUI, CLI, and Web interfaces.
"""

from engine.chat_engine import ChatEngine
from engine.events import EngineEvent, EngineEventType

__all__ = ["ChatEngine", "EngineEvent", "EngineEventType"]
