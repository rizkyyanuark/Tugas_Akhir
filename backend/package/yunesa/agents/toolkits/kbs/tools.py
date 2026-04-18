"""Knowledge base toolkit module."""

import inspect
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from yunesa import knowledge_base
from yunesa.utils import logger

# ========== Common knowledge base tool functions ==========


class ListKBsInput(BaseModel):
    """Input model for listing user-accessible knowledge bases."""

    # LangChain runtime injection requires at least one parameter.
    dummy: str = Field(
        default="", description="Dummy parameter - ignore")  # Add this


@tool(args_schema=ListKBsInput)
async def list_kbs(dummy: str, runtime: ToolRuntime) -> str:  # Now has 2 params
    """List knowledge bases accessible to the current user.

    Returns a list of knowledge base names that the user can access by permission.
    The list is filtered by user role and department, and excludes knowledge bases
    that are not enabled in the current conversation.

    Returns:
        Accessible knowledge base list.
    """
    # Get user info from runtime.context.
    runtime_context = runtime.context
    user_id = getattr(runtime_context, "user_id", None)
    if not user_id:
        return "Unable to get user information"

    # Log full runtime context for debugging.
    logger.debug(f"Runtime context: {runtime_context.__dict__}")

    # Get knowledge bases enabled in the current conversation.
    enabled_kb_names = getattr(runtime_context, "knowledges", []) or []

    # Get all knowledge bases accessible to user (including name and description).
    try:
        result = await knowledge_base.get_databases_by_raw_id(user_id)
        all_kbs = result.get("databases", [])
    except Exception as e:
        logger.error(f"Failed to get user knowledge base list: {e}")
        return f"Failed to get knowledge base list: {str(e)}"

    all_kb_names = [kb["name"] for kb in all_kbs]

    logger.debug(
        f"Knowledge bases accessible to user {user_id}: {all_kb_names}")
    logger.debug(
        f"Knowledge bases enabled in current conversation for user {user_id}: {enabled_kb_names}")

    # Intersect with enabled knowledge bases.
    available_kbs = [kb for kb in all_kbs if kb["name"] in enabled_kb_names]

    if not available_kbs:
        return "No accessible knowledge base is currently available"

    # Format output (include name and description).
    kb_list = []
    for kb in available_kbs:
        name = kb.get("name", "")
        desc = kb.get("description") or "No description"
        kb_list.append({"name": name, "description": desc})

    return kb_list


class GetMindmapInput(BaseModel):
    """Input model for mindmap retrieval."""

    kb_name: str = Field(
        description="Knowledge base name used to specify which mindmap to retrieve")


@tool(args_schema=GetMindmapInput)
async def get_mindmap(kb_name: str, runtime: ToolRuntime) -> str:
    """Get the mindmap structure of a specific knowledge base.

    Use this tool when the user wants to understand overall structure,
    file categorization, and knowledge architecture.

    Args:
        kb_name: Knowledge base name

    Returns:
        Mindmap hierarchy in text format
    """
    if not kb_name:
        return "Please provide a knowledge base name"

    # Get all retrievers.
    retrievers = knowledge_base.get_retrievers()

    # Find target knowledge base.
    target_db_id = None
    target_info = None
    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            target_db_id = db_id
            target_info = info
            break

    if not target_db_id:
        return f"knowledge base '{kb_name}' does not exist"

    try:
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(target_db_id)

        if kb is None:
            return f"knowledge base {target_info['name']} does not exist"

        mindmap_data = kb.mindmap

        if not mindmap_data:
            return f"Knowledge base {target_info['name']} does not have a generated mindmap yet."

        # Convert mindmap JSON data to hierarchical text.
        def mindmap_to_text(node, level=0):
            """Recursively convert mindmap JSON to hierarchical text."""
            indent = "  " * level
            text = f"{indent}- {node.get('content', '')}\n"
            for child in node.get("children", []):
                text += mindmap_to_text(child, level + 1)
            return text

        mindmap_text = f"Mindmap structure for knowledge base {target_info['name']}:\n\n"
        mindmap_text += mindmap_to_text(mindmap_data)

        return mindmap_text

    except Exception as e:
        logger.error(f"Failed to get mindmap: {e}")
        return f"Failed to get mindmap: {str(e)}"


