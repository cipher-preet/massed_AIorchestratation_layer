import logging
from typing import Any, Dict, List
from uuid import uuid4

from app.agents.erp_analytics_agent.graph import erp_analytics_graph
from app.schemas.chat_schema import ChatRequest
from app.services.chat_history_store import chat_history_store


logger = logging.getLogger(__name__)


class OrchestrationService:
    @staticmethod
    def _conversation_id(request: ChatRequest) -> str:
        if request.conversation_id:
            return request.conversation_id

        latest_conversation_id = chat_history_store.get_latest_conversation_id(
            user_id=request.user_id,
            space_id=request.space_id,
        )
        return latest_conversation_id or str(uuid4())

    @staticmethod
    def _thread_id(user_id: str, space_id: str, conversation_id: str) -> str:
        return f"{space_id}:{user_id}:{conversation_id}"

    async def invoke(self, request: ChatRequest) -> Dict[str, Any]:
        conversation_id = self._conversation_id(request)
        initial_state = {
            "user_id": request.user_id,
            "space_id": request.space_id,
            "message": request.message,
            "conversation_id": conversation_id,
            "conversation_reference": None,
            "intent": None,
            "schema_catalog": None,
            "relationship_map": None,
            "task_decomposition": None,
            "query_plan": None,
            "tool_result": None,
            "parsed_tool_result": None,
            "result_status": None,
            "answer": None,
            "error": None,
            "tool_calls": [],
            "persist_chat_history": True,
            "chat_history": chat_history_store.get_history(
                user_id=request.user_id,
                space_id=request.space_id,
                conversation_id=conversation_id,
                limit=20,
            ),
        }
        config = {
            "configurable": {
                "thread_id": self._thread_id(request.user_id, request.space_id, conversation_id),
            }
        }
        try:
            return await erp_analytics_graph.ainvoke(initial_state, config=config)
        except Exception:
            logger.exception("LangGraph orchestration failed")
            return {
                **initial_state,
                "answer": "I could not complete this analytics request.",
                "error": "The analytics request could not be completed.",
            }

    async def get_history(self, user_id: str, space_id: str, conversation_id: str) -> List[Dict[str, Any]]:
        return chat_history_store.get_history(
            user_id=user_id,
            space_id=space_id,
            conversation_id=conversation_id,
        )

    async def get_histories(self, user_id: str, space_id: str) -> List[Dict[str, Any]]:
        return chat_history_store.get_histories(
            user_id=user_id,
            space_id=space_id,
        )


orchestration_service = OrchestrationService()
