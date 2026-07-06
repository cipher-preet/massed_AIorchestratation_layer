from fastapi import APIRouter, Query

from app.schemas.chat_schema import ChatHistoriesResponse, ChatHistoryResponse, ChatRequest, ChatResponse
from app.services.chat_service import chat_service


router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await chat_service.handle_chat(request)


@router.get("/chat/history", response_model=ChatHistoriesResponse)
async def chat_histories(
    user_id: str = Query(alias="userId"),
    space_id: str = Query(alias="spaceId"),
) -> ChatHistoriesResponse:
    return await chat_service.get_histories(user_id=user_id, space_id=space_id)


@router.get("/chat/{conversation_id}/history", response_model=ChatHistoryResponse)
async def chat_history(
    conversation_id: str,
    user_id: str = Query(alias="userId"),
    space_id: str = Query(alias="spaceId"),
) -> ChatHistoryResponse:
    return await chat_service.get_history(user_id=user_id, space_id=space_id, conversation_id=conversation_id)
