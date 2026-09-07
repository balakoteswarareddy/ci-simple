"""JSON schemas for LLM structured outputs (PDF §5 step 5, §7).

Every model response is validated against these schemas with the jsonschema
library; invalid output triggers one corrective retry, then a deterministic
fallback. The model proposes — deterministic code disposes.
"""
from __future__ import annotations

from typing import Any

INTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["platform", "capabilities"],
    "additionalProperties": False,
    "properties": {
        "platform": {"type": "string", "enum": ["github", "azure", "gitlab", "jenkins"]},
        "capabilities": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
        "deployment_target": {"type": "string", "maxLength": 64},
        "constraints": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
        "prohibited_tools": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
        "required_controls": {"type": "array", "items": {"type": "string"}, "maxItems": 16},
        "trigger_branches": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
}

REPAIR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["repairs", "summary"],
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string", "maxLength": 500},
        "repairs": {
            "type": "array",
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["job_id", "action"],
                "additionalProperties": False,
                "properties": {
                    "job_id": {"type": "string"},
                    "step_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["set_uses", "set_run", "set_permission", "add_step",
                                 "remove_step", "set_with", "set_runs_on", "rename"],
                    },
                    "value": {},
                    "reason": {"type": "string", "maxLength": 300},
                },
            },
        },
    },
}
