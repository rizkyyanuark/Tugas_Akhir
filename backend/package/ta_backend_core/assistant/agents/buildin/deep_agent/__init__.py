"""Deep Agent - deep analysis agent module

Deep analysis agent built on the deepagents library with the following capabilities:
- Task planning and decomposition
- Deep knowledge search and analysis
- Subagent collaboration
- File system access and long-term memory
- Comprehensive analysis and report generation
"""

from .context import DeepContext
from .graph import DeepAgent

__all__ = [
    "DeepAgent",
    "DeepContext",
]

# Module metadata
__version__ = "1.0.0"
__author__ = "Yuxi Team"
__description__ = "Deep analysis agent based on create_deep_agent"
