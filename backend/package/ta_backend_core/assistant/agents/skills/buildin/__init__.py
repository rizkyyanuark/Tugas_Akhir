from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ta_backend_core.assistant.agents.toolkits.mysql import get_mysql_tools
from ta_backend_core.assistant.agents.toolkits.utils import get_tool_info


@dataclass(frozen=True)
class BuiltinSkillSpec:
    slug: str
    source_dir: Path
    description: str = ""
    version: str = "1.0.0"
    tool_dependencies: tuple[str, ...] = ()
    mcp_dependencies: tuple[str, ...] = ()
    skill_dependencies: tuple[str, ...] = ()


_SKILLS_ROOT = Path(__file__).resolve().parent

BUILTIN_SKILLS: list[BuiltinSkillSpec] = [
    BuiltinSkillSpec(
        slug="deep-reporter",
        source_dir=_SKILLS_ROOT / "deep-reporter",
        description="Guides the generation of research reports, industry research, and other structured long-form reports that require deep analysis.",
        version="2026.03.28",
        tool_dependencies=["tavily_search"],
    ),
    BuiltinSkillSpec(
        slug="reporter",
        source_dir=_SKILLS_ROOT / "reporter",
        description="Generate SQL query reports and create visual charts.",
        version="2026.03.28",
        tool_dependencies=[t["name"] for t in get_tool_info(get_mysql_tools())],
        mcp_dependencies=("mcp-server-chart",),
    ),
]
