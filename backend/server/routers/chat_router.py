import traceback
import uuid
from typing import Any
from mimetypes import guess_type

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.storage.postgres.models_business import User
from server.routers.auth_router import get_admin_user
from server.utils.auth_middleware import get_db, get_required_user
from yunesa import config as conf
from yunesa.agents.buildin import agent_manager
from yunesa.models import select_model
from yunesa.services.chat_service import agent_chat, get_agent_state_view, stream_agent_chat, stream_agent_resume
from yunesa.services.agent_run_service import (
    cancel_agent_run_view,
    create_agent_run_view,
    get_active_run_by_thread,
    get_agent_run_view,
    stream_agent_run_events,
)
from yunesa.repositories.conversation_repository import ConversationRepository
from yunesa.services.conversation_service import (
    create_thread_view,
    delete_thread_attachment_view,
    delete_thread_view,
    get_thread_history_view,
    list_thread_attachments_view,
    list_threads_view,
    update_thread_view,
    upload_thread_attachment_view,
)
from yunesa.services.thread_files_service import (
    list_thread_files_view,
    read_thread_file_content_view,
    resolve_thread_artifact_view,
    save_thread_artifact_to_workspace_view,
)
from yunesa.services.feedback_service import get_message_feedback_view, submit_message_feedback_view
from yunesa.repositories.agent_config_repository import AgentConfigRepository
from yunesa.utils.logging_config import logger
from yunesa.utils.image_processor import process_uploaded_image
from yunesa.utils.paths import VIRTUAL_PATH_PREFIX


# TODO: This file currently has too many responsibilities and mixed route labels.

# Image upload response model
class ImageUploadResponse(BaseModel):
    success: bool
    image_content: str | None = None
    thumbnail_content: str | None = None
    width: int | None = None
    height: int | None = None
    format: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    error: str | None = None


class AgentConfigCreate(BaseModel):
    name: str
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    examples: list[str] | None = None
    config_json: dict | None = None
    set_default: bool = False


class AgentConfigUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    pics: list[str] | None = None
    examples: list[str] | None = None
    config_json: dict | None = None


class AgentRunCreate(BaseModel):
    query: str = Field(..., description="User input question")
    agent_config_id: int = Field(
        ..., description="Agent Configuration ID; used by backend to parse agent_id and runtime context")
    thread_id: str = Field(..., description="Session thread ID")
    meta: dict = Field(default_factory=dict,
                       description="Optional request tracing metadata, such as request_id")
    image_content: str | None = Field(
        None, description="Optional base64 image content")


class AgentChatRequest(BaseModel):
    query: str = Field(..., description="User input question")
    agent_config_id: int = Field(
        ..., description="Agent Configuration ID; used by backend to parse agent_id and runtime context")
    thread_id: str | None = Field(
        None, description="Optional session thread ID; auto-created when omitted")
    meta: dict = Field(default_factory=dict,
                       description="Optional request tracing metadata, such as request_id")
    image_content: str | None = Field(
        None, description="Optional base64 image content")


chat = APIRouter(prefix="/chat", tags=["chat"])

# =============================================================================
# > === agentmanagementgroup ===
# =============================================================================


@chat.get("/default_agent")
async def get_default_agent(current_user: User = Depends(get_required_user)):
    """Get default agent ID (login required)."""
    try:
        default_agent_id = conf.default_agent_id
        # If no default agent is set, try the first available agent.
        if not default_agent_id:
            agents = await agent_manager.get_agents_info(include_configurable_items=False)
            if agents:
                default_agent_id = agents[0].get("id", "")

        return {"default_agent_id": default_agent_id}
    except Exception as e:
        logger.error(f"Error getting default agent: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error getting default agent: {str(e)}")


