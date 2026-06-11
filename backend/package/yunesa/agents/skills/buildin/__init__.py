from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        description="Membantu menyusun laporan riset atau analisis panjang yang terstruktur dan berbasis sumber.",
        version="2026.03.28",
        tool_dependencies=["tavily_search"],
    ),
]