class QueryKBInput(BaseModel):
    """Input model for knowledge base retrieval."""

    kb_name: str = Field(description="Knowledge base name to query")
    query_text: str = Field(
        description=(
            "Keywords for retrieval. Prefer focused keywords that help answer the question "
            "instead of directly using the user's raw input."
        )
    )
    file_name: str | None = Field(
        default=None,
        description=(
            "(Optional, leave empty unless needed) After reading the mindmap, you may provide a file keyword "
            "for fuzzy matching.\nUse only when retrieval results are too broad and need narrowing."
        ),
    )


async def _resolve_visible_knowledge_bases_for_query(runtime: ToolRuntime | None) -> list[dict[str, Any]]:
    if runtime is None:
        return []

    context = getattr(runtime, "context", None)
    if context is None:
        return []

    visible_kbs = getattr(context, "_visible_knowledge_bases", None)
    if isinstance(visible_kbs, list):
        return visible_kbs

    try:
        from yunesa.agents.backends.knowledge_base_backend import resolve_visible_knowledge_bases_for_context

        return await resolve_visible_knowledge_bases_for_context(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Failed to parse session-visible knowledge bases, skip filepath injection: {exc}")
        return []


def _find_query_target(
    *,
    kb_name: str,
    retrievers: dict[str, Any],
    visible_kbs: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if visible_kbs:
        matched_kbs = [db for db in visible_kbs if str(
            db.get("name") or "").strip() == kb_name]
        if not matched_kbs:
            return None, None, f"Knowledge base '{kb_name}' does not exist or is not enabled in current session"
        if len(matched_kbs) > 1:
            return None, None, f"Knowledge base '{kb_name}' has duplicate names; rename and retry"

        target_db_id = str(matched_kbs[0].get("db_id") or "")
        target_info = retrievers.get(target_db_id)
        if target_info is None:
            return None, None, f"knowledge base '{kb_name}' does not exist"
        return target_db_id, target_info, None

    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            return str(db_id), info, None

    return None, None, f"knowledge base '{kb_name}' does not exist"


@tool(args_schema=QueryKBInput)
async def query_kb(kb_name: str, query_text: str, file_name: str | None = None, runtime: ToolRuntime = None) -> Any:
    """Retrieve content from a specified knowledge base.

    Use this tool when the user needs specific content retrieval. It retrieves
    related document chunks from the target knowledge base by keywords.

    Args:
        kb_name: Knowledge base name
        query_text: Retrieval keywords
        file_name: Optional filename filter

    Returns:
        Retrieval result
    """
    if not kb_name:
        return "Please provide a knowledge base name"
    if not query_text:
        return "Please provide query text"

    # Get all retrievers.
    retrievers = knowledge_base.get_retrievers()

    visible_kbs = await _resolve_visible_knowledge_bases_for_query(runtime)

    target_db_id, target_info, target_error = _find_query_target(
        kb_name=kb_name,
        retrievers=retrievers,
        visible_kbs=visible_kbs,
    )
    if target_error:
        return target_error

    metadata = target_info.get("metadata") if isinstance(
        target_info, dict) else None
    kb_type = str((metadata or {}).get("kb_type") or "").strip().lower()

    try:
        retriever = target_info["retriever"]
        kwargs = {}
        if file_name:
            kwargs["file_name"] = file_name

        if inspect.iscoroutinefunction(retriever):
            result = await retriever(query_text, **kwargs)
        else:
            result = retriever(query_text, **kwargs)

        if kb_type != "milvus":
            return result

        if not isinstance(result, list):
            return f"Knowledge base '{kb_name}' returned a non-Milvus chunk list; filepath injection is unavailable"

        from yunesa.agents.backends.knowledge_base_backend import inject_filepaths_into_retrieval_result

        # Only Milvus result file_ids map to local filesystem paths and can be enriched.
        return await inject_filepaths_into_retrieval_result(
            retrieval_chunks=result,
            visible_kbs=visible_kbs,
            target_db_id=target_db_id,
            target_kb_name=kb_name,
        )

    except Exception as e:
        logger.error(f"retrievalfailed: {e}")
        return f"retrievalfailed: {str(e)}"


def get_common_kb_tools() -> list:
    """Get common knowledge base tool list.

    Returns three common tools:
    - list_kbs: list user-accessible knowledge bases
    - get_mindmap: get mindmap for a specified knowledge base
    - query_kb: retrieve from a specified knowledge base
    """
    return [list_kbs, get_mindmap, query_kb]
