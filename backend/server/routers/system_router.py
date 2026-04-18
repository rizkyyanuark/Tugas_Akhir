import os
import aiofiles
from pathlib import Path

import yaml
from fastapi import APIRouter, Body, Depends, HTTPException

from yunesa.storage.postgres.models_business import User
from server.utils.auth_middleware import get_admin_user
from yunesa import config, get_version
from yunesa.models.chat import test_chat_model_status, test_all_chat_models_status
from yunesa.utils.logging_config import logger

system = APIRouter(prefix="/system", tags=["system"])

# =============================================================================
# === Health Check Group ===
# =============================================================================


@system.get("/health")
async def health_check():
    """System health check endpoint (public endpoint)."""
    return {"status": "ok", "message": "Service is running", "version": get_version()}


# =============================================================================
# === configuremanagementgroup ===
# =============================================================================


@system.get("/config")
async def get_config(current_user: User = Depends(get_admin_user)):
    """Get system configuration."""
    return config.dump_config()


@system.post("/config")
async def update_config_single(key=Body(...), value=Body(...), current_user: User = Depends(get_admin_user)) -> dict:
    """Update a single configuration item."""
    config[key] = value
    config.save()
    return config.dump_config()


@system.post("/config/update")
async def update_config_batch(items: dict = Body(...), current_user: User = Depends(get_admin_user)) -> dict:
    """Batch update configuration items."""
    config.update(items)
    config.save()
    return config.dump_config()


@system.get("/logs")
async def get_system_logs(levels: str | None = None, current_user: User = Depends(get_admin_user)):
    """Get system logs.

    Args:
        levels: Optional log level filter. Multiple levels can be comma-separated,
            e.g. "INFO,ERROR,DEBUG,WARNING".
    """
    try:
        from yunesa.utils.logging_config import LOG_FILE

        # Parse log level filter.
        level_filter = None
        if levels:
            level_filter = set(level.strip().upper()
                               for level in levels.split(",") if level.strip())

        async with aiofiles.open(LOG_FILE) as f:
            # Read the last 1000 lines.
            lines = []
            async for line in f:
                filtered_line = line.rstrip("\n\r")
                # If a level filter is specified, filter by level.
                if level_filter:
                    # Log format: 2025-03-10 08:26:37,269 - INFO - module - message
                    # Extract log level.
                    parts = filtered_line.split(" - ")
                    if len(parts) >= 2 and parts[1].strip() in level_filter:
                        lines.append(filtered_line + "\n")
                    # Keep reading to preserve line count behavior.
                    if len(lines) > 1000:
                        lines.pop(0)
                else:
                    lines.append(filtered_line + "\n")
                    if len(lines) > 1000:
                        lines.pop(0)

        log = "".join(lines)
        return {"log": log, "message": "success", "log_file": LOG_FILE}
    except Exception as e:
        logger.error(f"Failed to get system logs: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get system logs: {str(e)}")


# =============================================================================
# === Information Management Group ===
# =============================================================================


async def load_info_config():
    """Load information config file."""
    try:
        # Config file path.
        brand_file_path = os.environ.get(
            "TA_BRAND_FILE_PATH", "package/yunesa/config/static/info.local.yaml")
        config_path = Path(brand_file_path)

        # Check whether the file exists.
        if not config_path.exists():
            logger.debug(
                f"The config file {config_path} does not exist, using default config")
            config_path = Path(
                "package/yunesa/config/static/info.template.yaml")

        # Read config file asynchronously.
        async with aiofiles.open(config_path, encoding="utf-8") as file:
            content = await file.read()
            config = yaml.safe_load(content)

        return config

    except Exception as e:
        logger.error(f"Failed to load info config: {e}")
        return {}


@system.get("/info")
async def get_info_config():
    """Get system info configuration (public endpoint, no authentication required)."""
    try:
        config = await load_info_config()
        return {"success": True, "data": config}
    except Exception as e:
        logger.error(f"Failed to get info configuration: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to get info configuration")


@system.post("/info/reload")
async def reload_info_config(current_user: User = Depends(get_admin_user)):
    """Reload info configuration."""
    try:
        config = await load_info_config()
        return {"success": True, "message": "Configuration reloaded successfully", "data": config}
    except Exception as e:
        logger.error(f"Failed to reload info configuration: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to reload info configuration")


# =============================================================================
# === OCRservicegroup ===
# =============================================================================


@system.get("/ocr/health")
async def check_ocr_services_health(current_user: User = Depends(get_admin_user)):
    """
    Check health status of all OCR services.
    Returns availability information for each OCR service.
    """
    from yunesa.plugins.parser.factory import DocumentProcessorFactory

    try:
        # Use unified health check interface.
        health_status = await DocumentProcessorFactory.check_all_health_async()

        # Convert to legacy format for API compatibility.
        formatted_status = {}
        for service_name, health_info in health_status.items():
            formatted_status[service_name] = {
                "status": health_info.get("status", "unknown"),
                "message": health_info.get("message", ""),
                "details": health_info.get("details", {}),
            }

        # Calculate overall health status.
        overall_status = (
            "healthy" if any(
                svc["status"] == "healthy" for svc in formatted_status.values()) else "unhealthy"
        )

        return {
            "overall_status": overall_status,
            "services": formatted_status,
            "message": "OCR service health check completed",
        }

    except Exception as e:
        logger.error(f"OCR health check failed: {str(e)}")
        return {
            "overall_status": "error",
            "services": {},
            "message": f"OCR health check failed: {str(e)}",
        }