@chat.post("/set_default_agent")
async def set_default_agent(request_data: dict = Body(...), current_user=Depends(get_admin_user)):
    """Set default agent ID (admin only)."""
    try:
        agent_id = request_data.get("agent_id")
        if not agent_id:
            raise HTTPException(
                status_code=422, detail="Missing required field: agent_id")

        # Verify that the agent exists.
        agents = await agent_manager.get_agents_info(include_configurable_items=False)
        agent_ids = [agent.get("id", "") for agent in agents]

        if agent_id not in agent_ids:
            raise HTTPException(
                status_code=404, detail=f"agent {agent_id} does not exist")

        # setdefaultagentID
        conf.default_agent_id = agent_id
        # saveconfigure
        conf.save()

        return {"success": True, "default_agent_id": agent_id}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error setting default agent: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error setting default agent: {str(e)}")


@chat.post("/call")
async def call(query: str = Body(...), meta: dict = Body(None), current_user: User = Depends(get_required_user)):
    """Call model for simple Q&A (login required)."""
    meta = meta or {}

    # Ensure request_id exists.
    if "request_id" not in meta or not meta.get("request_id"):
        meta["request_id"] = str(uuid.uuid4())

    model = select_model(
        model_provider=meta.get("model_provider"),
        model_name=meta.get("model_name"),
        model_spec=meta.get("model_spec") or meta.get("model"),
    )

    response = await model.call(query)
    logger.debug({"query": query, "response": response.content})

    return {"response": response.content, "request_id": meta["request_id"]}


@chat.get("/agent")
async def get_agent(current_user: User = Depends(get_required_user)):
    """Get basic info for all available agents (login required)."""
    agents_info = await agent_manager.get_agents_info(include_configurable_items=False)
    return {"agents": agents_info}


@chat.get("/agent/{agent_id}")
async def get_single_agent(agent_id: str, current_user: User = Depends(get_required_user)):
    """Get full info for a specific agent (including configuration options) (login required)."""
    try:
        # Check whether the agent exists.
        if not (agent := agent_manager.get_agent(agent_id)):
            raise HTTPException(
                status_code=404, detail=f"agent {agent_id} does not exist")

        # Get full agent info (including configurable_items).
        agent_info = await agent.get_info()

        return agent_info

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent {agent_id} info: {e}")
        raise HTTPException(
            status_code=500, detail=f"Error getting agent info: {str(e)}")


