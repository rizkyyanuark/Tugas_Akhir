"""Skills management routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from server.utils.auth_middleware import get_admin_user, get_db, get_superadmin_user
from yunesa.services.remote_skill_install_service import install_remote_skill, list_remote_skills
from yunesa.services.skill_service import (
    BuiltinSkillUpdateConflictError,
    create_skill_node,
    delete_skill,
    delete_skill_node,
    export_skill_zip,
    get_skill_dependency_options,
    get_skill_tree,
    import_skill_zip,
    install_builtin_skill,
    list_builtin_skill_specs,
    list_skills,
    read_skill_file,
    update_builtin_skill,
    update_skill_dependencies,
    update_skill_file,
)
from yunesa.storage.postgres.models_business import User
from yunesa.utils.logging_config import logger

skills = APIRouter(prefix="/system/skills", tags=["skills"])


class SkillNodeCreateRequest(BaseModel):
    path: str = Field(...,
                      description="Path relative to the skill root directory")
    is_dir: bool = Field(False, description="Whether to create a directory")
    content: str | None = Field(
        "", description="File content (used only when creating a file)")


class SkillFileUpdateRequest(BaseModel):
    path: str = Field(...,
                      description="Path relative to the skill root directory")
    content: str = Field(..., description="File content")


class SkillDependenciesUpdateRequest(BaseModel):
    tool_dependencies: list[str] = Field(
        default_factory=list, description="Built-in tool dependency list")
    mcp_dependencies: list[str] = Field(
        default_factory=list, description="MCP service dependency list")
    skill_dependencies: list[str] = Field(
        default_factory=list, description="List of dependent skill slugs")


class BuiltinSkillUpdateRequest(BaseModel):
    force: bool = Field(
        False, description="Whether to force-overwrite local installed content")


class RemoteSkillSourceRequest(BaseModel):
    source: str = Field(...,
                        description="Skills repository source, e.g. owner/repo or GitHub URL")


class RemoteSkillInstallRequest(RemoteSkillSourceRequest):
    skill: str = Field(..., description="Skill name to install")


def _raise_from_value_error(e: ValueError) -> None:
    message = str(e)
    status_code = 404 if "does not exist" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _cleanup_export_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning(
            f"Failed to cleanup exported skill archive '{path}': {e}")


@skills.get("")
async def list_skills_route(
    _current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get skill list (admin readable)."""
    try:
        items = await list_skills(db)
        return {"success": True, "data": [item.to_dict() for item in items]}
    except Exception as e:
        logger.error(f"Failed to list skills: {e}")
        raise HTTPException(status_code=500, detail="Failed to get skill list")


