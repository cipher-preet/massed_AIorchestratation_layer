import json
import re
from typing import Any, Dict

from app.agents.erp_analytics_agent.prompts import RESPONSE_FORMATTER_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.config.settings import settings
from app.core.cost_optimization import (
    compact_chat_history,
    compact_conversation_reference,
    compact_prompt_value,
    compact_text,
    invoke_llm,
)
from app.core.llm import get_llm


BAD_EMPTY_HISTORY_ANSWER = "There is no previous message in this conversation."


def _count_field_from_query_plan(query_plan: Dict[str, Any]) -> str | None:
    arguments = query_plan.get("arguments") or {}
    pipeline = arguments.get("pipeline")
    if not isinstance(pipeline, list):
        return None

    for stage in pipeline:
        if isinstance(stage, dict) and isinstance(stage.get("$count"), str):
            return stage["$count"]
    return None


def _format_count_answer(query_plan: Dict[str, Any], parsed_result: Dict[str, Any] | None) -> str | None:
    count_field = _count_field_from_query_plan(query_plan)
    if not count_field or not isinstance(parsed_result, dict):
        return None

    data = parsed_result.get("data")
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        return None

    count_value = data[0].get(count_field)
    if isinstance(count_value, (int, float)):
        return f"{count_field}: {int(count_value) if count_value == int(count_value) else count_value}"
    return None


def _has_executed_query(query_plan: Dict[str, Any], state: AgentState) -> bool:
    tool = query_plan.get("tool")
    if tool not in {"run_find_query", "run_aggregation_query", "multi_step_plan"}:
        return False
    return bool(state.get("parsed_tool_result") or state.get("tool_result") or query_plan.get("step_results"))


def _effective_intent(state: AgentState, query_plan: Dict[str, Any]) -> str | None:
    if _has_executed_query(query_plan, state):
        return "analytics_query"
    return state.get("intent")


def _with_chat_history(state: AgentState, answer: str, response_kind: str = "answer") -> AgentState:
    history = list(state.get("chat_history") or [])
    history.extend(
        [
            {"type": "human", "content": state.get("message", "")},
            {"type": "ai", "content": answer},
        ]
    )
    return {
        "answer": answer,
        "chat_history": history,
        "persist_chat_history": True,
        "intent": _effective_intent(state, state.get("query_plan") or {}),
        "last_response_kind": response_kind,
        "last_response_content": answer,
    }


def _without_chat_history(answer: str, response_kind: str) -> AgentState:
    return {
        "answer": answer,
        "persist_chat_history": False,
        "last_response_kind": response_kind,
        "last_response_content": answer,
    }


