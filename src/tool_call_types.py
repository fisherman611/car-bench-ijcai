"""Shared tool-call data structures for the CAR-bench A2A contract.

Agents under test return CAR-bench tool calls in an A2A data Part shaped like:

    {"tool_calls": [{"tool_name": "...", "arguments": {...}}]}

These Pydantic models keep that payload consistent across the baseline, Codex,
planner/executor, and Python-call reference agents.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """A single CAR-bench tool call embedded in an A2A data Part."""

    tool_name: str = Field(description="The name of the tool to call.")
    arguments: dict[str, Any] = Field(description="The arguments to pass to the tool.")

    def __str__(self) -> str:
        return f"ToolCall(tool_name={self.tool_name}, arguments={json.dumps(self.arguments)})"


class ToolCallsData(BaseModel):
    """Machine-readable tool-call payload returned by an agent under test."""

    tool_calls: list[ToolCall] = Field(description="List of tool calls to execute.")

    def __str__(self) -> str:
        return "ToolCallsData([" + ", ".join(str(tc) for tc in self.tool_calls) + "])"


def normalize_tool_arguments(
    tool_name: str,
    arguments: dict[str, Any],
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Coerce model-produced tool arguments according to the supplied tool schema."""

    if not isinstance(arguments, dict):
        return arguments

    parameters = _parameters_for_tool(tool_name, tools)
    if not parameters:
        return arguments

    normalized = _normalize_value(arguments, parameters)
    return normalized if isinstance(normalized, dict) else arguments


def _parameters_for_tool(
    tool_name: str,
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not tools:
        return None

    for tool in tools:
        function = tool.get("function", {})
        if function.get("name") == tool_name:
            parameters = function.get("parameters")
            return parameters if isinstance(parameters, dict) else None
    return None


def _normalize_value(value: Any, schema: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return value

    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            return _normalize_from_options(value, options)

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        for one_type in schema_type:
            normalized = _normalize_value(value, {**schema, "type": one_type})
            if _matches_type(normalized, one_type):
                return normalized
        return value

    if schema_type == "object" and isinstance(value, dict):
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return value
        return {
            key: _normalize_value(item, properties[key])
            if key in properties and isinstance(properties[key], dict)
            else item
            for key, item in value.items()
        }

    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return value
        return [_normalize_value(item, item_schema) for item in value]

    if schema_type == "integer":
        return _coerce_integer(value)

    if schema_type == "number":
        return _coerce_number(value, schema)

    if schema_type == "boolean":
        return _coerce_boolean(value)

    return value


def _normalize_from_options(value: Any, options: list[Any]) -> Any:
    for option in options:
        if not isinstance(option, dict):
            continue
        normalized = _normalize_value(value, option)
        option_type = option.get("type")
        if option_type is None or _matches_type(normalized, option_type):
            return normalized
    return value


def _coerce_integer(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = float(text) if "." in text else int(text)
        except ValueError:
            return value
        if isinstance(parsed, int):
            return parsed
        if parsed.is_integer():
            return int(parsed)
    return value


def _coerce_number(value: Any, schema: dict[str, Any]) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _maybe_integer_number(value, schema)
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = float(text)
        except ValueError:
            return value
        return _maybe_integer_number(parsed, schema)
    return value


def _maybe_integer_number(value: int | float, schema: dict[str, Any]) -> int | float:
    if schema.get("multipleOf") == 1 and float(value).is_integer():
        return int(value)
    return value


def _coerce_boolean(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return value


def _matches_type(value: Any, schema_type: Any) -> bool:
    if isinstance(schema_type, list):
        return any(_matches_type(value, item) for item in schema_type)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    return True
