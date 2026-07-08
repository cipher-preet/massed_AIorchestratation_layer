import json
import re
from typing import Any

from app.agents.erp_analytics_agent.prompts import TASK_DECOMPOSITION_PROMPT
from app.agents.erp_analytics_agent.state import AgentState
from app.config.settings import settings
from app.core.llm import get_llm
from app.utils.json_utils import extract_json_object


READ_WORDS = {
    "get",
    "give",
    "show",
    "list",
    "fetch",
    "find",
    "display",
    "retrieve",
}
DETAIL_WORDS = {
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
STOP_ENTITY_WORDS = READ_WORDS | DETAIL_WORDS | {
    "all",
    "the",
    "a",
    "an",
    "me",
    "please",
    "full",
    "complete",
    "every",
    "with",
    "and",
    "also",
    "filter",
    "filtered",
    "by",
    "for",
    "of",
    "in",
    "on",
    "from",
    "to",
    "need",
    "i",
    "about",
}


def _mcp_payload(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    content = value.get("content")
    if not isinstance(content, list) or not content:
        return value

    first_item = content[0]
    if not isinstance(first_item, dict) or first_item.get("type") != "text":
        return value

    text = first_item.get("text")
    if not isinstance(text, str):
        return value

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _has_branch_collection(schema_catalog: Any) -> bool:
    payload = _mcp_payload(schema_catalog)
    if isinstance(payload, dict):
        return any("branch" in str(key).lower() for key in payload.keys()) or any(
            _has_branch_collection(child_value) for child_value in payload.values()
        )
    if isinstance(payload, list):
        return any(_has_branch_collection(item) for item in payload)
    if isinstance(payload, str):
        return "branch" in payload.lower()
    return False


def _schema_text(schema_catalog: Any) -> str:
    payload = _mcp_payload(schema_catalog)
    try:
        return json.dumps(payload, default=str).lower()
    except TypeError:
        return str(payload).lower()


def _looks_like_collection_definition(value: Any) -> bool:
    return isinstance(value, dict) and any(
        key in value for key in ("fields", "schema", "sample", "indexes", "relationships", "collectionName")
    )


def _collect_collection_names(value: Any, in_collection_container: bool = False) -> list[str]:
    payload = _mcp_payload(value)
    collection_names: list[str] = []

    if isinstance(payload, dict):
        for key, child_value in payload.items():
            key_text = str(key)
            child_is_collection = _looks_like_collection_definition(child_value)
            if key_text in {"collections", "schema_catalog"}:
                collection_names.extend(_collect_collection_names(child_value, in_collection_container=True))
                continue
            if (in_collection_container or child_is_collection) and key_text and not key_text.startswith("$"):
                collection_names.append(key_text)
            if key in {"collection", "collectionName", "name"} and isinstance(child_value, str):
                collection_names.append(child_value)
            collection_names.extend(_collect_collection_names(child_value, in_collection_container=False))
        return list(dict.fromkeys(collection_names))

    if isinstance(payload, list):
        for item in payload:
            collection_names.extend(_collect_collection_names(item, in_collection_container=in_collection_container))
        return list(dict.fromkeys(collection_names))

    return []


def _normalize_entity_token(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    if normalized.endswith("s") and len(normalized) > 4:
        normalized = normalized[:-1]
    return normalized


def _token_matches_collection(token: str, collection_name: str) -> bool:
    token_normalized = _normalize_entity_token(token)
    collection_normalized = _normalize_entity_token(collection_name)
    return token_normalized == collection_normalized or token_normalized in collection_normalized.split("_")


def _matching_collections_for_terms(schema_catalog: Any, terms: list[str]) -> list[str]:
    matches = []
    for collection_name in _collect_collection_names(schema_catalog):
        if any(_token_matches_collection(term, collection_name) for term in terms):
            matches.append(collection_name)
    return list(dict.fromkeys(matches))


def _candidate_entity_words(message: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", message.lower())
    candidates = []
    for token in tokens:
        if token in STOP_ENTITY_WORDS or len(token) < 3:
            continue
        candidates.append(token)
        if token.endswith("s") and len(token) > 4:
            candidates.append(token[:-1])
    return candidates


def _requested_terms_before_about(message: str) -> list[str]:
    before_about = re.split(r"\babout\b", message, flags=re.IGNORECASE, maxsplit=1)[0]
    return _candidate_entity_words(before_about)


def _lookup_value_after_about(message: str) -> str | None:
    parts = re.split(r"\babout\b", message, flags=re.IGNORECASE, maxsplit=1)
    if len(parts) != 2:
        return None
    lookup_value = parts[1].strip(" \t\r\n:,-")
    return lookup_value or None


def _has_schema_entity_match(message: str, schema_catalog: Any) -> bool:
    schema_text = _schema_text(schema_catalog)
    return any(candidate in schema_text for candidate in _candidate_entity_words(message))


def _looks_like_complete_detail_request(message: str, parsed: dict[str, Any]) -> bool:
    normalized = message.lower()
    if not any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in READ_WORDS):
        return False
    if not ("all" in normalized or "full" in normalized or "complete" in normalized or "every" in normalized):
        return False
    if not any(re.search(rf"\b{re.escape(word)}\b", normalized) for word in DETAIL_WORDS):
        return False
    if parsed.get("complexity") != "clarification_needed":
        return False

    question = str(parsed.get("question") or "").lower()
    reason = str(parsed.get("reason") or "").lower()
    return any(word in f"{question} {reason}" for word in ("filter", "time", "period", "date", "range"))


def _all_details_decomposition(message: str) -> dict[str, Any]:
    entities = _candidate_entity_words(message)[:3]
    return {
        "complexity": "simple",
        "recommended_plan_type": "find",
        "tasks": [
            {
                "id": "fetch_all_details",
                "description": "Fetch all matching records for the requested ERP entity with full detail fields.",
                "depends_on": [],
            }
        ],
        "entities": entities,
        "reason": "The user asked for all details of a specific entity; no filter or time period is required.",
    }


def _looks_like_related_detail_request(message: str, schema_catalog: Any) -> bool:
    if not re.search(r"\babout\b", message, re.IGNORECASE):
        return False
    if not any(re.search(rf"\b{re.escape(word)}\b", message, re.IGNORECASE) for word in DETAIL_WORDS):
        return False
    requested_terms = _requested_terms_before_about(message)
    lookup_value = _lookup_value_after_about(message)
    return bool(requested_terms and lookup_value and _matching_collections_for_terms(schema_catalog, requested_terms))


def _related_detail_decomposition(message: str, schema_catalog: Any) -> dict[str, Any]:
    requested_terms = _requested_terms_before_about(message)
    lookup_value = _lookup_value_after_about(message)
    matching_collections = _matching_collections_for_terms(schema_catalog, requested_terms)
    target_collection = matching_collections[0] if matching_collections else requested_terms[0]

    return {
        "complexity": "multi_step",
        "recommended_plan_type": "dependent_tools",
        "tasks": [
            {
                "id": "resolve_subject",
                "description": (
                    f"Find the person/entity record matching '{lookup_value}' using real searchable fields "
                    "from schema_catalog, keeping _id and any real id/reference fields."
                ),
                "depends_on": [],
            },
            {
                "id": "fetch_requested_details",
                "description": (
                    f"Fetch records from '{target_collection}' linked to the resolved subject through "
                    "relationship_map or real reference fields. Do not answer from the subject lookup alone."
                ),
                "depends_on": ["resolve_subject"],
            },
        ],
        "entities": list(dict.fromkeys([target_collection, *matching_collections, "technicians"])),
        "requested_entity_terms": requested_terms,
        "target_collection_hint": target_collection,
        "lookup_value": lookup_value,
        "reason": (
            "The request asks for a related detail collection before 'about'; the text after 'about' is only "
            "the lookup value used to find the linked subject."
        ),
    }


def _looks_like_missing_branch_filter(message: str, parsed: dict[str, Any]) -> bool:
    normalized = message.lower()
    if "branch" not in normalized:
        return False

    if parsed.get("complexity") != "clarification_needed":
        return False

    question = str(parsed.get("question") or "").lower()
    reason = str(parsed.get("reason") or "").lower()
    return "branch" in question or "branch" in reason or bool(
        re.search(r"\b(filter|filtered|group|grouped|by)\s+(the\s+)?branch\b", normalized)
    )


def _branch_options_decomposition(message: str) -> dict[str, Any]:
    return {
        "complexity": "simple",
        "recommended_plan_type": "find",
        "tasks": [
            {
                "id": "list_branch_options",
                "description": (
                    "List available branch records with user-facing display fields so the user can choose "
                    "the branch value before technician details are filtered."
                ),
                "depends_on": [],
            }
        ],
        "entities": ["branches", "technicians"],
        "reason": f"The request needs a branch filter value before technician details can be filtered: {message}",
    }


async def task_decomposition_node(state: AgentState) -> AgentState:
    llm = get_llm(model=settings.openai_planner_model)
    prompt_context = {
        "user_message": state["message"],
        "chat_history": (state.get("chat_history") or [])[-10:],
        "conversation_reference": state.get("conversation_reference"),
        "schema_domain": state.get("schema_domain"),
        "schema_catalog": state.get("schema_catalog"),
        "relationship_map": state.get("relationship_map"),
    }
    try:
        response = await llm.ainvoke(
            [
                ("system", TASK_DECOMPOSITION_PROMPT),
                ("human", json.dumps(prompt_context, default=str)),
            ]
        )
        parsed = extract_json_object(str(response.content))
    except Exception:
        parsed = {
            "complexity": "clarification_needed",
            "recommended_plan_type": "clarification",
            "tasks": [],
            "entities": [],
            "question": "Which ERP data should I use, and what filter or time period should apply?",
            "reason": "The request could not be decomposed safely.",
        }

    if _looks_like_related_detail_request(state["message"], state.get("schema_catalog")):
        parsed = _related_detail_decomposition(state["message"], state.get("schema_catalog"))
    elif _looks_like_missing_branch_filter(state["message"], parsed) and _has_branch_collection(
        state.get("schema_catalog")
    ):
        parsed = _branch_options_decomposition(state["message"])
    elif _looks_like_complete_detail_request(state["message"], parsed) and _has_schema_entity_match(
        state["message"], state.get("schema_catalog")
    ):
        parsed = _all_details_decomposition(state["message"])

    return {"task_decomposition": parsed}
