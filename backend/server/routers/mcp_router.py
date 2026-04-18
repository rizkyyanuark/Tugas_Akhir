"""MCP server management routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from yunesa.services.mcp_service import (
    create_mcp_server,
    get_mcp_tools_stats,
    delete_mcp_server,
    get_all_mcp_servers,
    get_all_mcp_tools,
    get_mcp_server,
    set_server_enabled,
    toggle_tool_enabled,
    update_mcp_server,
)
from yunesa.storage.postgres.models_business import User
from yunesa.utils import logger
from server.utils.auth_middleware import get_admin_user, get_db

mcp = APIRouter(prefix="/system/mcp-servers", tags=["mcp"])


# =============================================================================
# === DTOs ===
# =============================================================================


class CreateMcpServerRequest(BaseModel):
    name: str = Field(..., description="servername")
    transport: str = Field(...,
                           description="Transport type: sse/streamable_http/stdio")
    url: str | None = Field(
        None, description="Server URL (sse/streamable_http)")
    command: str | None = Field(None, description="Command (stdio)")
    args: list | None = Field(
        None, description="Command argument array (stdio)")
    env: dict | None = Field(None, description="Environment variables (stdio)")
    description: str | None = Field(None, description="description")
    headers: dict | None = Field(None, description="HTTP request headers")
    timeout: int | None = Field(None, description="HTTP timeout (seconds)")
    sse_read_timeout: int | None = Field(
        None, description="SSE read timeout (seconds)")
    tags: list | None = Field(None, description="Tag array")
    icon: str | None = Field(None, description="Icon (emoji)")


class UpdateMcpServerRequest(BaseModel):
    transport: str | None = Field(None, description="Transport type")
    url: str | None = Field(None, description="server URL")
    command: str | None = Field(None, description="Command (stdio)")
    args: list | None = Field(
        None, description="Command argument array (stdio)")
    env: dict | None = Field(None, description="Environment variables (stdio)")
    description: str | None = Field(None, description="description")
    headers: dict | None = Field(None, description="HTTP request headers")
    timeout: int | None = Field(None, description="HTTP timeout (seconds)")
    sse_read_timeout: int | None = Field(
        None, description="SSE read timeout (seconds)")
    tags: list | None = Field(None, description="Tag array")
    icon: str | None = Field(None, description="Icon (emoji)")


class UpdateMcpServerStatusRequest(BaseModel):
    enabled: bool = Field(..., description="Whether enabled")


# =============================================================================
# === Helpers ===
# =============================================================================


async def get_server_or_404(db: AsyncSession, name: str):
    """Helper to get server or raise 404."""
    server = await get_mcp_server(db, name)
    if not server:
        raise HTTPException(
            status_code=404, detail=f"server '{name}' does not exist")
    return server


# =============================================================================
# === MCP server CRUD ===
# =============================================================================


@mcp.get("")
async def get_mcp_servers(
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all MCP server configurations."""
    try:
        servers = await get_all_mcp_servers(db)
        return {"success": True, "data": [s.to_dict() for s in servers]}
    except Exception as e:
        logger.error(f"Failed to get MCP servers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.post("")
async def create_mcp_server_route(
    request: CreateMcpServerRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new MCP server."""
    # Validate transport type.
    valid_transports = ("sse", "streamable_http", "stdio")
    if request.transport not in valid_transports:
        raise HTTPException(
            status_code=400, detail=f"Transport type must be one of: {', '.join(valid_transports)}")

    # Validate required fields by transport type.
    if request.transport in ("sse", "streamable_http") and not request.url:
        raise HTTPException(
            status_code=400, detail=f"URL is required when transport type is {request.transport}")
    if request.transport == "stdio" and not request.command:
        raise HTTPException(
            status_code=400, detail="Command is required when transport type is stdio")

    try:
        server = await create_mcp_server(
            db,
            name=request.name,
            transport=request.transport,
            url=request.url,
            command=request.command,
            args=request.args,
            env=request.env,
            description=request.description,
            headers=request.headers,
            timeout=request.timeout,
            sse_read_timeout=request.sse_read_timeout,
            tags=request.tags,
            icon=request.icon,
            created_by=current_user.username,
        )
        return {"success": True, "data": server.to_dict()}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.get("/{name}")
async def get_mcp_server_route(
    name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single MCP server configuration."""
    try:
        server = await get_server_or_404(db, name)
        return {"success": True, "data": server.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.put("/{name}")
async def update_mcp_server_route(
    name: str,
    request: UpdateMcpServerRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update MCP server configuration."""
    # Validate transport type.
    valid_transports = ("sse", "streamable_http", "stdio")
    if request.transport is not None and request.transport not in valid_transports:
        raise HTTPException(
            status_code=400, detail=f"Transport type must be one of: {', '.join(valid_transports)}")

    try:
        fields_set = getattr(request, "model_fields_set",
                             getattr(request, "__fields_set__", set()))
        update_kwargs = {}
        if "env" in fields_set:
            update_kwargs["env"] = request.env

        server = await update_mcp_server(
            db,
            name=name,
            description=request.description,
            transport=request.transport,
            url=request.url,
            command=request.command,
            args=request.args,
            headers=request.headers,
            timeout=request.timeout,
            sse_read_timeout=request.sse_read_timeout,
            tags=request.tags,
            icon=request.icon,
            updated_by=current_user.username,
            **update_kwargs,
        )
        return {"success": True, "data": server.to_dict()}
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to update MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.delete("/{name}")
async def delete_mcp_server_route(
    name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """delete MCP server"""
    try:
        # Check whether this is a built-in system server.
        server = await get_mcp_server(db, name)
        if server and server.created_by == "system":
            raise HTTPException(
                status_code=403, detail="Built-in system MCP servers cannot be deleted")

        deleted = await delete_mcp_server(db, name)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"server '{name}' does not exist")
        return {"success": True, "message": f"server '{name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# === MCP serveroperation ===
# =============================================================================


@mcp.post("/{name}/test")
async def test_mcp_server(
    name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Test MCP server connectivity."""
    try:
        await get_server_or_404(db, name)

        try:
            tools = await get_all_mcp_tools(name)
            return {
                "success": True,
                "message": f"Connection successful, found {len(tools)} tools",
                "tool_count": len(tools),
            }
        except Exception as test_error:
            raise HTTPException(
                status_code=500, detail=f"connection failed: {str(test_error)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to test MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.put("/{name}/status")
async def update_mcp_server_status_route(
    name: str,
    request: UpdateMcpServerStatusRequest,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Update MCP server enabled status."""
    try:
        is_enabled, server = await set_server_enabled(db, name, request.enabled, current_user.username)
        return {
            "success": True,
            "enabled": is_enabled,
            "data": server.to_dict(),
            "message": f"MCP '{name}' {'enabled' if is_enabled else 'disabled'}",
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to toggle MCP server: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# === MCP toolmanagement ===
# =============================================================================


@mcp.get("/{name}/tools")
async def get_mcp_server_tools(
    name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Get MCP server tool list."""
    try:
        server = await get_server_or_404(db, name)
        disabled_tools = server.disabled_tools or []

        try:
            # Get all tools (do not filter disabled tools).
            tools = await get_all_mcp_tools(name)
            tool_list = []

            for tool in tools:
                original_name = tool.name
                unique_id = tool.metadata.get(
                    "id") if tool.metadata else original_name

                tool_info = {
                    "name": original_name,
                    "id": unique_id,
                    "description": getattr(tool, "description", ""),
                    "enabled": original_name not in disabled_tools,
                }
                # Extract parameter metadata.
                if hasattr(tool, "args_schema") and tool.args_schema:
                    schema = tool.args_schema.schema() if hasattr(
                        tool.args_schema, "schema") else {}
                    tool_info["parameters"] = schema.get("properties", {})
                    tool_info["required"] = schema.get("required", [])
                else:
                    tool_info["parameters"] = {}
                    tool_info["required"] = []
                tool_list.append(tool_info)

            return {
                "success": True,
                "data": tool_list,
                "total": len(tool_list),
            }
        except Exception as tool_error:
            logger.error(
                f"Failed to get tools from MCP server '{name}': {tool_error}")
            raise HTTPException(
                status_code=500, detail=f"Failed to get tools: {str(tool_error)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get MCP server tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.post("/{name}/tools/refresh")
async def refresh_mcp_server_tools(
    name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Refresh MCP server tool list (clear cache and fetch again)."""
    try:
        await get_server_or_404(db, name)

        try:
            # Get all tools (do not filter disabled tools).
            tools = await get_all_mcp_tools(name)

            # Get tool statistics.
            stats = get_mcp_tools_stats(name)
            enabled_count = stats.get(
                "enabled", len(tools)) if stats else len(tools)
            disabled_count = stats.get("disabled", 0) if stats else 0

            message = "Tool list refreshed"
            if disabled_count > 0:
                message += f", {enabled_count} enabled, {disabled_count} disabled"
            else:
                message += f", found {enabled_count} tools"

            return {
                "success": True,
                "message": message,
                "tool_count": enabled_count,
                "enabled_count": enabled_count,
                "disabled_count": disabled_count,
            }
        except Exception as tool_error:
            raise HTTPException(
                status_code=500, detail=f"Refresh failed: {str(tool_error)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to refresh MCP server tools: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@mcp.put("/{name}/tools/{tool_name}/toggle")
async def toggle_mcp_server_tool_route(
    name: str,
    tool_name: str,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle enabled status of a single tool."""
    try:
        enabled, server = await toggle_tool_enabled(db, name, tool_name, current_user.username)
        return {
            "success": True,
            "tool_name": tool_name,
            "enabled": enabled,
            "message": f"Tool '{tool_name}' {'enabled' if enabled else 'disabled'}",
        }
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        logger.error(f"Failed to toggle MCP server tool: {e}")
        raise HTTPException(status_code=500, detail=str(e))
