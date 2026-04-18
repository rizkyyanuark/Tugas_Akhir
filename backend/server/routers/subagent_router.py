"""SubAgent managementroute"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, HTTPException

from server.utils.auth_middleware import get_admin_user, get_db
from yunesa.services import subagent_service as service
from yunesa.storage.postgres.models_business import User
from yunesa.utils import logger

subagents_router = APIRouter(prefix="/system/subagents", tags=["subagents"])


class SubAgentCreateRequest(BaseModel):
    name: str = Field(..., description="unique identifier")
    description: str = Field(..., description="description")
    system_prompt: str = Field(..., description="System prompt")
    tools: list[str] = Field(default_factory=list,
                             description="Tool name list")
    model: str | None = Field(None, description="Optional model override")


class SubAgentUpdateRequest(BaseModel):
    description: str | None = Field(None, description="description")
    system_prompt: str | None = Field(None, description="System prompt")
    tools: list[str] | None = Field(None, description="Tool name list")
    model: str | None = Field(None, description="Optional model override")


class SubAgentStatusRequest(BaseModel):
    enabled: bool = Field(..., description="Whether enabled")


def _raise_from_value_error(e: ValueError) -> None:
    message = str(e)
    status_code = 404 if "does not exist" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _raise_internal_error(action: str, error: Exception) -> None:
    logger.exception("SubAgent %s failed: %s", action, error)
    raise HTTPException(status_code=500, detail=f"{action}failed")


def _is_subagent_name_duplicate_error(error: IntegrityError) -> bool:
    raw_message = str(getattr(error, "orig", error)).lower()
    return (
        "duplicate key" in raw_message
        and "subagents" in raw_message
        and ("(name)" in raw_message or "subagents_pkey" in raw_message)
    )


@subagents_router.get("")
async def list_subagents_route(
    _current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the SubAgent list (admin readable)."""
    try:
        items = await service.get_all_subagents(db)
        return {"success": True, "data": items}
    except Exception as e:
        _raise_internal_error("getlist", e)


@subagents_router.get("/{name}")
async def get_subagent_route(
    name: str,
    _current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single SubAgent (admin readable)."""
    try:
        item = await service.get_subagent(name, db)
        if not item:
            raise HTTPException(
                status_code=404, detail=f"SubAgent '{name}' does not exist")
        return {"success": True, "data": item}
    except HTTPException:
        raise
    except Exception as e:
        _raise_internal_error("get", e)


@subagents_router.post("")
async def create_subagent_route(
    payload: SubAgentCreateRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a SubAgent (admin)."""
    try:
        data = payload.model_dump()
        item = await service.create_subagent(data, created_by=current_user.username, db=db)
        return {"success": True, "data": item}
    except IntegrityError as e:
        if _is_subagent_name_duplicate_error(e):
            raise HTTPException(
                status_code=409, detail=f"SubAgent '{payload.name}' already exists")
        _raise_internal_error("create", e)
    except HTTPException:
        raise
    except ValueError as e:
        _raise_from_value_error(e)
    except Exception as e:
        _raise_internal_error("create", e)


@subagents_router.put("/{name}")
async def update_subagent_route(
    name: str,
    payload: SubAgentUpdateRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a SubAgent (admin)."""
    try:
        data = payload.model_dump(exclude_unset=True)
        item = await service.update_subagent(name, data, updated_by=current_user.username, db=db)
        if not item:
            raise HTTPException(
                status_code=404, detail=f"SubAgent '{name}' does not exist")
        return {"success": True, "data": item}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        _raise_internal_error("update", e)


@subagents_router.delete("/{name}")
async def delete_subagent_route(
    name: str,
    _current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a SubAgent (admin)."""
    try:
        deleted = await service.delete_subagent(name, db=db)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"SubAgent '{name}' does not exist")
        return {"success": True}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        _raise_internal_error("delete", e)


@subagents_router.put("/{name}/status")
async def update_subagent_status_route(
    name: str,
    payload: SubAgentStatusRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update SubAgent enabled status (admin)."""
    try:
        item = await service.set_subagent_enabled(name, payload.enabled, updated_by=current_user.username, db=db)
        if not item:
            raise HTTPException(
                status_code=404, detail=f"SubAgent '{name}' does not exist")
        return {
            "success": True,
            "data": item,
            "message": f"SubAgent '{name}' {'enabled' if payload.enabled else 'disabled'}",
        }
    except HTTPException:
        raise
    except Exception as e:
        _raise_internal_error("updatestatus", e)
