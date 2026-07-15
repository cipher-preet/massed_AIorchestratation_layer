import re
from typing import Any, Dict, List, Optional

from app.agents.erp_analytics_agent.state import AgentState


def _normalized_history(chat_history: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normalized = []
    for item in chat_history:
        role = item.get("type") or item.get("role")
        content = item.get("content")
        if role not in {"human", "ai", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        normalized.append(
            {
                "type": "human" if role == "user" else "ai" if role == "assistant" else role,
                "content": content,
            }
        )
    return normalized


def _latest_message(history: List[Dict[str, str]], message_type: str) -> Optional[str]:
    for item in reversed(history):
        if item.get("type") == message_type:
            return item.get("content")
    return None


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", value.lower())


def _is_clarification_question(value: Optional[str]) -> bool:
    if not value or "?" not in value:
        return False
    normalized = value.lower()
    return any(
        phrase in normalized
        for phrase in (
            "do you mean",
            "do you want",
            "did you mean",
            "which",
            "what exactly",
            "for all",
            "specific",
            "clarify",
        )
    )


def _is_short_clarification_reply(value: str) -> bool:
    normalized = value.strip().lower().strip(".,!? ")
    if not normalized:
        return False
    if len(_tokens(normalized)) <= 8:
        return True
    return normalized.startswith(("yes ", "no ", "i want ", "i need "))


def _quoted_values(value: str) -> list[str]:
    quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", value)
    return [left or right for left, right in quoted if left or right]


def _mentions_any(value: str, words: set[str]) -> bool:
    normalized = value.lower()
    return any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in words)


def _resolved_followup_message(message: str, history: List[Dict[str, str]], previous_assistant_answer: Optional[str]) -> Optional[str]:
    if not _is_clarification_question(previous_assistant_answer) or not _is_short_clarification_reply(message):
        return None

    previous_user_message = _latest_message(history, "human") or ""
    context = " ".join([previous_user_message, previous_assistant_answer or "", message]).lower()

    wants_revenue = _mentions_any(context, {"revenue", "sales", "sale", "slaes", "payment", "purchased", "purchase"})
    wants_membership = _mentions_any(context, {"membership", "memberships", "plan", "plans", "amc"})
    wants_all = _mentions_any(message, {"all", "everything", "every"}) or "all memberships" in context
    wants_sales = _mentions_any(context, {"sales", "sale", "slaes", "purchased", "purchase"})

    if wants_revenue and wants_membership:
        request = "Show "
        if wants_sales:
            request += "membership sales revenue"
        else:
            request += "membership revenue"

        if wants_all:
            return f"{request} for all membership plans."

        quoted_names = _quoted_values(previous_assistant_answer or "")
        if quoted_names and not _mentions_any(message, {"all", "everything", "every"}):
            return f"{request} for membership named {quoted_names[-1]}."

        return f"{request}."

    if wants_all and previous_user_message:
        return f"{previous_user_message} for all records."

    return None


async def conversation_reference_node(state: AgentState) -> AgentState:
    history = _normalized_history(state.get("chat_history") or [])
    previous_user_message = _latest_message(history, "human")
    previous_assistant_answer = _latest_message(history, "ai")
    original_message = state.get("message", "")
    resolved_message = _resolved_followup_message(original_message, history, previous_assistant_answer)

    conversation_reference = {
        "conversation_id": state.get("conversation_id"),
        "recent_messages": history[-20:],
        "previous_user_message": previous_user_message,
        "previous_assistant_answer": previous_assistant_answer,
        "original_user_message": original_message,
        "resolved_user_message": resolved_message,
    }

    updates: AgentState = {
        "chat_history": history,
        "conversation_reference": conversation_reference,
    }

    if resolved_message:
        updates["message"] = resolved_message

    if previous_assistant_answer and not state.get("last_response_content"):
        updates["last_response_kind"] = state.get("last_response_kind") or "answer"
        updates["last_response_content"] = previous_assistant_answer

    return updates
