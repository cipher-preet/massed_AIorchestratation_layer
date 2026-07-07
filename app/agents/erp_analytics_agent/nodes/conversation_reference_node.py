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


async def conversation_reference_node(state: AgentState) -> AgentState:
    history = _normalized_history(state.get("chat_history") or [])
    previous_user_message = _latest_message(history, "human")
    previous_assistant_answer = _latest_message(history, "ai")

    conversation_reference = {
        "conversation_id": state.get("conversation_id"),
        "recent_messages": history[-20:],
        "previous_user_message": previous_user_message,
        "previous_assistant_answer": previous_assistant_answer,
    }

    updates: AgentState = {
        "chat_history": history,
        "conversation_reference": conversation_reference,
    }

    if previous_assistant_answer and not state.get("last_response_content"):
        updates["last_response_kind"] = state.get("last_response_kind") or "answer"
        updates["last_response_content"] = previous_assistant_answer

    return updates
