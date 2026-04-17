"""Deep Agent module.

A deep analysis agent built on top of the deepagents library, with:
- Task planning and decomposition
- In-depth knowledge search and analysis
- Sub-agent collaboration
- Filesystem and long-term memory usage
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
__author__ = "Yunesa Team"
__description__ = "Deep analysis agent based on create_deep_agent"
