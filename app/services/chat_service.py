from app.schemas.chat_schema import ChatHistoriesResponse, ChatHistoryResponse, ChatRequest, ChatResponse
from app.services.chat_history_store import chat_history_store
from app.services.orchestration_service import orchestration_service


BAD_EMPTY_HISTORY_ANSWER = "There is no previous message in this conversation."


def _is_simple_greeting(message: str) -> bool:
    normalized = "".join(char.lower() for char in message if char.isalnum() or char.isspace()).strip()
    return normalized in {"hello", "hey", "hi", "hiya", "namaste"}


def _safe_answer(message: str, answer: str) -> str:
    if _is_simple_greeting(message):
        return "Hi! How can I help you with your ERP analytics today?"

    if answer.strip().rstrip(".") == BAD_EMPTY_HISTORY_ANSWER.rstrip("."):
        return "I do not have earlier conversation context to reference yet. How can I help with your ERP analytics?"

    return answer


class ChatService:
    @staticmethod
    def _should_persist_history(state: dict) -> bool:
        return state.get("persist_chat_history") is not False

    async def handle_chat(self, request: ChatRequest) -> ChatResponse:
        state = await orchestration_service.invoke(request)
        success = not bool(state.get("error"))
        conversation_id = state.get("conversation_id") or request.conversation_id
        metadata = {
            "conversationId": conversation_id,
            "intent": state.get("intent"),
            "schemaDomain": state.get("schema_domain"),
            "conversationReference": state.get("conversation_reference"),
            "taskDecomposition": state.get("task_decomposition"),
            "queryPlan": state.get("query_plan"),
            "resultStatus": state.get("result_status"),
        }
        answer = _safe_answer(
            request.message,
            state.get("answer") or "I could not complete this analytics request.",
        )
        error = None if success else state.get("error") or "The analytics request could not be completed."

        if conversation_id and self._should_persist_history(state):
            chat_history_store.append_turn(
                user_id=request.user_id,
                space_id=request.space_id,
                conversation_id=conversation_id,
                message=request.message,
                answer=answer,
            )

        return ChatResponse(
            success=success,
            answer=answer,
            toolCalls=state.get("tool_calls", []),
            metadata=metadata,
            error=error,
        )





    async def get_history(self, user_id: str, space_id: str, conversation_id: str) -> ChatHistoryResponse:
        history = await orchestration_service.get_history(user_id, space_id, conversation_id)
        return ChatHistoryResponse(
            success=True,
            conversationId=conversation_id,
            history=history,
            error=None,
        )

    async def get_histories(self, user_id: str, space_id: str) -> ChatHistoriesResponse:
        conversations = await orchestration_service.get_histories(user_id, space_id)
        return ChatHistoriesResponse(
            success=True,
            conversations=conversations,
            error=None,
        )


chat_service = ChatService()
