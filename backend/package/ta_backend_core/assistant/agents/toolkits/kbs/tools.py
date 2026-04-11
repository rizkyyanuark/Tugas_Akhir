"""Knowledge base tools module"""

import inspect
from typing import Any

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import BaseModel, Field

from ta_backend_core.assistant import knowledge_base
from ta_backend_core.assistant.utils import logger

# ========== Common knowledge base tool functions ==========


class ListKBsInput(BaseModel):
    """Input model for listing knowledge bases accessible to the user"""

    # LangChain runtime injection requires at least one parameter
    dummy: str = Field(default="", description="Dummy parameter - ignore")  # Add this


@tool(args_schema=ListKBsInput)
async def list_kbs(dummy: str, runtime: ToolRuntime) -> str:  # Now has 2 params
    """List the knowledge bases currently accessible to the user

    Returns a list of knowledge base names the user can access based on permissions.
    The list is filtered using the user's role and department information,
    but excludes knowledge bases that are not enabled in the current conversation.

    Returns:
        List of accessible knowledge base names (string format)
    """
    # Get user info from runtime.context
    runtime_context = runtime.context
    user_id = getattr(runtime_context, "user_id", None)
    if not user_id:
        return "Unable to retrieve user information"

    # Print all runtime context information for debugging
    logger.debug(f"Runtime context: {runtime_context.__dict__}")

    # Get the knowledge bases enabled for the current conversation
    enabled_kb_names = getattr(runtime_context, "knowledges", []) or []

    # Get the list of knowledge bases accessible to the user (with names and descriptions)
    try:
        result = await knowledge_base.get_databases_by_raw_id(user_id)
        all_kbs = result.get("databases", [])
    except Exception as e:
        logger.error(f"Failed to get user knowledge base list: {e}")
        return f"Failed to get knowledge base list: {str(e)}"

    all_kb_names = [kb["name"] for kb in all_kbs]

    logger.debug(f"Knowledge bases accessible to user {user_id}: {all_kb_names}")
    logger.debug(f"Knowledge bases enabled in current conversation for user {user_id}: {enabled_kb_names}")

    # Intersect with enabled knowledge bases
    available_kbs = [kb for kb in all_kbs if kb["name"] in enabled_kb_names]

    if not available_kbs:
        return "No accessible knowledge bases are currently available"

    # Format output (including name and description)
    kb_list = []
    for kb in available_kbs:
        name = kb.get("name", "")
        desc = kb.get("description") or "No description"
        kb_list.append({"name": name, "description": desc})

    return kb_list


class GetMindmapInput(BaseModel):
    """Input model for retrieving a mindmap"""

    kb_name: str = Field(description="Knowledge base name to identify the target knowledge base")


@tool(args_schema=GetMindmapInput)
async def get_mindmap(kb_name: str, runtime: ToolRuntime) -> str:
    """Get the mindmap structure of a specified knowledge base

    Use this tool when the user wants to understand the overall structure,
    file categories, or knowledge architecture of a knowledge base.
    Returns the hierarchical mindmap structure.

    Args:
        kb_name: Knowledge base name

    Returns:
        Mindmap structure of the knowledge base (text format)
    """
    if not kb_name:
        return "Please provide a knowledge base name"

    # Get all retrievers
    retrievers = knowledge_base.get_retrievers()

    # Find the target knowledge base
    target_db_id = None
    target_info = None
    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            target_db_id = db_id
            target_info = info
            break

    if not target_db_id:
        return f"Knowledge base '{kb_name}' does not exist"

    try:
        from ta_backend_core.assistant.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(target_db_id)

        if kb is None:
            return f"Knowledge base {target_info['name']} does not exist"

        mindmap_data = kb.mindmap

        if not mindmap_data:
            return f"Knowledge base {target_info['name']} has not generated a mindmap yet."

        # Convert mindmap data to text format
        def mindmap_to_text(node, level=0):
            """Recursively convert mindmap JSON to hierarchical text"""
            indent = "  " * level
            text = f"{indent}- {node.get('content', '')}\n"
            for child in node.get("children", []):
                text += mindmap_to_text(child, level + 1)
            return text

        mindmap_text = f"Mindmap structure for knowledge base {target_info['name']}:\n\n"
        mindmap_text += mindmap_to_text(mindmap_data)

        return mindmap_text

    except Exception as e:
        logger.error(f"Failed to retrieve mindmap: {e}")
        return f"Failed to retrieve mindmap: {str(e)}"


