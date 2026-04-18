from yunesa.utils import logger

# Tool metadata cache
_metadata_cache: list[dict] = []


def _extract_tool_info(tool_obj) -> dict:
    """Extract basic information from a tool object."""
    metadata = getattr(tool_obj, "metadata", {}) or {}
    info = {
        "id": tool_obj.name,
        # Prefer display name from metadata.
        "name": metadata.get("name", tool_obj.name),
        "description": tool_obj.description,
        "metadata": metadata,
        "args": [],
    }

    if hasattr(tool_obj, "args_schema") and tool_obj.args_schema:
        schema = tool_obj.args_schema
        if hasattr(schema, "schema"):
            schema = schema.schema()
        for arg_name, arg_info in schema.get("properties", {}).items():
            info["args"].append(
                {
                    "name": arg_name,
                    "type": arg_info.get("type", ""),
                    "description": arg_info.get("description", ""),
                }
            )
    return info


def _ensure_metadata_loaded():
    """Lazy-load tool metadata on first access."""
    global _metadata_cache

    if _metadata_cache:  # Already loaded.
        return

    from yunesa.agents.toolkits.registry import (
        get_all_extra_metadata,
        get_all_tool_instances,
    )

    # Get all tool instances.
    all_tools = get_all_tool_instances()
    extra_meta = get_all_extra_metadata()

    for tool in all_tools:
        tool_name = tool.name
        runtime_info = _extract_tool_info(tool)

        # Merge additional metadata.
        if tool_name in extra_meta:
            extra = extra_meta[tool_name]
            runtime_info["category"] = extra.category
            runtime_info["tags"] = extra.tags
            runtime_info["config_guide"] = extra.config_guide
            # display_name has higher priority than tool.name.
            if extra.display_name:
                runtime_info["name"] = extra.display_name
        else:
            # Not registered; use default category.
            runtime_info["category"] = "buildin"
            runtime_info["tags"] = []
            runtime_info["config_guide"] = ""

        _metadata_cache.append(runtime_info)

    logger.info(
        f"Tool service loaded {len(_metadata_cache)} tools (lazy load)")


def get_tool_metadata(category: str = None) -> list[dict]:
    """Get tool metadata list (lazy-loaded)."""
    _ensure_metadata_loaded()

    if category:
        return [t for t in _metadata_cache if t.get("category") == category]
    return _metadata_cache
