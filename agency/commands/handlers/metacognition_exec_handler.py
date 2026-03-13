"""
Pattern Project - Metacognition Tool Handlers
Handles store_bridge_memory, store_meta_observation, update_memory_self_model.

Extracted from agency/tools/executor.py for modularity.
Named metacognition_exec_handler to avoid collision with agency/metacognition/.
"""

from typing import Any, Dict

from core.logger import log_error, log_warning
import config


def exec_store_bridge_memory(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Store a bridge memory targeting unreachable knowledge."""
    from agency.tools.executor import ToolResult
    from agency.metacognition.bridge_manager import BridgeManager

    tool_name = "store_bridge_memory"
    content = input.get("content", "")
    target_ids = input.get("target_ids", [])
    importance = input.get("importance", 0.7)

    if not content or not target_ids:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content="Missing required fields: content and target_ids",
            is_error=True
        )

    try:
        bridge_mgr = BridgeManager(
            effectiveness_window_days=config.BRIDGE_EFFECTIVENESS_WINDOW_DAYS,
            self_sustaining_access_count=config.BRIDGE_SELF_SUSTAINING_ACCESS_COUNT,
            max_attempts=config.BRIDGE_MAX_ATTEMPTS,
        )
        memory_id = bridge_mgr.store_bridge(content, target_ids, importance)
    except Exception as e:
        log_error(f"store_bridge_memory failed: {e}")
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Failed to store bridge memory: {e}",
            is_error=True
        )

    if memory_id is None:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content="Failed to store bridge memory (embedding generation failed)",
            is_error=True
        )

    return ToolResult(
        tool_use_id=tool_use_id, tool_name=tool_name,
        content=f"Bridge memory stored (ID: {memory_id}, targeting: {target_ids})"
    )


def exec_store_meta_observation(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Store a meta-observation as a regular memory."""
    from agency.tools.executor import ToolResult
    from memory.vector_store import get_vector_store

    tool_name = "store_meta_observation"
    content = input.get("content", "")
    importance = input.get("importance", 0.6)

    if not content:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content="Missing required field: content",
            is_error=True
        )

    try:
        vector_store = get_vector_store()
        memory_id = vector_store.add_memory(
            content=content,
            source_conversation_ids=[],
            importance=importance,
            memory_type="reflection",
            decay_category="standard",
            memory_category="episodic",
            meta_source="observation",
        )
    except Exception as e:
        log_error(f"store_meta_observation failed: {e}")
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Failed to store meta-observation: {e}",
            is_error=True
        )

    if memory_id is None:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content="Failed to store meta-observation (embedding generation failed)",
            is_error=True
        )

    return ToolResult(
        tool_use_id=tool_use_id, tool_name=tool_name,
        content=f"Meta-observation stored (ID: {memory_id})"
    )


def exec_update_memory_self_model(
    input: Dict, tool_use_id: str, ctx: Dict
) -> Any:
    """Update the memory self-model in the state table."""
    from agency.tools.executor import ToolResult
    from core.database import get_database

    tool_name = "update_memory_self_model"
    content = input.get("content", "")

    if not content:
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content="Missing required field: content",
            is_error=True
        )

    # Enforce size cap (approximate: 1 token ≈ 4 chars)
    max_chars = getattr(config, 'SELF_MODEL_MAX_TOKENS', 250) * 4
    was_truncated = False
    if len(content) > max_chars:
        was_truncated = True
        truncated = content[:max_chars]
        # Find last sentence boundary (period or newline) before the cap
        last_period = truncated.rfind('.')
        last_newline = truncated.rfind('\n')
        cut_point = max(last_period, last_newline)
        if cut_point > max_chars // 2:
            content = truncated[:cut_point + 1].rstrip()
        else:
            # Fall back to word boundary
            last_space = truncated.rfind(' ')
            if last_space > max_chars // 2:
                content = truncated[:last_space].rstrip()
            else:
                content = truncated
        log_warning(f"Self-model truncated to {len(content)} chars (~{len(content)//4} tokens)")

    try:
        db = get_database()
        db.set_state("memory_self_model", content)
    except Exception as e:
        log_error(f"update_memory_self_model failed: {e}")
        return ToolResult(
            tool_use_id=tool_use_id, tool_name=tool_name,
            content=f"Failed to update memory self-model: {e}",
            is_error=True
        )

    msg = f"Memory self-model updated ({len(content)} chars)"
    if was_truncated:
        msg += f". WARNING: Content exceeded {max_chars} char limit and was truncated at the nearest sentence boundary."
    return ToolResult(
        tool_use_id=tool_use_id, tool_name=tool_name,
        content=msg
    )