@skills.get("/dependency-options")
async def get_skill_dependency_options_route(
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get dependency option list for skills (superadmin only)."""
    try:
        return {"success": True, "data": await get_skill_dependency_options(db)}
    except Exception as e:
        logger.error(f"Failed to get skill dependency options: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get skill dependency options")


@skills.get("/builtin")
async def list_builtin_skills_route(
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        installed_map = {item.slug: item for item in await list_skills(db)}
        data = []
        for spec in list_builtin_skill_specs():
            installed = installed_map.get(spec["slug"])
            status = "not_installed"
            if installed:
                status = "installed"
                if installed.version != spec["version"] or installed.content_hash != spec["content_hash"]:
                    status = "update_available"
            data.append(
                {
                    "slug": spec["slug"],
                    "name": spec["name"],
                    "description": spec["description"],
                    "version": spec["version"],
                    "status": status,
                    "installed_record": installed.to_dict() if installed else None,
                }
            )
        return {"success": True, "data": data}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list builtin skills: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get built-in skill list")


@skills.post("/builtin/{slug}/install")
async def install_builtin_skill_route(
    slug: str,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await install_builtin_skill(db, slug, installed_by=current_user.username)
        return {"success": True, "data": item.to_dict()}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to install builtin skill '{slug}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to install built-in skill")


@skills.post("/builtin/{slug}/update")
async def update_builtin_skill_route(
    slug: str,
    payload: BuiltinSkillUpdateRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await update_builtin_skill(
            db,
            slug,
            force=payload.force,
            updated_by=current_user.username,
        )
        return {"success": True, "data": item.to_dict()}
    except BuiltinSkillUpdateConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"needs_confirm": True, "message": str(e)},
        )
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update builtin skill '{slug}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to update built-in skill")


@skills.post("/import")
async def import_skill_route(
    file: UploadFile = File(...),
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Import a skill package (ZIP or single SKILL.md, superadmin only)."""
    try:
        file_bytes = await file.read()
        item = await import_skill_zip(
            db,
            filename=file.filename or "",
            file_bytes=file_bytes,
            created_by=current_user.username,
        )
        return {"success": True, "data": item.to_dict()}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to import skill package: {e}")
        raise HTTPException(status_code=500, detail="Failed to import skill")


@skills.post("/remote/list")
async def list_remote_skills_route(
    payload: RemoteSkillSourceRequest,
    _current_user: User = Depends(get_superadmin_user),
):
    try:
        return {"success": True, "data": await list_remote_skills(payload.source)}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to list remote skills from '{payload.source}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get remote skill list")


@skills.post("/remote/install")
async def install_remote_skill_route(
    payload: RemoteSkillInstallRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        item = await install_remote_skill(
            db,
            source=payload.source,
            skill=payload.skill,
            created_by=current_user.username,
        )
        return {"success": True, "data": item.to_dict()}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to install remote skill '{payload.skill}' from '{payload.source}': {e}"
        )
        raise HTTPException(
            status_code=500, detail="Failed to install remote skill")


@skills.get("/{slug}/tree")
async def get_skill_tree_route(
    slug: str,
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get skill directory tree (superadmin only)."""
    try:
        tree = await get_skill_tree(db, slug)
        return {"success": True, "data": tree}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill tree '{slug}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get skill directory tree")


@skills.get("/{slug}/file")
async def get_skill_file_route(
    slug: str,
    path: str = Query(...,
                      description="Path relative to the skill root directory"),
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Read skill text file (superadmin only)."""
    try:
        data = await read_skill_file(db, slug, path)
        return {"success": True, "data": data}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to read skill file '{slug}/{path}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to read skill file")


@skills.post("/{slug}/file")
async def create_skill_file_route(
    slug: str,
    payload: SkillNodeCreateRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create skill file or directory (superadmin only)."""
    try:
        await create_skill_node(
            db,
            slug=slug,
            relative_path=payload.path,
            is_dir=payload.is_dir,
            content=payload.content,
            updated_by=current_user.username,
        )
        return {"success": True}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to create skill node '{slug}/{payload.path}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to create skill file")


@skills.put("/{slug}/file")
async def update_skill_file_route(
    slug: str,
    payload: SkillFileUpdateRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update skill text file (superadmin only)."""
    try:
        await update_skill_file(
            db,
            slug=slug,
            relative_path=payload.path,
            content=payload.content,
            updated_by=current_user.username,
        )
        return {"success": True}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to update skill file '{slug}/{payload.path}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to update skill file")


@skills.put("/{slug}/dependencies")
async def update_skill_dependencies_route(
    slug: str,
    payload: SkillDependenciesUpdateRequest,
    current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update skill dependencies (superadmin only)."""
    try:
        item = await update_skill_dependencies(
            db,
            slug=slug,
            tool_dependencies=payload.tool_dependencies,
            mcp_dependencies=payload.mcp_dependencies,
            skill_dependencies=payload.skill_dependencies,
            updated_by=current_user.username,
        )
        return {"success": True, "data": item.to_dict()}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill dependencies '{slug}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to update skill dependencies")


@skills.delete("/{slug}/file")
async def delete_skill_file_route(
    slug: str,
    path: str = Query(...,
                      description="Path relative to the skill root directory"),
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete skill file or directory (superadmin only)."""
    try:
        await delete_skill_node(db, slug=slug, relative_path=path)
        return {"success": True}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete skill file '{slug}/{path}': {e}")
        raise HTTPException(
            status_code=500, detail="Failed to delete skill file")


@skills.get("/{slug}/export")
async def export_skill_route(
    slug: str,
    background_tasks: BackgroundTasks,
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Export skill archive package (superadmin only)."""
    try:
        export_path, download_name = await export_skill_zip(db, slug)
        background_tasks.add_task(_cleanup_export_file, export_path)
        return FileResponse(
            path=export_path,
            media_type="application/zip",
            filename=download_name,
        )
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to export skill '{slug}': {e}")
        raise HTTPException(status_code=500, detail="Failed to export skill")


@skills.delete("/{slug}")
async def delete_skill_route(
    slug: str,
    _current_user: User = Depends(get_superadmin_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete skill (directory + database record, superadmin only)."""
    try:
        await delete_skill(db, slug=slug)
        return {"success": True}
    except ValueError as e:
        _raise_from_value_error(e)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete skill '{slug}': {e}")
        raise HTTPException(status_code=500, detail="Failed to delete skill")