# =============================================================================
# === Chat Model Status Check Group ===
# =============================================================================


@system.get("/chat-models/status")
async def get_chat_model_status(provider: str, model_name: str, current_user: User = Depends(get_admin_user)):
    """Get status of a specific chat model."""
    logger.debug(f"Checking chat model status: {provider}/{model_name}")
    try:
        status = await test_chat_model_status(provider, model_name)
        return {"status": status, "message": "success"}
    except Exception as e:
        logger.error(
            f"Failed to get chat model status {provider}/{model_name}: {e}")
        return {
            "message": f"Failed to get chat model status: {e}",
            "status": {"provider": provider, "model_name": model_name, "status": "error", "message": str(e)},
        }


@system.get("/chat-models/all/status")
async def get_all_chat_models_status(current_user: User = Depends(get_admin_user)):
    """Get status of all chat models."""
    logger.debug("Checking all chat models status")
    try:
        status = await test_all_chat_models_status()
        return {"status": status, "message": "success"}
    except Exception as e:
        logger.error(f"Failed to get all chat model statuses: {e}")
        return {
            "message": f"Failed to get all chat model statuses: {e}",
            "status": {"models": {}, "total": 0, "available": 0},
        }


# =============================================================================
# === Custom Provider Management Group ===
# =============================================================================


@system.get("/custom-providers")
async def get_custom_providers(current_user: User = Depends(get_admin_user)):
    """Get all custom providers."""
    try:
        custom_providers = config.get_custom_providers()
        return {
            "providers": {provider: info.model_dump() for provider, info in custom_providers.items()},
            "message": "success",
        }
    except Exception as e:
        logger.error(f"Failed to get custom providers: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get custom providers: {str(e)}")


@system.post("/custom-providers")
async def add_custom_provider(
    provider_id: str = Body(..., description="Provider ID"),
    provider_data: dict = Body(..., description="Provider configuration data"),
    current_user: User = Depends(get_admin_user),
):
    """Add a custom provider."""
    try:
        success = config.add_custom_provider(provider_id, provider_data)
        if success:
            return {"message": f"Custom provider {provider_id} added successfully"}
        else:
            raise HTTPException(
                status_code=400, detail=f"Provider ID {provider_id} already exists, use another ID")
    except Exception as e:
        logger.error(f"Failed to add custom provider {provider_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to add custom provider: {str(e)}")


@system.put("/custom-providers/{provider_id}")
async def update_custom_provider(
    provider_id: str,
    provider_data: dict = Body(..., description="Provider configuration data"),
    current_user: User = Depends(get_admin_user),
):
    """Update a custom provider."""
    try:
        success = config.update_custom_provider(provider_id, provider_data)
        if success:
            return {"message": f"Custom provider {provider_id} updated successfully"}
        else:
            raise HTTPException(
                status_code=404, detail=f"Custom provider {provider_id} does not exist or update failed")
    except Exception as e:
        logger.error(f"Failed to update custom provider {provider_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to update custom provider: {str(e)}")


@system.delete("/custom-providers/{provider_id}")
async def delete_custom_provider(provider_id: str, current_user: User = Depends(get_admin_user)):
    """Delete a custom provider."""
    try:
        success = config.delete_custom_provider(provider_id)
        if success:
            return {"message": f"Custom provider {provider_id} deleted successfully"}
        else:
            raise HTTPException(
                status_code=404, detail=f"Custom provider {provider_id} does not exist or delete failed")
    except Exception as e:
        logger.error(f"Failed to delete custom provider {provider_id}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to delete custom provider: {str(e)}")


@system.post("/custom-providers/{provider_id}/test")
async def test_custom_provider(
    provider_id: str, request: dict = Body(..., description="testrequest"), current_user: User = Depends(get_admin_user)
):
    """Test custom provider connectivity."""
    try:
        # Get model_name from request.
        model_name = request.get("model_name")
        if not model_name:
            raise HTTPException(
                status_code=400, detail="Missing model_name parameter")

        # Check whether provider exists.
        if provider_id not in config.model_names:
            raise HTTPException(
                status_code=404, detail=f"Provider {provider_id} does not exist")

        # Test model status.
        status = await test_chat_model_status(provider_id, model_name)
        return {"status": status, "message": "Test completed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to test custom provider {provider_id}/{model_name}: {e}")
        return {
            "message": f"Failed to test custom provider: {e}",
            "status": {"provider": provider_id, "model_name": model_name, "status": "error", "message": str(e)},
        }
