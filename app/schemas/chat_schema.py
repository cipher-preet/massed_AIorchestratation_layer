from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: str = Field(alias="userId")
    space_id: str = Field(alias="spaceId")
    message: str
    conversation_id: Optional[str] = Field(default=None, alias="conversationId")

    model_config = {"populate_by_name": True}


class ChatResponse(BaseModel):
    success: bool
    answer: str
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list, alias="toolCalls")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


class ChatHistoryMessage(BaseModel):
    type: str
    content: str

    model_config = {"populate_by_name": True}


class ChatHistoryResponse(BaseModel):
    success: bool
    conversation_id: str = Field(alias="conversationId")
    history: List[ChatHistoryMessage] = Field(default_factory=list)
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


class ChatConversationHistory(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    history: List[ChatHistoryMessage] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class ChatHistoriesResponse(BaseModel):
    success: bool
    conversations: List[ChatConversationHistory] = Field(default_factory=list)
    error: Optional[str] = None

    model_config = {"populate_by_name": True}
