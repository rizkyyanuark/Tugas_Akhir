"""Message feedback data access layer - Repository."""

from typing import Any

from sqlalchemy import select

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import MessageFeedback


class MessageFeedbackRepository:
    """Message feedback data access layer."""

    async def get_by_id(self, id: int) -> MessageFeedback | None:
        """Get message feedback by ID."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MessageFeedback).where(MessageFeedback.id == id))
            return result.scalar_one_or_none()

    async def list_by_message(self, message_id: int) -> list[MessageFeedback]:
        """Get feedback list for a message."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MessageFeedback).where(MessageFeedback.message_id == message_id))
            return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> MessageFeedback:
        """Create message feedback."""
        async with pg_manager.get_async_session_context() as session:
            feedback = MessageFeedback(**data)
            session.add(feedback)
        return feedback

    async def exists_by_message_and_user(self, message_id: int, user_id: str) -> bool:
        """Check whether the user has already submitted feedback for the message."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(MessageFeedback.id).where(
                    MessageFeedback.message_id == message_id, MessageFeedback.user_id == user_id
                )
            )
            return result.scalar_one_or_none() is not None
