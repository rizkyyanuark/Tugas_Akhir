"""
Mindmap route module.

Provides APIs related to mindmaps, including:
- Get knowledge base file lists
- AI-generated mindmaps
- Save and load mindmap configuration
"""

import json
import traceback
import textwrap

from fastapi import APIRouter, Body, Depends, HTTPException

from yunesa.storage.postgres.models_business import User
from server.utils.auth_middleware import get_admin_user
from yunesa import knowledge_base
from yunesa.models import select_model
from yunesa.utils import logger

mindmap = APIRouter(prefix="/mindmap", tags=["mindmap"])


# =============================================================================
# === Get Knowledge Base File List ===
# =============================================================================
MINDMAP_SYSTEM_PROMPT = """You are a professional knowledge organization assistant.

Your task is to analyze the user-provided file list and generate a mindmap with a clear hierarchy.

**Core rule: each filename can appear only once. No duplicates allowed.**

Requirements:
1. The mindmap should have a clear hierarchy (2-4 levels).
2. The root node should be the knowledge base name.
3. The first level should be major categories (e.g., technical documents, policies, data resources).
4. The second level should be subcategories.
5. **Leaf nodes must be specific filenames.**
6. **Each filename can appear only once in the whole mindmap.**
7. If a file can belong to multiple categories, place it in the single best category.
8. Use suitable emoji icons to improve readability.
9. Return JSON format following this structure:

```json
{
  "content": "knowledge basename",
  "children": [
    {
            "content": "🎯 Main Category 1",
      "children": [
        {
                    "content": "Subcategory 1.1",
          "children": [
                        {"content": "filename1.txt", "children": []},
                        {"content": "filename2.pdf", "children": []}
          ]
        }
      ]
    },
    {
            "content": "💻 Main Category 2",
      "children": [
                {"content": "filename3.docx", "children": []},
                {"content": "filename4.md", "children": []}
      ]
    }
  ]
}
```

**Important constraints:**
- Each filename may appear only once in the JSON.
- Do not classify by multiple dimensions in a way that duplicates files.
- Choose the most important and appropriate classification dimension.
- Each leaf node must have an empty children array: [].
- Category names should be concise and clear.
- Use emojis to improve visual clarity.
"""


