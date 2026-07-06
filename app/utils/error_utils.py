from app.schemas.chat_schema import ChatResponse


def safe_error_response(message: str = "I could not complete this analytics request.") -> ChatResponse:
    return ChatResponse(success=False, answer=message, error="The analytics request could not be completed.")
