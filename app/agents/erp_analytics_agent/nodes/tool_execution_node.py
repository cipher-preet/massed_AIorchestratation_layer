import json
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


async def tool_execution_node(state: AgentState) -> AgentState:
    query_plan = state.get("query_plan") or {}
    tool_name = query_plan.get("tool")
    arguments = query_plan.get("arguments") or {}

    if tool_name in {"clarification_needed", "schema_answer"}:
        return {}

    try:
        if tool_name == "run_aggregation_query":
            _validate_aggregation_operator_keys(arguments.get("pipeline"))
        result = await call_registered_tool(tool_name, arguments)
        parsed_result = _parse_mcp_text_result(result)
        if tool_name == "run_aggregation_query":
            parsed_result = _normalize_count_result(parsed_result, arguments)

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append({"tool": tool_name, "arguments": arguments, "reason": query_plan.get("reason")})
        return {"tool_result": result, "parsed_tool_result": parsed_result, "tool_calls": tool_calls}
    except Exception:
        return {"error": "Could not execute the planned analytics query."}
