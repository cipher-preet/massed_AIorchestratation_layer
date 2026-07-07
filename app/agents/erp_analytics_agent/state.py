from typing import Any, Dict, List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    user_id: str
    space_id: str
    message: str
    conversation_id: Optional[str]
    conversation_reference: Optional[Dict[str, Any]]
    intent: Optional[str]
    schema_catalog: Optional[Dict[str, Any]]
    relationship_map: Optional[Dict[str, Any]]
    task_decomposition: Optional[Dict[str, Any]]
    query_plan: Optional[Dict[str, Any]]
    tool_result: Optional[Dict[str, Any]]
    parsed_tool_result: Optional[Dict[str, Any]]
    result_status: Optional[str]
    answer: Optional[str]
    error: Optional[str]
    tool_calls: List[Dict[str, Any]]
    chat_history: List[Dict[str, Any]]
    persist_chat_history: Optional[bool]
    last_response_kind: Optional[str]
    last_response_content: Optional[str]
