import json
import re

from app.agents.erp_analytics_agent.prompts import INTENT_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.core.cost_optimization import compact_chat_history, compact_conversation_reference, invoke_llm
from app.core.llm import get_llm
from app.utils.json_utils import extract_json_object


WRITE_VERBS = {
    "create",
    "insert",
    "update",
    "edit",
    "patch",
    "delete",
    "remove",
    "drop",
}

READ_VERBS = {
    "get",
    "give",
    "show",
    "list",
    "fetch",
    "find",
    "search",
    "count",
    "compare",
    "summarize",
    "analyse",
    "analyze",
    "display",
    "retrieve",
}
DETAIL_TERMS = {
    "detail",
    "details",
    "profile",
    "profiles",
    "record",
    "records",
    "data",
    "info",
    "information",
}

GREETING_MESSAGES = {
    "hello",
    "hey",
    "hi",
    "hiya",
    "namaste",
}


def _contains_word(message: str, words: set[str]) -> bool:
    return any(re.search(rf"\b{re.escape(word)}\b", message, re.IGNORECASE) for word in words)


def _is_simple_greeting(message: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", message.lower()).strip()
    return normalized in GREETING_MESSAGES


def _is_direct_read_request(message: str) -> bool:
    return _contains_word(message, READ_VERBS) and (
        _contains_word(message, DETAIL_TERMS) or bool(re.search(r"\ball\b", message, re.IGNORECASE))
    )


async def intent_node(state: AgentState) -> AgentState:
    message = state["message"]
    chat_history = state.get("chat_history") or []

    if _is_simple_greeting(message):
        return {"intent": "conversation_response"}

    if _contains_word(message, WRITE_VERBS):
        return {"intent": "unsupported"}

    if _is_direct_read_request(message):
        return {"intent": "analytics_query"}

    llm = get_llm()
    try:
        response = await invoke_llm(
            llm,
            [
                ("system", INTENT_PROMPT),
                (
                    "human",
                    json.dumps(
                        {
                            "user_request": message,
                            "chat_history": compact_chat_history(chat_history),
                            "conversation_reference": compact_conversation_reference(state.get("conversation_reference")),
                            "previous_response": {
                                "kind": state.get("last_response_kind"),
                                "content": state.get("last_response_content"),
                            },
                        },
                        default=str,
                    ),
                ),
            ],
            operation="intent",
        )
        parsed = extract_json_object(str(response.content))
    except Exception:
        if _contains_word(message, READ_VERBS):
            return {"intent": "analytics_query"}
        return {"intent": "clarification_needed"}

    intent = parsed.get("intent", "unsupported")
    if intent not in {"analytics_query", "schema_question", "clarification_needed", "unsupported", "conversation_response"}:
        intent = "unsupported"
    if intent == "unsupported" and _contains_word(message, READ_VERBS):
        intent = "analytics_query"
    return {"intent": intent}
