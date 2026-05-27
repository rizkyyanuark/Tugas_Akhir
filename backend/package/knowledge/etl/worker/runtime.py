"""Runtime objects shared by ETL worker entrypoints and pipelines."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunConfig:
    """Run configuration passed to every task handler."""

    mode: str = "incremental"
    sample_size: int = 50
    prodi_filter: str | None = None

    @property
    def is_sample(self) -> bool:
        return self.mode == "sample"

    @property
    def is_full(self) -> bool:
        return self.mode == "full"

    @property
    def is_incremental(self) -> bool:
        return self.mode == "incremental"

    def __repr__(self) -> str:
        parts = [f"mode={self.mode}"]
        if self.is_sample:
            parts.append(f"sample_size={self.sample_size}")
        if self.prodi_filter:
            parts.append(f"prodi_filter={self.prodi_filter}")
        return f"RunConfig({', '.join(parts)})"

