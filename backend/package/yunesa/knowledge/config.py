"""
config.py — Configuration Models & Environment Loaders
======================================================
Configuration data classes and env loaders for KG construction,
vector storage, extraction, and LLM suggestions.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_DIM,
    SILICONFLOW_EMBEDDING_DIMS,
    DEFAULT_GLINER_MODEL,
    DEFAULT_GLIREL_MODEL,
)

logger = logging.getLogger(__name__)


def _positive_env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def _positive_env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except ValueError:
        return default


def load_project_env(project_root: Path | str | None = None) -> Path:
    """Locate the project root and load optional .env files."""
    start_dir = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    current = start_dir
    while current != current.parent:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            break
        current = current.parent

    root = current if (current / ".git").exists() or (current / "pyproject.toml").exists() else start_dir
    env_paths = [
        root / ".env",
        root / "backend" / ".env",
        root / "backend" / "package" / ".env",
        root / "notebooks" / "build-graph" / ".env",
    ]

    try:
        from dotenv import load_dotenv
        for env_path in env_paths:
            if env_path.exists():
                load_dotenv(env_path, override=False)
    except ImportError:
        pass

    return root


def load_colab_env() -> None:
    """Helper function to load environment variables when running in Google Colab."""
    try:
        from google.colab import userdata  # type: ignore
        for key in [
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_KEY",
            "NEO4J_URI",
            "NEO4J_USERNAME",
            "NEO4J_PASSWORD",
            "MILVUS_URI",
            "MILVUS_TOKEN",
            "SILICONFLOW_API_KEY",
            "GROQ_API_KEY",
            "DEEPSEEK_API_KEY",
        ]:
            try:
                val = userdata.get(key)
                if val:
                    os.environ[key] = str(val)
            except Exception:
                pass
    except Exception:
        pass


@dataclass(frozen=True)
class KGConfig:
    """Runtime configuration for YUNESA Academic KG construction."""

    project_root: Path
    build_graph_dir: Path
    output_dir: Path
    thesaurus_path: Path
    taxonomy_path: Path
    concept_aliases_path: Path
    sample_size: int = 50
    max_ieee_terms: int | None = None
    max_concepts_per_paper: int = 14

    @classmethod
    def default(cls, sample_size: int = 50) -> "KGConfig":
        root = load_project_env()
        bg_dir = root / "notebooks" / "build-graph"
        out_dir = bg_dir / "output"
        return cls(
            project_root=root,
            build_graph_dir=bg_dir,
            output_dir=out_dir,
            thesaurus_path=bg_dir / "ieee-thesaurus.ttl",
            taxonomy_path=bg_dir / "ieee-taxonomy.ttl",
            concept_aliases_path=bg_dir / "config" / "concept_aliases.yml",
            sample_size=sample_size,
        )


@dataclass(frozen=True)
class MilvusVectorIndexConfig:
    """Configuration for Milvus / Zilliz Cloud vector index creation."""

    uri: str
    token: str = ""
    db_name: str = ""
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dim: int = DEFAULT_EMBEDDING_DIM
    metric_type: str = "COSINE"
    batch_size: int = 32

    @classmethod
    def from_env(cls) -> "MilvusVectorIndexConfig":
        uri = os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI") or ""
        token = os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN") or ""
        db_name = os.getenv("MILVUS_DB_NAME", "")
        provider = os.getenv("YUNESA_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER)
        model = os.getenv("YUNESA_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)
        default_dim = SILICONFLOW_EMBEDDING_DIMS.get(model, DEFAULT_EMBEDDING_DIM)
        dim = _positive_env_int("YUNESA_EMBEDDING_DIM", default_dim)
        metric = os.getenv("YUNESA_MILVUS_METRIC_TYPE", "COSINE").upper()
        batch_size = _positive_env_int("YUNESA_EMBEDDING_BATCH_SIZE", 32)

        return cls(
            uri=uri,
            token=token,
            db_name=db_name,
            embedding_provider=provider,
            embedding_model=model,
            embedding_dim=dim,
            metric_type=metric,
            batch_size=batch_size,
        )


def milvus_config_from_env() -> MilvusVectorIndexConfig:
    return MilvusVectorIndexConfig.from_env()


@dataclass(frozen=True)
class AcademicExtractionConfig:
    """Configuration for GLiNER and GLiREL zero-shot extraction."""

    use_gliner: bool = False
    use_glirel: bool = False
    gliner_model: str = DEFAULT_GLINER_MODEL
    glirel_model: str = DEFAULT_GLIREL_MODEL
    entity_threshold: float = 0.50
    relation_threshold: float = 0.30
    max_text_chars: int = 3500
    max_entities_per_paper: int = 20
    max_relations_per_paper: int = 20

    @classmethod
    def from_env(cls) -> "AcademicExtractionConfig":
        use_gliner = os.getenv("YUNESA_USE_GLINER", "0").lower() in {"1", "true", "yes"}
        use_glirel = os.getenv("YUNESA_USE_GLIREL", "0").lower() in {"1", "true", "yes"} and use_gliner
        return cls(
            use_gliner=use_gliner,
            use_glirel=use_glirel,
            gliner_model=os.getenv("YUNESA_GLINER_MODEL", DEFAULT_GLINER_MODEL),
            glirel_model=os.getenv("YUNESA_GLIREL_MODEL", DEFAULT_GLIREL_MODEL),
            entity_threshold=_positive_env_float("YUNESA_GLINER_THRESHOLD", 0.50),
            relation_threshold=_positive_env_float("YUNESA_GLIREL_THRESHOLD", 0.30),
            max_text_chars=_positive_env_int("YUNESA_EXTRACTION_MAX_TEXT_CHARS", 3500),
            max_entities_per_paper=_positive_env_int("YUNESA_MAX_ENTITIES_PER_PAPER", 20),
            max_relations_per_paper=_positive_env_int("YUNESA_MAX_RELATIONS_PER_PAPER", 20),
        )


@dataclass(frozen=True)
class LLMAliasSuggestionConfig:
    """Configuration for LLM-assisted alias suggestions."""

    provider: str = "groq"
    model: str = "llama-3.1-8b-instant"
    max_candidates: int = 40
    batch_size: int = 15
    min_confidence_for_auto_candidate: float = 0.85

    @classmethod
    def from_env(cls) -> "LLMAliasSuggestionConfig":
        return cls(
            provider=os.getenv("YUNESA_ALIAS_LLM_PROVIDER", "groq"),
            model=os.getenv("YUNESA_ALIAS_LLM_MODEL", "llama-3.1-8b-instant"),
            max_candidates=_positive_env_int("YUNESA_ALIAS_MAX_CANDIDATES", 40),
            batch_size=_positive_env_int("YUNESA_ALIAS_LLM_BATCH_SIZE", 15),
            min_confidence_for_auto_candidate=_positive_env_float(
                "YUNESA_ALIAS_MIN_CONFIDENCE", 0.85
            ),
        )


def supabase_credential_status() -> dict[str, bool]:
    """Return non-secret Supabase credential availability."""
    return {
        "SUPABASE_URL": bool(os.getenv("SUPABASE_URL")),
        "SUPABASE_SERVICE_ROLE_KEY": bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        "SUPABASE_KEY": bool(os.getenv("SUPABASE_KEY")),
    }


def milvus_credential_status() -> dict[str, bool]:
    """Return non-secret Milvus credential availability."""
    return {
        "MILVUS_URI": bool(os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI")),
        "MILVUS_TOKEN": bool(os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN")),
        "SILICONFLOW_API_KEY": bool(os.getenv("SILICONFLOW_API_KEY")),
    }
