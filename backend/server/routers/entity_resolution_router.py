from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from server.routers.auth_router import get_admin_user
from yunesa.services.entity_resolution_service import entity_resolution_curation_store
from yunesa.storage.postgres.models_business import User


entity_resolution = APIRouter(prefix="/entity-resolution", tags=["entity-resolution"])


class SyncSuggestionsRequest(BaseModel):
    source_path: str | None = None


class ApproveSuggestionRequest(BaseModel):
    canonical_label: str | None = None
    canonical_key: str | None = None
    concept_type: str | None = None
    aliases: list[str] = Field(default_factory=list)
    rationale: str | None = None


class RejectSuggestionRequest(BaseModel):
    reason: str = ""


class ExportAliasesRequest(BaseModel):
    output_path: str | None = None
    base_aliases_path: str | None = None


@entity_resolution.get("/suggestions")
async def list_alias_suggestions(
    status: str | None = None,
    current_user: User = Depends(get_admin_user),
):
    result = entity_resolution_curation_store.list_suggestions(status=status)
    return {"success": True, "data": result}


@entity_resolution.post("/suggestions/sync")
async def sync_alias_suggestions(
    payload: SyncSuggestionsRequest | None = None,
    current_user: User = Depends(get_admin_user),
):
    source_path = Path(payload.source_path) if payload and payload.source_path else None
    result = entity_resolution_curation_store.sync_suggestions(source_path=source_path)
    return {"success": True, "data": result}


@entity_resolution.post("/suggestions/{suggestion_id}/approve")
async def approve_alias_suggestion(
    suggestion_id: str,
    payload: ApproveSuggestionRequest,
    current_user: User = Depends(get_admin_user),
):
    try:
        item = entity_resolution_curation_store.approve(
            suggestion_id,
            canonical_label=payload.canonical_label,
            canonical_key=payload.canonical_key,
            concept_type=payload.concept_type,
            aliases=payload.aliases,
            rationale=payload.rationale,
            reviewer=getattr(current_user, "username", "") or getattr(current_user, "email", ""),
        )
        return {"success": True, "data": item}
    except KeyError:
        raise HTTPException(status_code=404, detail="Alias suggestion not found")


@entity_resolution.post("/suggestions/{suggestion_id}/reject")
async def reject_alias_suggestion(
    suggestion_id: str,
    payload: RejectSuggestionRequest,
    current_user: User = Depends(get_admin_user),
):
    try:
        item = entity_resolution_curation_store.reject(
            suggestion_id,
            reason=payload.reason,
            reviewer=getattr(current_user, "username", "") or getattr(current_user, "email", ""),
        )
        return {"success": True, "data": item}
    except KeyError:
        raise HTTPException(status_code=404, detail="Alias suggestion not found")


@entity_resolution.post("/aliases/export")
async def export_approved_aliases(
    payload: ExportAliasesRequest | None = None,
    current_user: User = Depends(get_admin_user),
):
    output_path = Path(payload.output_path) if payload and payload.output_path else None
    base_aliases_path = Path(payload.base_aliases_path) if payload and payload.base_aliases_path else None
    result = entity_resolution_curation_store.export_aliases(
        output_path=output_path,
        base_path=base_aliases_path,
    )
    return {"success": True, "data": result}
