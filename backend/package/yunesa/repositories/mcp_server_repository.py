"""MCP server data access layer - Repository."""

from typing import Any

from sqlalchemy import select

from yunesa.storage.postgres.manager import pg_manager
from yunesa.storage.postgres.models_business import MCPServer


class MCPServerRepository:
    """MCP server data access layer."""

    async def get_by_name(self, name: str) -> MCPServer | None:
        """Get MCP server by name."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).where(MCPServer.name == name))
            return result.scalar_one_or_none()

    async def list(self) -> list[MCPServer]:
        """Get all MCP servers."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer))
            return list(result.scalars().all())

    async def list_enabled(self) -> list[MCPServer]:
        """Get all enabled MCP servers."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).where(MCPServer.enabled == 1))
            return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> MCPServer:
        """Create MCP server."""
        async with pg_manager.get_async_session_context() as session:
            server = MCPServer(**data)
            session.add(server)
        return server

    async def update(self, name: str, data: dict[str, Any]) -> MCPServer | None:
        """Update MCP server."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).where(MCPServer.name == name))
            server = result.scalar_one_or_none()
            if server is None:
                return None
            for key, value in data.items():
                if key != "name":
                    setattr(server, key, value)
        return server

    async def delete(self, name: str) -> bool:
        """Delete MCP server."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).where(MCPServer.name == name))
            server = result.scalar_one_or_none()
            if server is None:
                return False
            await session.delete(server)
        return True

    async def upsert(self, data: dict[str, Any]) -> MCPServer:
        """Insert or update MCP server."""
        name = data.get("name")
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer).where(MCPServer.name == name))
            existing = result.scalar_one_or_none()
            if existing is None:
                server = MCPServer(**data)
                session.add(server)
            else:
                for key, value in data.items():
                    if key != "name":
                        setattr(existing, key, value)
                server = existing
        return server

    async def exists_by_name(self, name: str) -> bool:
        """Check whether MCP server exists by name."""
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(select(MCPServer.id).where(MCPServer.name == name))
            return result.scalar_one_or_none() is not None
