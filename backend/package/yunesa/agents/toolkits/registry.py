from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ToolExtraMetadata:
    """Extra metadata registered via decorator."""

    category: str = ""  # Category: buildin, mysql, subagents, debug
    tags: list[str] = field(default_factory=list)
    display_name: str = ""  # Human-friendly display name
    icon: str = ""
    config_guide: str = ""  # Setup guide shown before tool usage


# Global registry: tool_name -> ToolExtraMetadata
_extra_registry: dict[str, ToolExtraMetadata] = {}

# Global tool instance list (automatically collected by @tool decorator)
_all_tool_instances: list = []


def get_extra_metadata(tool_name: str) -> ToolExtraMetadata | None:
    """Get extra metadata for a tool."""
    return _extra_registry.get(tool_name)


def get_all_extra_metadata() -> dict[str, ToolExtraMetadata]:
    """Get all extra metadata entries."""
    return _extra_registry.copy()


def get_all_tool_instances() -> list:
    """Get all tool instances collected by the @tool decorator."""
    return _all_tool_instances


# Extended decorator based on langchain.tool
def tool(
    category: str = "",
    tags: list[str] = None,
    display_name: str = "",
    icon: str = "",
    config_guide: str = "",
    name_or_callable: str | Callable | None = None,
    description: str | None = None,
    args_schema: type | None = None,
    return_direct: bool = False,
):
    """Extended decorator based on langchain.tool that also registers metadata.

    Usage:
    @tool(category="buildin", tags=["calculate"], display_name="Calculator")
    def calculator(a: float, b: float, operation: str) -> float:
        ...

    Or keep the original name_or_callable and description:
    @tool(
        category="buildin",
        display_name="queryknowledge graph",
        name_or_callable="queryknowledge graph",
        description=KG_QUERY_DESCRIPTION,
    )
    def query_knowledge_graph(query: str) -> str:
        ...
    """
    from langchain.tools import tool as langchain_tool

    # First apply the langchain tool decorator.
    langchain_decorator = langchain_tool(
        name_or_callable=name_or_callable,
        description=description,
        args_schema=args_schema,
        return_direct=return_direct,
    )

    def decorator(func: Callable) -> Callable:
        # Apply langchain decorator.
        tool_obj = langchain_decorator(func)

        # Register extra metadata.
        tool_name = tool_obj.name
        _extra_registry[tool_name] = ToolExtraMetadata(
            category=category,
            tags=tags or [],
            display_name=display_name,
            icon=icon,
            config_guide=config_guide,
        )

        # Automatically collect tool instance.
        _all_tool_instances.append(tool_obj)

        return tool_obj

    return decorator
