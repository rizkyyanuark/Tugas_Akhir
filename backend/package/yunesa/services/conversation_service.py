import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from yunesa.repositories.conversation_repository import ConversationRepository
from yunesa.utils.logging_config import logger


async def require_user_conversation(conv_repo: ConversationRepository, thread_id: str, user_id: str):
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(user_id) or conversation.status == "deleted":
        raise HTTPException(
            status_code=404, detail="conversation thread does not exist")
    return conversation


async def create_thread_view(
    *,
    agent_id: str,
    title: str | None,
    metadata: dict | None,
    db: AsyncSession,
    current_user_id: str,
) -> dict:
    thread_id = str(uuid.uuid4())
    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.create_conversation(
        user_id=str(current_user_id),
        agent_id=agent_id,
        title=title or "New conversation",
        thread_id=thread_id,
        metadata=metadata,
    )

    return {
        "id": conversation.thread_id,
        "user_id": conversation.user_id,
        "agent_id": conversation.agent_id,
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "metadata": conversation.extra_metadata or {},
    }


async def list_threads_view(
    *,
    agent_id: str | None,
    db: AsyncSession,
    current_user_id: str,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    conv_repo = ConversationRepository(db)
    conversations = await conv_repo.list_conversations(
        user_id=str(current_user_id),
        agent_id=agent_id,
        status="active",
        limit=limit,
        offset=offset,
    )

    return [
        {
            "id": conv.thread_id,
            "user_id": conv.user_id,
            "agent_id": conv.agent_id,
            "title": conv.title,
            "is_pinned": bool(conv.is_pinned),
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "metadata": conv.extra_metadata or {},
        }
        for conv in conversations
    ]


async def delete_thread_view(
    *,
    thread_id: str,
    db: AsyncSession,
    current_user_id: str,
) -> dict:
    conv_repo = ConversationRepository(db)
    await require_user_conversation(conv_repo, thread_id, str(current_user_id))
    deleted = await conv_repo.delete_conversation(thread_id, soft_delete=True)
    if not deleted:
        raise HTTPException(
            status_code=404, detail="conversation thread does not exist")
    return {"message": "deletesuccessful"}


async def update_thread_view(
    *,
    thread_id: str,
    title: str | None = None,
    is_pinned: bool | None = None,
    db: AsyncSession,
    current_user_id: str,
) -> dict:
    conv_repo = ConversationRepository(db)
    await require_user_conversation(conv_repo, thread_id, str(current_user_id))
    updated_conv = await conv_repo.update_conversation(thread_id, title=title, is_pinned=is_pinned)
    if not updated_conv:
        raise HTTPException(status_code=500, detail="updatefailed")
    return {
        "id": updated_conv.thread_id,
        "user_id": updated_conv.user_id,
        "agent_id": updated_conv.agent_id,
        "title": updated_conv.title,
        "is_pinned": bool(updated_conv.is_pinned),
        "created_at": updated_conv.created_at.isoformat(),
        "updated_at": updated_conv.updated_at.isoformat(),
        "metadata": updated_conv.extra_metadata or {},
    }


async def get_thread_history_view(
    *,
    thread_id: str,
    current_user_id: str,
    db: AsyncSession,
) -> dict:
    """Get conversation message history, including user feedback status."""
    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(current_user_id) or conversation.status == "deleted":
        raise HTTPException(
            status_code=404, detail="conversation thread does not exist")

    messages = await conv_repo.get_messages_by_thread_id(thread_id)

    history: list[dict] = []
    role_type_map = {"user": "human", "assistant": "ai",
                     "tool": "tool", "system": "system"}

    for msg in messages:
        user_feedback = None
        if msg.feedbacks:
            for feedback in msg.feedbacks:
                if feedback.user_id == str(current_user_id):
                    user_feedback = {
                        "id": feedback.id,
                        "rating": feedback.rating,
                        "reason": feedback.reason,
                        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
                    }
                    break

        msg_dict = {
            "id": msg.id,
            "type": role_type_map.get(msg.role, msg.role),
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "error_type": msg.extra_metadata.get("error_type") if msg.extra_metadata else None,
            "error_message": msg.extra_metadata.get("error_message") if msg.extra_metadata else None,
            "extra_metadata": msg.extra_metadata,
            "message_type": msg.message_type,
            "feedback": user_feedback,
        }

        if msg.tool_calls:
            msg_dict["tool_calls"] = [
                {
                    "id": str(tc.id),
                    "name": tc.tool_name,
                    "function": {"name": tc.tool_name},
                    "args": tc.tool_input or {},
                    "tool_call_result": {"content": (tc.tool_output or "")} if tc.status == "success" else None,
                    "status": tc.status,
                    "error_message": tc.error_message,
                }
                for tc in msg.tool_calls
            ]

        history.append(msg_dict)

    logger.info(
        f"Loaded {len(history)} messages with feedback for thread {thread_id}")
    return {"history": history}
