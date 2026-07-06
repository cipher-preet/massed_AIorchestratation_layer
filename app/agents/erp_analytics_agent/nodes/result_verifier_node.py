from typing import Any

from app.agents.erp_analytics_agent.state import AgentState


def _is_empty_result(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)) and len(value) == 0:
        return True
    if isinstance(value, dict):
        if len(value) == 0:
            return True
        if value.get("ok") is False:
            return False
        if "data" in value:
            return _is_empty_result(value.get("data"))
        content = value.get("content")
        if isinstance(content, list) and len(content) == 0:
            return True
        if value.get("is_error"):
            return True
    return False


async def result_verifier_node(state: AgentState) -> AgentState:
    if state.get("error"):
        return {}
    if state.get("query_plan", {}).get("tool") in {"clarification_needed", "schema_answer"}:
        return {}
    if isinstance(state.get("tool_result"), dict) and state["tool_result"].get("is_error"):
        return {"error": "The analytics query returned an error."}
    if isinstance(state.get("parsed_tool_result"), dict) and state["parsed_tool_result"].get("ok") is False:
        return {"error": "The analytics query returned an error."}
    result_to_check = state.get("parsed_tool_result") or state.get("tool_result")
    if _is_empty_result(result_to_check):
        return {"result_status": "no_data"}
    return {}
