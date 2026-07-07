import json
import re
from typing import Any, Dict

from app.agents.erp_analytics_agent.state import AgentState
from app.mcp_client.mcp_tool_registry import call_registered_tool


def _parse_mcp_text_result(result: Dict[str, Any]) -> Dict[str, Any]:
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return {"ok": not result.get("is_error", False), "data": None}

    first_item = content[0]
    if not isinstance(first_item, dict) or first_item.get("type") != "text":
        return {"ok": not result.get("is_error", False), "data": content}

    text = first_item.get("text")
    if not isinstance(text, str):
        return {"ok": not result.get("is_error", False), "data": None}

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"ok": not result.get("is_error", False), "data": text}

    return parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}


def _count_field_from_pipeline(pipeline: Any) -> str | None:
    if not isinstance(pipeline, list):
        return None

    for stage in pipeline:
        if isinstance(stage, dict) and isinstance(stage.get("$count"), str):
            return stage["$count"]
    return None


def _normalize_count_result(parsed: Dict[str, Any], arguments: Dict[str, Any]) -> Dict[str, Any]:
    count_field = _count_field_from_pipeline(arguments.get("pipeline"))
    if not count_field:
        return parsed

    if parsed.get("ok") is True and parsed.get("data") == []:
        return {**parsed, "data": [{count_field: 0}]}
    return parsed


def _validate_aggregation_operator_keys(value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _validate_aggregation_operator_keys(item)
        return

    if not isinstance(value, dict):
        return

    for key, child_value in value.items():
        if isinstance(key, str) and key.strip().startswith("$") and key != key.strip():
            raise ValueError(f"Invalid MongoDB operator key: {key!r}")
        _validate_aggregation_operator_keys(child_value)


PLACEHOLDER_PATTERN = re.compile(r"^\{\{steps\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_.*-]+(?:\.[A-Za-z0-9_.*-]+)*)\}\}$")


def _extract_path_parts(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value

    part = parts[0]
    remaining = parts[1:]

    if part == "*":
        if not isinstance(value, list):
            return []
        return [_extract_path_parts(item, remaining) for item in value]

    if isinstance(value, list):
        if not part.isdigit():
            return []
        index = int(part)
        if index >= len(value):
            return None
        return _extract_path_parts(value[index], remaining)

    if not isinstance(value, dict):
        return None

    return _extract_path_parts(value.get(part), remaining)


def _extract_path(value: Any, path: str) -> Any:
    return _extract_path_parts(value, path.split("."))


def _flatten_values(value: Any) -> list[Any]:
    if isinstance(value, list):
        flattened: list[Any] = []
        for item in value:
            flattened.extend(_flatten_values(item))
        return flattened
    if value is None:
        return []
    return [value]


def _resolve_placeholders(value: Any, step_results: Dict[str, Dict[str, Any]]) -> Any:
    if isinstance(value, list):
        return [_resolve_placeholders(item, step_results) for item in value]

    if isinstance(value, dict):
        return {key: _resolve_placeholders(child_value, step_results) for key, child_value in value.items()}

    if not isinstance(value, str):
        return value

    match = PLACEHOLDER_PATTERN.match(value)
    if not match:
        return value

    step_id, path = match.groups()
    if step_id not in step_results:
        raise ValueError(f"Unknown step placeholder: {step_id}")

    resolved = _extract_path(step_results[step_id], path)
    if ".*." in f".{path}." or path.endswith(".*"):
        return _flatten_values(resolved)
    return resolved


async def _execute_one_step(tool_name: str, arguments: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if tool_name == "run_aggregation_query":
        _validate_aggregation_operator_keys(arguments.get("pipeline"))
    result = await call_registered_tool(tool_name, arguments)
    parsed_result = _parse_mcp_text_result(result)
    if tool_name == "run_aggregation_query":
        parsed_result = _normalize_count_result(parsed_result, arguments)
    return result, parsed_result


async def _execute_multi_step_plan(query_plan: Dict[str, Any], state: AgentState) -> AgentState:
    steps = query_plan.get("steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("multi_step_plan requires at least one step")

    step_results: Dict[str, Dict[str, Any]] = {}
    tool_calls = list(state.get("tool_calls", []))
    final_result: Dict[str, Any] | None = None
    final_parsed_result: Dict[str, Any] | None = None

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError("Invalid multi-step plan step")
        step_id = step.get("id") or f"step_{index + 1}"
        tool_name = step.get("tool")
        arguments = _resolve_placeholders(step.get("arguments") or {}, step_results)

        result, parsed_result = await _execute_one_step(tool_name, arguments)
        step_results[step_id] = parsed_result
        final_result = result
        final_parsed_result = parsed_result
        tool_calls.append({"tool": tool_name, "arguments": arguments, "reason": step.get("reason"), "stepId": step_id})

    return {
        "tool_result": final_result,
        "parsed_tool_result": final_parsed_result,
        "tool_calls": tool_calls,
        "query_plan": {**query_plan, "step_results": step_results},
    }


async def tool_execution_node(state: AgentState) -> AgentState:
    query_plan = state.get("query_plan") or {}
    tool_name = query_plan.get("tool")
    arguments = query_plan.get("arguments") or {}

    if tool_name in {"clarification_needed", "schema_answer"}:
        return {}

    try:
        if tool_name == "multi_step_plan":
            return await _execute_multi_step_plan(query_plan, state)

        result, parsed_result = await _execute_one_step(tool_name, arguments)

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append({"tool": tool_name, "arguments": arguments, "reason": query_plan.get("reason")})
        return {"tool_result": result, "parsed_tool_result": parsed_result, "tool_calls": tool_calls}
    except Exception:
        return {"error": "Could not execute the planned analytics query."}
