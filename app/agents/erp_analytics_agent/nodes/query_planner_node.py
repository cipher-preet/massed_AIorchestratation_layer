import json
from datetime import datetime, timezone

from app.agents.erp_analytics_agent.prompts import QUERY_PLANNER_PROMPT
from app.agents.erp_analytics_agent.plan_validation import validate_query_plan
from app.agents.erp_analytics_agent.state import AgentState
from app.config.settings import settings
from app.core.cost_optimization import (
    compact_chat_history,
    compact_conversation_reference,
    compact_prompt_value,
    compact_tools,
    invoke_llm,
)
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


def _planner_model_for_task(state: AgentState) -> str:
    task_decomposition = state.get("task_decomposition") or {}
    if task_decomposition.get("complexity") == "multi_step" and settings.openai_complex_planner_model:
        return settings.openai_complex_planner_model
    return settings.openai_planner_model


async def _retry_plan(
    llm,
    prompt_context: dict,
    invalid_plan: dict,
    correction_required: str,
    operation: str,
) -> dict:
    response = await invoke_llm(
        llm,
        [
            ("system", QUERY_PLANNER_PROMPT),
            (
                "human",
                json.dumps(
                    {
                        **prompt_context,
                        "previous_invalid_plan": invalid_plan,
                        "correction_required": correction_required,
                    },
                    default=str,
                ),
            ),
        ],
        operation=operation,
    )
    return extract_json_object(str(response.content))


async def query_planner_node(state: AgentState) -> AgentState:
    if state.get("intent") == "schema_question":
        return {
            "query_plan": {
                "tool": "schema_answer",
                "arguments": {},
                "reason": "The user asked about available ERP data schema.",
            }
        }

    llm = get_llm(model=_planner_model_for_task(state))
    available_tools = await list_tools()
    prompt_context = {
        "user_message": state["message"],
        "current_utc_datetime": datetime.now(timezone.utc).isoformat(),
        "chat_history": compact_chat_history(state.get("chat_history")),
        "conversation_reference": compact_conversation_reference(state.get("conversation_reference")),
        "schema_domain": state.get("schema_domain"),
        "schema_catalog": compact_prompt_value(state.get("schema_catalog"), settings.ai_schema_prompt_max_chars),
        "relationship_map": compact_prompt_value(state.get("relationship_map"), settings.ai_schema_prompt_max_chars),
        "task_decomposition": state.get("task_decomposition"),
        "available_mcp_tools": compact_tools(available_tools),
    }
    try:
        messages = [
            ("system", QUERY_PLANNER_PROMPT),
            ("human", json.dumps(prompt_context, default=str)),
        ]
        response = await invoke_llm(llm, messages, operation="query_planner")
        parsed = extract_json_object(str(response.content))

        if _is_valid_plan(parsed) and not _plan_uses_target_hint(parsed, state.get("task_decomposition")):
            target_collection = state.get("task_decomposition", {}).get("target_collection_hint")
            parsed = await _retry_plan(
                llm,
                prompt_context,
                parsed,
                (
                    f"The previous plan ignored target_collection_hint={target_collection!r}. "
                    "Replan so the final answer queries that target collection. Use the named "
                    "person/entity only as an intermediate lookup when needed."
                ),
                operation="query_planner_target_retry",
            )

        validation_errors = validate_query_plan(parsed, state.get("schema_catalog")) if _is_valid_plan(parsed) else []
        if validation_errors:
            parsed = await _retry_plan(
                llm,
                prompt_context,
                parsed,
                (
                    "The previous plan used collections or fields that are not present in schema_catalog. "
                    "Replan using only exact schema names. Validation errors: "
                    + "; ".join(validation_errors[:10])
                ),
                operation="query_planner_schema_retry",
            )
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

    validation_errors = validate_query_plan(parsed, state.get("schema_catalog"))
    if validation_errors:
        return _clarification_plan(
            "I could not safely map that request to the available ERP fields. Could you clarify the exact record type or field name?",
            "The planner returned a query using unavailable schema fields: " + "; ".join(validation_errors[:5]),
        )

    return {"query_plan": parsed}
