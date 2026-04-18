from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from yunesa.agents.toolkits.mysql import get_mysql_tools
from yunesa.agents.toolkits.utils import get_tool_info


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
        description="指导generate科研report、row业调研和其他需要深度分析的结构化长report。",
        version="2026.03.28",
        tool_dependencies=["tavily_search"],
    ),
    BuiltinSkillSpec(
        slug="reporter",
        source_dir=_SKILLS_ROOT / "reporter",
        description="generate SQL query报table并generate可视化图table。",
        version="2026.03.28",
        tool_dependencies=[t["name"] for t in get_tool_info(get_mysql_tools())],
        mcp_dependencies=("mcp-server-chart",),
    ),
]