@mindmap.get("/databases/{db_id}/files")
async def get_database_files(db_id: str, current_user: User = Depends(get_admin_user)):
    """
    Get all files from a specified knowledge base.

    Args:
        db_id: Knowledge base ID.

    Returns:
        File list information.
    """
    try:
        # Get detailed knowledge base info.
        db_info = await knowledge_base.get_database_info(db_id)

        if not db_info:
            raise HTTPException(
                status_code=404, detail=f"knowledge base {db_id} does not exist")

        # Extract file info.
        files = db_info.get("files", {})

        # Convert to list format.
        file_list = []
        for file_id, file_info in files.items():
            file_list.append(
                {
                    "file_id": file_id,
                    "filename": file_info.get("filename", ""),
                    "type": file_info.get("type", ""),
                    "status": file_info.get("status", ""),
                    "created_at": file_info.get("created_at", ""),
                }
            )

        return {
            "message": "success",
            "db_id": db_id,
            "db_name": db_info.get("name", ""),
            "files": file_list,
            "total": len(file_list),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get knowledge base file list: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get file list: {str(e)}")


# =============================================================================
# === AI Generate Mindmap ===
# =============================================================================


@mindmap.post("/generate")
async def generate_mindmap(
    db_id: str = Body(..., description="knowledge baseID"),
    file_ids: list[str] = Body(
        default=[], description="Selected file ID list"),
    user_prompt: str = Body(default="", description="User custom prompt"),
    current_user: User = Depends(get_admin_user),
):
    """
    Use AI to analyze knowledge base files and generate a mindmap structure.

    Args:
        db_id: Knowledge base ID.
        file_ids: Selected file ID list (uses all files if empty).
        user_prompt: User custom prompt.

    Returns:
        Mindmap data in Markmap-compatible format.
    """
    try:
        # Get knowledge base info.
        db_info = await knowledge_base.get_database_info(db_id)

        if not db_info:
            raise HTTPException(
                status_code=404, detail=f"knowledge base {db_id} does not exist")

        db_name = db_info.get("name", "knowledge base")
        all_files = db_info.get("files", {})

        # If no specific files are provided, use all files.
        if not file_ids:
            file_ids = list(all_files.keys())

        if not file_ids:
            raise HTTPException(
                status_code=400, detail="No files found in knowledge base")

        # Limit file count to 20; if exceeded, keep the first 20.
        if len(file_ids) > 20:
            original_count = len(file_ids)
            file_ids = file_ids[:20]
            logger.info(
                f"File count exceeded limit, selected first 20 from {original_count} files")

        # Collect file info.
        files_info = []
        for file_id in file_ids:
            if file_id in all_files:
                file_info = all_files[file_id]
                files_info.append(
                    {
                        "filename": file_info.get("filename", ""),
                        "type": file_info.get("type", ""),
                    }
                )

        if not files_info:
            raise HTTPException(
                status_code=400, detail="Selected files do not exist")

        # Build AI prompt.
        system_prompt = MINDMAP_SYSTEM_PROMPT

        # Build user message.
        files_text = "\n".join(
            [f"- {f['filename']} ({f['type']})" for f in files_info])

        user_message = textwrap.dedent(f"""Please generate a mindmap structure for knowledge base "{db_name}".

            File list (total {len(files_info)} files):
            {files_text}

            {f"User additional notes: {user_prompt}" if user_prompt else ""}

            **Important reminders:**
            1. This knowledge base contains {len(files_info)} files.
            2. Each filename may appear only once in the mindmap.
            3. Do not place the same file under multiple categories.
            4. Choose the most suitable unique category for each file.

            Please generate a reasonable mindmap structure.""")

        # Call AI to generate.
        logger.info(
            f"Start generating mindmap, knowledge base: {db_name}, file count: {len(files_info)}")

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

            mindmap_data = json.loads(content)

            # Validate structure.
            if not isinstance(mindmap_data, dict) or "content" not in mindmap_data:
                raise ValueError("Invalid mindmap structure")

            logger.info("Mindmap generated successfully")

            # Save mindmap to knowledge base metadata.
            try:
                from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

                await KnowledgeBaseRepository().update(db_id, {"mindmap": mindmap_data})
                logger.info(f"Mindmap saved to knowledge base: {db_id}")
            except Exception as save_error:
                logger.error(f"Failed to save mindmap: {save_error}")
                # Do not affect return result; only log the error.

            return {
                "message": "success",
                "mindmap": mindmap_data,
                "db_id": db_id,
                "db_name": db_name,
                "file_count": len(files_info),
                "original_file_count": original_count if "original_count" in locals() else len(files_info),
                "truncated": len(files_info) < (original_count if "original_count" in locals() else len(files_info)),
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
            f"Failed to generate mindmap: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate mindmap: {str(e)}")


# =============================================================================
# === Get All Knowledge Base Overviews (for selection) ===
# =============================================================================


@mindmap.get("/databases")
async def get_databases_overview(current_user: User = Depends(get_admin_user)):
    """
    Get overview info for all knowledge bases for mindmap selection
    (filtered by user permission).

    Returns:
        Knowledge base list.
    """
    try:
        databases = await knowledge_base.get_databases_by_user_id(current_user.user_id)

        # databases["databases"] is a list; each element already includes basic info.
        db_list_raw = databases.get("databases", [])

        db_list = []
        for db_info in db_list_raw:
            db_id = db_info.get("db_id")
            if not db_id:
                continue

            # Get detailed info to obtain file count.
            detail_info = await knowledge_base.get_database_info(db_id)
            file_count = len(detail_info.get("files", {})
                             ) if detail_info else 0

            db_list.append(
                {
                    "db_id": db_id,
                    "name": db_info.get("name", ""),
                    "description": db_info.get("description", ""),
                    "kb_type": db_info.get("kb_type", ""),
                    "file_count": file_count,
                }
            )

        return {
            "message": "success",
            "databases": db_list,
            "total": len(db_list),
        }

    except Exception as e:
        logger.error(
            f"Failed to get knowledge base list: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get knowledge base list: {str(e)}")


# =============================================================================
# === Knowledge Base Associated Mindmap Management ===
# =============================================================================


@mindmap.get("/database/{db_id}")
async def get_database_mindmap(db_id: str, current_user: User = Depends(get_admin_user)):
    """
    Get the mindmap associated with a knowledge base.

    Args:
        db_id: Knowledge base ID.

    Returns:
        Mindmap data.
    """
    try:
        from yunesa.repositories.knowledge_base_repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository()
        kb = await kb_repo.get_by_id(db_id)

        if kb is None:
            raise HTTPException(
                status_code=404, detail=f"knowledge base {db_id} does not exist")

        return {
            "message": "success",
            "mindmap": kb.mindmap,
            "db_id": db_id,
            "db_name": kb.name,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get knowledge base mindmap: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get mindmap: {str(e)}")
