"""Define the configurable parameters for the agent."""

import uuid
from dataclasses import MISSING, dataclass, field, fields
from typing import Annotated, get_args, get_origin

from yunesa import config as sys_config


@dataclass(kw_only=True)
class BaseContext:
    """
    Define a base Context for various graphs to inherit from.

    Configuration priority:
    1. Runtime configuration (RunnableConfig): Highest priority, passed directly from function parameters.
    2. Class default configuration: Lowest priority, default values defined in the class.
    """

    def update(self, data: dict):
        """Update configuration fields"""
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
        metadata={"name": "System prompt", "description": "Used to describe the agent's role and behavior"},
    )

    model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default=sys_config.default_model,
        metadata={
            "name": "Agent model",
            "options": [],
            "description": "Driving model for the agent. It is recommended to choose a model with strong Agent capabilities; small parameter models are not recommended.",
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
            "description": "Knowledge base list, you can create a knowledge base in the left knowledge base page.",
            "type": "list",  # Explicitly mark as list type for frontend if needed
        },
    )

    mcps: Annotated[list[str], {"__template_metadata__": {"kind": "mcps"}}] = field(
        default_factory=list,
        metadata={
            "name": "MCP Servers",
            "options": [],
            "description": (
                "MCP server list. It is recommended to use an MCP server that supports SSE. "
                "If you need to use a server running via uvx or npx, please start the MCP server outside the project and configure it in the project."
            ),
        },
    )

    skills: Annotated[list[str], {"__template_metadata__": {"kind": "skills"}}] = field(
        default_factory=list,
        metadata={
            "name": "Skills",
            "options": [],
            "description": "Optional skill list (maintained by super admin). At runtime, only the selected "
            "skills are mounted as read-only. Dependent tools and MCP servers will also be automatically mounted.",
            "type": "list",
        },
    )

    subagents_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default=sys_config.default_model,
        metadata={
            "name": "Subagent default model",
            "description": "Set default model for all subagents, which can be individually overridden in each Subagent Configuration.",
        },
    )

    subagents: Annotated[list[str], {"__template_metadata__": {"kind": "subagents"}}] = field(
        default_factory=list,
        metadata={
            "name": "Subagents",
            "options": [],
            "description": "Optional subagent list. Empty indicates no SubAgents are enabled, but a general-purpose subagent will still be enabled.",
            "type": "list",
        },
    )

    summary_threshold: int = field(
        default=100,
        metadata={
            "name": "Context summary trigger threshold (KB)",
            "description": "When context size exceeds this value, enable summary feature to optimize context usage. Unit is KB, default is 100KB.",
            "type": "number",
        },
    )

    @classmethod
    def get_configurable_items(cls):
        """Return a list of configurable parameters to be used for UI configuration"""
        configurable_items = {}
        for f in fields(cls):
            if f.init and not f.metadata.get("hide", False):
                if f.metadata.get("configurable", True):
                    # Process type information
                    field_type = f.type
                    type_name = cls._get_type_name(field_type)

                    # Extract metadata from Annotated
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
                        "template_metadata": template_metadata,  # Additional metadata from Annotated
                    }

        return configurable_items

    @classmethod
    def _get_type_name(cls, field_type) -> str:
        """Get type name, resolve Annotated type"""
        # Check if it is an Annotated type
        if get_origin(field_type) is not None:
            # Handle generic types like list[str], Annotated[str, {...}]
            origin = get_origin(field_type)
            if hasattr(origin, "__name__"):
                if origin.__name__ == "Annotated":
                    # For Annotated type, get the actual type
                    args = get_args(field_type)
                    if args:
                        return cls._get_type_name(args[0])  # Recursively process the actual type
                return origin.__name__
            else:
                return str(origin)
        elif hasattr(field_type, "__name__"):
            return field_type.__name__
        else:
            return str(field_type)

    @classmethod
    def _extract_template_metadata(cls, field_type) -> dict:
        """Extract template metadata from Annotated type"""
        if get_origin(field_type) is not None:
            origin = get_origin(field_type)
            if hasattr(origin, "__name__") and origin.__name__ == "Annotated":
                args = get_args(field_type)
                if len(args) > 1:
                    # Look for dictionaries containing __template_metadata__
                    for metadata in args[1:]:
                        if isinstance(metadata, dict) and "__template_metadata__" in metadata:
                            return metadata["__template_metadata__"]
        return {}

    def update_from_dict(self, data: dict):
        """Update configuration fields from a dictionary"""
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
