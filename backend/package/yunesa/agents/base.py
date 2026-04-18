from __future__ import annotations

import os
from abc import abstractmethod
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver, aiosqlite
from langgraph.graph.state import CompiledStateGraph

from yunesa import config as sys_config
from yunesa.agents.context import BaseContext
from yunesa.storage.postgres.manager import pg_manager
from yunesa.utils import logger


class BaseAgent:
    """
    Define a base Agent class for various graph implementations to inherit.
    """

    name = "base_agent"
    description = "base_agent"
    # Agent capability list, e.g. ["file_upload", "web_search"]
    capabilities: list[str] = []
    context_schema: type[BaseContext] = BaseContext  # Agent context schema

    def __init__(self, **kwargs):
        self.graph = None  # will be covered by get_graph
        self.checkpointer = None
        self._async_conn = None
        self.workdir = Path(sys_config.save_dir) / "agents" / self.module_name
        self.workdir.mkdir(parents=True, exist_ok=True)

    @property
    def module_name(self) -> str:
        """Get the module name of the agent class."""
        return self.__class__.__module__.split(".")[-2]

    @property
    def id(self) -> str:
        """Get the agent's class name."""
        return self.__class__.__name__

    async def get_info(self, include_configurable_items: bool = True):
        # Metadata is defined in code and provided by each agent class property.
        metadata = self.load_metadata()
        configurable_items = {}
        if include_configurable_items:
            configurable_items = self.context_schema.get_configurable_items()

        # Merge metadata with class attributes, metadata takes precedence
        return {
            "id": self.id,
            "name": getattr(self, "name", "Unknown"),
            "description": getattr(self, "description", "Unknown"),
            "metadata": metadata,
            "configurable_items": configurable_items,
            # Agent capability list
            "capabilities": getattr(self, "capabilities", []),
        }

    async def get_config(self):
        return self.context_schema()

    async def stream_values(self, messages: list[str], input_context=None, **kwargs):
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        for event in graph.astream({"messages": messages}, stream_mode="values", context=context):
            yield event["messages"]

    async def stream_messages(self, messages: list[str], input_context=None, **kwargs):
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        logger.debug(f"stream_messages: {context=}")

        # Build runtime config; LangGraph will automatically restore state from checkpointer.
        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 300,
        }

        # langfuse metadata and callbacks integration
        if callbacks := kwargs.get("callbacks"):
            input_config["callbacks"] = list(callbacks)
        if metadata := kwargs.get("metadata"):
            input_config["metadata"] = dict(metadata)
        if tags := kwargs.get("tags"):
            input_config["tags"] = list(tags)

        async for msg, metadata in graph.astream(
            {"messages": messages},
            stream_mode="messages",
            context=context,
            config=input_config,
        ):
            yield msg, metadata

    async def stream_messages_with_state(self, messages: list[str], input_context=None, **kwargs):
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        logger.debug(f"stream_messages_with_state: {context=}")

        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 300,
        }

        if callbacks := kwargs.get("callbacks"):
            input_config["callbacks"] = list(callbacks)
        if metadata := kwargs.get("metadata"):
            input_config["metadata"] = dict(metadata)
        if tags := kwargs.get("tags"):
            input_config["tags"] = list(tags)

        async for mode, payload in graph.astream(
            {"messages": messages},
            stream_mode=["messages", "values"],
            context=context,
            config=input_config,
        ):
            yield mode, payload

    async def invoke_messages(self, messages: list[str], input_context=None, **kwargs):
        context = self.context_schema()
        context.update_from_dict(input_context or {})
        graph = await self.get_graph(context=context)
        logger.debug(f"invoke_messages: {context}")

        # buildconfigure
        input_config = {
            "configurable": {"thread_id": context.thread_id, "user_id": context.user_id},
            "recursion_limit": 100,
        }

        # langfuse metadata and callbacks integration
        if callbacks := kwargs.get("callbacks"):
            input_config["callbacks"] = list(callbacks)
        if metadata := kwargs.get("metadata"):
            input_config["metadata"] = dict(metadata)
        if tags := kwargs.get("tags"):
            input_config["tags"] = list(tags)

        msg = await graph.ainvoke(
            {"messages": messages},
            context=context,
            config=input_config,
        )
        return msg

    async def check_checkpointer(self):
        app = await self.get_graph()
        if not hasattr(app, "checkpointer") or app.checkpointer is None:
            return False
        return True

    async def get_history(self, user_id, thread_id) -> list[dict]:
        """Get historical messages."""
        try:
            app = await self.get_graph()

            if not await self.check_checkpointer():
                return []

            config = {"configurable": {
                "thread_id": thread_id, "user_id": user_id}}
            state = await app.aget_state(config)

            result = []
            if state:
                messages = state.values.get("messages", [])
                for msg in messages:
                    if hasattr(msg, "model_dump"):
                        msg_dict = msg.model_dump()  # Convert to dictionary
                    else:
                        msg_dict = dict(msg) if hasattr(
                            msg, "__dict__") else {"content": str(msg)}
                    result.append(msg_dict)

            return result

        except Exception as e:
            logger.error(
                f"Failed to get message history for agent {self.name}: {e}")
            return []

    def reload_graph(self):
        """Reset graph cache and force rebuilding on the next get_graph call."""
        self.graph = None
        logger.info(
            f"{self.name} graph cache cleared; it will be rebuilt on the next call")

    @abstractmethod
    async def get_graph(self, **kwargs) -> CompiledStateGraph:
        """
        Get and compile the conversation graph instance.
        Ensure checkpointer is set during compilation; otherwise message history cannot be retrieved.
        For example: graph = workflow.compile(checkpointer=sqlite_checkpointer)
        """
        pass

    async def _get_checkpointer(self):
        if self.checkpointer is not None:
            return self.checkpointer

        checkpointer = None
        backend = os.getenv("LANGGRAPH_CHECKPOINTER_BACKEND",
                            "sqlite").strip().lower()

        if backend == "postgres":
            checkpointer = await self._create_postgres_checkpointer()

        if checkpointer is None:
            try:
                checkpointer = AsyncSqliteSaver(await self.get_async_conn())
            except Exception as e:
                logger.error(
                    f"Failed to build sqlite checkpointer: {e}, trying in-memory storage")
                checkpointer = InMemorySaver()

        self.checkpointer = checkpointer
        return self.checkpointer

    async def _create_postgres_checkpointer(self):
        postgres_url = os.getenv("POSTGRES_URL")
        if not postgres_url:
            logger.warning(
                "POSTGRES_URL is not configured; postgres checkpointer is disabled, falling back to sqlite")
            return None

        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # type: ignore
        except Exception as e:
            logger.warning(
                f"LangGraph postgres checkpointer unavailable, falling back to sqlite: {e}")
            return None

        try:
            saver = AsyncPostgresSaver(pg_manager.langgraph_pool)

            logger.info(f"{self.name} is using postgres checkpointer")
            return saver
        except Exception as e:
            logger.warning(
                f"Failed to initialize postgres checkpointer, falling back to sqlite: {e}")
            return None

    async def get_async_conn(self) -> aiosqlite.Connection:
        """Get asynchronous database connection."""
        if self._async_conn is not None:
            return self._async_conn

        conn = await aiosqlite.connect(os.path.join(self.workdir, "aio_history.db"))
        # Patch: langgraph's AsyncSqliteSaver expects is_alive() method which aiosqlite may not have
        if not hasattr(conn, "is_alive"):
            conn.is_alive = lambda: True
        self._async_conn = conn
        return self._async_conn

    async def get_aio_memory(self) -> AsyncSqliteSaver:
        """Get asynchronous storage instance."""
        return AsyncSqliteSaver(await self.get_async_conn())

    def load_metadata(self) -> dict:
        """Load metadata from agent class attribute."""
        metadata = getattr(self, "metadata", {})
        if isinstance(metadata, dict):
            return metadata
        logger.warning(
            f"Agent {self.module_name} metadata is not a dict, fallback to empty metadata")
        return {}
