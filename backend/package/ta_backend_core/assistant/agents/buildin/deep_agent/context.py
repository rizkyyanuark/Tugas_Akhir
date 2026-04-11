"""Deep Agent Context - deep analysis context configuration based on BaseContext"""

from dataclasses import dataclass, field
from typing import Annotated

from ta_backend_core.assistant.agents import BaseContext

from .prompt import DEEP_PROMPT


@dataclass
class DeepContext(BaseContext):
    """
    Deep Agent context configuration, inheriting from BaseContext.
    Specifically used to manage configuration for deep analysis tasks.
    """

    # System prompt for deep analysis tasks
    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default=DEEP_PROMPT,
        metadata={"name": "System Prompt", "description": "Guidance for the Deep agent's role and behavior"},
    )

    subagents_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="siliconflow/Pro/deepseek-ai/DeepSeek-V3.2",
        metadata={
            "name": "Sub-agent Model",
            "description": "Default model for subagents, overridden by each subagent's own configuration.",
        },
    )
