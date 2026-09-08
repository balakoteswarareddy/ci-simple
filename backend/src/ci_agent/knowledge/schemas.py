"""JSON schemas for knowledge extraction (PDF §6.2 step 4: schema validation
rejects malformed records). Used both for LLM structured outputs and for
validating heuristic/ad-hoc ingestion before it touches the store."""
from __future__ import annotations

from typing import Any

import jsonschema

TOOL_FACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tool", "capabilities", "ecosystems"],
    "additionalProperties": False,
    "properties": {
        "tool": {"type": "string", "minLength": 1, "maxLength": 128},
        "capabilities": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "ecosystems": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "install_methods": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": ["type", "command"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string"},
                    "command": {"type": "string", "maxLength": 500},
                },
            },
        },
        "ci_integrations": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "versions": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
}

TOOL_FACT_LIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["tools"],
    "additionalProperties": False,
    "properties": {"tools": {"type": "array", "items": TOOL_FACT_SCHEMA, "maxItems": 20}},
}


class KnowledgeValidationError(ValueError):
    pass


def validate_tool_fact(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        jsonschema.validate(payload, TOOL_FACT_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise KnowledgeValidationError(f"tool fact failed schema validation: {exc.message}") from exc
    return payload


def validate_tool_fact_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        jsonschema.validate(payload, TOOL_FACT_LIST_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise KnowledgeValidationError(f"tool fact list failed schema validation: {exc.message}") from exc
    return payload["tools"]
