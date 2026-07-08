import json
from datetime import datetime, timezone

from app.agents.erp_analytics_agent.prompts import QUERY_PLANNER_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.config.settings import settings
from app.core.llm import get_llm
from app.mcp_client.mcp_tool_registry import list_tools
from app.utils.json_utils import extract_json_object


def _clarification_plan(question: str, reason: str) -> AgentState:
    return {
        "query_plan": {
            "tool": "clarification_needed",
            "arguments": {"question": question},
            "reason": reason,
        }
    }


def _is_valid_plan(plan: dict) -> bool:
    tool = plan.get("tool")
    if tool in {"run_find_query", "run_aggregation_query", "schema_answer", "clarification_needed"}:
        return isinstance(plan.get("arguments"), dict)
    if tool == "multi_step_plan":
        steps = plan.get("steps")
        return isinstance(steps, list) and bool(steps)
    return False


def _plan_uses_target_hint(plan: dict, task_decomposition: dict | None) -> bool:
    if not isinstance(task_decomposition, dict):
        return True

    target_collection = task_decomposition.get("target_collection_hint")
    if not isinstance(target_collection, str) or not target_collection:
        return True

    serialized_plan = json.dumps(plan, default=str).lower()
    return target_collection.lower() in serialized_plan


async def query_planner_node(state: AgentState) -> AgentState:
    if state.get("intent") == "schema_question":
        return {
            "query_plan": {
                "tool": "schema_answer",
                "arguments": {},
                "reason": "The user asked about available ERP data schema.",
            }
        }

    llm = get_llm(model=settings.openai_planner_model)
    available_tools = await list_tools()
    prompt_context = {
        "user_message": state["message"],
        "current_utc_datetime": datetime.now(timezone.utc).isoformat(),
        "chat_history": (state.get("chat_history") or [])[-10:],
        "conversation_reference": state.get("conversation_reference"),
        "schema_domain": state.get("schema_domain"),
        "schema_catalog": state.get("schema_catalog"),
        "relationship_map": state.get("relationship_map"),
        "task_decomposition": state.get("task_decomposition"),
        "available_mcp_tools": available_tools,
    }
    try:
        messages = [
            ("system", QUERY_PLANNER_PROMPT),
            ("human", json.dumps(prompt_context, default=str)),
        ]
        response = await llm.ainvoke(messages)
        parsed = extract_json_object(str(response.content))

        if _is_valid_plan(parsed) and not _plan_uses_target_hint(parsed, state.get("task_decomposition")):
            target_collection = state.get("task_decomposition", {}).get("target_collection_hint")
            response = await llm.ainvoke(
                [
                    ("system", QUERY_PLANNER_PROMPT),
                    (
                        "human",
                        json.dumps(
                            {
                                **prompt_context,
                                "previous_invalid_plan": parsed,
                                "correction_required": (
                                    f"The previous plan ignored target_collection_hint={target_collection!r}. "
                                    "Replan so the final answer queries that target collection. Use the named "
                                    "person/entity only as an intermediate lookup when needed."
                                ),
                            },
                            default=str,
                        ),
                    ),
                ]
            )
            parsed = extract_json_object(str(response.content))
    except Exception:
        return _clarification_plan(
            "Could you clarify exactly which ERP record, metric, filter, or time period you want?",
            "The planner could not decode the analytics request safely.",
        )

    if not _is_valid_plan(parsed):
        return _clarification_plan(
            "Could you clarify the ERP data you want and any required filter, name, status, or date range?",
            "The planner returned an incomplete analytics plan.",
        )

    if not _plan_uses_target_hint(parsed, state.get("task_decomposition")):
        target_collection = state.get("task_decomposition", {}).get("target_collection_hint")
        return _clarification_plan(
            f"I found the requested detail type, but I could not safely build the relationship query for {target_collection}. Which field links it to the named record?",
            "The planner did not use the requested target collection after retry.",
        )

    return {"query_plan": parsed}
