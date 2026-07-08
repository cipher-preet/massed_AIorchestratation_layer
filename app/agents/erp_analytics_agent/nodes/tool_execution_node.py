import json
import re
from typing import Any, Dict

from app.agents.erp_analytics_agent.state import AgentState
from app.mcp_client.mcp_tool_registry import call_registered_tool


def _clarification_state(question: str, reason: str) -> AgentState:
    return {
        "query_plan": {
            "tool": "clarification_needed",
            "arguments": {"question": question},
            "reason": reason,
        },
        "persist_chat_history": False,
    }


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
ISO_DATE_STRING_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
DATE_COMPARISON_OPERATORS = {"$gte", "$gt", "$lte", "$lt", "$eq", "$ne"}
OBJECT_ID_STRING_PATTERN = re.compile(r"^[a-fA-F0-9]{24}$")
OBJECT_ID_FIELD_NAMES = {
    "_id",
    "id",
    "technician",
    "technicians",
    "branch",
    "branches",
    "client",
    "clients",
    "customer",
    "customers",
    "vendor",
    "vendors",
    "user",
    "users",
    "employee",
    "employees",
    "engineer",
    "engineers",
    "staff",
    "area",
    "areas",
    "space",
    "company",
    "organization",
    "createdby",
    "updatedby",
    "assignedto",
    "assigneduser",
    "assignedtechnician",
}
ID_MATCH_OPERATORS = {"$eq", "$ne", "$in", "$nin"}


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


def _as_extended_json_date(value: Any) -> Any:
    if isinstance(value, str) and ISO_DATE_STRING_PATTERN.match(value):
        return {"$date": value}
    if isinstance(value, list):
        return [_as_extended_json_date(item) for item in value]
    return value


def _normalize_date_literals(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_date_literals(item) for item in value]

    if not isinstance(value, dict):
        return value

    normalized: Dict[str, Any] = {}
    for key, child_value in value.items():
        if key in DATE_COMPARISON_OPERATORS:
            normalized[key] = _as_extended_json_date(child_value)
        else:
            normalized[key] = _normalize_date_literals(child_value)
    return normalized


def _is_object_id_field(field_name: str | None) -> bool:
    if not field_name:
        return False

    normalized = field_name.rsplit(".", 1)[-1].replace("_", "").replace("-", "").lower()
    return (
        normalized in OBJECT_ID_FIELD_NAMES
        or normalized.endswith("id")
        or normalized.endswith("ids")
        or normalized.endswith("ref")
        or normalized.endswith("refs")
    )


def _as_extended_json_object_id(value: Any, field_name: str | None) -> Any:
    if not _is_object_id_field(field_name):
        return value

    if isinstance(value, dict):
        if set(value.keys()) == {"$oid"}:
            return value
        return _normalize_object_id_literals(value, field_name)

    if isinstance(value, list):
        return [_as_extended_json_object_id(item, field_name) for item in value]

    if isinstance(value, str) and OBJECT_ID_STRING_PATTERN.match(value):
        return {"$oid": value}

    return value


def _field_name_from_expression(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith("$") and not value.startswith("$$"):
        return value.lstrip("$")
    return None


def _normalize_object_id_literals(value: Any, field_name: str | None = None) -> Any:
    if isinstance(value, list):
        return [_normalize_object_id_literals(item, field_name) for item in value]

    if not isinstance(value, dict):
        return _as_extended_json_object_id(value, field_name)

    if set(value.keys()) == {"$oid"}:
        return value

    normalized: Dict[str, Any] = {}
    for key, child_value in value.items():
        if key in {"$date", "$regex", "$options"}:
            normalized[key] = child_value
            continue

        if key.startswith("$"):
            expression_field_name = (
                _field_name_from_expression(child_value[0])
                if key in ID_MATCH_OPERATORS and isinstance(child_value, list) and child_value
                else None
            )
            if expression_field_name:
                normalized[key] = [
                    item if index == 0 else _as_extended_json_object_id(item, expression_field_name)
                    for index, item in enumerate(child_value)
                ]
                continue
            if key in ID_MATCH_OPERATORS:
                normalized[key] = _as_extended_json_object_id(child_value, field_name)
            else:
                normalized[key] = _normalize_object_id_literals(child_value, field_name)
            continue

        normalized[key] = _normalize_object_id_literals(child_value, key)

    return normalized


def _normalize_tool_arguments(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "run_find_query":
        normalized_filter = _normalize_date_literals(arguments.get("filter") or {})
        normalized_filter = _normalize_object_id_literals(normalized_filter)
        return {**arguments, "filter": normalized_filter}
    if tool_name == "run_aggregation_query":
        normalized_pipeline = _normalize_date_literals(arguments.get("pipeline") or [])
        normalized_pipeline = _normalize_object_id_literals(normalized_pipeline)
        return {**arguments, "pipeline": normalized_pipeline}
    return arguments


async def _execute_one_step(tool_name: str, arguments: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    if tool_name not in {"run_find_query", "run_aggregation_query"}:
        raise ValueError(f"Unsupported analytics tool: {tool_name}")
    if not isinstance(arguments, dict):
        raise ValueError("Analytics tool arguments must be an object")
    normalized_arguments = _normalize_tool_arguments(tool_name, arguments)
    if tool_name == "run_aggregation_query":
        _validate_aggregation_operator_keys(normalized_arguments.get("pipeline"))
    result = await call_registered_tool(tool_name, normalized_arguments)
    parsed_result = _parse_mcp_text_result(result)
    if tool_name == "run_aggregation_query":
        parsed_result = _normalize_count_result(parsed_result, normalized_arguments)
    return result, parsed_result, normalized_arguments


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

        result, parsed_result, normalized_arguments = await _execute_one_step(tool_name, arguments)
        step_results[step_id] = parsed_result
        final_result = result
        final_parsed_result = parsed_result
        step["arguments"] = normalized_arguments
        tool_calls.append({"tool": tool_name, "arguments": normalized_arguments, "reason": step.get("reason"), "stepId": step_id})

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

        result, parsed_result, normalized_arguments = await _execute_one_step(tool_name, arguments)

        tool_calls = list(state.get("tool_calls", []))
        tool_calls.append({"tool": tool_name, "arguments": normalized_arguments, "reason": query_plan.get("reason")})
        return {
            "tool_result": result,
            "parsed_tool_result": parsed_result,
            "tool_calls": tool_calls,
            "query_plan": {**query_plan, "arguments": normalized_arguments},
        }
    except ValueError:
        return _clarification_state(
            "Could you clarify the exact ERP data and filter you want so I can build a valid query?",
            "The planned analytics query was incomplete or unsafe.",
        )
    except Exception:
        return _clarification_state(
            "I could not run that query safely. Could you clarify the record type, filter, and date range you need?",
            "The planned analytics query failed during execution.",
        )
