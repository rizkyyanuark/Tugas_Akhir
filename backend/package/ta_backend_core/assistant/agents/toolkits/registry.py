from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ToolExtraMetadata:
    """Extra metadata (registered via decorator)"""

    category: str = ""  # Category: buildin, mysql, subagents, debug
    tags: list[str] = field(default_factory=list)
    display_name: str = ""  # Display name (human-readable)
    icon: str = ""
    config_guide: str = ""  # Configuration guide (pre-use setup hint)


# Global registry: tool_name -> ToolExtraMetadata
_extra_registry: dict[str, ToolExtraMetadata] = {}

# Global tool instance list (collected automatically by the @tool decorator)
_all_tool_instances: list = []


def get_extra_metadata(tool_name: str) -> ToolExtraMetadata | None:
    """Get extra metadata for a tool"""
    return _extra_registry.get(tool_name)


def get_all_extra_metadata() -> dict[str, ToolExtraMetadata]:
    """Get all extra metadata"""
    return _extra_registry.copy()


def get_all_tool_instances() -> list:
    """Get all tool instances (collected automatically by the @tool decorator)"""
    return _all_tool_instances


# Extended decorator built on top of langchain.tool
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
    """Extended decorator based on langchain.tool that also registers metadata

    Usage:
    @tool(category="buildin", tags=["math"], display_name="Calculator")
    def calculator(a: float, b: float, operation: str) -> float:
        ...

    Or keep the original name_or_callable and description:
    @tool(
        category="buildin",
        display_name="Query Knowledge Graph",
        name_or_callable="Query Knowledge Graph",
        description=KG_QUERY_DESCRIPTION,
    )
    def query_knowledge_graph(query: str) -> str:
        ...
    """
    from langchain.tools import tool as langchain_tool

    # Apply the langchain tool decorator first
    langchain_decorator = langchain_tool(
        name_or_callable=name_or_callable,
        description=description,
        args_schema=args_schema,
        return_direct=return_direct,
    )

    def decorator(func: Callable) -> Callable:
        # Apply the langchain decorator
        tool_obj = langchain_decorator(func)

        # Register extra metadata
        tool_name = tool_obj.name
        _extra_registry[tool_name] = ToolExtraMetadata(
            category=category,
            tags=tags or [],
            display_name=display_name,
            icon=icon,
            config_guide=config_guide,
        )

        # Collect tool instances automatically
        _all_tool_instances.append(tool_obj)

        return tool_obj

    return decorator
