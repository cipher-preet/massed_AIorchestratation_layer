import json
import logging
from time import perf_counter
from typing import Any, Iterable

from app.config.settings import settings


logger = logging.getLogger(__name__)


SAMPLE_KEYS = {"sample", "samples", "example", "examples", "sample_documents", "sample_records", "sample_rows"}
FIELD_KEYS = {"field", "fields", "schema", "properties", "columns"}


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
        return text


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return max(1, len(text) // 4)


def compact_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str) or len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}... [truncated {len(value) - max_chars} chars]"


def compact_chat_history(history: Iterable[dict[str, Any]] | None) -> list[dict[str, str]]:
    compacted: list[dict[str, str]] = []
    max_messages = max(0, settings.ai_chat_history_prompt_messages)
    max_chars = max(200, settings.ai_chat_history_message_chars)

    for item in list(history or [])[-max_messages:]:
        role = item.get("type") or item.get("role")
        content = item.get("content")
        if role not in {"human", "ai", "user", "assistant"} or not isinstance(content, str) or not content.strip():
            continue
        compacted.append(
            {
                "type": "human" if role == "user" else "ai" if role == "assistant" else role,
                "content": compact_text(content, max_chars),
            }
        )
    return compacted


def compact_conversation_reference(reference: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(reference, dict):
        return reference

    max_chars = max(200, settings.ai_chat_history_message_chars)
    max_messages = max(0, settings.ai_conversation_reference_messages)
    recent_messages = reference.get("recent_messages")
    if not isinstance(recent_messages, list):
        recent_messages = []
    return {
        "conversation_id": reference.get("conversation_id"),
        "recent_messages": compact_chat_history(recent_messages[-max_messages:]),
        "previous_user_message": compact_text(reference.get("previous_user_message"), max_chars),
        "previous_assistant_answer": compact_text(reference.get("previous_assistant_answer"), max_chars),
        "original_user_message": compact_text(reference.get("original_user_message"), max_chars),
        "resolved_user_message": compact_text(reference.get("resolved_user_message"), max_chars),
    }


def compact_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for tool in tools:
        input_schema = tool.get("inputSchema") or tool.get("args_schema") or tool.get("schema")
        compacted.append(
            {
                "name": tool.get("name"),
                "description": compact_text(tool.get("description"), 500),
                "inputSchema": _compact_json_value(input_schema, max_list_items=20, max_dict_keys=80),
            }
        )
    return compacted


def _looks_like_collection_definition(value: Any) -> bool:
    return isinstance(value, dict) and any(key in value for key in ("fields", "schema", "sample", "indexes", "relationships", "collectionName"))


def _collection_field_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        fields = value.get("fields") or value.get("schema") or value.get("properties") or value.get("columns")
        if isinstance(fields, dict):
            return [str(key) for key in fields.keys()]
        if isinstance(fields, list):
            names = []
            for field in fields:
                if isinstance(field, str):
                    names.append(field)
                elif isinstance(field, dict):
                    name = field.get("name") or field.get("field") or field.get("key")
                    if name:
                        names.append(str(name))
            return names
    return []


def _schema_overview(value: Any) -> Any:
    payload = _mcp_payload(value)
    collections: dict[str, Any] = {}

    def visit(node: Any, key_name: str | None = None, in_collection_container: bool = False) -> None:
        if isinstance(node, dict):
            child_is_collection = _looks_like_collection_definition(node)
            if key_name and (in_collection_container or child_is_collection):
                collections[key_name] = {
                    "fields": _collection_field_names(node),
                    "relationships": _compact_json_value(node.get("relationships"), max_list_items=50, max_dict_keys=80),
                    "indexes": _compact_json_value(node.get("indexes"), max_list_items=20, max_dict_keys=40),
                }
            for key, child in node.items():
                visit(child, str(key), in_collection_container=str(key) in {"collections", "schema_catalog"})
        elif isinstance(node, list):
            for child in node:
                visit(child, key_name, in_collection_container=in_collection_container)

    visit(payload)
    return {"collections": collections} if collections else _compact_json_value(payload)


def _compact_json_value(value: Any, max_list_items: int = 40, max_dict_keys: int = 200, parent_key: str | None = None) -> Any:
    payload = _mcp_payload(value)

    if isinstance(payload, str):
        return compact_text(payload, 1000)

    if isinstance(payload, list):
        item_limit = 2 if parent_key and parent_key.lower() in SAMPLE_KEYS else max_list_items
        return [_compact_json_value(item, max_list_items, max_dict_keys, parent_key) for item in payload[:item_limit]]

    if isinstance(payload, dict):
        compacted: dict[str, Any] = {}
        for index, (key, child_value) in enumerate(payload.items()):
            if index >= max_dict_keys and str(key).lower() not in FIELD_KEYS:
                compacted["_truncated_keys"] = len(payload) - max_dict_keys
                break
            compacted[str(key)] = _compact_json_value(child_value, max_list_items, max_dict_keys, str(key))
        return compacted

    return payload


def compact_prompt_value(value: Any, max_chars: int) -> Any:
    payload = _mcp_payload(value)
    compacted = _compact_json_value(payload)
    if len(json.dumps(compacted, default=str)) <= max_chars:
        return compacted

    overview = _schema_overview(payload)
    if len(json.dumps(overview, default=str)) <= max_chars:
        return overview

    return compact_text(json.dumps(overview, default=str), max_chars)


async def invoke_llm(llm: Any, messages: list[tuple[str, str]], *, operation: str) -> Any:
    started_at = perf_counter()
    input_tokens = estimate_tokens(messages)
    response = await llm.ainvoke(messages)

    if settings.ai_enable_cost_logging:
        output_tokens = estimate_tokens(str(getattr(response, "content", "")))
        metadata = getattr(response, "response_metadata", {}) or {}
        usage = metadata.get("token_usage") or metadata.get("usage") or {}
        logger.info(
            "llm_call operation=%s model=%s input_tokens_est=%s output_tokens_est=%s usage=%s elapsed_ms=%s",
            operation,
            getattr(llm, "model_name", None) or getattr(llm, "model", None),
            input_tokens,
            output_tokens,
            usage,
            int((perf_counter() - started_at) * 1000),
        )

    return response