class QueryKBInput(BaseModel):
    """Input model for knowledge base retrieval"""

    kb_name: str = Field(description="Knowledge base name for the target knowledge base")
    query_text: str = Field(
        description=(
            "Keywords for the query. When querying, use keywords that are likely to help answer the question, "
            "and do not query using the user's original input directly."
        )
    )
    file_name: str | None = Field(
        default=None,
        description=(
            "(Leave empty unless necessary) After reading the mindmap, you can specify file keywords with fuzzy matching.\n"
            "Use this only when the retrieval results are too many or irrelevant and need to be narrowed down further."
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
        from ta_backend_core.assistant.agents.backends.knowledge_base_backend import resolve_visible_knowledge_bases_for_context

        return await resolve_visible_knowledge_bases_for_context(context)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Failed to resolve visible knowledge bases for the session; skipping filepath injection: {exc}")
        return []


def _find_query_target(
    *,
    kb_name: str,
    retrievers: dict[str, Any],
    visible_kbs: list[dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None, str | None]:
    if visible_kbs:
        matched_kbs = [db for db in visible_kbs if str(db.get("name") or "").strip() == kb_name]
        if not matched_kbs:
            return None, None, f"Knowledge base '{kb_name}' does not exist or is not enabled in the current session"
        if len(matched_kbs) > 1:
            return None, None, f"Knowledge base '{kb_name}' has duplicate names; please rename and try again"

        target_db_id = str(matched_kbs[0].get("db_id") or "")
        target_info = retrievers.get(target_db_id)
        if target_info is None:
            return None, None, f"Knowledge base '{kb_name}' does not exist"
        return target_db_id, target_info, None

    for db_id, info in retrievers.items():
        if info["name"] == kb_name:
            return str(db_id), info, None

    return None, None, f"Knowledge base '{kb_name}' does not exist"


@tool(args_schema=QueryKBInput)
async def query_kb(kb_name: str, query_text: str, file_name: str | None = None, runtime: ToolRuntime = None) -> Any:
    """Query content within a specified knowledge base

    Use this tool when the user needs to query specific content.
    It retrieves relevant document chunks from the knowledge base based on keywords.

    Args:
        kb_name: Knowledge base name
        query_text: Query keywords
        file_name: Optional file name filter

    Returns:
        Retrieval results
    """
    if not kb_name:
        return "Please provide a knowledge base name"
    if not query_text:
        return "Please provide query text"

    # Get all retrievers
    retrievers = knowledge_base.get_retrievers()

    visible_kbs = await _resolve_visible_knowledge_bases_for_query(runtime)

    target_db_id, target_info, target_error = _find_query_target(
        kb_name=kb_name,
        retrievers=retrievers,
        visible_kbs=visible_kbs,
    )
    if target_error:
        return target_error

    metadata = target_info.get("metadata") if isinstance(target_info, dict) else None
    kb_type = str((metadata or {}).get("kb_type") or "").strip().lower()
    if kb_type != "milvus":
        return f"Knowledge base '{kb_name}' is not a Milvus type; the current query_kb only supports Milvus"

    try:
        retriever = target_info["retriever"]
        kwargs = {}
        if file_name:
            kwargs["file_name"] = file_name

        if inspect.iscoroutinefunction(retriever):
            result = await retriever(query_text, **kwargs)
        else:
            result = retriever(query_text, **kwargs)

        if not isinstance(result, list):
            return f"Knowledge base '{kb_name}' returned a result that is not a Milvus chunks list; the current query_kb only supports Milvus"

        from ta_backend_core.assistant.agents.backends.knowledge_base_backend import inject_filepaths_into_retrieval_result

        return await inject_filepaths_into_retrieval_result(
            retrieval_chunks=result,
            visible_kbs=visible_kbs,
            target_db_id=target_db_id,
            target_kb_name=kb_name,
        )

    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        return f"Retrieval failed: {str(e)}"


def get_common_kb_tools() -> list:
    """Get the list of common knowledge base tools

    Returns 3 common tools:
    - list_kbs: list knowledge bases accessible to the user
    - get_mindmap: get the mindmap for a specified knowledge base
    - query_kb: retrieve content from a specified knowledge base
    """
    return [list_kbs, get_mindmap, query_kb]
