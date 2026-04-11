"""Define the configurable parameters for the agent."""

import uuid
from dataclasses import MISSING, dataclass, field, fields
from typing import Annotated, get_args, get_origin

from ta_backend_core.assistant import config as sys_config


@dataclass(kw_only=True)
class BaseContext:
    """
    Define a base Context for all graph implementations to inherit from.

    Configuration precedence:
    1. Runtime config (RunnableConfig): highest priority, passed directly from function arguments
    2. Class default config: lowest priority, default values defined on the class
    """

    def update(self, data: dict):
        """Update configuration fields."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    thread_id: str = field(
        default_factory=lambda: str(uuid.uuid4()),
        metadata={"name": "Thread ID", "configurable": False, "description": "Used to uniquely identify a conversation thread"},
    )

    user_id: str = field(
        default_factory=lambda: str(uuid.uuid4()),
        metadata={"name": "User ID", "configurable": False, "description": "Used to uniquely identify a user"},
    )

    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default="You are a helpful assistant.",
        metadata={"name": "System Prompt", "description": "Used to describe the agent's role and behavior"},
    )

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default=sys_config.default_model,
        metadata={
            "name": "Agent Model",
            "options": [],
            "description": "The model that powers the agent. Choose a model with strong agent capabilities; small parameter models are not recommended.",
        },
    )

    tools: Annotated[list[str], {"__template_metadata__": {"kind": "tools"}}] = field(
        default_factory=lambda: ["ask_user_question", "tavily_search"],
        metadata={
            "name": "Tools",
            "description": "Built-in tools.",
        },
    )

    knowledges: Annotated[list[str], {"__template_metadata__": {"kind": "knowledges"}}] = field(
        default_factory=list,
        metadata={
            "name": "Knowledge Bases",
            "description": "List of knowledge bases. You can create knowledge bases from the left-side knowledge base page.",
            "type": "list",  # Explicitly mark as list type for the frontend if needed
        },
    )

    mcps: Annotated[list[str], {"__template_metadata__": {"kind": "mcps"}}] = field(
        default_factory=list,
        metadata={
            "name": "MCP Servers",
            "options": [],
            "description": (
                "List of MCP servers. Prefer MCP servers that support SSE. "
                "If you need to use servers run with uvx or npx, start the MCP server outside the project and configure it in the project."
            ),
        },
    )

    skills: Annotated[list[str], {"__template_metadata__": {"kind": "skills"}}] = field(
        default_factory=list,
        metadata={
            "name": "Skills",
            "options": [],
            "description": "Optional skill list (maintained by the super admin). At runtime, only the selected skills are mounted and exposed read-only. The tools and MCP servers required by those skills are mounted automatically.",
            "type": "list",
        },
    )

    subagents_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default=sys_config.default_model,
        metadata={
            "name": "Default Subagent Model",
            "description": "Set a default model for all subagents; it can be overridden in each subagent's configuration.",
        },
    )

    subagents: Annotated[list[str], {"__template_metadata__": {"kind": "subagents"}}] = field(
        default_factory=list,
        metadata={
            "name": "Subagents",
            "options": [],
            "description": "Optional subagent list. An empty list means no SubAgent will be enabled, but a general-purpose subagent will still be enabled.",
            "type": "list",
        },
    )

    summary_threshold: int = field(
        default=100,
        metadata={
            "name": "Context Summary Threshold (KB)",
            "description": "When the context size exceeds this value, summary generation is enabled to optimize context usage. Unit: KB; default is 100 KB.",
            "type": "number",
        },
    )

    @classmethod
    def get_configurable_items(cls):
        """Build a list of configurable parameters for UI configuration."""
        configurable_items = {}
        for f in fields(cls):
            if f.init and not f.metadata.get("hide", False):
                if f.metadata.get("configurable", True):
                    # Process type information
                    field_type = f.type
                    type_name = cls._get_type_name(field_type)

                    # Extract Annotated metadata
                    template_metadata = cls._extract_template_metadata(field_type)

                    options = f.metadata.get("options", [])
                    if callable(options):
                        options = options()

                    configurable_items[f.name] = {
                        "type": f.metadata.get("type", type_name),
                        "name": f.metadata.get("name", f.name),
                        "options": options,
                        "default": f.default
                        if f.default is not MISSING
                        else f.default_factory()
                        if f.default_factory is not MISSING
                        else None,
                        "description": f.metadata.get("description", ""),
                        "template_metadata": template_metadata,  # Additional Annotated metadata
                    }

        return configurable_items

    @classmethod
    def _get_type_name(cls, field_type) -> str:
        """Get the type name, handling Annotated types."""
        # Check whether this is an Annotated type
        if get_origin(field_type) is not None:
            # Handle generic types such as list[str] and Annotated[str, {...}]
            origin = get_origin(field_type)
            if hasattr(origin, "__name__"):
                if origin.__name__ == "Annotated":
                    # For Annotated types, get the underlying type
                    args = get_args(field_type)
                    if args:
                        return cls._get_type_name(args[0])  # Recursively handle the underlying type
                return origin.__name__
            else:
                return str(origin)
        elif hasattr(field_type, "__name__"):
            return field_type.__name__
        else:
            return str(field_type)

    @classmethod
    def _extract_template_metadata(cls, field_type) -> dict:
        """Extract template metadata from an Annotated type."""
        if get_origin(field_type) is not None:
            origin = get_origin(field_type)
            if hasattr(origin, "__name__") and origin.__name__ == "Annotated":
                args = get_args(field_type)
                if len(args) > 1:
                    # Look for a dictionary containing __template_metadata__
                    for metadata in args[1:]:
                        if isinstance(metadata, dict) and "__template_metadata__" in metadata:
                            return metadata["__template_metadata__"]
        return {}

    def update_from_dict(self, data: dict):
        """Update configuration fields from a dictionary."""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
