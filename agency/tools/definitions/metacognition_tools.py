"""Metacognition tool definitions (pulse-only).

These tools are used during reflective pulse phases for memory
self-awareness and bridge memory management.
"""

from typing import Any, Dict

STORE_BRIDGE_MEMORY_TOOL: Dict[str, Any] = {
    "name": "store_bridge_memory",
    "description": (
        "Store a bridge memory that creates a new retrieval pathway to unreachable "
        "knowledge. Write in first person, in associatively broad retrospective "
        "language — how this topic would naturally come up in future conversation, "
        "not the clinical language it was originally recorded in."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The bridge memory text"
            },
            "target_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "IDs of the unreachable memories this bridges to"
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0-1.0"
            }
        },
        "required": ["content", "target_ids", "importance"]
    }
}

STORE_META_OBSERVATION_TOOL: Dict[str, Any] = {
    "name": "store_meta_observation",
    "description": (
        "Store a meta-observation about the memory landscape as a regular memory "
        "for demand-driven retrieval. Write as self-knowledge in natural register."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The meta-observation text"
            },
            "importance": {
                "type": "number",
                "description": "Importance score 0.0-1.0"
            }
        },
        "required": ["content", "importance"]
    }
}

UPDATE_MEMORY_SELF_MODEL_TOOL: Dict[str, Any] = {
    "name": "update_memory_self_model",
    "description": (
        "Rewrite the compact memory self-model (~150-200 tokens). "
        "Observations only, never directives. Natural self-knowledge register, "
        "not statistics."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The new self-model text"
            }
        },
        "required": ["content"]
    }
}
