import logging
from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from pymongo import DESCENDING, MongoClient

from app.config.settings import settings


logger = logging.getLogger(__name__)


class ChatHistoryStore:
    @property
    def is_configured(self) -> bool:
        return bool(settings.mongo_uri)

    @staticmethod
    def _session_id(user_id: str, space_id: str, conversation_id: str) -> str:
        return f"{space_id}:{user_id}:{conversation_id}"

    @staticmethod
    def _session_prefix(user_id: str, space_id: str) -> str:
        return f"{space_id}:{user_id}:"

    @staticmethod
    def _conversation_id_from_session(session_id: str) -> Optional[str]:
        parts = session_id.split(":", 2)
        return parts[2] if len(parts) == 3 and parts[2] else None

    def _history(self, session_id: str):
        if not settings.mongo_uri:
            raise RuntimeError("MONGO_URI is not configured.")

        try:
            from langchain_mongodb import MongoDBChatMessageHistory
        except ImportError as exc:
            raise RuntimeError(
                "langchain-mongodb is not installed. Run `pip install -r requirements.txt`."
            ) from exc

        return MongoDBChatMessageHistory(
            connection_string=settings.mongo_uri,
            session_id=session_id,
            database_name=settings.mongo_db_name,
            collection_name=settings.mongo_chat_history_collection,
        )

    def append_turn(
        self,
        *,
        user_id: str,
        space_id: str,
        conversation_id: str,
        message: str,
        answer: str,
    ) -> None:
        if not self.is_configured:
            logger.warning("MONGO_URI is not configured; chat history was not persisted.")
            return

        try:
            history = self._history(self._session_id(user_id, space_id, conversation_id))
            history.add_user_message(message)
            history.add_ai_message(answer)
        except Exception:
            logger.exception("Could not persist MongoDB chat history.")

    def get_history(
        self,
        *,
        user_id: str,
        space_id: str,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("MONGO_URI is not configured; returning empty chat history.")
            return []

        try:
            messages = self._history(self._session_id(user_id, space_id, conversation_id)).messages
            if limit and limit > 0:
                messages = messages[-limit * 2 :]
            return self._serialize_messages(messages)
        except Exception:
            logger.exception("Could not load MongoDB chat history.")
            return []

    def get_histories(
        self,
        *,
        user_id: str,
        space_id: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not self.is_configured:
            logger.warning("MONGO_URI is not configured; returning empty chat histories.")
            return []

        conversations = []
        for session_id in self._list_session_ids(user_id=user_id, space_id=space_id):
            conversation_id = self._conversation_id_from_session(session_id)
            if not conversation_id:
                continue

            try:
                messages = self._history(session_id).messages
                if limit and limit > 0:
                    messages = messages[-limit * 2 :]
            except Exception:
                logger.exception("Could not load MongoDB chat history session.")
                messages = []

            conversations.append(
                {
                    "conversationId": conversation_id,
                    "history": self._serialize_messages(messages),
                }
            )

        return conversations

    def get_latest_conversation_id(self, *, user_id: str, space_id: str) -> Optional[str]:
        for session_id in self._list_session_ids(user_id=user_id, space_id=space_id):
            conversation_id = self._conversation_id_from_session(session_id)
            if conversation_id:
                return conversation_id
        return None

    def _list_session_ids(self, *, user_id: str, space_id: str) -> List[str]:
        if not settings.mongo_uri:
            return []

        prefix = self._session_prefix(user_id, space_id)
        client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=10000)
        try:
            collection = client[settings.mongo_db_name][settings.mongo_chat_history_collection]
            collection.create_index("SessionId")
            documents = collection.find(
                {"SessionId": {"$regex": f"^{prefix}"}},
                {"_id": 0, "SessionId": 1},
                sort=[("_id", DESCENDING)],
            )
            seen = set()
            session_ids = []
            for document in documents:
                session_id = document.get("SessionId")
                if isinstance(session_id, str) and session_id not in seen:
                    seen.add(session_id)
                    session_ids.append(session_id)
            return session_ids
        except Exception:
            logger.exception("Could not list MongoDB chat history sessions.")
            return []
        finally:
            client.close()

    @staticmethod
    def _serialize_messages(messages: List[BaseMessage]) -> List[Dict[str, str]]:
        return [
            {
                "type": message.type,
                "content": str(message.content),
            }
            for message in messages
        ]


chat_history_store = ChatHistoryStore()
