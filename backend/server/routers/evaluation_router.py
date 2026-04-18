import traceback

from fastapi import APIRouter, HTTPException, Depends, File, Form, Body, UploadFile
from fastapi.responses import FileResponse
from yunesa.storage.postgres.models_business import User
from server.utils.auth_middleware import get_admin_user
from yunesa.utils import logger

# Create router.
evaluation = APIRouter(prefix="/evaluation", tags=["evaluation"])


# Remove old detail endpoint and unify on db_id-based endpoints.
# ============================================================================
# evaluationbenchmark
# ============================================================================


@evaluation.get("/databases/{db_id}/benchmarks/{benchmark_id}")
async def get_evaluation_benchmark_by_db(
    db_id: str, benchmark_id: str, page: int = 1, page_size: int = 10, current_user: User = Depends(get_admin_user)
):
    """Get benchmark details by db_id (supports pagination)."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        # Validate pagination parameters.
        if page < 1:
            raise HTTPException(
                status_code=400, detail="Page number must be greater than 0")
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400, detail="Page size must be between 1 and 100")

        service = EvaluationService()
        benchmark = await service.get_benchmark_detail_by_db(db_id, benchmark_id, page, page_size)
        return {"message": "success", "data": benchmark}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to get evaluation benchmark details: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get evaluation benchmark details: {str(e)}")


@evaluation.delete("/benchmarks/{benchmark_id}")
async def delete_evaluation_benchmark(benchmark_id: str, current_user: User = Depends(get_admin_user)):
    """Delete evaluation benchmark."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        await service.delete_benchmark(benchmark_id)
        return {"message": "success", "data": None}
    except Exception as e:
        logger.error(
            f"Failed to delete evaluation benchmark: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete evaluation benchmark: {str(e)}")


@evaluation.get("/benchmarks/{benchmark_id}/download")
async def download_evaluation_benchmark(benchmark_id: str, current_user: User = Depends(get_admin_user)):
    """Download evaluation benchmark file."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        download_info = await service.get_benchmark_download_info(benchmark_id)
        return FileResponse(
            path=download_info["file_path"],
            filename=download_info["filename"],
            media_type="application/x-ndjson",
        )
    except ValueError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        logger.error(
            f"Failed to download evaluation benchmark: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to download evaluation benchmark: {str(e)}")
    except Exception as e:
        logger.error(
            f"Failed to download evaluation benchmark: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to download evaluation benchmark: {str(e)}")


@evaluation.get("/databases/{db_id}/results/{task_id}")
async def get_evaluation_results_by_db(
    db_id: str,
    task_id: str,
    page: int = 1,
    page_size: int = 20,
    error_only: bool = False,
    current_user: User = Depends(get_admin_user),
):
    """Get evaluation results (db_id-based, supports pagination)."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        # Validate pagination parameters.
        if page < 1:
            raise HTTPException(
                status_code=400, detail="Page number must be greater than 0")
        if page_size < 1 or page_size > 100:
            raise HTTPException(
                status_code=400, detail="Page size must be between 1 and 100")

        service = EvaluationService()
        results = await service.get_evaluation_results_by_db(
            db_id, task_id, page=page, page_size=page_size, error_only=error_only
        )
        return {"message": "success", "data": results}
    except Exception as e:
        logger.error(
            f"Failed to get evaluation results: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get evaluation results: {str(e)}")


@evaluation.delete("/databases/{db_id}/results/{task_id}")
async def delete_evaluation_result_by_db(db_id: str, task_id: str, current_user: User = Depends(get_admin_user)):
    """Delete evaluation result by db_id."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        await service.delete_evaluation_result_by_db(db_id, task_id)
        return {"message": "success", "data": None}
    except Exception as e:
        logger.error(
            f"Failed to delete evaluation result: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete evaluation result: {str(e)}")


# ============================================================================
# RAG Evaluation
# ============================================================================


@evaluation.post("/databases/{db_id}/benchmarks/upload")
async def upload_evaluation_benchmark(
    db_id: str,
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    current_user: User = Depends(get_admin_user),
):
    """Upload evaluation benchmark file."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        # Validate file format.
        if not file.filename.endswith(".jsonl"):
            raise HTTPException(
                status_code=400, detail="Only JSONL files are supported")

        # Read file content.
        content = await file.read()

        # Call evaluation service to process upload.
        service = EvaluationService()
        result = await service.upload_benchmark(
            db_id=db_id,
            file_content=content,
            filename=file.filename,
            name=name,
            description=description,
            created_by=current_user.user_id,
        )

        return {"message": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to upload evaluation benchmark: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to upload evaluation benchmark: {str(e)}")


@evaluation.get("/databases/{db_id}/benchmarks")
async def get_evaluation_benchmarks(db_id: str, current_user: User = Depends(get_admin_user)):
    """Get evaluation benchmark list for a knowledge base."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        benchmarks = await service.get_benchmarks(db_id)
        return {"message": "success", "data": benchmarks}
    except Exception as e:
        logger.error(
            f"Failed to get evaluation benchmark list: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get evaluation benchmark list: {str(e)}")


@evaluation.post("/databases/{db_id}/benchmarks/generate")
async def generate_evaluation_benchmark(
    db_id: str, params: dict = Body(...), current_user: User = Depends(get_admin_user)
):
    """Automatically generate evaluation benchmark."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        result = await service.generate_benchmark(db_id=db_id, params=params, created_by=current_user.user_id)
        return {"message": "success", "data": result}
    except Exception as e:
        logger.error(
            f"Failed to generate evaluation benchmark: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to generate evaluation benchmark: {str(e)}")


@evaluation.post("/databases/{db_id}/run")
async def run_evaluation(db_id: str, params: dict = Body(...), current_user: User = Depends(get_admin_user)):
    """Run RAG evaluation."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        task_id = await service.run_evaluation(
            db_id=db_id,
            benchmark_id=params.get("benchmark_id"),
            model_config=params.get("model_config", {}),
            created_by=current_user.user_id,
        )
        return {"message": "success", "data": {"task_id": task_id}}
    except Exception as e:
        logger.error(
            f"Failed to start evaluation: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to start evaluation: {str(e)}")


@evaluation.get("/databases/{db_id}/history")
async def get_evaluation_history(db_id: str, current_user: User = Depends(get_admin_user)):
    """Get evaluation history for a knowledge base."""
    from yunesa.services.evaluation_service import EvaluationService

    try:
        service = EvaluationService()
        history = await service.get_evaluation_history(db_id)
        return {"message": "success", "data": history}
    except Exception as e:
        logger.error(
            f"Failed to get evaluation history: {e}, {traceback.format_exc()}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get evaluation history: {str(e)}")