def _is_simple_greeting(message: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", message.lower()).strip()
    return normalized in {"hello", "hey", "hi", "hiya", "namaste"}


def _asks_about_previous_message(message: str) -> bool:
    normalized = message.lower()
    previous_terms = {"previous", "last", "earlier", "prior", "before"}
    message_terms = {"message", "question", "answer", "response", "conversation", "chat"}
    return any(term in normalized for term in previous_terms) and any(term in normalized for term in message_terms)


def _clean_conversation_answer(answer: str) -> str:
    if answer.strip().rstrip(".") == BAD_EMPTY_HISTORY_ANSWER.rstrip("."):
        return "I do not have earlier conversation context to reference yet. How can I help with your ERP analytics?"
    return answer


def _conversation_messages(state: AgentState) -> list[tuple[str, str]]:
    messages = [
        (
            "system",
            (
                "You are an ERP analytics assistant. Answer the latest user message directly. "
                "Use prior chat messages only as conversation context. If the latest message is a greeting "
                "or small talk, reply naturally and do not discuss whether history exists. If the latest "
                "message explicitly asks about previous conversation, answer from the prior messages. "
                "Never say that the conversation has no previous message."
            ),
        )
    ]

    for item in compact_chat_history(state.get("chat_history")):
        role = item.get("type")
        content = item.get("content")
        if role not in {"human", "ai"} or not isinstance(content, str) or not content:
            continue
        messages.append(("human" if role == "human" else "ai", content))

    messages.append(("human", state.get("message", "")))
    return messages


async def _format_conversation_response(state: AgentState) -> AgentState:
    chat_history = state.get("chat_history") or []

    if _is_simple_greeting(state.get("message", "")):
        return _with_chat_history(
            state,
            "Hi! How can I help you with your ERP analytics today?",
            response_kind="conversation",
        )

    if _asks_about_previous_message(state.get("message", "")) and not chat_history:
        return _with_chat_history(
            state,
            "I do not have earlier conversation context to reference yet. How can I help with your ERP analytics?",
            response_kind="conversation",
        )

    llm = get_llm()
    response = await invoke_llm(llm, _conversation_messages(state), operation="conversation_response")
    return _with_chat_history(state, _clean_conversation_answer(str(response.content)), response_kind="conversation")


async def response_formatter_node(state: AgentState) -> AgentState:
    query_plan = state.get("query_plan") or {}
    intent = _effective_intent(state, query_plan)

    if intent == "conversation_response":
        return await _format_conversation_response(state)

    if intent == "unsupported":
        return _with_chat_history(
            state,
            "I can help with read-only ERP analytics questions, but I cannot complete that request.",
        )

    if state.get("error"):
        return _without_chat_history(
            "I could not access the ERP analytics data right now. Please try again, or ask with a specific record type, filter, and date range.",
            "error",
        )

    if query_plan.get("tool") == "clarification_needed":
        question = query_plan.get("arguments", {}).get("question")
        return _with_chat_history(
            state,
            question or "Please add the missing detail so I can answer accurately.",
            "clarification",
        )

    task_decomposition = state.get("task_decomposition") or {}
    if task_decomposition.get("complexity") == "clarification_needed":
        question = task_decomposition.get("question")
        return _with_chat_history(
            state,
            question or "Please add the missing detail so I can answer accurately.",
            "clarification",
        )

    if state.get("intent") == "clarification_needed" and not _has_executed_query(query_plan, state):
        return _with_chat_history(
            state,
            "Which ERP data should I use, and what filter or time period should apply?",
            "clarification",
        )

    count_answer = _format_count_answer(query_plan, state.get("parsed_tool_result"))
    if count_answer is not None:
        return _with_chat_history(state, count_answer)

    llm = get_llm()
    formatter_context = {
        "user_message": state.get("message"),
        "chat_history": compact_chat_history(state.get("chat_history")),
        "conversation_reference": compact_conversation_reference(state.get("conversation_reference")),
        "previous_response": {
            "kind": state.get("last_response_kind"),
            "content": compact_text(state.get("last_response_content"), settings.ai_chat_history_message_chars),
        },
        "intent": intent,
        "schema_domain": state.get("schema_domain"),
        "schema_catalog": (
            compact_prompt_value(state.get("schema_catalog"), settings.ai_schema_prompt_max_chars)
            if intent == "schema_question"
            else None
        ),
        "relationship_map": (
            compact_prompt_value(state.get("relationship_map"), settings.ai_schema_prompt_max_chars)
            if intent == "schema_question"
            else None
        ),
        "task_decomposition": state.get("task_decomposition"),
        "query_plan": query_plan,
        "parsed_tool_result": compact_prompt_value(
            state.get("parsed_tool_result"), settings.ai_tool_result_prompt_max_chars
        ),
        "tool_result": compact_prompt_value(state.get("tool_result"), settings.ai_tool_result_prompt_max_chars),
        "result_status": state.get("result_status"),
        "error": state.get("error"),
    }
    response = await invoke_llm(
        llm,
        [
            ("system", RESPONSE_FORMATTER_PROMPT),
            ("human", json.dumps(formatter_context, default=str)),
        ],
        operation="response_formatter",
    )
    return _with_chat_history(state, str(response.content))
