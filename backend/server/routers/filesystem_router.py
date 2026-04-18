"""Viewer filesystem routes.

Provides filesystem API endpoints used by the Viewer UI.
- /viewer/filesystem/* - Used by the Viewer UI
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_db, get_required_user
from yunesa.services.viewer_filesystem_service import (
    create_viewer_directory,
    delete_viewer_file,
    download_viewer_file,
    list_viewer_filesystem_tree,
    read_viewer_file_content,
    upload_viewer_file,
)
from yunesa.storage.postgres.models_business import User

filesystem_router = APIRouter(
    prefix="/viewer/filesystem", tags=["viewer-filesystem"])


class CreateViewerDirectoryRequest(BaseModel):
    thread_id: str
    parent_path: str
    name: str
    agent_id: str | None = None
    agent_config_id: int | None = None


@filesystem_router.get("/tree", response_model=dict)
async def get_viewer_tree(
    thread_id: str = Query(..., description="Thread ID"),
    path: str = Query("/", description="directorypath"),
    agent_id: str | None = Query(None, description="agent ID"),
    agent_config_id: int | None = Query(
        None, description="Agent Configuration ID"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_viewer_filesystem_tree(
        thread_id=thread_id,
        path=path,
        agent_id=agent_id,
        agent_config_id=agent_config_id,
        current_user=current_user,
        db=db,
    )


@filesystem_router.get("/file", response_model=dict)
async def get_viewer_file(
    thread_id: str = Query(..., description="Thread ID"),
    path: str = Query(..., description="filepath"),
    agent_id: str | None = Query(None, description="agent ID"),
    agent_config_id: int | None = Query(
        None, description="Agent Configuration ID"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await read_viewer_file_content(
        thread_id=thread_id,
        path=path,
        agent_id=agent_id,
        agent_config_id=agent_config_id,
        current_user=current_user,
        db=db,
    )


@filesystem_router.delete("/file", response_model=dict)
async def delete_viewer_file_route(
    thread_id: str = Query(..., description="Thread ID"),
    path: str = Query(..., description="filepath"),
    agent_id: str | None = Query(None, description="agent ID"),
    agent_config_id: int | None = Query(
        None, description="Agent Configuration ID"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await delete_viewer_file(
        thread_id=thread_id,
        path=path,
        agent_id=agent_id,
        agent_config_id=agent_config_id,
        current_user=current_user,
        db=db,
    )


@filesystem_router.post("/directory", response_model=dict)
async def create_viewer_directory_route(
    payload: CreateViewerDirectoryRequest,
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await create_viewer_directory(
        thread_id=payload.thread_id,
        parent_path=payload.parent_path,
        name=payload.name,
        agent_id=payload.agent_id,
        agent_config_id=payload.agent_config_id,
        current_user=current_user,
        db=db,
    )


@filesystem_router.post("/upload", response_model=dict)
async def upload_viewer_file_route(
    thread_id: str = Form(..., description="Thread ID"),
    parent_path: str = Form(..., description="Parent directory path"),
    agent_id: str | None = Form(None, description="agent ID"),
    agent_config_id: int | None = Form(
        None, description="Agent Configuration ID"),
    file: UploadFile = File(..., description="uploadfile"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await upload_viewer_file(
        thread_id=thread_id,
        parent_path=parent_path,
        file=file,
        agent_id=agent_id,
        agent_config_id=agent_config_id,
        current_user=current_user,
        db=db,
    )


@filesystem_router.get("/download")
async def download_viewer(
    thread_id: str = Query(..., description="Thread ID"),
    path: str = Query(..., description="filepath"),
    agent_id: str | None = Query(None, description="agent ID"),
    agent_config_id: int | None = Query(
        None, description="Agent Configuration ID"),
    current_user: User = Depends(get_required_user),
    db: AsyncSession = Depends(get_db),
):
    return await download_viewer_file(
        thread_id=thread_id,
        path=path,
        agent_id=agent_id,
        agent_config_id=agent_config_id,
        current_user=current_user,
        db=db,
    )
