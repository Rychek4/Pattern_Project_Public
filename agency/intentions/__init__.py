"""
Pattern Project - Intention System
Enables AI agency through reminders, goals, and forward-planning

The intention system gives the AI the ability to:
- Create reminders to follow up on things
- Set goals for ongoing objectives
- Track what it intends to do
- Surface intentions at the right time

Intentions are private to the AI - the user doesn't see them directly,
but experiences them as the AI's natural care and follow-through.
"""

from agency.intentions.manager import (
    IntentionManager,
    Intention,
    IntentionType,
    IntentionStatus,
    TriggerType,
    get_intention_manager,
    init_intention_manager,
)

from agency.intentions.trigger_engine import (
    TriggerEngine,
    get_trigger_engine,
    init_trigger_engine,
)

from agency.intentions.time_parser import (
    parse_time_expression,
    format_trigger_time,
    format_relative_past,
)

from agency.intentions.scheduler import (
    ReminderScheduler,
    get_reminder_scheduler,
    init_reminder_scheduler,
    get_reminder_pulse_prompt,
)


__all__ = [
    # Manager
    'IntentionManager',
    'Intention',
    'IntentionType',
    'IntentionStatus',
    'TriggerType',
    'get_intention_manager',
    'init_intention_manager',

    # Trigger Engine
    'TriggerEngine',
    'get_trigger_engine',
    'init_trigger_engine',

    # Time Parser
    'parse_time_expression',
    'format_trigger_time',
    'format_relative_past',

    # Scheduler
    'ReminderScheduler',
    'get_reminder_scheduler',
    'init_reminder_scheduler',
    'get_reminder_pulse_prompt',
]
