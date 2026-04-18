"""Deep Agent Context - 基于BaseContext的深度分析上下文configure"""

from dataclasses import dataclass, field
from typing import Annotated

from yunesa.agents import BaseContext

from .prompt import DEEP_PROMPT


@dataclass
class DeepContext(BaseContext):
    """
    Deep Agent 的上下文configure，继承自 BaseContext
    专门用于深度分析task的configuremanagement
    """

    # 深度分析专用的systemprompt词
    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default=DEEP_PROMPT,
        metadata={"name": "systemprompt词", "description": "Deepagent的role和row为指导"},
    )

    subagents_model: Annotated[str, {"__template_metadata__": {"kind": "llm"}}] = field(
        default="siliconflow/Pro/deepseek-ai/DeepSeek-V3.2",
        metadata={
            "name": "Sub-agent Model",
            "description": "子agent的defaultmodel，会被子agent的configure覆盖。",
        },
    )
