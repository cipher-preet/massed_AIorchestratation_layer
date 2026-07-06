from langchain_openai import ChatOpenAI

from app.config.settings import settings


def get_llm() -> ChatOpenAI:
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
        max_retries=settings.ai_max_retries,
        timeout=settings.ai_timeout_seconds,
        temperature=0,
    )
