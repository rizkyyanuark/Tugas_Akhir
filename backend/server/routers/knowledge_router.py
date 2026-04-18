import asyncio
import csv
import io
import json
import os
import textwrap
import traceback
from typing import Any
from urllib.parse import quote, unquote

import aiofiles
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse

from yunesa.services.task_service import TaskContext, tasker
from server.utils.auth_middleware import get_admin_user, get_required_user
from yunesa import config, graph_base, knowledge_base
from yunesa.knowledge.chunking.ragflow_like.presets import ensure_chunk_defaults_in_additional_params
from yunesa.plugins.parser import Parser, SUPPORTED_FILE_EXTENSIONS, is_supported_file_extension
from yunesa.knowledge.utils import calculate_content_hash
from yunesa.knowledge.utils.kb_utils import parse_minio_url
from yunesa.models.embed import test_all_embedding_models_status, test_embedding_model_status
from yunesa.storage.postgres.models_business import User
from yunesa.storage.minio.client import MinIOClient, StorageError, aupload_file_to_minio, get_minio_client
from yunesa.utils import logger

knowledge = APIRouter(prefix="/knowledge", tags=["knowledge"])

DIFY_REQUIRED_PARAMS = ("dify_api_url", "dify_token", "dify_dataset_id")

media_types = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".json": "application/json",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt": "application/vnd.ms-powerpoint",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
    ".rar": "application/x-rar-compressed",
    ".7z": "application/x-7z-compressed",
    ".tar": "application/x-tar",
    ".gz": "application/gzip",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "text/xml",
    ".css": "text/css",
    ".js": "application/javascript",
    ".py": "text/x-python",
    ".java": "text/x-java-source",
    ".cpp": "text/x-c++src",
    ".c": "text/x-csrc",
    ".h": "text/x-chdr",
    ".hpp": "text/x-c++hdr",
}


def _coerce_mapping_keys(mapping: dict, key: str, defaults: list[str]) -> list[str]:
    value = mapping.get(key)
    if value is None:
        return defaults
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(v).strip() for v in value if str(v).strip()]
    else:
        return defaults
    return values or defaults


def _pick_first_value(record: dict, keys: list[str]) -> str:
    for key in keys:
        if key not in record:
            continue
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"none", "nan"}:
            return text
    return ""


def _to_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    values: list[str] = []
    if isinstance(value, dict):
        for key in ("name", "full_name", "label", "value"):
            nested = value.get(key)
            if nested:
                values.extend(_to_string_list(nested))
                break
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            values.extend(_to_string_list(item))
    elif isinstance(value, str):
        normalized = value.replace("\n", ",").replace(
            ";", ",").replace("|", ",")
        values.extend(part.strip()
                      for part in normalized.split(",") if part.strip())
    else:
        text = str(value).strip()
        if text:
            values.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _records_from_payload(payload: dict) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    raw_records = payload.get("records")
    if isinstance(raw_records, list):
        records.extend(item for item in raw_records if isinstance(item, dict))
    elif isinstance(raw_records, dict):
        nested = raw_records.get("items") or raw_records.get(
            "records") or raw_records.get("data")
        if isinstance(nested, list):
            records.extend(item for item in nested if isinstance(item, dict))

    raw_data = payload.get("data")
    if isinstance(raw_data, list):
        records.extend(item for item in raw_data if isinstance(item, dict))

    csv_text = payload.get("csv_text")
    if isinstance(csv_text, str) and csv_text.strip():
        reader = csv.DictReader(io.StringIO(csv_text))
        records.extend(dict(row) for row in reader)

    return records


def _build_scival_triples(records: list[dict[str, Any]], db_id: str, mapping: dict | None = None) -> list[dict[str, Any]]:
    mapping = mapping or {}
    id_fields = _coerce_mapping_keys(
        mapping, "id_fields", ["paper_id", "id", "eid", "doi", "scopus_id"])
    title_fields = _coerce_mapping_keys(
        mapping,
        "title_fields",
        ["title", "paper_title", "judul", "judul_kegiatan", "document_title"],
    )
    author_fields = _coerce_mapping_keys(mapping, "author_fields", [
                                         "authors", "author_names", "penulis", "nama_dosen"])
    keyword_fields = _coerce_mapping_keys(
        mapping,
        "keyword_fields",
        ["keywords", "author_keywords", "indexed_keywords", "kata_kunci"],
    )
    institution_fields = _coerce_mapping_keys(
        mapping,
        "institution_fields",
        ["institution", "institusi", "affiliation", "affiliations"],
    )
    year_fields = _coerce_mapping_keys(
        mapping, "year_fields", ["year", "publication_year", "tahun"])

    triples: list[dict[str, Any]] = []

    for record in records:
        title = _pick_first_value(record, title_fields)
        paper_id = _pick_first_value(record, id_fields) or title
        if not paper_id:
            continue

        year = _pick_first_value(record, year_fields)
        paper_node: dict[str, Any] = {
            "name": title or paper_id,
            "db_id": db_id,
            "entity_type": "Paper",
            "paper_id": paper_id,
        }
        if title:
            paper_node["title"] = title
        if year:
            paper_node["year"] = year

        kb_node = {
            "name": f"KB::{db_id}",
            "db_id": db_id,
            "entity_type": "KnowledgeBase",
        }
        triples.append(
            {
                "h": paper_node,
                "r": {"type": "BELONGS_TO", "db_id": db_id},
                "t": kb_node,
            }
        )

        author_values: list[str] = []
        for field in author_fields:
            author_values.extend(_to_string_list(record.get(field)))
        for author in author_values:
            triples.append(
                {
                    "h": paper_node,
                    "r": {"type": "AUTHORED_BY", "db_id": db_id},
                    "t": {"name": author, "db_id": db_id, "entity_type": "Author"},
                }
            )

        keyword_values: list[str] = []
        for field in keyword_fields:
            keyword_values.extend(_to_string_list(record.get(field)))
        for keyword in keyword_values:
            triples.append(
                {
                    "h": paper_node,
                    "r": {"type": "HAS_KEYWORD", "db_id": db_id},
                    "t": {"name": keyword, "db_id": db_id, "entity_type": "Keyword"},
                }
            )

        institution_values: list[str] = []
        for field in institution_fields:
            institution_values.extend(_to_string_list(record.get(field)))
        for institution in institution_values:
            triples.append(
                {
                    "h": paper_node,
                    "r": {"type": "AFFILIATED_WITH", "db_id": db_id},
                    "t": {"name": institution, "db_id": db_id, "entity_type": "Institution"},
                }
            )

    return triples


def _validate_dify_additional_params(additional_params: dict | None) -> dict:
    params = dict(additional_params or {})
    missing_fields = [field for field in DIFY_REQUIRED_PARAMS if not str(
        params.get(field) or "").strip()]
    if missing_fields:
        raise HTTPException(
            status_code=400, detail=f"Missing Dify parameters: {', '.join(missing_fields)}")

    api_url = str(params.get("dify_api_url") or "").strip()
    if not api_url.endswith("/v1"):
        raise HTTPException(
            status_code=400, detail="Dify api_url must end with /v1")
    return params


async def _ensure_database_not_dify(db_id: str, operation: str) -> None:
    db_info = await knowledge_base.get_database_info(db_id)
    if not db_info:
        raise HTTPException(
            status_code=404, detail=f"knowledge base {db_id} does not exist")
    if (db_info.get("kb_type") or "").lower() == "dify":
        raise HTTPException(
            status_code=400, detail=f"Dify knowledge base supports retrieval only, not supported: {operation}")