@chat.get("/agent/{agent_id}/configs")
async def list_agent_configs(
    agent_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    items = await repo.list_by_department_agent(department_id=current_user.department_id, agent_id=agent_id)
    if not items:
        await repo.get_or_create_default(
            department_id=current_user.department_id,
            agent_id=agent_id,
            created_by=str(current_user.id),
        )
        items = await repo.list_by_department_agent(department_id=current_user.department_id, agent_id=agent_id)

    configs = [
        {
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "icon": item.icon,
            "pics": item.pics or [],
            "examples": item.examples or [],
            "is_default": bool(item.is_default),
        }
        for item in items
    ]
    return {"configs": configs}


@chat.get("/agent/{agent_id}/configs/{config_id}")
async def get_agent_config_profile(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="configuredoes not exist")

    return {"config": item.to_dict()}


@chat.post("/agent/{agent_id}/configs")
async def create_agent_config_profile(
    agent_id: str,
    payload: AgentConfigCreate,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    item = await repo.create(
        department_id=current_user.department_id,
        agent_id=agent_id,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        pics=payload.pics,
        examples=payload.examples,
        config_json=payload.config_json,
        is_default=payload.set_default,
        created_by=str(current_user.id),
    )
    if payload.set_default:
        item = await repo.set_default(config=item, updated_by=str(current_user.id))

    return {"config": item.to_dict()}


@chat.put("/agent/{agent_id}/configs/{config_id}")
async def update_agent_config_profile(
    agent_id: str,
    config_id: int,
    payload: AgentConfigUpdate,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="configuredoes not exist")

    updated = await repo.update(
        item,
        name=payload.name,
        description=payload.description,
        icon=payload.icon,
        pics=payload.pics,
        examples=payload.examples,
        config_json=payload.config_json,
        updated_by=str(current_user.id),
    )
    return {"config": updated.to_dict()}


@chat.post("/agent/{agent_id}/configs/{config_id}/set_default")
async def set_agent_config_default(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="configuredoes not exist")

    updated = await repo.set_default(config=item, updated_by=str(current_user.id))
    return {"config": updated.to_dict()}


@chat.delete("/agent/{agent_id}/configs/{config_id}")
async def delete_agent_config_profile(
    agent_id: str,
    config_id: int,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if not agent_manager.get_agent(agent_id):
        raise HTTPException(
            status_code=404, detail=f"agent {agent_id} does not exist")

    repo = AgentConfigRepository(db)
    item = await repo.get_by_id(config_id)
    if not item or item.agent_id != agent_id or item.department_id != current_user.department_id:
        raise HTTPException(status_code=404, detail="configuredoes not exist")

    await repo.delete(config=item, updated_by=str(current_user.id))
    return {"success": True}


@chat.post("/agent")
async def chat_agent(
    payload: AgentChatRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Use a specific agent for streaming conversation (login required)."""
    logger.info(
        f"query: {payload.query}, agent_config_id: {payload.agent_config_id}, meta: {payload.meta}")

    # Inspect image content.
    logger.info(f"image_content present: {payload.image_content is not None}")
    if payload.image_content:
        logger.info(f"image_content length: {len(payload.image_content)}")
        logger.info(f"image_content preview: {payload.image_content[:50]}...")

    return StreamingResponse(
        stream_agent_chat(
            query=payload.query,
            agent_config_id=payload.agent_config_id,
            thread_id=payload.thread_id,
            meta=dict(payload.meta or {}),
            image_content=payload.image_content,
            current_user=current_user,
            db=db,
        ),
        media_type="application/json",
    )


@chat.post("/agent/sync")
async def chat_agent_sync(
    payload: AgentChatRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Use a specific agent for non-streaming conversation (login required)."""
    logger.info(
        f"[sync] query: {payload.query}, agent_config_id: {payload.agent_config_id}, meta: {payload.meta}")
    logger.info(
        f"[sync] image_content present: {payload.image_content is not None}")
    if payload.image_content:
        logger.info(
            f"[sync] image_content length: {len(payload.image_content)}")

    return await agent_chat(
        query=payload.query,
        agent_config_id=payload.agent_config_id,
        thread_id=payload.thread_id,
        meta=dict(payload.meta or {}),
        image_content=payload.image_content,
        current_user=current_user,
        db=db,
    )


@chat.post("/runs")
async def create_agent_run(
    payload: AgentRunCreate,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Create async run task and enqueue it (login required)."""
    return await create_agent_run_view(
        query=payload.query,
        agent_config_id=payload.agent_config_id,
        thread_id=payload.thread_id,
        meta=dict(payload.meta or {}),
        image_content=payload.image_content,
        current_user_id=str(current_user.id),
        db=db,
    )


@chat.get("/runs/{run_id}")
async def get_agent_run(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Get run status (login required)."""
    return await get_agent_run_view(run_id=run_id, current_user_id=str(current_user.id), db=db)


@chat.post("/runs/{run_id}/cancel")
async def cancel_agent_run(
    run_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel run (login required)."""
    return await cancel_agent_run_view(run_id=run_id, current_user_id=str(current_user.id), db=db)


@chat.get("/runs/{run_id}/events")
async def stream_run_events(
    run_id: str,
    after_seq: str = Query("0"),
    current_user: User = Depends(get_required_user),
):
    """SSE stream run events (login required)."""
    return StreamingResponse(
        stream_agent_run_events(
            run_id=run_id,
            after_seq=after_seq,
            current_user_id=str(current_user.id),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# =============================================================================
# > === modelmanagementgroup ===
# =============================================================================


@chat.get("/models")
async def get_chat_models(model_provider: str, current_user: User = Depends(get_admin_user)):
    """Get model list for the specified model provider (login required)."""
    model = select_model(model_provider=model_provider)
    models = await model.get_models()
    return {"models": models}


@chat.post("/models/update")
async def update_chat_models(model_provider: str, model_names: list[str], current_user=Depends(get_admin_user)):
    """Update model list for the specified model provider (admin only)."""
    conf.model_names[model_provider].models = model_names
    conf._save_models_to_file(model_provider)
    return {"models": conf.model_names[model_provider].models}


@chat.post("/thread/{thread_id}/resume")
async def resume_thread_chat(
    thread_id: str,
    approved: bool | None = Body(None),
    answer: dict | None = Body(None),
    config: dict = Body({}),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a conversation interrupted by human approval (login required)."""

    # Verify that the thread exists and belongs to the current user.
    conv_repo = ConversationRepository(db)
    conversation = await conv_repo.get_conversation_by_thread_id(thread_id)
    if not conversation or conversation.user_id != str(current_user.id) or conversation.status == "deleted":
        raise HTTPException(
            status_code=404, detail="Conversation thread does not exist")
    agent_id = conversation.agent_id

    def normalize_resume_input(raw_answer: Any, raw_approved: bool | None) -> Any:
        def normalize_single_answer(value: Any) -> Any:
            if isinstance(value, str):
                normalized = value.strip()
                if not normalized:
                    raise HTTPException(
                        status_code=422, detail="answer cannot be empty")
                return normalized

            if isinstance(value, list):
                if len(value) == 0:
                    raise HTTPException(
                        status_code=422, detail="answer cannot be empty")

                normalized_list: list[str] = []
                for item in value:
                    if not isinstance(item, str) or not item.strip():
                        raise HTTPException(
                            status_code=422, detail="answer list must contain non-empty strings")
                    normalized_list.append(item.strip())
                return normalized_list

            if isinstance(value, dict):
                if value.get("type") == "other":
                    text = value.get("text")
                    if not isinstance(text, str) or not text.strip():
                        raise HTTPException(
                            status_code=422, detail="other text cannot be empty")
                return value

            raise HTTPException(
                status_code=422, detail="answer value type not supported")

        if raw_answer is not None:
            if isinstance(raw_answer, dict):
                if len(raw_answer) == 0:
                    raise HTTPException(
                        status_code=422, detail="answer cannot be empty")

                normalized_answers: dict[str, Any] = {}
                for question_id, value in raw_answer.items():
                    normalized_question_id = str(question_id).strip()
                    if not normalized_question_id:
                        raise HTTPException(
                            status_code=422, detail="question_id cannot be empty")
                    normalized_answers[normalized_question_id] = normalize_single_answer(
                        value)
                return normalized_answers

            raise HTTPException(
                status_code=422, detail="answer must be an object mapping {question_id: answer}")

        if raw_approved is not None:
            return "approve" if raw_approved else "reject"

        raise HTTPException(
            status_code=422, detail="At least one of approved or answer must be provided")

    resume_input = normalize_resume_input(answer, approved)

    logger.info(
        "Resuming agent_id: %s, thread_id: %s, approved: %s, answer_type: %s",
        agent_id,
        thread_id,
        approved,
        type(answer).__name__ if answer is not None else "None",
    )

    meta = {
        "agent_id": agent_id,
        "thread_id": thread_id,
        "user_id": current_user.id,
        "approved": approved,
        "answer": answer,
        "resume_input": resume_input,
    }
    if "request_id" not in meta or not meta.get("request_id"):
        meta["request_id"] = str(uuid.uuid4())
    return StreamingResponse(
        stream_agent_resume(
            agent_id=agent_id,
            thread_id=thread_id,
            resume_input=resume_input,
            meta=meta,
            config=config,
            current_user=current_user,
            db=db,
        ),
        media_type="application/json",
    )


@chat.get("/thread/{thread_id}/active_run")
async def get_thread_active_run(
    thread_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Get active run for the current thread (login required)."""
    return await get_active_run_by_thread(thread_id=thread_id, current_user_id=str(current_user.id), db=db)


@chat.get("/thread/{thread_id}/history")
async def get_thread_history(
    thread_id: str, current_user: User = Depends(get_required_user), db: AsyncSession = Depends(get_db)
):
    """Get conversation message history (login required) - includes user feedback status."""
    try:
        return await get_thread_history_view(
            thread_id=thread_id,
            current_user_id=str(current_user.id),
            db=db,
        )

    except Exception as e:
        logger.error(
            f"Error getting conversation history messages: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Error getting conversation history messages: {str(e)}")


@chat.get("/thread/{thread_id}/state")
async def get_thread_state(
    thread_id: str,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current conversation state (login required)."""
    try:
        return await get_agent_state_view(
            thread_id=thread_id,
            current_user_id=str(current_user.id),
            db=db,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting conversation status: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Error getting conversation status: {str(e)}")


# ==================== Thread Management API ====================


class ThreadCreate(BaseModel):
    title: str | None = None
    agent_id: str
    metadata: dict | None = None


class ThreadResponse(BaseModel):
    id: str
    user_id: str
    agent_id: str
    title: str | None = None
    is_pinned: bool = False
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttachmentResponse(BaseModel):
    file_id: str
    file_name: str
    file_type: str | None = None
    file_size: int
    status: str
    uploaded_at: str
    path: str
    artifact_url: str | None = None
    original_path: str | None = None
    original_artifact_url: str | None = None
    minio_url: str | None = None


class AttachmentLimits(BaseModel):
    allowed_extensions: list[str]
    max_size_bytes: int


class AttachmentListResponse(BaseModel):
    attachments: list[AttachmentResponse]
    limits: AttachmentLimits


class ThreadFileEntry(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int
    modified_at: str | None = None
    artifact_url: str | None = None


class ThreadFileListResponse(BaseModel):
    path: str
    files: list[ThreadFileEntry]


class ThreadFileContentResponse(BaseModel):
    path: str
    content: list[str]
    offset: int
    limit: int
    total_lines: int
    artifact_url: str


class SaveThreadArtifactRequest(BaseModel):
    path: str


class SaveThreadArtifactResponse(BaseModel):
    name: str
    source_path: str
    saved_path: str
    saved_artifact_url: str


# =============================================================================
# > === sessionmanagementgroup ===
# =============================================================================


@chat.post("/thread", response_model=ThreadResponse)
async def create_thread(
    thread: ThreadCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_required_user)
):
    """Create a new conversation thread (using the new storage system)."""
    return await create_thread_view(
        agent_id=thread.agent_id,
        title=thread.title,
        metadata=thread.metadata,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.get("/threads", response_model=list[ThreadResponse])
async def list_threads(
    agent_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Get all conversation threads for the current user (using the new storage system)."""
    return await list_threads_view(
        agent_id=agent_id, db=db, current_user_id=str(current_user.id), limit=limit, offset=offset
    )


@chat.delete("/thread/{thread_id}")
async def delete_thread(
    thread_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_required_user)
):
    """Delete a conversation thread (using the new storage system)."""
    return await delete_thread_view(thread_id=thread_id, db=db, current_user_id=str(current_user.id))


class ThreadUpdate(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None


@chat.put("/thread/{thread_id}", response_model=ThreadResponse)
async def update_thread(
    thread_id: str,
    thread_update: ThreadUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Update conversation thread information (using the new storage system)."""
    return await update_thread_view(
        thread_id=thread_id,
        title=thread_update.title,
        is_pinned=thread_update.is_pinned,
        db=db,
        current_user_id=str(current_user.id),
    )


# ================================
# > === Attachment Management Group ===
# ================================


@chat.post("/thread/{thread_id}/attachments", response_model=AttachmentResponse)
async def upload_thread_attachment(
    thread_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Upload a raw attachment and associate it with the specified conversation thread."""
    return await upload_thread_attachment_view(
        thread_id=thread_id,
        file=file,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.get("/thread/{thread_id}/attachments", response_model=AttachmentListResponse)
async def list_thread_attachments(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """List metadata for all attachments in the current conversation thread."""
    return await list_thread_attachments_view(
        thread_id=thread_id,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.delete("/thread/{thread_id}/attachments/{file_id}")
async def delete_thread_attachment(
    thread_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Remove the specified attachment."""
    return await delete_thread_attachment_view(
        thread_id=thread_id,
        file_id=file_id,
        db=db,
        current_user_id=str(current_user.id),
    )


@chat.get("/thread/{thread_id}/files", response_model=ThreadFileListResponse)
async def list_thread_files(
    thread_id: str,
    path: str = Query(f"{VIRTUAL_PATH_PREFIX}"),
    recursive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """List the thread file directory."""
    return await list_thread_files_view(
        thread_id=thread_id,
        current_user_id=str(current_user.id),
        db=db,
        path=path,
        recursive=recursive,
    )


@chat.get("/thread/{thread_id}/files/content", response_model=ThreadFileContentResponse)
async def read_thread_file_content(
    thread_id: str,
    path: str = Query(...),
    offset: int = Query(0, ge=0),
    limit: int = Query(2000, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Read a thread text file (line-based pagination)."""
    return await read_thread_file_content_view(
        thread_id=thread_id,
        current_user_id=str(current_user.id),
        db=db,
        path=path,
        offset=offset,
        limit=limit,
    )


@chat.get("/thread/{thread_id}/artifacts/{path:path}")
async def get_thread_artifact(
    thread_id: str,
    path: str,
    download: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Download or preview a thread file."""
    file_path = await resolve_thread_artifact_view(
        thread_id=thread_id,
        current_user_id=str(current_user.id),
        db=db,
        path=path,
    )

    media_type = guess_type(file_path.name)[0] or "application/octet-stream"
    headers = {
        "Content-Disposition": f'attachment; filename="{file_path.name}"'} if download else None
    return FileResponse(path=file_path, media_type=media_type, headers=headers)


@chat.post("/thread/{thread_id}/artifacts/save", response_model=SaveThreadArtifactResponse)
async def save_thread_artifact_to_workspace(
    thread_id: str,
    request: SaveThreadArtifactRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Save artifact to the shared workspace/saved_artifacts directory."""
    return await save_thread_artifact_to_workspace_view(
        thread_id=thread_id,
        current_user_id=str(current_user.id),
        db=db,
        path=request.path,
    )


# =============================================================================
# > === messagefeedbackgroup ===
# =============================================================================


class MessageFeedbackRequest(BaseModel):
    rating: str  # 'like' or 'dislike'
    reason: str | None = None  # Optional reason for dislike


class MessageFeedbackResponse(BaseModel):
    id: int
    message_id: int
    rating: str
    reason: str | None
    created_at: str


@chat.post("/message/{message_id}/feedback", response_model=MessageFeedbackResponse)
async def submit_message_feedback(
    message_id: int,
    feedback_data: MessageFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Submit message feedback (login required)."""
    result = await submit_message_feedback_view(
        message_id=message_id,
        rating=feedback_data.rating,
        reason=feedback_data.reason,
        db=db,
        current_user_id=str(current_user.id),
    )
    return MessageFeedbackResponse(**result)


@chat.get("/message/{message_id}/feedback")
async def get_message_feedback(
    message_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_required_user),
):
    """Get user feedback for the specified message (login required)."""
    return await get_message_feedback_view(
        message_id=message_id,
        db=db,
        current_user_id=str(current_user.id),
    )


# =============================================================================
# > === Multimodal Image Support Group ===
# =============================================================================


@chat.post("/image/upload", response_model=ImageUploadResponse)
async def upload_image(file: UploadFile = File(...), current_user: User = Depends(get_required_user)):
    """
    Upload and process an image, returning base64-encoded image data.
    """
    try:
        # Validate file type.
        if not file.content_type or not file.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400, detail="Only image file uploads are supported")

        # Read file content.
        image_data = await file.read()

        # Check file size (10MB limit).
        if len(image_data) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400, detail="Image file is too large, please upload an image smaller than 10MB")

        # Process image.
        result = process_uploaded_image(image_data, file.filename)

        if not result["success"]:
            raise HTTPException(
                status_code=400, detail=f"Image processing failed: {result['error']}")

        logger.info(
            f"user {current_user.id} successfully uploaded image: {file.filename}, "
            f"dimensions: {result['width']}x{result['height']}, "
            f"format: {result['format']}, "
            f"size: {result['size_bytes']} bytes"
        )

        return ImageUploadResponse(**result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Image upload processing failed: {str(e)}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Image processing failed: {str(e)}")
