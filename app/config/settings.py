from functools import lru_cache
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()
node_mcp_server_cwd = os.getenv("NODE_MCP_SERVER_CWD")
if node_mcp_server_cwd:
    load_dotenv(Path(node_mcp_server_cwd) / ".env", override=False)


class Settings(BaseSettings):
    app_name: str = "ERP AI Orchestration Backend"
    app_version: str = "0.1.0"
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    openai_base_url: Optional[str] = Field(default=None, alias="OPENAI_BASE_URL")
    node_mcp_server_command: str = Field(default="node", alias="NODE_MCP_SERVER_COMMAND")
    node_mcp_server_path: str = Field(default="../nodejsserver/dist/server.js", alias="NODE_MCP_SERVER_PATH")
    node_mcp_server_cwd: Optional[str] = Field(default=None, alias="NODE_MCP_SERVER_CWD")
    ai_max_retries: int = Field(default=2, alias="AI_MAX_RETRIES")
    ai_timeout_seconds: int = Field(default=60, alias="AI_TIMEOUT_SECONDS")
    api_cors_origins: str = Field(default="*", alias="API_CORS_ORIGINS")
    mongo_uri: Optional[str] = Field(default=None, alias="MONGO_URI")
    mongo_db_name: str = Field(default="massaed", alias="MONGO_DB_NAME")
    mongo_chat_history_collection: str = Field(default="ai_chat_histories", alias="MONGO_CHAT_HISTORY_COLLECTION")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @field_validator("openai_base_url")
    @classmethod
    def empty_base_url_to_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @field_validator("mongo_uri")
    @classmethod
    def empty_mongo_uri_to_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @property
    def cors_origins(self) -> List[str]:
        if self.api_cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