# =============================================================================
# === Knowledge Base Management Group ===
# =============================================================================


@knowledge.get("/databases")
async def get_databases(current_user: User = Depends(get_admin_user)):
    """Get all knowledge bases (filtered by user permissions)."""
    try:
        return await knowledge_base.get_databases_by_user_id(current_user.user_id)
    except Exception as e:
        logger.error(f"getdatabaselistfailed {e}, {traceback.format_exc()}")
        return {"message": f"getdatabaselistfailed {e}", "databases": []}


@knowledge.post("/databases")
async def create_database(
    database_name: str = Body(...),
    description: str = Body(...),
    embed_model_name: str | None = Body(None),
    kb_type: str = Body("lightrag"),
    additional_params: dict = Body({}),
    llm_info: dict = Body(None),
    share_config: dict = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """Create knowledge base."""
    logger.debug(
        f"Create database {database_name} with kb_type {kb_type}, "
        f"additional_params {additional_params}, llm_info {llm_info}, "
        f"embed_model_name {embed_model_name}, share_config {share_config}"
    )
    try:
        # Check whether the name already exists.
        if await knowledge_base.database_name_exists(database_name):
            raise HTTPException(
                status_code=409,
                detail=f"Knowledge base name '{database_name}' already exists, please use a different name",
            )

        additional_params = {**(additional_params or {})}
        # Do not auto-generate questions by default.
        additional_params["auto_generate_questions"] = False

        def remove_reranker_config(kb: str, params: dict) -> None:
            """
            Remove deprecated reranker_config.
            All reranker parameters are now configured through query_params.options.
            """
            reranker_cfg = params.get("reranker_config")
            if reranker_cfg:
                if kb == "milvus":
                    logger.info(
                        "reranker_config is deprecated, please use query_params.options instead")
                else:
                    logger.warning(
                        f"{kb} does not support reranker, ignoring reranker_config")
                # Remove reranker_config and stop persisting it.
                params.pop("reranker_config", None)

        remove_reranker_config(kb_type, additional_params)
        additional_params = ensure_chunk_defaults_in_additional_params(
            additional_params)

        embed_info_dict = None
        if kb_type == "dify":
            additional_params = _validate_dify_additional_params(
                additional_params)
        else:
            if not embed_model_name:
                raise HTTPException(
                    status_code=400, detail="embed_model_name cannot be empty")
            if embed_model_name not in config.embed_model_names:
                raise HTTPException(
                    status_code=400, detail=f"Unsupported embedding model: {embed_model_name}")
            embed_info = config.embed_model_names[embed_model_name]
            # Convert Pydantic model to dict for JSON serialization.
            embed_info_dict = embed_info.model_dump() if hasattr(
                embed_info, "model_dump") else embed_info.dict()

        database_info = await knowledge_base.create_database(
            database_name,
            description,
            kb_type=kb_type,
            embed_info=embed_info_dict,
            llm_info=llm_info,
            share_config=share_config,
            **additional_params,
        )

        # Reload all agents because tools were refreshed.
        from yunesa.agents.buildin import agent_manager

        await agent_manager.reload_all()

        return database_info
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"createdatabasefailed {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"createdatabasefailed: {e}")


@knowledge.get("/databases/accessible")
async def get_accessible_databases(current_user: User = Depends(get_required_user)):
    """Get knowledge bases accessible to current user (for Agent Configuration)."""
    try:
        databases = await knowledge_base.get_databases_by_user_id(current_user.user_id)

        accessible = [
            {
                "name": db.get("name", ""),
                "db_id": db.get("db_id"),
                "description": db.get("description", ""),
            }
            for db in databases.get("databases", [])
        ]

        return {"databases": accessible}
    except Exception as e:
        logger.error(
            f"Failed to get accessible knowledge base list: {e}, {traceback.format_exc()}")
        return {"message": f"Failed to get accessible knowledge base list: {str(e)}", "databases": []}


@knowledge.get("/databases/{db_id}")
async def get_database_info(db_id: str, current_user: User = Depends(get_admin_user)):
    """Get detailed knowledge base info."""
    database = await knowledge_base.get_database_info(db_id)
    if database is None:
        raise HTTPException(status_code=404, detail="Database not found")
    return database


@knowledge.put("/databases/{db_id}")
async def update_database_info(
    db_id: str,
    name: str = Body(...),
    description: str = Body(...),
    llm_info: dict = Body(None),
    additional_params: dict | None = Body(None),
    share_config: dict = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """Update knowledge base information."""
    logger.debug(
        f"[update_database_info] Received parameters: name={name}, llm_info={llm_info}, "
        f"additional_params={additional_params}, share_config={share_config}"
    )
    try:
        if additional_params is not None:
            additional_params = ensure_chunk_defaults_in_additional_params(
                additional_params)

            db_info = await knowledge_base.get_database_info(db_id)
            if not db_info:
                raise HTTPException(
                    status_code=404, detail=f"knowledge base {db_id} does not exist")

            kb_type = (db_info.get("kb_type") or "").lower()
            if kb_type == "dify":
                merged_params = dict(db_info.get("additional_params") or {})
                merged_params.update(additional_params)
                _validate_dify_additional_params(merged_params)

        database = await knowledge_base.update_database(
            db_id,
            name,
            description,
            llm_info,
            additional_params=additional_params,
            share_config=share_config,
        )
        return {"message": "Update successful", "database": database}
    except Exception as e:
        logger.error(f"updatedatabasefailed {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"updatedatabasefailed: {e}")


@knowledge.delete("/databases/{db_id}")
async def delete_database(db_id: str, current_user: User = Depends(get_admin_user)):
    """Delete knowledge base."""
    logger.debug(f"Delete database {db_id}")
    try:
        await knowledge_base.delete_database(db_id)

        # Reload all agents because tools were refreshed.
        from yunesa.agents.buildin import agent_manager

        await agent_manager.reload_all()

        return {"message": "Delete successful"}
    except Exception as e:
        logger.error(f"deletedatabasefailed {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"deletedatabasefailed: {e}")


@knowledge.get("/databases/{db_id}/export")
async def export_database(
    db_id: str,
    format: str = Query("csv", enum=["csv", "xlsx", "md", "txt"]),
    include_vectors: bool = Query(
        False, description="Whether to include vector data in export"),
    current_user: User = Depends(get_admin_user),
):
    """Export knowledge base data."""
    logger.debug(f"Exporting database {db_id} with format {format}")
    try:
        file_path = await knowledge_base.export_data(db_id, format=format, include_vectors=include_vectors)

        if not os.path.exists(file_path):
            raise HTTPException(
                status_code=404, detail="Exported file not found.")

        media_type = media_types.get(format, "application/octet-stream")

        return FileResponse(path=file_path, filename=os.path.basename(file_path), media_type=media_type)
    except NotImplementedError as e:
        logger.warning(f"A disabled feature was accessed: {e}")
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        logger.error(f"exportdatabasefailed {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"exportdatabasefailed: {e}")


# =============================================================================
# === Knowledge Base Document Management Group ===
# =============================================================================


@knowledge.post("/databases/{db_id}/documents")
async def add_documents(
    db_id: str, items: list[str] = Body(...), params: dict = Body(...), current_user: User = Depends(get_admin_user)
):
    """Add documents to knowledge base (upload -> parse -> optional indexing)."""
    logger.debug(f"Add documents for db_id {db_id}: {items} {params=}")
    await _ensure_database_not_dify(db_id, "document add/parse/index")

    content_type = params.get("content_type", "file")
    # Auto-indexing parameters.
    auto_index = params.get("auto_index", False)
    indexing_params = {
        "chunk_size": params.get("chunk_size", 1000),
        "chunk_overlap": params.get("chunk_overlap", 200),
        "qa_separator": params.get("qa_separator", ""),
        "chunk_preset_id": params.get("chunk_preset_id"),
        "chunk_parser_config": params.get("chunk_parser_config"),
    }
    if not indexing_params.get("chunk_preset_id"):
        indexing_params.pop("chunk_preset_id", None)
    if not isinstance(indexing_params.get("chunk_parser_config"), dict):
        indexing_params.pop("chunk_parser_config", None)

    # URL parse/index path (requires whitelist validation).
    if content_type == "url":
        raise HTTPException(
            status_code=400, detail="URL processing has changed, use fetch-url endpoint to retrieve content first")

    # Security check: validate file paths.
    if content_type == "file":
        from yunesa.knowledge.utils.kb_utils import validate_file_path

        for item in items:
            try:
                validate_file_path(item, db_id)
            except ValueError as e:
                raise HTTPException(status_code=403, detail=str(e))

    async def run_ingest(context: TaskContext):
        await context.set_message("taskinitialize")
        await context.set_progress(5.0, "preparingprocessdocument")

        total = len(items)
        processed_items = []

        # Store successfully added file records from stage 1: {item: (file_id, file_meta)}
        added_files = {}

        try:
            # ========== Stage 1: Batch add file records ==========
            await context.set_message("Stage 1: Add file records")
            for idx, item in enumerate(items, 1):
                await context.raise_if_cancelled()

                # Stage 1 progress: 5% ~ 30%
                progress = 5.0 + (idx / total) * 25.0
                await context.set_progress(progress, f"[1/2] Add record {idx}/{total}")

                try:
                    # 1. Add file record (UPLOADED)
                    file_meta = await knowledge_base.add_file_record(
                        db_id, item, params=params, operator_id=current_user.user_id
                    )
                    file_id = file_meta["file_id"]
                    added_files[item] = (file_id, file_meta)
                except Exception as add_error:
                    logger.error(
                        f"Failed to add file record {item}: {add_error}")
                    error_type = "timeout" if isinstance(
                        add_error, TimeoutError) else "add_failed"
                    error_msg = "Add timeout" if isinstance(
                        add_error, TimeoutError) else "Add record failed"
                    processed_items.append(
                        {
                            "item": item,
                            "status": "failed",
                            "error": f"{error_msg}: {str(add_error)}",
                            "error_type": error_type,
                        }
                    )

            # ========== Stage 2: Batch parse files ==========
            await context.set_message("Stage 2: Parse files")
            parse_success_count = 0
            # Calculate parse-stage progress range.
            parse_progress_range = 30.0 if not auto_index else 25.0

            for idx, (item, (file_id, add_file_meta)) in enumerate(added_files.items(), 1):
                await context.raise_if_cancelled()

                # Stage 2 progress: 25%~55% or 30%~60%
                progress = parse_progress_range + \
                    (idx / len(added_files)) * 30.0
                await context.set_progress(progress, f"[2/2] Parse file {idx}/{len(added_files)}")

                try:
                    # 2. Parse file (PARSING -> PARSED)
                    file_meta = await knowledge_base.parse_file(db_id, file_id, operator_id=current_user.user_id)
                    added_files[item] = (file_id, file_meta)
                    processed_items.append(file_meta)
                    parse_success_count += 1
                except Exception as parse_error:
                    logger.error(
                        f"File parse failed {item} (file_id={file_id}): {parse_error}")
                    error_type = "timeout" if isinstance(
                        parse_error, TimeoutError) else "parse_failed"
                    error_msg = "Parse timeout" if isinstance(
                        parse_error, TimeoutError) else "Parse failed"
                    processed_items.append(
                        {
                            "item": item,
                            "status": "failed",
                            "error": f"{error_msg}: {str(parse_error)}",
                            "error_type": error_type,
                        }
                    )

            # ========== Stage 3: Auto indexing ==========
            if auto_index:
                await context.set_message("Stage 3: Auto indexing")
                parsed_files = [(item, data) for item, data in added_files.items(
                ) if data[1].get("status") == "parsed"]
                total_parsed = len(parsed_files)

                for idx, (item, (file_id, file_meta)) in enumerate(parsed_files, 1):
                    await context.raise_if_cancelled()

                    # Stage 3 progress: 55%~95% or 60%~95%
                    progress = 55.0 + (idx / total_parsed) * 40.0
                    await context.set_progress(progress, f"[3/3] Index file {idx}/{total_parsed}")

                    try:
                        # 1. Update indexing parameters.
                        await knowledge_base.update_file_params(
                            db_id, file_id, indexing_params, operator_id=current_user.user_id
                        )
                        # 2. Execute indexing.
                        result = await knowledge_base.index_file(db_id, file_id, operator_id=current_user.user_id)
                        processed_items.append(result)
                    except Exception as index_error:
                        logger.error(
                            f"Auto indexing failed {item} (file_id={file_id}): {index_error}")
                        processed_items.append(
                            {
                                "item": item,
                                "status": "failed",
                                "error": f"Indexing failed: {str(index_error)}",
                                "error_type": "index_failed",
                            }
                        )

        except asyncio.CancelledError:
            await context.set_progress(100.0, "Task cancelled")
            raise
        except Exception as task_error:
            # Handle other task-level exceptions (e.g., OOM, network errors).
            logger.exception(f"Task processing failed: {task_error}")
            await context.set_progress(100.0, f"Task processing failed: {str(task_error)}")
            # No need to manually mark unprocessed files as failed because:
            # 1. Inner exception handlers already recorded processed files (success/failed).
            # 2. Unprocessed files are absent from processed_items and UI can reflect that.
            # 3. Users can resubmit unprocessed files.
            raise

        item_type = "URL" if content_type == "url" else "file"
        # Check for failed status (including ERROR_PARSING)
        failed_count = len(
            [_p for _p in processed_items if "error" in _p or _p.get("status") == "failed"])

        summary = {
            "db_id": db_id,
            "item_type": item_type,
            "submitted": len(processed_items),
            "failed": failed_count,
        }
        message = (
            f"{item_type} processing completed, failed {failed_count}"
            if failed_count
            else f"{item_type} processing completed"
        )
        await context.set_result(summary | {"items": processed_items})
        await context.set_progress(100.0, message)
        return summary | {"items": processed_items}

    try:
        database = await knowledge_base.get_database_info(db_id)
        task = await tasker.enqueue(
            name=f"knowledge basedocumentprocess ({database['name']})",
            task_type="knowledge_ingest",
            payload={
                "db_id": db_id,
                "items": items,
                "params": params,
                "content_type": content_type,
            },
            coroutine=run_ingest,
        )
        return {
            "message": "Task submitted, check progress in Task Center",
            "status": "queued",
            "task_id": task.id,
        }
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"Failed to enqueue {content_type}s: {e}, {traceback.format_exc()}")
        return {"message": f"Failed to enqueue task: {e}", "status": "failed"}


@knowledge.post("/databases/{db_id}/documents/parse")
async def parse_documents(db_id: str, file_ids: list[str] = Body(...), current_user: User = Depends(get_admin_user)):
    """Manually trigger document parsing."""
    logger.debug(f"Parse documents for db_id {db_id}: {file_ids}")
    await _ensure_database_not_dify(db_id, "document parse")

    async def run_parse(context: TaskContext):
        await context.set_message("taskinitialize")
        await context.set_progress(5.0, "preparingparsedocument")

        total = len(file_ids)
        processed_items = []

        try:
            for idx, file_id in enumerate(file_ids, 1):
                await context.raise_if_cancelled()
                progress = 5.0 + (idx / total) * 90.0
                await context.set_progress(progress, f"Currently parsing document {idx}/{total}")

                try:
                    result = await knowledge_base.parse_file(db_id, file_id, operator_id=current_user.user_id)
                    processed_items.append(result)
                except Exception as e:
                    logger.error(f"Parse failed for {file_id}: {e}")
                    processed_items.append(
                        {"file_id": file_id, "status": "failed", "error": str(e)})

        except Exception as e:
            logger.exception(f"Parse task failed: {e}")
            raise

        failed_count = len([p for p in processed_items if "error" in p])
        message = f"Parse completed, failed {failed_count}"
        await context.set_result({"items": processed_items})
        await context.set_progress(100.0, message)
        return {"items": processed_items}

    try:
        database = await knowledge_base.get_database_info(db_id)
        task = await tasker.enqueue(
            name=f"Document parse ({database['name']})",
            task_type="knowledge_parse",
            payload={"db_id": db_id, "file_ids": file_ids},
            coroutine=run_parse,
        )
        return {"message": "Parse task submitted", "status": "queued", "task_id": task.id}
    except Exception as e:
        return {"message": f"Submission failed: {e}", "status": "failed"}


@knowledge.post("/databases/{db_id}/documents/index")
async def index_documents(
    db_id: str,
    file_ids: list[str] = Body(...),
    params: dict = Body({}),
    current_user: User = Depends(get_admin_user),
):
    """Manually trigger document indexing, supports updating parameters."""
    logger.debug(f"Index documents for db_id {db_id}: {file_ids} {params=}")
    await _ensure_database_not_dify(db_id, "document indexing")

    # extract operator_id safely before background task
    operator_id = current_user.id

    async def run_index(context: TaskContext):
        await context.set_message("taskinitialize")
        await context.set_progress(5.0, "Preparing document indexing")

        total = len(file_ids)
        processed_items = []

        # Track files that failed param update
        param_update_failed = set()

        try:
            # Update params if provided
            if params:
                for file_id in file_ids:
                    try:
                        await knowledge_base.update_file_params(db_id, file_id, params, operator_id=operator_id)
                    except Exception as e:
                        logger.error(
                            f"Failed to update params for {file_id}: {e}")
                        param_update_failed.add(file_id)
                        processed_items.append(
                            {"file_id": file_id, "status": "failed",
                                "error": f"parameterupdatefailed: {str(e)}"}
                        )

            for idx, file_id in enumerate(file_ids, 1):
                await context.raise_if_cancelled()

                # Skip files that failed param update
                if file_id in param_update_failed:
                    logger.debug(
                        f"Skipping {file_id} due to param update failure")
                    continue

                progress = 5.0 + (idx / total) * 90.0
                await context.set_progress(progress, f"Currently indexing document {idx}/{total}")

                try:
                    result = await knowledge_base.index_file(db_id, file_id, operator_id=operator_id)
                    processed_items.append(result)
                except Exception as e:
                    logger.error(f"Index failed for {file_id}: {e}")
                    processed_items.append(
                        {"file_id": file_id, "status": "failed", "error": str(e)})

        except Exception as e:
            logger.exception(f"Index task failed: {e}")
            raise

        failed_count = len([p for p in processed_items if "error" in p])
        message = f"Indexing completed, failed {failed_count}"
        await context.set_result({"items": processed_items})
        await context.set_progress(100.0, message)
        return {"items": processed_items}

    try:
        database = await knowledge_base.get_database_info(db_id)
        task = await tasker.enqueue(
            name=f"Document indexing ({database['name']})",
            task_type="knowledge_index",
            payload={"db_id": db_id, "file_ids": file_ids, "params": params},
            coroutine=run_index,
        )
        return {"message": "Indexing task submitted", "status": "queued", "task_id": task.id}
    except Exception as e:
        return {"message": f"Submission failed: {e}", "status": "failed"}


@knowledge.post("/databases/{db_id}/scival-ingest")
async def scival_ingest(
    db_id: str,
    payload: dict = Body(...),
    current_user: User = Depends(get_admin_user),
):
    """Ingest structured JSON/CSV academic data directly into graph storage."""
    await _ensure_database_not_dify(db_id, "structured data indexing")

    if not hasattr(graph_base, "txt_add_vector_entity"):
        raise HTTPException(
            status_code=503, detail="Graph ingestion is unavailable while LITE_MODE is enabled")

    mapping = payload.get("mapping") if isinstance(
        payload.get("mapping"), dict) else {}
    embed_model_name = payload.get("embed_model_name")
    batch_size = payload.get("batch_size")

    if batch_size is not None:
        try:
            batch_size = int(batch_size)
        except (TypeError, ValueError) as e:
            raise HTTPException(
                status_code=400, detail=f"batch_size must be an integer: {e}")

    triples = payload.get("triples")
    if triples is not None and not isinstance(triples, list):
        raise HTTPException(status_code=400, detail="triples must be a list")

    if not triples:
        records = _records_from_payload(payload)
        if not records:
            raise HTTPException(
                status_code=400,
                detail="No input data found. Provide one of: triples, records/data, or csv_text.",
            )
        triples = _build_scival_triples(records, db_id=db_id, mapping=mapping)

    if not triples:
        raise HTTPException(
            status_code=400, detail="No graph triples could be generated from the provided payload")

    async def run_structured_ingest(context: TaskContext):
        await context.set_message("Structured dataset ingestion started")
        await context.set_progress(10.0, "Preparing graph ingestion")

        if hasattr(graph_base, "start") and not graph_base.is_running():
            graph_base.start()

        await context.set_progress(40.0, f"Writing {len(triples)} triples to Neo4j")
        await graph_base.txt_add_vector_entity(
            triples,
            kgdb_name="neo4j",
            embed_model_name=embed_model_name,
            batch_size=batch_size,
        )

        summary = {
            "db_id": db_id,
            "triples": len(triples),
            "status": "success",
        }
        await context.set_result(summary)
        await context.set_progress(100.0, "Structured dataset ingestion completed")
        return summary

    database = await knowledge_base.get_database_info(db_id)
    task = await tasker.enqueue(
        name=f"Structured ingest ({database['name']})",
        task_type="knowledge_scival_ingest",
        payload={
            "db_id": db_id,
            "triples": len(triples),
            "embed_model_name": embed_model_name,
            "operator": current_user.user_id,
        },
        coroutine=run_structured_ingest,
    )

    return {
        "message": "Structured ingest task has been queued",
        "status": "queued",
        "task_id": task.id,
        "triples": len(triples),
    }


@knowledge.get("/databases/{db_id}/documents/{doc_id}")
async def get_document_info(db_id: str, doc_id: str, current_user: User = Depends(get_admin_user)):
    """Get document details (including basic info and content info)."""
    logger.debug(f"GET document {doc_id} info in {db_id}")
    await _ensure_database_not_dify(db_id, "document view")

    try:
        info = await knowledge_base.get_file_info(db_id, doc_id)
        return info
    except Exception as e:
        logger.error(
            f"Failed to get file info, {e}, {db_id=}, {doc_id=}, {traceback.format_exc()}")
        return {"message": "Failed to get file info", "status": "failed"}


@knowledge.get("/databases/{db_id}/documents/{doc_id}/basic")
async def get_document_basic_info(db_id: str, doc_id: str, current_user: User = Depends(get_admin_user)):
    """Get document basic info (metadata only)."""
    logger.debug(f"GET document {doc_id} basic info in {db_id}")
    await _ensure_database_not_dify(db_id, "document view")

    try:
        info = await knowledge_base.get_file_basic_info(db_id, doc_id)
        return info
    except Exception as e:
        logger.error(
            f"Failed to get file basic info, {e}, {db_id=}, {doc_id=}, {traceback.format_exc()}")
        return {"message": "Failed to get file basic info", "status": "failed"}


@knowledge.get("/databases/{db_id}/documents/{doc_id}/content")
async def get_document_content(db_id: str, doc_id: str, current_user: User = Depends(get_admin_user)):
    """Get document content info (chunks and lines)."""
    logger.debug(f"GET document {doc_id} content in {db_id}")
    await _ensure_database_not_dify(db_id, "document view")

    try:
        info = await knowledge_base.get_file_content(db_id, doc_id)
        return info
    except Exception as e:
        logger.error(
            f"Failed to get file content, {e}, {db_id=}, {doc_id=}, {traceback.format_exc()}")
        return {"message": "Failed to get file content", "status": "failed"}


@knowledge.delete("/databases/{db_id}/documents/batch")
async def batch_delete_documents(
    db_id: str, file_ids: list[str] = Body(...), current_user: User = Depends(get_admin_user)
):
    """Batch delete documents or folders."""
    logger.debug(f"BATCH DELETE documents {file_ids} in {db_id}")
    await _ensure_database_not_dify(db_id, "batch document deletion")

    deleted_count = 0
    failed_items = []

    for doc_id in file_ids:
        try:
            file_meta_info = await knowledge_base.get_file_basic_info(db_id, doc_id)

            # Check if it is a folder
            is_folder = file_meta_info.get("meta", {}).get("is_folder", False)
            if is_folder:
                await knowledge_base.delete_folder(db_id, doc_id)
                deleted_count += 1
                continue

            file_path = file_meta_info.get("meta", {}).get("path", "")

            # Try deleting file object and parse result from MinIO.
            try:
                minio_client = get_minio_client()
                if file_path.startswith(("http://", "https://")):
                    bucket_name, object_name = parse_minio_url(file_path)
                    await minio_client.adelete_file(bucket_name, object_name)
                await minio_client.adelete_file(minio_client.KB_BUCKETS["parsed"], f"{db_id}/parsed/{doc_id}.md")
                logger.debug(
                    f"Successfully deleted file from MinIO: {file_path}")
            except Exception as minio_error:
                logger.warning(
                    f"Failed to delete file from MinIO: {minio_error}")

            # Continue deleting from knowledge base regardless of MinIO deletion result.
            await knowledge_base.delete_file(db_id, doc_id)
            deleted_count += 1
        except Exception as e:
            logger.error(
                f"Failed to delete document {doc_id} during batch delete: {e}, {traceback.format_exc()}")
            failed_items.append({"doc_id": doc_id, "error": str(e)})

    if failed_items:
        if deleted_count == 0:
            raise HTTPException(
                status_code=400, detail=f"Batch delete failed: all {len(failed_items)} files were not deleted.")
        return {
            "message": f"Partial delete successful: deleted {deleted_count} files, failed {len(failed_items)}",
            "deleted_count": deleted_count,
            "failed_items": failed_items,
        }

    return {"message": f"Batch delete successful: deleted {deleted_count} files", "deleted_count": deleted_count}


@knowledge.delete("/databases/{db_id}/documents/{doc_id}")
async def delete_document(db_id: str, doc_id: str, current_user: User = Depends(get_admin_user)):
    """Delete a document or folder."""
    logger.debug(f"DELETE document {doc_id} info in {db_id}")
    await _ensure_database_not_dify(db_id, "document deletion")
    try:
        file_meta_info = await knowledge_base.get_file_basic_info(db_id, doc_id)

        # Check if it is a folder
        is_folder = file_meta_info.get("meta", {}).get("is_folder", False)
        if is_folder:
            await knowledge_base.delete_folder(db_id, doc_id)
            return {"message": "Folder deleted successfully"}

        file_path = file_meta_info.get("meta", {}).get("path", "")

        # Try deleting file object and parse result from MinIO.
        try:
            minio_client = get_minio_client()
            if file_path.startswith(("http://", "https://")):
                bucket_name, object_name = parse_minio_url(file_path)
                await minio_client.adelete_file(bucket_name, object_name)
            await minio_client.adelete_file(minio_client.KB_BUCKETS["parsed"], f"{db_id}/parsed/{doc_id}.md")
            logger.debug(f"Successfully deleted file from MinIO: {file_path}")
        except Exception as minio_error:
            logger.warning(f"Failed to delete file from MinIO: {minio_error}")

        # Continue deleting from knowledge base regardless of MinIO deletion result.
        await knowledge_base.delete_file(db_id, doc_id)
        return {"message": "Delete successful"}
    except Exception as e:
        logger.error(f"deletedocumentfailed {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=400, detail=f"deletedocumentfailed: {e}")


@knowledge.get("/databases/{db_id}/documents/{doc_id}/download")
async def download_document(db_id: str, doc_id: str, request: Request, current_user: User = Depends(get_admin_user)):
    """Download original file - choose local or MinIO download by path type."""
    logger.debug(f"Download document {doc_id} from {db_id}")
    await _ensure_database_not_dify(db_id, "document download")
    try:
        file_info = await knowledge_base.get_file_basic_info(db_id, doc_id)
        file_meta = file_info.get("meta", {})

        # Get file type, path, and filename.
        file_type = file_meta.get("file_type", "file")
        file_path = file_meta.get("path", "")
        filename = file_meta.get("filename", "file")

        # URL-type files do not have downloadable original files.
        if file_type == "url":
            raise HTTPException(
                status_code=400, detail="URL-type files do not support original file download")
        logger.debug(f"File path from database: {file_path}")
        logger.debug(f"Original filename from database: {filename}")

        # Decode URL-encoded filename if present.
        try:
            decoded_filename = unquote(filename, encoding="utf-8")
            logger.debug(f"Decoded filename: {decoded_filename}")
        except Exception as e:
            logger.debug(f"Failed to decode filename {filename}: {e}")
            # Use original filename if decoding fails.
            decoded_filename = filename

        _, ext = os.path.splitext(decoded_filename)
        media_type = media_types.get(ext.lower(), "application/octet-stream")

        # Choose download method by path type.
        from yunesa.knowledge.utils.kb_utils import is_minio_url

        if is_minio_url(file_path):
            # MinIO download.
            logger.debug(f"Downloading from MinIO: {file_path}")

            try:
                # Parse MinIO URL using shared utility.
                from yunesa.knowledge.utils.kb_utils import parse_minio_url

                bucket_name, object_name = parse_minio_url(file_path)

                logger.debug(
                    f"Parsed bucket_name: {bucket_name}, object_name: {object_name}")

                minio_client = get_minio_client()

                # Download directly using parsed full object name.
                minio_response = await minio_client.adownload_response(
                    bucket_name=bucket_name,
                    object_name=object_name,
                )
                logger.debug(f"Successfully downloaded object: {object_name}")

            except Exception as e:
                logger.error(f"Failed to download MinIO file: {e}")
                raise StorageError(f"downloadfilefailed: {e}")

            # Create streaming generator.
            async def minio_stream():
                try:
                    while True:
                        chunk = await asyncio.to_thread(minio_response.read, 8192)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    minio_response.close()
                    minio_response.release_conn()

            # Create StreamingResponse.
            response = StreamingResponse(
                minio_stream(),
                media_type=media_type,
            )
            # Properly set HTTP headers for non-ASCII filenames.
            try:
                # Try ASCII encoding (works for English filenames).
                decoded_filename.encode("ascii")
                # If successful, use simple format.
                response.headers[
                    "Content-Disposition"] = f'attachment; filename="{decoded_filename}"'
            except UnicodeEncodeError:
                # For non-ASCII characters, use RFC 2231 format.
                encoded_filename = quote(decoded_filename.encode("utf-8"))
                response.headers[
                    "Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"

            return response

        else:
            # Local file download.
            logger.debug(f"Downloading from local filesystem: {file_path}")

            if not os.path.exists(file_path):
                raise StorageError(f"filedoes not exist: {file_path}")

            # Get file size.
            file_size = os.path.getsize(file_path)

            # Create file streaming generator.
            async def file_stream():
                async with aiofiles.open(file_path, "rb") as f:
                    while True:
                        chunk = await f.read(8192)
                        if not chunk:
                            break
                        yield chunk

            # Create StreamingResponse.
            response = StreamingResponse(
                file_stream(),
                media_type=media_type,
            )
            # Properly set HTTP headers for non-ASCII filenames.
            try:
                # Try ASCII encoding (works for English filenames).
                decoded_filename.encode("ascii")
                # If successful, use simple format.
                response.headers[
                    "Content-Disposition"] = f'attachment; filename="{decoded_filename}"'
                response.headers["Content-Length"] = str(file_size)
            except UnicodeEncodeError:
                # For non-ASCII characters, use RFC 2231 format.
                encoded_filename = quote(decoded_filename.encode("utf-8"))
                response.headers[
                    "Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
                response.headers["Content-Length"] = str(file_size)

            return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"downloadfilefailed: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"downloadfailed: {e}")


# =============================================================================
# === Knowledge Base Query Group ===
# =============================================================================


@knowledge.post("/databases/{db_id}/query")
async def query_knowledge_base(
    db_id: str, query: str = Body(...), meta: dict = Body(...), current_user: User = Depends(get_admin_user)
):
    """Query knowledge base."""
    logger.debug(f"Query knowledge base {db_id}: {query}")
    try:
        result = await knowledge_base.aquery(query, db_id=db_id, **meta)
        return {"result": result, "status": "success"}
    except Exception as e:
        logger.error(
            f"knowledge basequeryfailed {e}, {traceback.format_exc()}")
        return {"message": f"knowledge basequeryfailed: {e}", "status": "failed"}


@knowledge.post("/databases/{db_id}/query-test")
async def query_test(
    db_id: str, query: str = Body(...), meta: dict = Body(...), current_user: User = Depends(get_admin_user)
):
    """Test query against knowledge base."""
    logger.debug(f"Query test in {db_id}: {query}")
    try:
        result = await knowledge_base.aquery(query, db_id=db_id, **meta)
        return result
    except Exception as e:
        logger.error(f"testqueryfailed {e}, {traceback.format_exc()}")
        return {"message": f"testqueryfailed: {e}", "status": "failed"}


@knowledge.put("/databases/{db_id}/query-params")
async def update_knowledge_base_query_params(
    db_id: str, params: dict = Body(...), current_user: User = Depends(get_admin_user)
):
    """Update knowledge base query parameter configuration."""
    try:
        # Get knowledge base instance.
        kb_instance = await knowledge_base._get_kb_for_database(db_id)
        if not kb_instance:
            raise HTTPException(
                status_code=404, detail="Knowledge base not found")

        # Update query parameters in instance metadata.
        async with knowledge_base._metadata_lock:
            # Ensure db_id exists in instance databases_meta.
            if db_id not in kb_instance.databases_meta:
                raise HTTPException(
                    status_code=404, detail="Database not found in instance metadata")

            # Ensure query_params is not None.
            if kb_instance.databases_meta[db_id].get("query_params") is None:
                kb_instance.databases_meta[db_id]["query_params"] = {}

            options = kb_instance.databases_meta[db_id]["query_params"].setdefault(
                "options", {})
            options.update(params)
            await kb_instance._save_metadata()

            logger.info(
                f"Updated knowledge base {db_id} query parameters: {params}")

        return {"message": "success", "data": params}

    except Exception as e:
        logger.error(f"Failed to update knowledge base query parameters: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update query parameters: {str(e)}")


@knowledge.get("/databases/{db_id}/query-params")
async def get_knowledge_base_query_params(db_id: str, current_user: User = Depends(get_admin_user)):
    """Get query parameters for a specific knowledge base type."""
    try:
        # Get knowledge base instance.
        kb_instance = await knowledge_base._get_kb_for_database(db_id)

        # Call instance method to get config.
        params = kb_instance.get_query_params_config(
            db_id=db_id,
            reranker_names=config.reranker_names,  # Pass dynamic config.
        )

        # Merge user-saved config (read from instance metadata).
        saved_options = kb_instance._get_query_params(db_id)
        if saved_options:
            params = _merge_saved_options(params, saved_options)

        return {"params": params, "message": "success"}

    except Exception as e:
        logger.error(
            f"getknowledge basequeryparameterfailed {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


def _merge_saved_options(params: dict, saved_options: dict) -> dict:
    """Merge user-saved config into default config."""
    for option in params.get("options", []):
        key = option.get("key")
        if key in saved_options:
            option["default"] = saved_options[key]
    return params


# =============================================================================
# === AI Generate Sample Questions ===
# =============================================================================


SAMPLE_QUESTIONS_SYSTEM_PROMPT = """You are a professional expert in knowledge base Q&A testing.

Your task is to generate valuable test questions based on the knowledge base file list.

Requirements:
1. Questions should be specific and targeted, inferred from filenames and file types.
2. Questions should cover different aspects and difficulty levels.
3. Questions should be concise and suitable for retrieval testing.
4. Questions should be diverse, including factual queries, concept explanations, and operational guidance.
5. Keep question length around 10-30 Chinese characters or equivalent concise phrasing.
6. Return only a JSON array format, with no extra commentary.

Return format:
```json
{
  "questions": [
    "question1？",
    "question2？",
    "question3？"
  ]
}
```
"""


@knowledge.post("/databases/{db_id}/sample-questions")
async def generate_sample_questions(
    db_id: str,
    request_body: dict = Body(...),
    current_user: User = Depends(get_admin_user),
):
    """
    AI-generate test questions for a knowledge base.

    Args:
        db_id: Knowledge base ID.
        request_body: Request body containing count field.

    Returns:
        Generated question list.
    """
    try:
        db_info = await knowledge_base.get_database_info(db_id)
        if not db_info:
            raise HTTPException(
                status_code=404, detail=f"knowledge base {db_id} does not exist")
        if (db_info.get("kb_type") or "").lower() == "dify":
            raise HTTPException(
                status_code=400, detail="Dify knowledge base does not support file-based test question generation")

        from yunesa.models import select_model

        # Extract parameters from request body.
        count = request_body.get("count", 10)

        db_name = db_info.get("name", "")
        all_files = db_info.get("files", {})

        if not all_files:
            raise HTTPException(
                status_code=400, detail="No files found in knowledge base")

        # Collect file info.
        files_info = []
        for file_id, file_info in all_files.items():
            files_info.append(
                {
                    "filename": file_info.get("filename", ""),
                    "type": file_info.get("type", ""),
                }
            )

        # Build AI prompt.
        system_prompt = SAMPLE_QUESTIONS_SYSTEM_PROMPT

        # Build user message.
        files_text = "\n".join(
            [
                f"- {f['filename']} ({f['type']})"
                for f in files_info[:20]  # At most list 20 files.
            ]
        )

        file_count_text = f"(total {len(files_info)} files)" if len(
            files_info) > 20 else ""

        user_message = textwrap.dedent(f"""Please generate {count} test questions for knowledge base "{db_name}".

            Knowledge base file list {file_count_text}:
            {files_text}

            Based on these filenames and types, generate {count} valuable test questions.""")

        # Call AI generation.
        logger.info(
            f"Start generating knowledge base questions, knowledge base: {db_name}, "
            f"file count: {len(files_info)}, question count: {count}"
        )

        # Select model and call.
        model = select_model()
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}]
        response = await model.call(messages, stream=False)

        # Parse AI-returned JSON.
        try:
            # Extract JSON content.
            content = response.content if hasattr(
                response, "content") else str(response)

            # Try extracting JSON from markdown code blocks.
            if "```json" in content:
                json_start = content.find("```json") + 7
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()
            elif "```" in content:
                json_start = content.find("```") + 3
                json_end = content.find("```", json_start)
                content = content[json_start:json_end].strip()

            questions_data = json.loads(content)
            questions = questions_data.get("questions", [])

            if not questions or not isinstance(questions, list):
                raise ValueError("AI return question format is incorrect")

            logger.info(f"Successfully generated {len(questions)} questions")

            # Save questions to knowledge base metadata.
            try:
                from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

                await KnowledgeBaseRepository().update(db_id, {"sample_questions": questions})
                logger.info(
                    f"Successfully saved {len(questions)} questions to knowledge base {db_id}")
            except Exception as save_error:
                logger.error(f"Failed to save questions: {save_error}")

            return {
                "message": "success",
                "questions": questions,
                "count": len(questions),
                "db_id": db_id,
                "db_name": db_name,
            }

        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to parse AI-returned JSON: {e}, raw content: {content}")
            raise HTTPException(
                status_code=500, detail=f"AI return format error: {str(e)}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"generateknowledge basequestionfailed: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"generatequestionfailed: {str(e)}")


@knowledge.get("/databases/{db_id}/sample-questions")
async def get_sample_questions(db_id: str, current_user: User = Depends(get_admin_user)):
    """
    Get test questions for a knowledge base.

    Args:
        db_id: Knowledge base ID.

    Returns:
        Question list.
    """
    try:
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)

        if kb is None:
            raise HTTPException(
                status_code=404, detail=f"knowledge base {db_id} does not exist")

        questions = kb.sample_questions or []

        return {
            "message": "success",
            "questions": questions,
            "count": len(questions),
            "db_id": db_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"getknowledge basequestionfailed: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"getquestionfailed: {str(e)}")


# =============================================================================
# === File Management Group ===
# =============================================================================


@knowledge.post("/databases/{db_id}/folders")
async def create_folder(
    db_id: str,
    folder_name: str = Body(..., embed=True),
    parent_id: str | None = Body(None, embed=True),
    current_user: User = Depends(get_admin_user),
):
    """Create folder."""
    try:
        await _ensure_database_not_dify(db_id, "folder creation")
        return await knowledge_base.create_folder(db_id, folder_name, parent_id)
    except Exception as e:
        logger.error(f"createfolderfailed {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@knowledge.put("/databases/{db_id}/documents/{doc_id}/move")
async def move_document(
    db_id: str,
    doc_id: str,
    new_parent_id: str | None = Body(..., embed=True),
    current_user: User = Depends(get_admin_user),
):
    """Move file or folder."""
    logger.debug(f"Move document {doc_id} to {new_parent_id} in {db_id}")
    try:
        await _ensure_database_not_dify(db_id, "file move")
        return await knowledge_base.move_file(db_id, doc_id, new_parent_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"movefilefailed {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@knowledge.post("/files/fetch-url")
async def fetch_url(
    url: str = Body(..., embed=True),
    db_id: str | None = Body(None, embed=True),
    current_user: User = Depends(get_admin_user),
):
    """Fetch URL content and upload it to MinIO."""
    logger.debug(f"Fetching URL: {url} for db_id: {db_id}")
    try:
        from yunesa.knowledge.utils.url_fetcher import fetch_url_content
        from yunesa.storage.minio import get_minio_client
        from yunesa.knowledge.utils import calculate_content_hash

        # 1. Download content (includes whitelist check, size limit, and type check).
        content_bytes, final_url = await fetch_url_content(url)

        # 2. calculate Hash
        content_hash = await calculate_content_hash(content_bytes)

        # Check whether file with the same content already exists.
        if db_id:
            file_exists = await knowledge_base.file_existed_in_db(db_id, content_hash)
            if file_exists:
                raise HTTPException(
                    status_code=409,
                    detail="A file with the same content already exists in this database",
                )

        # 3. Upload to MinIO.
        minio_client = get_minio_client()
        bucket_name = MinIOClient.KB_BUCKETS["documents"]
        await asyncio.to_thread(minio_client.ensure_bucket_exists, bucket_name)

        folder = db_id if db_id else "unknown"
        object_name = f"{folder}/upload/{content_hash}.html"

        upload_result = await minio_client.aupload_file(
            bucket_name=bucket_name,
            object_name=object_name,
            data=content_bytes,
            content_type="text/html",
        )

        # Detect same-name files (URL itself is used as filename).
        same_name_files = []
        has_same_name = False
        if db_id:
            same_name_files = await knowledge_base.get_same_name_files(db_id, url)
            has_same_name = len(same_name_files) > 0

        return {
            "status": "success",
            "file_path": upload_result.url,
            "minio_url": upload_result.url,
            "content_hash": content_hash,
            "filename": url,  # Original URL as filename.
            "final_url": final_url,
            "size": len(content_bytes),
            "has_same_name": has_same_name,
            "same_name_files": same_name_files,
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"URL fetch validation failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(
            f"Failed to fetch URL {url}: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch URL: {str(e)}")


@knowledge.post("/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    db_id: str | None = Query(None),
    allow_jsonl: bool = Query(False),
    current_user: User = Depends(get_admin_user),
):
    """Upload file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No selected file")

    logger.debug(f"Received upload file with filename: {file.filename}")

    ext = os.path.splitext(file.filename)[1].lower()

    if ext == ".jsonl":
        if allow_jsonl is not True or db_id is not None:
            raise HTTPException(
                status_code=400, detail=f"Unsupported file type: {ext}")
    elif not (is_supported_file_extension(file.filename) or ext == ".zip"):
        raise HTTPException(
            status_code=400, detail=f"Unsupported file type: {ext}")

    basename, ext = os.path.splitext(file.filename)
    # Use original filename directly (lowercase).
    filename = f"{basename}{ext}".lower()

    file_bytes = await file.read()

    content_hash = await calculate_content_hash(file_bytes)

    file_exists = await knowledge_base.file_existed_in_db(db_id, content_hash)
    if file_exists:
        raise HTTPException(
            status_code=409,
            detail="A file with the same content already exists in this database",
        )

    # Upload directly to MinIO and add timestamp to differentiate versions.
    import time

    timestamp = int(time.time() * 1000)
    minio_filename = f"{basename}_{timestamp}{ext}"

    bucket_name = MinIOClient.KB_BUCKETS["documents"]
    folder = db_id if db_id else "unknown"
    object_name = f"{folder}/upload/{minio_filename}"

    # Upload to MinIO.
    minio_url = await aupload_file_to_minio(bucket_name, object_name, file_bytes)

    # Detect same-name files (based on original filename).
    same_name_files = await knowledge_base.get_same_name_files(db_id, filename)
    has_same_name = len(same_name_files) > 0

    return {
        "message": "File successfully uploaded",
        "file_path": minio_url,  # MinIO path as primary path.
        "minio_path": minio_url,  # MinIO path.
        "db_id": db_id,
        "content_hash": content_hash,
        "filename": filename,  # Original filename (lowercase).
        # Original filename (without extension).
        "original_filename": basename,
        # Filename in MinIO (with timestamp).
        "minio_filename": minio_filename,
        "object_name": object_name,
        "bucket_name": bucket_name,  # MinIO storage bucket name.
        "same_name_files": same_name_files,  # Same-name file list.
        "has_same_name": has_same_name,  # Whether same-name files exist.
    }


@knowledge.get("/files/supported-types")
async def get_supported_file_types(current_user: User = Depends(get_admin_user)):
    """Get currently supported file types."""
    return {"message": "success", "file_types": sorted(SUPPORTED_FILE_EXTENSIONS)}


@knowledge.post("/files/markdown")
async def mark_it_down(file: UploadFile = File(...), current_user: User = Depends(get_admin_user)):
    """Parse file to markdown using unified Parser (admin permission required)."""
    import tempfile

    if not file.filename:
        return {"message": "File parse failed: unable to identify filename", "markdown_content": ""}

    suffix = os.path.splitext(file.filename)[1].lower()
    temp_path = None

    try:
        content = await file.read()

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name

        async with aiofiles.open(temp_path, "wb") as temp_buffer:
            await temp_buffer.write(content)

        markdown_content = await Parser.aparse(temp_path)
        return {"markdown_content": markdown_content, "message": "success"}
    except Exception as e:
        logger.error(f"fileparsefailed {e}, {traceback.format_exc()}")
        return {"message": f"fileparsefailed {e}", "markdown_content": ""}
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as cleanup_error:
                logger.warning(
                    f"Temporary file cleanup failed {temp_path}: {cleanup_error}")


# =============================================================================
# === Knowledge Base Type Group ===
# =============================================================================


@knowledge.get("/types")
async def get_knowledge_base_types(current_user: User = Depends(get_admin_user)):
    """Get supported knowledge base types."""
    try:
        kb_types = knowledge_base.get_supported_kb_types()
        return {"kb_types": kb_types, "message": "success"}
    except Exception as e:
        logger.error(
            f"getknowledge basetypefailed {e}, {traceback.format_exc()}")
        return {"message": f"getknowledge basetypefailed {e}", "kb_types": {}}


@knowledge.get("/stats")
async def get_knowledge_base_statistics(current_user: User = Depends(get_admin_user)):
    """Get knowledge base statistics."""
    try:
        stats = await knowledge_base.get_statistics()
        return {"stats": stats, "message": "success"}
    except Exception as e:
        logger.error(
            f"getknowledge basestatisticsfailed {e}, {traceback.format_exc()}")
        return {"message": f"getknowledge basestatisticsfailed {e}", "stats": {}}


# =============================================================================
# === Embedding Model Status Check Group ===
# =============================================================================


@knowledge.get("/embedding-models/{model_id}/status")
async def get_embedding_model_status(model_id: str, current_user: User = Depends(get_admin_user)):
    """Get status for specified embedding model."""
    logger.debug(f"Checking embedding model status: {model_id}")
    try:
        status = await test_embedding_model_status(model_id)
        return {"status": status, "message": "success"}
    except Exception as e:
        logger.error(
            f"getembeddingmodelstatusfailed {model_id}: {e}, {traceback.format_exc()}")
        return {
            "message": f"getembeddingmodelstatusfailed: {e}",
            "status": {"model_id": model_id, "status": "error", "message": str(e)},
        }


@knowledge.get("/embedding-models/status")
async def get_all_embedding_models_status(current_user: User = Depends(get_admin_user)):
    """Get status for all embedding models."""
    logger.debug("Checking all embedding models status")
    try:
        status = await test_all_embedding_models_status()
        return {"status": status, "message": "success"}
    except Exception as e:
        logger.error(
            f"Failed to get all embedding model statuses: {e}, {traceback.format_exc()}")
        return {
            "message": f"Failed to get all embedding model statuses: {e}",
            "status": {"models": {}, "total": 0, "available": 0},
        }


# =============================================================================
# === Knowledge Base AI Utility Group ===
# =============================================================================


@knowledge.post("/generate-description")
async def generate_description(
    name: str = Body(..., description="knowledge basename"),
    current_description: str = Body(
        "", description="Current description (optional, used for optimization)"),
    file_list: list[str] = Body([], description="File list"),
    current_user: User = Depends(get_admin_user),
):
    """Use LLM to generate or optimize knowledge base description.

    Based on knowledge base name and current description, generate content
    suitable for agent tool descriptions.
    """
    from yunesa.models import select_model

    logger.debug(
        f"Generating description for knowledge base: {name}, files: {len(file_list)}")

    # Build file list text.
    if file_list:
        # Limit file count to avoid overly long prompts.
        display_files = file_list[:50]
        files_str = "\n".join([f"- {f}" for f in display_files])
        more_text = f"\n... ({len(file_list) - 50} more files)" if len(
            file_list) > 50 else ""
        current_description += f"\n\nKnowledge base contains files:\n{files_str}{more_text}"

    current_description = current_description or "No description yet"

    # Build prompt text.
    prompt = textwrap.dedent(f"""
        Please help optimize the following knowledge base description.

        Knowledge base name: {name}
        Current description: {current_description}

        Requirements:
        1. This description will be used as an agent tool description.
        2. The agent selects tools based on knowledge base title and description.
        3. The description should be clear and specific, explaining what content is included and what questions it can answer.
        4. Keep it concise and strong, usually 2-4 sentences.
        5. Do not use Markdown format.
        {"6. Refer to the provided file list to summarize knowledge base content accurately" if file_list else ""}

        Output only the optimized description, without any prefix or explanation.
    """).strip()

    try:
        model = select_model()
        response = await model.call(prompt)
        description = response.content.strip()
        logger.debug(f"Generated description: {description}")
        return {"description": description, "status": "success"}
    except Exception as e:
        logger.error(
            f"generatedescriptionfailed: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"generatedescriptionfailed: {e}")
