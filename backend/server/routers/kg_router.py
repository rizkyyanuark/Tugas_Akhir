from fastapi import APIRouter, Body, Depends, HTTPException, Request
from server.utils.auth_middleware import get_superadmin_user
from yunesa.services.task_service import tasker
from yunesa.storage.postgres.models_business import User
from yunesa.utils.logging_config import logger

kg_router = APIRouter(prefix="/graph/kg", tags=["kg"])


@kg_router.post("/build")
async def build_knowledge_graph(
    request: Request,
    data: dict = Body(default={}),
    _current_user: User = Depends(get_superadmin_user),
):
    """
    Trigger the full KG construction pipeline (Northern Standard).
    This processes documents from the knowledge repository and constructs a Neo4j + Milvus KG.
    """
    kg_service = request.app.state.kg_service

    test_mode = data.get("test_mode", False)
    max_papers = data.get("max_papers")
    clear_db = data.get("clear_db", True)
    llm_model_spec = (data.get("llm_model_spec") or "").strip() or None

    logger.info(
        "🚀 Northern KG Build triggered "
        f"(test_mode={test_mode}, max_papers={max_papers}, llm_model_spec={llm_model_spec})"
    )

    result = await kg_service.start_build(
        test_mode=test_mode,
        max_papers=max_papers,
        clear_db=clear_db,
        llm_model_spec=llm_model_spec,
    )

    if "error" in result:
        raise HTTPException(status_code=409, detail=result["error"])

    return {"success": True, **result}


@kg_router.get("/status")
async def get_kg_build_status(
    request: Request,
    _current_user: User = Depends(get_superadmin_user),
):
    """Get the current real-time status of the KG build process."""
    kg_service = request.app.state.kg_service
    status = kg_service.get_status()

    # Also fetch recent tasks from tasker for history
    try:
        history = await tasker.list_tasks(limit=10)
        kg_history = [t for t in history.get(
            "tasks", []) if t.get("name") == "kg_build"]
    except Exception as e:
        logger.warning(f"Failed to fetch task history: {e}")
        kg_history = []

    return {
        "success": True,
        "data": {
            "current": status,
            "history": kg_history
        }
    }


@kg_router.post("/stop")
async def stop_kg_build(
    request: Request,
    _current_user: User = Depends(get_superadmin_user),
):
    """Stop the current KG build process."""
    kg_service = request.app.state.kg_service
    result = await kg_service.stop_build()
    return {"success": True, **result}
