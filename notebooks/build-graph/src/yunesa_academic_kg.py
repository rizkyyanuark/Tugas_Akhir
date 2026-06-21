"""
YUNESA academic knowledge graph construction utilities.

This module is intentionally notebook-oriented. It builds a reproducible
NetworkX property graph from Supabase paper data plus the IEEE taxonomy and
thesaurus files already stored in notebooks/build-graph.

Design principles:
- Keep structured facts from Supabase as the graph backbone.
- Use IEEE SKOS labels as a controlled vocabulary for semantic grounding.
- Keep provenance on concept edges so extraction decisions are auditable.
- Avoid LLM calls by default. TLDR text produced by the ETL can be consumed as
  an input field, but this module does not spend API credits.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from array import array
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import pandas as pd


logger = logging.getLogger(__name__)


try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency guard
    yaml = None


try:
    import rdflib
    from rdflib.namespace import RDF, RDFS, SKOS
except ImportError:  # pragma: no cover - notebook dependency guard
    rdflib = None
    RDF = RDFS = SKOS = None


STRUCTURAL_NODE_TYPES = {
    "Lecturer",
    "Publication",
    "Venue",
    "Year",
    "Keyword",
    "Institution",
}

CONCEPT_TYPES = {
    "Problem",
    "ResearchTopic",
    "Task",
    "Method",
    "Model",
    "Dataset",
    "Metric",
    "Result",
    "Results",
    "Innovation",
    "Domain",
    "Field",
}

CONCEPT_EDGE_BY_TYPE = {
    "Problem": "HAS_TOPIC",
    "ResearchTopic": "HAS_TOPIC",
    "Task": "HAS_TOPIC",
    "Method": "USES_METHOD",
    "Model": "USES_MODEL",
    "Dataset": "USES_DATASET",
    "Metric": "EVALUATED_WITH",
    "Result": "HAS_RESULT",
    "Results": "HAS_RESULT",
    "Innovation": "HAS_TOPIC",
    "Domain": "BELONGS_TO_DOMAIN",
    "Field": "BELONGS_TO_DOMAIN",
}

AUTHOR_RELATIONS = {"HAS_AUTHOR", "PUBLISHES", "WRITES"}
CONCEPT_RELATIONS = set(CONCEPT_EDGE_BY_TYPE.values())
ONTOLOGY_RELATIONS = {
    "PUBLISHES",
    "HAS_AUTHOR",
    "HAS_TOPIC",
    "USES_METHOD",
    "USES_MODEL",
    "USES_DATASET",
    "EVALUATED_WITH",
    "HAS_RESULT",
    "HAS_AFFILIATION",
    "BELONGS_TO_DOMAIN",
    "COLLABORATES_WITH",
    "PUBLISHED_IN_YEAR",
    "PUBLISHED_IN_VENUE",
    "HAS_KEYWORD",
    "SKOS_RELATED",
    "SKOS_EXACT_MATCH",
    "SKOS_BROADER",
    "SKOS_NARROWER",
    "RELATED_TO",
}

RELATION_ALIASES = {
    "WRITES": "PUBLISHES",
    "WORKS_ON": "HAS_TOPIC",
    "SOLVES": "HAS_TOPIC",
    "EVALUATED_BY": "EVALUATED_WITH",
    "IN_FIELD": "BELONGS_TO_DOMAIN",
    "AFFILIATED_WITH": "HAS_AFFILIATION",
    "USES": "USES_METHOD",
    "PROPOSED": "HAS_TOPIC",
}

GLINER_LABEL_TO_CONCEPT_TYPE = {
    "research problem": "Problem",
    "problem": "Problem",
    "research topic": "ResearchTopic",
    "topic": "ResearchTopic",
    "research task": "Task",
    "task": "Task",
    "application domain": "Domain",
    "domain": "Domain",
    "field": "Domain",
    "method": "Method",
    "algorithm": "Method",
    "model": "Model",
    "dataset": "Dataset",
    "data source": "Dataset",
    "metric": "Metric",
    "evaluation metric": "Metric",
    "result": "Result",
    "main result": "Result",
    "innovation": "Innovation",
}

ACADEMIC_NER_LABELS = [
    "research problem",
    "research topic",
    "research task",
    "application domain",
    "method",
    "algorithm",
    "model",
    "dataset",
    "data source",
    "evaluation metric",
    "main result",
    "innovation",
]

ACADEMIC_RELATION_LABELS = [
    "works on",
    "solves",
    "uses method",
    "uses model",
    "uses dataset",
    "evaluated by",
    "has result",
    "belongs to domain",
    "innovates",
]

GLIREL_RELATION_TO_EDGE = {
    "works on": "HAS_TOPIC",
    "solves": "HAS_TOPIC",
    "uses method": "USES_METHOD",
    "uses model": "USES_MODEL",
    "uses dataset": "USES_DATASET",
    "evaluated by": "EVALUATED_WITH",
    "has result": "HAS_RESULT",
    "belongs to domain": "BELONGS_TO_DOMAIN",
    "innovates": "HAS_TOPIC",
}

DEFAULT_MILVUS_COLLECTIONS = {
    "paper_chunks": "PaperChunk",
    "entities": "EntityEmbedding",
    "relationships": "RelationshipEmbedding",
    "content_keywords": "ContentKeyword",
}

DEFAULT_EMBEDDING_PROVIDER = "siliconflow"
DEFAULT_EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-0.6B"
DEFAULT_EMBEDDING_DIM = 1024
SILICONFLOW_EMBEDDING_DIMS = {
    "Qwen/Qwen3-Embedding-0.6B": 1024,
    "Qwen/Qwen3-Embedding-4B": 2560,
    "Qwen/Qwen3-Embedding-8B": 4096,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}

DEFAULT_GLINER_MODEL = "urchade/gliner_medium-v2.1"
DEFAULT_GLIREL_MODEL = "jackboyla/glirel-large-v0"

MILVUS_VARCHAR_LIMITS = {
    "PaperChunk": {
        "graphName": 256,
        "title": 1024,
        "content": 8192,
        "year": 16,
        "paperUrl": 1024,
        "authors": 2048,
    },
    "EntityEmbedding": {
        "graphName": 256,
        "entityName": 512,
        "entityType": 256,
        "description": 4096,
        "nodeId": 256,
        "sourceId": 256,
    },
    "RelationshipEmbedding": {
        "graphName": 256,
        "srcId": 256,
        "tgtId": 256,
        "relType": 256,
        "description": 4096,
        "sourceId": 256,
    },
    "ContentKeyword": {
        "graphName": 256,
        "keywords": 2048,
        "sourcePaper": 512,
    },
}


MODEL_PATTERNS = [
    r"\bbert\b",
    r"\bindobert\b",
    r"\btransformer\b",
    r"\bvision transformer\b",
    r"\bvit\b",
    r"\bmobilevit\b",
    r"\befficientnet\b",
    r"\bxgboost\b",
    r"\bcnn\b",
    r"\brnn\b",
    r"\blstm\b",
    r"\bgru\b",
    r"\bbi[- ]?lstm\b",
    r"\bbi[- ]?gru\b",
    r"\byolo\b",
    r"\bresnet\b",
    r"\bsupport vector machine[s]?\b",
    r"\bsvm\b",
    r"\brandom forest\b",
    r"\bnaive bayes\b",
    r"\blightgbm\b",
    r"\bcatboost\b",
]

METHOD_PATTERNS = [
    r"\balgorithm\b",
    r"\bmethod\b",
    r"\bapproach\b",
    r"\btechnique\b",
    r"\bframework\b",
    r"\boptimization\b",
    r"\boptimizer\b",
    r"\boptuna\b",
    r"\bboosting\b",
    r"\bensemble learning\b",
    r"\bmetaheuristic\b",
    r"\bclassification\b",
    r"\bclustering\b",
    r"\bregression\b",
    r"\bdeep learning\b",
    r"\bmachine learning\b",
    r"\bnatural language processing\b",
    r"\bcomputer vision\b",
]

TASK_PATTERNS = [
    r"\bclassification\b",
    r"\bdetection\b",
    r"\bprediction\b",
    r"\bsegmentation\b",
    r"\brecommendation\b",
    r"\branking\b",
    r"\bforecasting\b",
    r"\brecognition\b",
    r"\bentity extraction\b",
    r"\binformation retrieval\b",
    r"\bsentiment analysis\b",
]

DATASET_PATTERNS = [
    r"\bdataset\b",
    r"\bdata set\b",
    r"\bcorpus\b",
    r"\bbenchmark\b",
    r"\baptos\b",
    r"\bimagenet\b",
    r"\bcifar\b",
    r"\bmnist\b",
    r"\bscopus\b",
    r"\bgoogle scholar\b",
    r"\bopenalex\b",
    r"\bsemantic scholar\b",
]

METRIC_PATTERNS = [
    r"\baccuracy\b",
    r"\bprecision\b",
    r"\brecall\b",
    r"\bf1\b",
    r"\bf1-score\b",
    r"\bauc\b",
    r"\brmse\b",
    r"\bmae\b",
    r"\bmape\b",
    r"\bflops\b",
    r"\btime\b",
    r"\bseconds?\b",
    r"\bminutes?\b",
    r"\b\d+(?:\.\d+)?\s*%",
]

DOMAIN_PATTERNS = [
    r"\beducation\b",
    r"\be-learning\b",
    r"\bmedical\b",
    r"\bhealth\b",
    r"\bretina\b",
    r"\bdiabetic retinopathy\b",
    r"\bimage analysis\b",
    r"\bfacial image\b",
    r"\bfinance\b",
    r"\bcredit\b",
    r"\bsolar energy\b",
    r"\brenewable energy\b",
    r"\bsoftware engineering\b",
    r"\binformation system\b",
    r"\bpower system\b",
    r"\bnetwork\b",
    r"\bcybersecurity\b",
]

PROBLEM_PATTERNS = [
    r"\bproblem\b",
    r"\bchallenge\b",
    r"\bissue\b",
    r"\bthreat\b",
    r"\bdisease\b",
    r"\bdiabetic retinopathy\b",
    r"\bcancer\b",
    r"\boscillation\b",
    r"\bclassification problem\b",
]

RESULT_PATTERNS = [
    r"\bresult\b",
    r"\bperformance\b",
    r"\bachiev(?:e|ed|es|ing)\b",
    r"\bimprov(?:e|ed|es|ing|ement)\b",
    r"\breduc(?:e|ed|es|ing|tion)\b",
    r"\boutperform(?:s|ed|ing)?\b",
    r"\boptimal\b",
]

INNOVATION_PATTERNS = [
    r"\bnovel\b",
    r"\bnew\b",
    r"\bpropos(?:e|ed|es|ing)\b",
    r"\bdevelop(?:s|ed|ing)?\b",
    r"\bintroduc(?:e|ed|es|ing)\b",
    r"\bframework\b",
    r"\bhybrid\b",
]

GENERIC_IEEE_TEXT_TERMS = {
    "analysis",
    "analyses",
    "learning",
    "model",
    "models",
    "system",
    "systems",
    "method",
    "methods",
    "performance",
    "data",
    "information",
    "energy",
}


DEFAULT_CONCEPT_ALIASES = {
    "support_vector_machine": {
        "canonical_label": "Support Vector Machine",
        "concept_type": "Model",
        "aliases": ["svm", "support vector machine", "support-vector machine"],
    },
    "convolutional_neural_network": {
        "canonical_label": "Convolutional Neural Network",
        "concept_type": "Model",
        "aliases": ["cnn", "convolutional neural network"],
    },
    "artificial_neural_network": {
        "canonical_label": "Artificial Neural Network",
        "concept_type": "Model",
        "aliases": ["ann", "artificial neural network"],
    },
    "long_short_term_memory": {
        "canonical_label": "Long Short-Term Memory",
        "concept_type": "Model",
        "aliases": ["lstm", "long short term memory", "long short-term memory"],
    },
    "bidirectional_lstm": {
        "canonical_label": "Bidirectional LSTM",
        "concept_type": "Model",
        "aliases": ["bilstm", "bi lstm", "bidirectional lstm"],
    },
    "k_nearest_neighbors": {
        "canonical_label": "K-Nearest Neighbors",
        "concept_type": "Model",
        "aliases": ["knn", "k nearest neighbors", "k-nearest neighbors"],
    },
    "naive_bayes": {
        "canonical_label": "Naive Bayes",
        "concept_type": "Model",
        "aliases": ["naive bayes", "naive bayes classifier"],
    },
    "decision_tree": {
        "canonical_label": "Decision Tree",
        "concept_type": "Model",
        "aliases": ["decision tree", "decision trees", "tree algorithm", "tree algorithms"],
    },
    "efficientnet": {
        "canonical_label": "EfficientNet",
        "concept_type": "Model",
        "aliases": ["efficientnet", "efficient net"],
    },
    "vision_transformer": {
        "canonical_label": "Vision Transformer",
        "concept_type": "Model",
        "aliases": ["vit", "vision transformer"],
    },
    "auc": {
        "canonical_label": "AUC",
        "concept_type": "Metric",
        "aliases": ["auc", "roc auc", "roc-auc", "area under curve", "area under the curve"],
    },
    "accuracy": {
        "canonical_label": "Accuracy",
        "concept_type": "Metric",
        "aliases": ["accuracy", "akurasi"],
    },
    "precision": {
        "canonical_label": "Precision",
        "concept_type": "Metric",
        "aliases": ["precision"],
    },
    "recall": {
        "canonical_label": "Recall",
        "concept_type": "Metric",
        "aliases": ["recall"],
    },
    "f1_score": {
        "canonical_label": "F1-score",
        "concept_type": "Metric",
        "aliases": ["f1", "f1 score", "f1-score", "f1score"],
    },
    "aptos_2019": {
        "canonical_label": "APTOS 2019",
        "concept_type": "Dataset",
        "aliases": ["aptos", "aptos 2019", "aptos dataset", "aptos 2019 blindness detection"],
    },
    "imagenet": {
        "canonical_label": "ImageNet",
        "concept_type": "Dataset",
        "aliases": ["imagenet", "image net"],
    },
    "cifar_10": {
        "canonical_label": "CIFAR-10",
        "concept_type": "Dataset",
        "aliases": ["cifar10", "cifar-10", "cifar 10"],
    },
    "mnist": {
        "canonical_label": "MNIST",
        "concept_type": "Dataset",
        "aliases": ["mnist"],
    },
}


@dataclass(frozen=True)
class KGConfig:
    """Runtime configuration for the notebook pipeline."""

    project_root: Path
    build_graph_dir: Path
    output_dir: Path
    thesaurus_path: Path
    taxonomy_path: Path
    concept_aliases_path: Path
    sample_size: int = 50
    max_concepts_per_paper: int = 14
    max_ieee_terms: int | None = None

    @classmethod
    def default(cls, sample_size: int = 50) -> "KGConfig":
        here = Path(__file__).resolve()
        build_graph_dir = here.parents[1]
        notebooks_dir = build_graph_dir.parent
        project_root = notebooks_dir.parent
        output_dir = build_graph_dir / "outputs" / "academic_kg"
        approved_aliases_path = build_graph_dir / "config" / "concept_aliases.approved.yml"
        concept_aliases_path = (
            approved_aliases_path
            if approved_aliases_path.exists()
            else build_graph_dir / "config" / "concept_aliases.yml"
        )
        return cls(
            project_root=project_root,
            build_graph_dir=build_graph_dir,
            output_dir=output_dir,
            thesaurus_path=build_graph_dir / "ieee-thesaurus.ttl",
            taxonomy_path=build_graph_dir / "ieee-taxonomy.ttl",
            concept_aliases_path=concept_aliases_path,
            sample_size=sample_size,
        )


@dataclass(frozen=True)
class MilvusVectorIndexConfig:
    """Milvus/Zilliz vector index configuration for notebook KG construction."""

    uri: str
    token: str
    db_name: str | None = None
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dim: int = DEFAULT_EMBEDDING_DIM
    metric_type: str = "L2"
    batch_size: int = 32
    collection_names: dict[str, str] | None = None

    @property
    def collections(self) -> dict[str, str]:
        return self.collection_names or DEFAULT_MILVUS_COLLECTIONS


@dataclass(frozen=True)
class AcademicExtractionConfig:
    """Optional GLiNER/GLiREL extraction settings for unstructured paper text."""

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
        return cls(
            use_gliner=os.getenv("YUNESA_USE_GLINER", "0") == "1",
            use_glirel=os.getenv("YUNESA_USE_GLIREL", "0") == "1",
            gliner_model=os.getenv("YUNESA_GLINER_MODEL", DEFAULT_GLINER_MODEL),
            glirel_model=os.getenv("YUNESA_GLIREL_MODEL", DEFAULT_GLIREL_MODEL),
            entity_threshold=float(os.getenv("YUNESA_GLINER_THRESHOLD", "0.50")),
            relation_threshold=float(os.getenv("YUNESA_GLIREL_THRESHOLD", "0.30")),
            max_text_chars=int(os.getenv("YUNESA_EXTRACTION_MAX_TEXT_CHARS", "3500")),
            max_entities_per_paper=int(os.getenv("YUNESA_MAX_ENTITIES_PER_PAPER", "20")),
            max_relations_per_paper=int(os.getenv("YUNESA_MAX_RELATIONS_PER_PAPER", "20")),
        )

    def status(self) -> dict[str, Any]:
        return {
            "use_gliner": self.use_gliner,
            "use_glirel": self.use_glirel,
            "gliner_model": self.gliner_model,
            "glirel_model": self.glirel_model,
            "entity_threshold": self.entity_threshold,
            "relation_threshold": self.relation_threshold,
            "max_text_chars": self.max_text_chars,
        }


@dataclass(frozen=True)
class LLMAliasSuggestionConfig:
    """LLM-assisted concept alias review settings.

    Suggestions are intentionally written as review artifacts. They are not
    merged into the production alias file unless a human accepts them.
    """

    provider: str = "groq"
    model: str = "llama-3.3-70b-versatile"
    max_candidates: int = 60
    batch_size: int = 15
    min_confidence_for_auto_candidate: float = 0.95

    @classmethod
    def from_env(cls) -> "LLMAliasSuggestionConfig":
        return cls(
            provider=os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_PROVIDER", "groq"),
            model=os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MODEL", "llama-3.3-70b-versatile"),
            max_candidates=int(os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MAX_CANDIDATES", "60")),
            batch_size=int(os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_BATCH_SIZE", "15")),
            min_confidence_for_auto_candidate=float(
                os.getenv("YUNESA_ENTITY_RESOLUTION_LLM_MIN_CONFIDENCE", "0.95")
            ),
        )


def extraction_runtime_status() -> dict[str, Any]:
    """Return non-secret runtime readiness for optional GLiNER/GLiREL extraction."""
    checks: dict[str, Any] = {}
    for module_name in ["gliner", "glirel", "transformers", "datasets", "pyarrow"]:
        checks[module_name] = {
            "ok": importlib.util.find_spec(module_name) is not None,
            "error": "",
        }
    try:
        importlib.import_module("pyarrow.dataset")
        checks["pyarrow.dataset"] = {"ok": True, "error": ""}
    except Exception as exc:
        checks["pyarrow.dataset"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    checks["gliner_ready"] = all(
        checks[name]["ok"]
        for name in ["gliner", "transformers", "datasets", "pyarrow", "pyarrow.dataset"]
    )
    checks["glirel_ready"] = all(
        checks[name]["ok"]
        for name in ["glirel", "transformers", "datasets", "pyarrow", "pyarrow.dataset"]
    )
    checks["ready"] = checks["gliner_ready"] and checks["glirel_ready"]
    return checks


def is_colab_runtime() -> bool:
    """Return True when code is running in Google Colab or VS Code Colab."""
    return (
        "google.colab" in sys.modules
        or bool(os.getenv("COLAB_RELEASE_TAG"))
        or importlib.util.find_spec("google.colab") is not None
    )


def _read_colab_secret(name: str, attempts: int = 2) -> str | None:
    """Read one Google Colab secret without exposing its value."""
    if os.getenv("YUNESA_USE_COLAB_SECRETS", "0") != "1":
        return None
    if not is_colab_runtime():
        return None
    try:
        from google.colab import userdata
    except Exception:
        return None
    value = None
    for attempt in range(attempts):
        try:
            value = userdata.get(name)
            break
        except Exception:
            if attempt + 1 < attempts:
                time.sleep(1.0)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def load_project_env(project_root: Path) -> None:
    """Load runtime secrets from local .env, then Colab Secrets for missing keys."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    if load_dotenv is not None:
        load_dotenv(project_root / ".env", override=False)

    for name in [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_KEY",
        "NEO4J_URI",
        "NEO4J_USERNAME",
        "NEO4J_PASSWORD",
        "NEO4J_DATABASE",
        "MILVUS_URI",
        "MILVUS_TOKEN",
        "MILVUS_DB_NAME",
        "ZILLIZ_URI",
        "ZILLIZ_TOKEN",
        "ZILLIZ_DB_NAME",
        "SILICONFLOW_API_KEY",
    ]:
        if os.getenv(name):
            continue
        value = _read_colab_secret(name)
        if value:
            os.environ[name] = value


def supabase_credential_status() -> dict[str, bool]:
    """Return non-secret Supabase credential availability for notebook debugging."""
    return {
        "SUPABASE_URL": bool(os.getenv("SUPABASE_URL")),
        "SUPABASE_SERVICE_ROLE_KEY": bool(os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
        "SUPABASE_KEY": bool(os.getenv("SUPABASE_KEY")),
    }


def milvus_credential_status() -> dict[str, bool]:
    """Return non-secret Milvus/Zilliz credential availability for notebook debugging."""
    return {
        "MILVUS_URI": bool(os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI")),
        "MILVUS_TOKEN": bool(os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN")),
        "MILVUS_DB_NAME": bool(os.getenv("MILVUS_DB_NAME") or os.getenv("ZILLIZ_DB_NAME")),
    }


def milvus_config_from_env(
    *,
    embedding_provider: str = DEFAULT_EMBEDDING_PROVIDER,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_dim: int = DEFAULT_EMBEDDING_DIM,
    batch_size: int = 32,
) -> MilvusVectorIndexConfig:
    """Build Milvus/Zilliz config from secret env plus code-level embedding defaults."""
    uri = os.getenv("MILVUS_URI") or os.getenv("ZILLIZ_URI")
    if uri and uri.startswith("https://") and not ":" in uri.replace("https://", ""):
        uri = uri + ":443"
    token = os.getenv("MILVUS_TOKEN") or os.getenv("ZILLIZ_TOKEN")
    db_name = os.getenv("MILVUS_DB_NAME") or os.getenv("ZILLIZ_DB_NAME")
    embedding_dim = int(SILICONFLOW_EMBEDDING_DIMS.get(embedding_model, embedding_dim))
    if not uri or not token:
        raise ValueError("Set MILVUS_URI and MILVUS_TOKEN first.")
    return MilvusVectorIndexConfig(
        uri=uri,
        token=token,
        db_name=db_name or None,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        batch_size=batch_size,
    )



def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, float) and pd.isna(value):
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return default
    return text


def normalize_text(text: Any) -> str:
    text = safe_str(text).lower()
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"[_/]+", " ", text)
    text = re.sub(r"[^a-z0-9%+.\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    return text


class NoopObservation:
    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    tags: list[str] | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None
    provider: str | None = None


def truthy_env(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def opik_project_name() -> str:
    return os.getenv("OPIK_PROJECT_NAME") or os.getenv("OPIK_PROJECT") or "yunesa-academic-graphrag"


def opik_environment() -> str:
    return os.getenv("OPIK_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "development"


def opik_enabled() -> bool:
    if not truthy_env("OPIK_ENABLED", default=True):
        return False
    return bool(os.getenv("OPIK_API_KEY") or os.getenv("OPIK_URL_OVERRIDE") or os.getenv("OPIK_USE_LOCAL"))


@lru_cache(maxsize=1)
def _opik_module() -> Any | None:
    if not opik_enabled():
        return None
    try:
        import opik

        return opik
    except Exception:
        return None


def _opik_metadata(metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "application": "yunesa",
        "component": "academic-graphrag-notebook",
        "environment": opik_environment(),
        **(metadata or {}),
    }


def _opik_tags(tags: list[str] | None = None) -> list[str]:
    merged = ["yunesa", "academic-graphrag", "notebook", opik_environment()]
    for tag in tags or []:
        if tag and tag not in merged:
            merged.append(tag)
    return merged


@contextmanager
def opik_trace(
    name: str,
    *,
    input: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    thread_id: str | None = None,
) -> Iterable[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return
    try:
        manager = opik.start_as_current_trace(
            name=name,
            input=input,
            metadata=_opik_metadata(metadata),
            tags=_opik_tags(tags),
            thread_id=thread_id,
            project_name=opik_project_name(),
            flush=truthy_env("OPIK_FLUSH", default=False),
        )
    except Exception:
        yield NoopObservation()
        return
    with manager as trace:
        yield trace


@contextmanager
def opik_span(
    name: str,
    *,
    type: str = "general",
    input: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> Iterable[Any]:
    opik = _opik_module()
    if opik is None:
        yield NoopObservation()
        return
    try:
        manager = opik.start_as_current_span(
            name=name,
            type=type,
            input=input,
            metadata=_opik_metadata(metadata),
            tags=_opik_tags(tags),
            project_name=opik_project_name(),
            model=model,
            provider=provider,
            flush=truthy_env("OPIK_FLUSH", default=False),
        )
    except Exception:
        yield NoopObservation()
        return
    with manager as span:
        yield span


def set_observation_output(
    observation: Any,
    *,
    output: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
) -> None:
    try:
        if output is not None:
            observation.output = output
        if metadata:
            current = getattr(observation, "metadata", None) or {}
            observation.metadata = {**current, **metadata}
        if usage:
            observation.usage = usage
    except Exception:
        return


def slugify(text: Any) -> str:
    norm = normalize_text(text)
    norm = re.sub(r"[^a-z0-9]+", "_", norm).strip("_")
    return norm or "unknown"


def stable_id(prefix: str, value: Any) -> str:
    raw = safe_str(value)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def split_list_field(value: Any) -> list[str]:
    text = safe_str(value)
    if not text:
        return []

    # Handle JSON-like arrays from some exports.
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text.replace("'", '"'))
            if isinstance(parsed, list):
                return [safe_str(item) for item in parsed if safe_str(item)]
        except json.JSONDecodeError:
            pass

    parts = re.split(r"\s*[;,|]\s*", text)
    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        item = safe_str(part)
        key = normalize_text(item)
        if item and len(key) >= 2 and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned


def canonical_document_type(value: Any) -> str:
    doc = normalize_text(value)
    if not doc:
        return "article"
    mapping = {
        "artikel": "article",
        "article": "article",
        "journal article": "article",
        "journal-article": "article",
        "conference": "conference paper",
        "conference paper": "conference paper",
        "conference-paper": "conference paper",
        "proceedings article": "conference paper",
        "proceedings-article": "conference paper",
    }
    return mapping.get(doc, doc.replace("-", " "))


def canonical_venue_name(value: Any) -> str:
    """Return a stable venue identity for KG nodes.

    Scholar venue strings can include article-specific bibliographic suffixes
    such as volume, issue, page range, and year. Those suffixes belong on the
    publication, not on the Venue node identity.
    """
    venue = re.sub(r"\s+", " ", safe_str(value)).strip(" ,.-")
    if not venue:
        return ""
    venue = re.sub(
        r"\s+\d+\s*\([^)]*\)\s*,\s*\d+\s*[-–]\s*\d+\s*,\s*(?:19|20)\d{2}\s*$",
        "",
        venue,
    )
    venue = re.sub(
        r"\s+\d+\s*,\s*\d+\s*[-–]\s*\d+\s*,\s*(?:19|20)\d{2}\s*$",
        "",
        venue,
    )
    venue = re.sub(
        r"\s*,\s*\d+\s*[-–]\s*\d+\s*,\s*(?:19|20)\d{2}\s*$",
        "",
        venue,
    )
    return re.sub(r"\s+", " ", venue).strip(" ,.-")


def canonical_relation(value: Any) -> str:
    """Map legacy/internal relation labels into the thesis ontology vocabulary."""
    relation = re.sub(r"[^A-Za-z0-9_]", "_", safe_str(value).upper()).strip("_")
    if not relation:
        return "RELATED_TO"
    return RELATION_ALIASES.get(relation, relation)


def canonical_concept_type(value: Any, *, fallback_label: Any = "") -> str:
    concept_type = safe_str(value)
    aliases = {
        "Topic": "ResearchTopic",
        "Research Topic": "ResearchTopic",
        "Field": "Domain",
        "ApplicationDomain": "Domain",
        "Application Domain": "Domain",
        "Results": "Result",
        "Main Result": "Result",
    }
    concept_type = aliases.get(concept_type, concept_type)
    label_inferred = infer_concept_type(safe_str(fallback_label)) if safe_str(fallback_label) else ""
    if label_inferred in {"Model", "Dataset", "Metric"}:
        return label_inferred
    if concept_type in CONCEPT_TYPES:
        return concept_type
    return label_inferred if label_inferred in CONCEPT_TYPES else "ResearchTopic"


def has_relation(graph: nx.MultiDiGraph, source: str, target: str, relation: str) -> bool:
    relation = canonical_relation(relation)
    if not graph.has_edge(source, target):
        return False
    for edge_data in graph.get_edge_data(source, target, default={}).values():
        if canonical_relation(edge_data.get("relation")) == relation:
            return True
    return False


def academic_document_id(paper: pd.Series | dict[str, Any]) -> str:
    paper_id = field_value(paper, "paper_id", "id")
    doi = field_value(paper, "doi", "DOI")
    title = field_value(paper, "title", "Title")
    if paper_id:
        return safe_str(paper_id)
    if doi:
        return stable_id("doc", doi)
    return stable_id("doc", title)


def academic_document_text(paper: pd.Series | dict[str, Any], max_chars: int | None = None) -> str:
    title = field_value(paper, "title", "Title")
    tldr = field_value(paper, "tldr", "TLDR")
    abstract = field_value(paper, "abstract", "Abstract")
    keywords = ", ".join(split_list_field(field_value(paper, "keywords", "Keywords")))
    text = "\n".join(
        part
        for part in [
            f"Title: {title}" if title else "",
            f"TLDR: {tldr}" if tldr else "",
            f"Abstract: {abstract}" if abstract else "",
            f"Keywords: {keywords}" if keywords else "",
        ]
        if part
    )
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0].strip()
    return text


def content_hash(text: Any) -> str:
    return hashlib.md5(safe_str(text).encode("utf-8")).hexdigest()


def semantic_text_chunks(text: str, max_chars: int = 2024, overlap_chars: int = 50) -> list[str]:
    """Split academic text into lightweight semantic-ish chunks without external tokenizers."""
    text = re.sub(r"\s+", " ", safe_str(text)).strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = sentence
        while len(current) > max_chars:
            chunks.append(current[:max_chars].strip())
            current = current[max(0, max_chars - overlap_chars) :].strip()
    if current:
        chunks.append(current)
    return chunks


def field_value(row: pd.Series | dict[str, Any], *names: str, default: str = "") -> str:
    for name in names:
        if isinstance(row, pd.Series):
            if name in row:
                value = safe_str(row.get(name))
                if value:
                    return value
        elif name in row:
            value = safe_str(row.get(name))
            if value:
                return value
    return default


def _looks_like_noise(label: str) -> bool:
    text = safe_str(label)
    norm = normalize_text(text)
    if len(norm) < 3 or len(norm) > 90:
        return True
    if norm.count(".") >= 3:
        return True
    if re.search(r"(copyright|download|license|ieee terms|page \d+)", norm):
        return True
    if len(re.findall(r"[a-z]", norm)) < 3:
        return True
    if len(norm.split()) > 8:
        return True
    return False


class IeeeSemanticIndex:
    """Controlled vocabulary matcher backed by IEEE SKOS files."""

    def __init__(self) -> None:
        self.label_index: dict[str, dict[str, str]] = {}
        self.uri_to_label: dict[str, str] = {}
        self.uri_relations: list[tuple[str, str, str]] = []
        self.source_counts: Counter[str] = Counter()
        self._sorted_labels: list[tuple[str, dict[str, str]]] | None = None

    @classmethod
    def from_files(
        cls,
        thesaurus_path: Path,
        taxonomy_path: Path | None = None,
        max_terms: int | None = None,
    ) -> "IeeeSemanticIndex":
        if rdflib is None:
            raise ImportError("rdflib is required to load IEEE taxonomy/thesaurus files.")

        index = cls()
        if thesaurus_path.exists():
            index._load_graph(thesaurus_path, source="ieee_thesaurus", max_terms=max_terms)
        if taxonomy_path and taxonomy_path.exists():
            index._load_graph(taxonomy_path, source="ieee_taxonomy", max_terms=max_terms)
        return index

    def _load_graph(self, path: Path, source: str, max_terms: int | None) -> None:
        graph = rdflib.Graph()
        graph.parse(str(path), format="ttl")
        self._sorted_labels = None

        label_predicates = [SKOS.prefLabel, SKOS.altLabel, RDFS.label]
        loaded = 0

        for subject in set(graph.subjects()):
            labels = []
            for predicate in label_predicates:
                labels.extend(str(label) for label in graph.objects(subject, predicate))

            if not labels:
                continue

            canonical = next((label for label in labels if not _looks_like_noise(label)), "")
            if not canonical:
                continue

            uri = str(subject)
            self.uri_to_label[uri] = canonical

            for label in labels:
                if _looks_like_noise(label):
                    continue
                key = normalize_text(label)
                if not key:
                    continue
                self.label_index.setdefault(
                    key,
                    {
                        "label": canonical,
                        "matched_label": label,
                        "uri": uri,
                        "source": source,
                    },
                )
                loaded += 1
                if max_terms and loaded >= max_terms:
                    break

            if max_terms and loaded >= max_terms:
                break

        for predicate, rel_name in [
            (SKOS.broader, "SKOS_BROADER"),
            (SKOS.narrower, "SKOS_NARROWER"),
            (SKOS.related, "SKOS_RELATED"),
            (SKOS.exactMatch, "SKOS_EXACT_MATCH"),
        ]:
            for source_uri, target_uri in graph.subject_objects(predicate):
                s = str(source_uri)
                t = str(target_uri)
                if s in self.uri_to_label and t in self.uri_to_label:
                    self.uri_relations.append((s, t, rel_name))

        self.source_counts[source] += loaded

    def match_label(self, text: Any) -> dict[str, str] | None:
        return self.label_index.get(normalize_text(text))

    def match_text(self, text: str, max_matches: int = 8) -> list[dict[str, Any]]:
        norm_text = f" {normalize_text(text)} "
        if len(norm_text.strip()) < 3:
            return []

        matches: list[dict[str, Any]] = []
        seen: set[str] = set()
        if self._sorted_labels is None:
            self._sorted_labels = sorted(
                self.label_index.items(),
                key=lambda item: (len(item[0].split()), len(item[0])),
                reverse=True,
            )

        for key, data in self._sorted_labels:
            if len(key) < 4 or data["uri"] in seen:
                continue
            pattern = f" {key} "
            if pattern in norm_text:
                matches.append({**data, "match": key, "match_type": "ieee_text"})
                seen.add(data["uri"])
            if len(matches) >= max_matches:
                break

        return matches

    def summary(self) -> dict[str, Any]:
        return {
            "labels": len(self.label_index),
            "concept_uris": len(self.uri_to_label),
            "relations": len(self.uri_relations),
            "source_counts": dict(self.source_counts),
        }


def _metric_label_from_base(base: str) -> str:
    mapping = {
        "roc auc": "AUC",
        "auc": "AUC",
        "accuracy": "Accuracy",
        "precision": "Precision",
        "recall": "Recall",
        "f1": "F1-score",
        "f1-score": "F1-score",
        "f1 score": "F1-score",
        "rmse": "RMSE",
        "mae": "MAE",
        "flops": "FLOPs",
    }
    return mapping.get(normalize_text(base), safe_str(base))


def _extract_metric_value(label: Any) -> dict[str, Any]:
    text = safe_str(label)
    norm = normalize_text(text)
    base_match = re.search(r"\b(roc auc|f1 score|f1-score|f1|auc|accuracy|precision|recall|rmse|mae|flops)\b", norm)
    if not base_match:
        return {}

    tail = norm[base_match.end() :]
    value_match = re.search(r"(\d+(?:\.\d+)?)\s*%", tail)
    unit = "%"
    if not value_match:
        value_match = re.search(
            r"\b(?:of|around|about|sebesar|=|:)\s*(0?\.\d+|1\.0+|\d+(?:\.\d+)?)\b",
            tail,
            flags=re.IGNORECASE,
        )
        unit = ""

    result = {
        "metric_base": normalize_text(base_match.group(1)).replace("f1 score", "f1-score"),
        "metric_label": _metric_label_from_base(base_match.group(1)),
    }
    if value_match:
        value_text = value_match.group(1)
        try:
            result["metric_value"] = float(value_text)
            result["metric_unit"] = unit
        except ValueError:
            pass
    return result


def _load_alias_records(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load curated concept aliases and merge them with built-in aliases."""
    records = json.loads(json.dumps(DEFAULT_CONCEPT_ALIASES))
    if not path or not path.exists():
        return records

    loaded: dict[str, Any] = {}
    try:
        if yaml is not None:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return records

    alias_records = loaded.get("aliases", loaded) if isinstance(loaded, dict) else {}
    if not isinstance(alias_records, dict):
        return records

    for key, value in alias_records.items():
        if not isinstance(value, dict):
            continue
        canonical_key = slugify(value.get("canonical_key") or key)
        aliases = [safe_str(item) for item in value.get("aliases", []) if safe_str(item)]
        canonical_label = safe_str(value.get("canonical_label") or value.get("label") or key)
        if canonical_label and canonical_label not in aliases:
            aliases.append(canonical_label)
        records[canonical_key] = {
            "canonical_label": canonical_label,
            "concept_type": safe_str(value.get("concept_type") or "ResearchTopic"),
            "aliases": aliases,
            "source": safe_str(value.get("source") or "curated_alias"),
        }
    return records


class AcademicConceptResolver:
    """Resolve raw concept labels into canonical KG identities.

    The resolver is deterministic by default: metric-value parsing, curated
    aliases, IEEE URI identity, then local fallback. LLM-assisted suggestions
    can be layered later by writing candidates into the alias file, not by
    directly changing production graph identities.
    """

    def __init__(self, alias_path: Path | None = None) -> None:
        self.alias_path = alias_path
        self.alias_records = _load_alias_records(alias_path)
        self.alias_lookup: dict[str, dict[str, Any]] = {}
        for canonical_key, record in self.alias_records.items():
            aliases = list(record.get("aliases") or [])
            canonical_label = safe_str(record.get("canonical_label"))
            if canonical_label:
                aliases.append(canonical_label)
            for alias in aliases:
                norm = normalize_text(alias)
                if norm:
                    self.alias_lookup[norm] = {"canonical_key": canonical_key, **record}

    @classmethod
    def from_path(cls, alias_path: Path | None = None) -> "AcademicConceptResolver":
        return cls(alias_path=alias_path)

    def resolve(
        self,
        *,
        label: Any,
        concept_type: Any = "",
        ieee_uri: Any = "",
        source: Any = "",
    ) -> dict[str, Any]:
        raw_label = safe_str(label)
        norm = normalize_text(raw_label)
        inferred_type = canonical_concept_type(concept_type, fallback_label=raw_label)

        metric = _extract_metric_value(raw_label)
        if metric and inferred_type == "Metric":
            canonical_label = metric["metric_label"]
            canonical_key = f"metric:{slugify(canonical_label)}"
            return {
                "raw_label": raw_label,
                "label": canonical_label,
                "canonical_label": canonical_label,
                "canonical_key": canonical_key,
                "concept_type": "Metric",
                "resolution_source": "metric_value_parser" if "metric_value" in metric else "metric_parser",
                **metric,
            }

        alias_record = self.alias_lookup.get(norm)
        if alias_record:
            resolved_type = canonical_concept_type(alias_record.get("concept_type"), fallback_label=raw_label)
            canonical_label = safe_str(alias_record.get("canonical_label") or raw_label)
            return {
                "raw_label": raw_label,
                "label": canonical_label,
                "canonical_label": canonical_label,
                "canonical_key": f"alias:{alias_record['canonical_key']}",
                "concept_type": resolved_type,
                "resolution_source": alias_record.get("source") or "curated_alias",
            }

        uri = safe_str(ieee_uri)
        if uri:
            canonical_key = f"ieee_label:{slugify(raw_label)}" if norm else f"ieee:{uri}"
            return {
                "raw_label": raw_label,
                "label": raw_label,
                "canonical_label": raw_label,
                "canonical_key": canonical_key,
                "concept_type": inferred_type,
                "resolution_source": safe_str(source) or "ieee_uri",
            }

        local_key = f"local:{inferred_type}:{slugify(norm or raw_label)}"
        return {
            "raw_label": raw_label,
            "label": raw_label,
            "canonical_label": raw_label,
            "canonical_key": local_key,
            "concept_type": inferred_type,
            "resolution_source": safe_str(source) or "local_fallback",
        }

    def summary(self) -> dict[str, Any]:
        return {
            "alias_records": len(self.alias_records),
            "alias_terms": len(self.alias_lookup),
            "alias_path": str(self.alias_path) if self.alias_path else "",
        }


def infer_concept_type(label: str, evidence_text: str = "") -> str:
    text = normalize_text(label)
    evidence = normalize_text(evidence_text)

    def has(patterns: Iterable[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    if has(MODEL_PATTERNS):
        return "Model"
    if has(DATASET_PATTERNS):
        return "Dataset"
    if has(METRIC_PATTERNS):
        return "Metric"
    if has(TASK_PATTERNS):
        return "Task"
    if has(METHOD_PATTERNS):
        return "Method"
    if has(INNOVATION_PATTERNS):
        return "Innovation"
    if has(RESULT_PATTERNS):
        return "Result"
    if has(DOMAIN_PATTERNS):
        return "Domain"
    if has(PROBLEM_PATTERNS):
        return "Problem"
    if text in evidence and any(re.search(pattern, evidence, flags=re.IGNORECASE) for pattern in DOMAIN_PATTERNS):
        return "ResearchTopic"
    return "ResearchTopic"


def extract_regex_concepts(text: str) -> list[dict[str, Any]]:
    """Extract high-value concepts not always covered by IEEE terms."""
    concepts: list[dict[str, Any]] = []
    norm = safe_str(text)

    named_patterns = {
        "Metric": [
            r"\b\d+(?:\.\d+)?\s*%\b",
            r"\b(?:accuracy|precision|recall|f1-score|f1|auc|roc auc|rmse|mae|flops)\b(?:\s+(?:of|around|about|sebesar))?\s*(?:\d+(?:\.\d+)?\s*%?|\d?\.\d+)(?=[\s,.;)]|$)",
            r"\b(?:accuracy|precision|recall|f1-score|f1|auc|roc auc|rmse|mae|flops)\b",
        ],
        "Dataset": [
            r"\bAPTOS\s*2019\b",
            r"\bImageNet\b",
            r"\bCIFAR-?10\b",
            r"\bCIFAR-?100\b",
            r"\bMNIST\b",
        ],
        "Model": [
            r"\bMobileViT-?[A-Z0-9]*\b",
            r"\bEfficientNet-?[A-Z0-9]*\b",
            r"\bIndoBERT\b",
            r"\bBiLSTM(?:[- ]BiGRU)?\b",
            r"\bXGBoost\b",
            r"\bLightGBM\b",
            r"\bCatBoost\b",
            r"\bSupport Vector Machine\b",
            r"\bSVM\b",
        ],
        "Result": [
            r"\bachiev(?:e|ed|es|ing)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
            r"\breduc(?:e|ed|es|ing|tion)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
            r"\bimprov(?:e|ed|es|ing|ement)\s+[^.]{0,80}?\b\d+(?:\.\d+)?\s*%\b",
        ],
        "Innovation": [
            r"\bhybrid\s+[A-Za-z0-9][A-Za-z0-9+/ _-]{2,80}?\bmodel\b",
            r"\bnovel\s+[A-Za-z0-9][A-Za-z0-9+/ _-]{2,80}?\b(?:method|framework|approach|model)\b",
        ],
    }

    seen: set[str] = set()
    for concept_type, patterns in named_patterns.items():
        for pattern in patterns:
            for match in re.finditer(pattern, norm, flags=re.IGNORECASE):
                label = match.group(0).strip(" .,-")
                key = normalize_text(label)
                if len(key) < 2 or key in seen:
                    continue
                seen.add(key)
                concepts.append(
                    {
                        "label": label,
                        "concept_type": concept_type,
                        "source": "regex",
                        "matched_label": label,
                        "uri": "",
                        "match_type": "regex",
                    }
                )
    return concepts


def _metric_base(label: Any) -> str:
    text = normalize_text(label)
    match = re.match(r"^(roc auc|f1 score|f1-score|f1|auc|accuracy|precision|recall|rmse|mae|flops)\b", text)
    if match and match.group(1) == "f1 score":
        return "f1-score"
    return match.group(1) if match else ""


def _metric_has_value(label: Any) -> bool:
    text = safe_str(label)
    return bool(
        re.search(r"\b(?:of|around|about|sebesar)\s*\d", text, flags=re.IGNORECASE)
        or re.search(r"\d+(?:\.\d+)?\s*%", text)
        or re.search(r"\b\d?\.\d+\b", text)
        or re.search(r"\b\d{2,}(?:\.\d+)?\b", text)
    )


def suppress_plain_metric_duplicates(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop plain metric labels when a value-bearing version is already present."""
    valued_metric_bases = {
        base
        for concept in concepts
        if canonical_concept_type(concept.get("concept_type"), fallback_label=concept.get("label")) == "Metric"
        for base in [_metric_base(concept.get("label"))]
        if base and _metric_has_value(concept.get("label"))
    }
    if not valued_metric_bases:
        return concepts

    filtered: list[dict[str, Any]] = []
    for concept in concepts:
        concept_type = canonical_concept_type(concept.get("concept_type"), fallback_label=concept.get("label"))
        label = safe_str(concept.get("label"))
        base = _metric_base(label)
        is_plain_duplicate = concept_type == "Metric" and base in valued_metric_bases and not _metric_has_value(label)
        if not is_plain_duplicate:
            filtered.append(concept)
    return filtered


def extract_concepts_for_paper(
    paper: pd.Series,
    ieee_index: IeeeSemanticIndex,
    max_concepts: int = 14,
) -> list[dict[str, Any]]:
    title = field_value(paper, "title", "Title")
    abstract = field_value(paper, "abstract", "Abstract")
    tldr = field_value(paper, "tldr", "TLDR")
    keywords = split_list_field(field_value(paper, "keywords", "Keywords"))
    text = ". ".join([title, tldr, abstract, " ".join(keywords)])

    candidates: list[dict[str, Any]] = []

    for keyword in keywords:
        matched = ieee_index.match_label(keyword)
        if matched:
            candidates.append({**matched, "match": keyword, "match_type": "keyword_ieee"})
        else:
            candidates.append(
                {
                    "label": keyword,
                    "matched_label": keyword,
                    "uri": "",
                    "source": "author_keyword",
                    "match": keyword,
                    "match_type": "keyword_raw",
                }
            )

    candidates.extend(ieee_index.match_text(f"{title}. {tldr}", max_matches=max(6, max_concepts // 2)))
    candidates.extend(extract_regex_concepts(text))

    ranked: dict[str, dict[str, Any]] = {}
    for item in candidates:
        label = safe_str(item.get("label") or item.get("matched_label"))
        if not label:
            continue
        key = normalize_text(label)
        if not key:
            continue
        if item.get("match_type") == "ieee_text" and key in GENERIC_IEEE_TEXT_TERMS:
            continue

        score = 1.0
        if item.get("match_type") == "keyword_ieee":
            score = 3.0
        elif item.get("match_type") == "keyword_raw":
            score = 2.0
        elif item.get("match_type") == "regex":
            score = 2.5
        elif item.get("match_type") == "ieee_text":
            score = 1.5

        current = ranked.get(key)
        if not current or score > current["score"]:
            concept_type = item.get("concept_type") or infer_concept_type(label, text)
            ranked[key] = {
                "label": label,
                "concept_type": concept_type,
                "source": item.get("source", ""),
                "matched_label": item.get("matched_label", ""),
                "uri": item.get("uri", ""),
                "match": item.get("match", label),
                "match_type": item.get("match_type", ""),
                "score": score,
            }

    ordered = sorted(
        ranked.values(),
        key=lambda item: (item["score"], len(item["label"].split()), len(item["label"])),
        reverse=True,
    )
    ordered = suppress_plain_metric_duplicates(ordered)
    return ordered[:max_concepts]


def _concept_type_from_ner_label(label: Any) -> str:
    normalized = normalize_text(label)
    return GLINER_LABEL_TO_CONCEPT_TYPE.get(normalized, infer_concept_type(normalized))


def _dedupe_entities(entities: list[dict[str, Any]], max_entities: int) -> list[dict[str, Any]]:
    ranked: dict[str, dict[str, Any]] = {}
    for entity in entities:
        text = safe_str(entity.get("text") or entity.get("label"))
        if not text:
            continue
        key = normalize_text(text)
        if len(key) < 2:
            continue
        score = float(entity.get("score") or 0.0)
        current = ranked.get(key)
        if not current or score > float(current.get("score") or 0.0):
            ranked[key] = {**entity, "text": text, "score": score}
    return sorted(ranked.values(), key=lambda item: float(item.get("score") or 0.0), reverse=True)[:max_entities]


def _token_spans(text: str) -> list[tuple[str, int, int]]:
    return [(match.group(0), match.start(), match.end()) for match in re.finditer(r"\S+", text)]


def _entity_to_token_span(entity: dict[str, Any], spans: list[tuple[str, int, int]]) -> list[Any] | None:
    start = entity.get("start")
    end = entity.get("end")
    if start is None or end is None:
        entity_text = safe_str(entity.get("text"))
        if not entity_text:
            return None
        return None
    try:
        char_start = int(start)
        char_end = int(end)
    except (TypeError, ValueError):
        return None
    token_indexes = [
        idx
        for idx, (_, token_start, token_end) in enumerate(spans)
        if token_start < char_end and token_end > char_start
    ]
    if not token_indexes:
        return None
    return [
        min(token_indexes),
        max(token_indexes),
        safe_str(entity.get("concept_type") or entity.get("label")).upper(),
        safe_str(entity.get("text")),
    ]


@lru_cache(maxsize=2)
def _load_gliner_model(model_name: str) -> Any:
    try:
        from gliner import GLiNER
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise ImportError(
            "GLiNER could not be imported. Install the backend 'kg' dependency group or "
            "disable extraction with YUNESA_USE_GLINER=0. "
            f"Underlying error: {type(exc).__name__}: {exc}"
        ) from exc
    return GLiNER.from_pretrained(model_name)


@lru_cache(maxsize=2)
def _load_glirel_model(model_name: str) -> Any:
    try:
        from glirel import GLiREL
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise ImportError(
            "GLiREL could not be imported. If glirel is already installed, inspect the "
            "underlying ImportError; on Windows this can happen when security policy blocks "
            "pyarrow/transformers DLLs. Disable extraction with YUNESA_USE_GLIREL=0, or run "
            "the extraction step in Colab/server runtime where GLiREL imports cleanly."
        ) from exc
    try:
        return GLiREL.from_pretrained(model_name)
    except TypeError as exc:
        if "proxies" not in str(exc) and "resume_download" not in str(exc):
            raise
        return GLiREL._from_pretrained(
            model_id=model_name,
            revision=None,
            cache_dir=None,
            force_download=False,
            proxies=None,
            resume_download=False,
            local_files_only=False,
            token=None,
            map_location="cpu",
        )


def _run_glirel_relations(
    text: str,
    entities: list[dict[str, Any]],
    config: AcademicExtractionConfig,
) -> list[dict[str, Any]]:
    if not config.use_glirel or len(entities) < 2:
        return []

    spans = _token_spans(text)
    if not spans:
        return []
    ner = [_entity_to_token_span(entity, spans) for entity in entities]
    ner = [item for item in ner if item is not None]
    if len(ner) < 2:
        return []

    model = _load_glirel_model(config.glirel_model)
    tokens = [token for token, _, _ in spans]
    raw_relations = model.predict_relations(
        tokens,
        ACADEMIC_RELATION_LABELS,
        threshold=config.relation_threshold,
        ner=ner,
        top_k=1,
    )

    relations: list[dict[str, Any]] = []
    for relation in raw_relations or []:
        label = safe_str(relation.get("label"))
        head = safe_str(relation.get("head_text") or relation.get("head"))
        tail = safe_str(relation.get("tail_text") or relation.get("tail"))
        if not label or not head or not tail:
            continue
        relations.append(
            {
                "head": head,
                "tail": tail,
                "label": label,
                "relation": GLIREL_RELATION_TO_EDGE.get(normalize_text(label), _neo4j_relation(label)),
                "score": float(relation.get("score") or 0.0),
                "source": "glirel",
            }
        )
        if len(relations) >= config.max_relations_per_paper:
            break
    return relations


def extract_academic_elements_with_gliner_glirel(
    papers_df: pd.DataFrame,
    config: AcademicExtractionConfig | None = None,
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Run optional GLiNER/GLiREL extraction over paper text.

    This replaces AcademicRAG's LLM extraction step with thesis-aligned
    zero-shot NER/RE while preserving the same output categories:
    entities, relationships, and content keywords.
    """
    config = config or AcademicExtractionConfig.from_env()
    if not config.use_gliner:
        return {}

    gliner_model = _load_gliner_model(config.gliner_model)
    extraction_by_doc: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for _, paper in papers_df.iterrows():
        doc_id = academic_document_id(paper)
        text = academic_document_text(paper, max_chars=config.max_text_chars)
        if not text:
            extraction_by_doc[doc_id] = {"entities": [], "relationships": [], "keywords": []}
            continue

        raw_entities = gliner_model.predict_entities(
            text,
            ACADEMIC_NER_LABELS,
            threshold=config.entity_threshold,
        )
        entities = []
        for entity in raw_entities or []:
            entity_text = safe_str(entity.get("text"))
            if not entity_text:
                continue
            label = safe_str(entity.get("label"))
            concept_type = _concept_type_from_ner_label(label)
            entities.append(
                {
                    "text": entity_text,
                    "label": label,
                    "concept_type": canonical_concept_type(concept_type, fallback_label=entity_text),
                    "score": float(entity.get("score") or 0.0),
                    "start": entity.get("start"),
                    "end": entity.get("end"),
                    "source": "gliner",
                }
            )
        entities = _dedupe_entities(entities, config.max_entities_per_paper)
        relationships = _run_glirel_relations(text, entities, config) if config.use_glirel else []
        keywords = [
            {
                "keyword": item,
                "source": "paper_metadata",
                "score": 1.0,
            }
            for item in split_list_field(field_value(paper, "keywords", "Keywords"))
        ]
        extraction_by_doc[doc_id] = {
            "entities": entities,
            "relationships": relationships,
            "keywords": keywords,
        }

    return extraction_by_doc


def summarize_extracted_elements(
    extracted_elements: dict[str, dict[str, list[dict[str, Any]]]]
) -> dict[str, int]:
    return {
        "documents": len(extracted_elements),
        "entities": sum(len(value.get("entities", [])) for value in extracted_elements.values()),
        "relationships": sum(len(value.get("relationships", [])) for value in extracted_elements.values()),
        "keywords": sum(len(value.get("keywords", [])) for value in extracted_elements.values()),
    }


def fetch_supabase_sample(sample_size: int = 50) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read sample data from Supabase.

    Required env vars:
    - SUPABASE_URL
    - SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY
    """
    try:
        from supabase import create_client
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("supabase package is required for fetch_supabase_sample().") from exc

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise ValueError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY or SUPABASE_KEY first.")

    client = create_client(url, key)

    paper_cols = ",".join(
        [
            "paper_id",
            "title",
            "abstract",
            "tldr",
            "keywords",
            "year",
            "journal",
            "document_type",
            "authors",
            "author_ids",
            "doi",
            "link",
        ]
    )
    lecturer_cols = "nip,nama_dosen,nama_norm,nidn,prodi,scopus_id,scholar_id,sinta_id"

    paper_response = (
        client.table("papers")
        .select(paper_cols)
        .order("year", desc=True)
        .limit(max(sample_size * 3, sample_size))
        .execute()
    )
    papers_df = pd.DataFrame(paper_response.data or [])

    if not papers_df.empty:
        papers_df = papers_df[
            papers_df["title"].map(lambda value: bool(safe_str(value)))
            & (
                papers_df["abstract"].map(lambda value: len(safe_str(value)) > 20)
                | papers_df["tldr"].map(lambda value: len(safe_str(value)) > 20)
            )
        ].head(sample_size)

    lecturer_response = client.table("lecturers").select(lecturer_cols).limit(2000).execute()
    lecturers_df = pd.DataFrame(lecturer_response.data or [])

    link_response = (
        client.table("paper_lecturers")
        .select("paper_id,nip")
        .limit(max(sample_size * 20, 200))
        .execute()
    )
    links_df = pd.DataFrame(link_response.data or [])

    if not papers_df.empty and not links_df.empty:
        links_df = links_df[links_df["paper_id"].isin(set(papers_df["paper_id"].astype(str)))]

    return papers_df, lecturers_df, links_df


def load_local_csv_sample(base_dir: Path, sample_size: int = 50) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Fallback loader for offline notebook runs."""
    lecturer_path = base_dir / "dosen_infokom_final.csv"
    paper_candidates = [
        base_dir / "dosen_papers_scopus_final.csv",
        base_dir / "dosen_papers_scopus.csv",
        base_dir / "dosen_papers_scholar.csv",
    ]

    lecturers_df = pd.read_csv(lecturer_path, dtype=str).fillna("") if lecturer_path.exists() else pd.DataFrame()

    frames = []
    for path in paper_candidates:
        if path.exists():
            frames.append(pd.read_csv(path, dtype=str).fillna(""))

    papers_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not papers_df.empty:
        rename_map = {
            "Title": "title",
            "Abstract": "abstract",
            "Keywords": "keywords",
            "Year": "year",
            "Journal": "journal",
            "Authors": "authors",
            "Author IDs": "author_ids",
            "DOI": "doi",
            "Link": "link",
            "Document Type": "document_type",
        }
        papers_df = papers_df.rename(columns={k: v for k, v in rename_map.items() if k in papers_df.columns})
        if "paper_id" not in papers_df.columns:
            papers_df["paper_id"] = papers_df["title"].map(lambda title: stable_id("paper", title))
        papers_df = papers_df.head(sample_size)

    return papers_df, lecturers_df, pd.DataFrame(columns=["paper_id", "nip"])


class AcademicKGBuilder:
    """Construct a thesis-aligned academic KG as a NetworkX MultiDiGraph."""

    def __init__(
        self,
        ieee_index: IeeeSemanticIndex | None = None,
        concept_resolver: AcademicConceptResolver | None = None,
        extracted_elements: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
        graph_name: str = "yunesa_academic_kg",
    ) -> None:
        self.ieee_index = ieee_index or IeeeSemanticIndex()
        self.concept_resolver = concept_resolver or AcademicConceptResolver()
        self.extracted_elements = extracted_elements or {}
        self.graph_name = graph_name
        self.graph = nx.MultiDiGraph()
        self.stats: Counter[str] = Counter()

    def build(
        self,
        papers_df: pd.DataFrame,
        lecturers_df: pd.DataFrame,
        links_df: pd.DataFrame | None = None,
        max_concepts_per_paper: int = 14,
    ) -> nx.MultiDiGraph:
        links_df = links_df if links_df is not None else pd.DataFrame(columns=["paper_id", "nip"])
        lecturer_by_nip, lecturer_by_author_id, lecturer_by_name = self._build_lecturer_indexes(lecturers_df)

        self._add_lecturers(lecturers_df)

        for _, paper in papers_df.iterrows():
            paper_node = self._add_paper(paper)
            paper_id = field_value(paper, "paper_id", "id", default=paper_node.split(":", 1)[1])

            self._add_publication_dimensions(paper_node, paper)
            self._add_author_edges(
                paper_node=paper_node,
                paper=paper,
                paper_id=paper_id,
                links_df=links_df,
                lecturer_by_nip=lecturer_by_nip,
                lecturer_by_author_id=lecturer_by_author_id,
                lecturer_by_name=lecturer_by_name,
            )
            self._add_keyword_edges(paper_node, paper)
            self._add_concept_edges(paper_node, paper, max_concepts_per_paper)
            self._add_extracted_element_edges(paper_node, paper)

        self._add_collaboration_edges()
        self._add_ieee_relations_between_used_concepts()
        return self.graph

    def _build_lecturer_indexes(
        self,
        lecturers_df: pd.DataFrame,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        by_nip: dict[str, str] = {}
        by_author_id: dict[str, str] = {}
        by_name: dict[str, str] = {}

        for _, row in lecturers_df.iterrows():
            nip = field_value(row, "nip", "NIP")
            name = field_value(row, "nama_norm", "nama_dosen", "name", "Name")
            if not nip and not name:
                continue

            node_id = self._lecturer_node_id(row)
            if nip:
                by_nip[nip] = node_id

            for column in ["scopus_id", "scholar_id", "sinta_id", "Scopus ID", "Scholar ID"]:
                author_id = field_value(row, column)
                if author_id:
                    by_author_id[author_id] = node_id

            if name:
                by_name[normalize_text(name)] = node_id

        return by_nip, by_author_id, by_name

    def _lecturer_node_id(self, row: pd.Series) -> str:
        nip = field_value(row, "nip", "NIP")
        name = field_value(row, "nama_norm", "nama_dosen", "name", "Name")
        return f"lecturer:{slugify(nip)}" if nip else stable_id("lecturer", name)

    def _add_lecturers(self, lecturers_df: pd.DataFrame) -> None:
        for _, row in lecturers_df.iterrows():
            name = field_value(row, "nama_norm", "nama_dosen", "name", "Name")
            if not name:
                continue

            node_id = self._lecturer_node_id(row)
            self.graph.add_node(
                node_id,
                node_type="Lecturer",
                label=name,
                nama_dosen=field_value(row, "nama_dosen", "name", "Name", default=name),
                nama_norm=name,
                nip=field_value(row, "nip", "NIP"),
                nidn=field_value(row, "nidn", "NIDN"),
                prodi=field_value(row, "prodi", "Prodi"),
                scopus_id=field_value(row, "scopus_id", "Scopus ID"),
                scholar_id=field_value(row, "scholar_id", "Scholar ID"),
                sinta_id=field_value(row, "sinta_id", "Sinta ID"),
            )
            self.stats["Lecturer"] += 1

            prodi = field_value(row, "prodi", "Prodi", "program_studi", "Program Studi")
            if prodi:
                institution_node = stable_id("institution", prodi)
                self.graph.add_node(
                    institution_node,
                    node_type="Institution",
                    label=prodi,
                    name=prodi,
                    institution_type="ProgramStudy",
                )
                self.graph.add_edge(node_id, institution_node, relation="HAS_AFFILIATION", source="lecturer_metadata")
                self.stats["HAS_AFFILIATION"] += 1

    def _paper_node_id(self, paper: pd.Series | dict[str, Any]) -> str:
        paper_id = field_value(paper, "paper_id", "id")
        title = field_value(paper, "title", "Title")
        return f"paper:{slugify(paper_id)}" if paper_id else stable_id("paper", title)

    def _add_paper(self, paper: pd.Series) -> str:
        node_id = self._paper_node_id(paper)
        paper_id = field_value(paper, "paper_id", "id")
        title = field_value(paper, "title", "Title")
        venue_raw = field_value(paper, "journal", "Journal")
        venue = canonical_venue_name(venue_raw)
        self.graph.add_node(
            node_id,
            node_type="Publication",
            label=title,
            paper_id=paper_id or node_id,
            title=title,
            abstract=field_value(paper, "abstract", "Abstract"),
            tldr=field_value(paper, "tldr", "TLDR"),
            keywords=field_value(paper, "keywords", "Keywords"),
            year=field_value(paper, "year", "Year"),
            venue=venue,
            venue_raw=venue_raw,
            document_type=canonical_document_type(field_value(paper, "document_type", "Document Type")),
            doi=field_value(paper, "doi", "DOI"),
            link=field_value(paper, "link", "Link"),
        )
        self.stats["Publication"] += 1
        return node_id

    def _add_publication_dimensions(self, paper_node: str, paper: pd.Series) -> None:
        year = field_value(paper, "year", "Year")
        if year:
            year_value = safe_str(year)[:4]
            year_node = f"year:{slugify(year_value)}"
            self.graph.add_node(year_node, node_type="Year", label=year_value, value=year_value)
            self.graph.add_edge(paper_node, year_node, relation="PUBLISHED_IN_YEAR", source="paper_metadata")
            self.stats["PUBLISHED_IN_YEAR"] += 1

        venue = field_value(paper, "journal", "Journal")
        if venue:
            venue_clean = canonical_venue_name(venue)
            if not venue_clean:
                return
            venue_node = stable_id("venue", venue_clean)
            self.graph.add_node(venue_node, node_type="Venue", label=venue_clean, name=venue_clean)
            self.graph.add_edge(paper_node, venue_node, relation="PUBLISHED_IN_VENUE", source="paper_metadata")
            self.stats["PUBLISHED_IN_VENUE"] += 1

    def _add_author_edges(
        self,
        paper_node: str,
        paper: pd.Series,
        paper_id: str,
        links_df: pd.DataFrame,
        lecturer_by_nip: dict[str, str],
        lecturer_by_author_id: dict[str, str],
        lecturer_by_name: dict[str, str],
    ) -> None:
        linked = False

        if not links_df.empty and {"paper_id", "nip"}.issubset(set(links_df.columns)):
            rows = links_df[links_df["paper_id"].astype(str) == safe_str(paper_id)]
            for _, link in rows.iterrows():
                lecturer_node = lecturer_by_nip.get(safe_str(link.get("nip")))
                if lecturer_node:
                    self._add_author_pair(paper_node, lecturer_node, source="paper_lecturers")
                    linked = True

        author_ids = split_list_field(field_value(paper, "author_ids", "Author IDs"))
        for author_id in author_ids:
            lecturer_node = lecturer_by_author_id.get(author_id)
            if lecturer_node and not has_relation(self.graph, paper_node, lecturer_node, "HAS_AUTHOR"):
                self._add_author_pair(paper_node, lecturer_node, source="author_id")
                linked = True

        if linked:
            return

        for author_name in split_list_field(field_value(paper, "authors", "Authors")):
            lecturer_node = lecturer_by_name.get(normalize_text(author_name))
            if lecturer_node and not has_relation(self.graph, paper_node, lecturer_node, "HAS_AUTHOR"):
                self._add_author_pair(paper_node, lecturer_node, source="author_name")

    def _add_author_pair(self, paper_node: str, lecturer_node: str, *, source: str) -> None:
        """Add both query-friendly author directions without relying on inverse traversal."""
        if not has_relation(self.graph, paper_node, lecturer_node, "HAS_AUTHOR"):
            self.graph.add_edge(paper_node, lecturer_node, relation="HAS_AUTHOR", source=source)
            self.stats["HAS_AUTHOR"] += 1
        if not has_relation(self.graph, lecturer_node, paper_node, "PUBLISHES"):
            self.graph.add_edge(lecturer_node, paper_node, relation="PUBLISHES", source=source)
            self.stats["PUBLISHES"] += 1

    def _add_collaboration_edges(self) -> None:
        """Derive canonical lecturer collaboration edges from shared publications."""
        pair_to_papers: dict[tuple[str, str], dict[str, Any]] = {}
        for paper_node, paper_data in self.graph.nodes(data=True):
            if paper_data.get("node_type") != "Publication":
                continue
            lecturers: list[str] = []
            for _, target, edge_data in self.graph.out_edges(paper_node, data=True):
                if canonical_relation(edge_data.get("relation")) != "HAS_AUTHOR":
                    continue
                if self.graph.nodes[target].get("node_type") == "Lecturer":
                    lecturers.append(target)
            lecturers = sorted(dict.fromkeys(lecturers))
            if len(lecturers) < 2:
                continue

            paper_id = field_value(paper_data, "paper_id", default=paper_node)
            paper_title = field_value(paper_data, "title", "label", default=paper_node)
            for idx, source in enumerate(lecturers):
                for target in lecturers[idx + 1 :]:
                    pair = (source, target)
                    payload = pair_to_papers.setdefault(pair, {"paper_ids": [], "paper_titles": []})
                    payload["paper_ids"].append(paper_id)
                    payload["paper_titles"].append(paper_title)

        for (source, target), payload in pair_to_papers.items():
            paper_ids = list(dict.fromkeys(payload["paper_ids"]))
            paper_titles = list(dict.fromkeys(payload["paper_titles"]))
            if has_relation(self.graph, source, target, "COLLABORATES_WITH"):
                for edge_data in self.graph.get_edge_data(source, target, default={}).values():
                    if canonical_relation(edge_data.get("relation")) == "COLLABORATES_WITH":
                        edge_data.update(
                            paper_count=len(paper_ids),
                            paper_ids=paper_ids,
                            paper_titles=paper_titles,
                            source="coauthorship",
                            graph_name=self.graph_name,
                        )
                continue
            self.graph.add_edge(
                source,
                target,
                relation="COLLABORATES_WITH",
                source="coauthorship",
                graph_name=self.graph_name,
                paper_count=len(paper_ids),
                paper_ids=paper_ids,
                paper_titles=paper_titles,
            )
            self.stats["COLLABORATES_WITH"] += 1

    def _add_keyword_edges(self, paper_node: str, paper: pd.Series) -> None:
        for keyword in split_list_field(field_value(paper, "keywords", "Keywords")):
            key_node = stable_id("keyword", normalize_text(keyword))
            self.graph.add_node(key_node, node_type="Keyword", label=keyword, name=keyword)
            self.graph.add_edge(paper_node, key_node, relation="HAS_KEYWORD", source="paper_metadata")
            self.stats["HAS_KEYWORD"] += 1

    def _add_or_update_concept_node(self, resolved: dict[str, Any], *, source: Any = "", ieee_uri: Any = "") -> str:
        canonical_key = safe_str(resolved.get("canonical_key"))
        concept_type = canonical_concept_type(resolved.get("concept_type"), fallback_label=resolved.get("label"))
        concept_node = stable_id("concept", f"{concept_type}:{canonical_key}")
        raw_label = safe_str(resolved.get("raw_label") or resolved.get("label"))
        label = safe_str(resolved.get("canonical_label") or resolved.get("label") or raw_label)

        existing = self.graph.nodes[concept_node] if self.graph.has_node(concept_node) else {}
        raw_labels = split_list_field(existing.get("raw_labels", ""))
        if raw_label and raw_label not in raw_labels:
            raw_labels.append(raw_label)
        sources = split_list_field(existing.get("resolution_sources", ""))
        resolution_source = safe_str(resolved.get("resolution_source") or source)
        if resolution_source and resolution_source not in sources:
            sources.append(resolution_source)
        ieee_uris = split_list_field(existing.get("ieee_uris", ""))
        current_ieee_uri = safe_str(ieee_uri)
        if current_ieee_uri and current_ieee_uri not in ieee_uris:
            ieee_uris.append(current_ieee_uri)

        primary_ieee_uri = safe_str(existing.get("ieee_uri")) or current_ieee_uri

        self.graph.add_node(
            concept_node,
            node_type="Concept",
            concept_type=concept_type,
            label=label,
            name=label,
            canonical_label=label,
            canonical_key=canonical_key,
            raw_labels=", ".join(raw_labels),
            resolution_source=resolution_source,
            resolution_sources=", ".join(sources),
            ieee_uri=primary_ieee_uri,
            ieee_uris=", ".join(ieee_uris),
            source=safe_str(source) or safe_str(existing.get("source")),
        )
        return concept_node

    def _add_concept_edges(self, paper_node: str, paper: pd.Series, max_concepts: int) -> None:
        concepts = extract_concepts_for_paper(paper, self.ieee_index, max_concepts=max_concepts)
        for concept in concepts:
            label = concept["label"]
            resolved = self.concept_resolver.resolve(
                label=label,
                concept_type=concept.get("concept_type"),
                ieee_uri=concept.get("uri", ""),
                source=concept.get("source", ""),
            )
            concept_type = canonical_concept_type(resolved.get("concept_type"), fallback_label=resolved.get("label"))
            concept_node = self._add_or_update_concept_node(resolved, source=concept.get("source", ""), ieee_uri=concept.get("uri", ""))
            relation = CONCEPT_EDGE_BY_TYPE[concept_type]
            self.graph.add_edge(
                paper_node,
                concept_node,
                relation=relation,
                source=concept.get("source", ""),
                match_type=concept.get("match_type", ""),
                matched_text=concept.get("match", ""),
                score=float(concept.get("score", 0.0)),
                canonical_label=resolved.get("canonical_label", ""),
                canonical_key=resolved.get("canonical_key", ""),
                metric_value=safe_str(resolved.get("metric_value", "")),
                metric_unit=resolved.get("metric_unit", ""),
                resolution_source=resolved.get("resolution_source", ""),
                provenance=json.dumps(
                    {
                        "matched_label": concept.get("matched_label", ""),
                        "ieee_uri": concept.get("uri", ""),
                        "source": concept.get("source", ""),
                        "raw_label": resolved.get("raw_label", ""),
                        "canonical_label": resolved.get("canonical_label", ""),
                        "canonical_key": resolved.get("canonical_key", ""),
                        "metric_value": resolved.get("metric_value", ""),
                        "metric_unit": resolved.get("metric_unit", ""),
                        "resolution_source": resolved.get("resolution_source", ""),
                    },
                    ensure_ascii=False,
                ),
            )
            self.stats[relation] += 1

    def _concept_node_from_extracted_entity(self, entity: dict[str, Any]) -> str:
        label = safe_str(entity.get("text") or entity.get("label"))
        resolved = self.concept_resolver.resolve(
            label=label,
            concept_type=entity.get("concept_type"),
            source=entity.get("source", "gliner"),
        )
        entity["resolved"] = resolved
        return self._add_or_update_concept_node(resolved, source=entity.get("source", "gliner"), ieee_uri="")

    def _add_extracted_element_edges(self, paper_node: str, paper: pd.Series) -> None:
        doc_id = academic_document_id(paper)
        extraction = self.extracted_elements.get(doc_id)
        if not extraction:
            return

        entity_node_by_text: dict[str, str] = {}
        for entity in extraction.get("entities", []):
            label = safe_str(entity.get("text") or entity.get("label"))
            if not label:
                continue
            concept_type = canonical_concept_type(entity.get("concept_type"), fallback_label=label)
            entity["concept_type"] = concept_type
            concept_node = self._concept_node_from_extracted_entity(entity)
            resolved = entity.get("resolved", {})
            entity_node_by_text[normalize_text(label)] = concept_node
            resolved_type = canonical_concept_type(resolved.get("concept_type") or concept_type, fallback_label=label)
            relation = CONCEPT_EDGE_BY_TYPE.get(resolved_type, "WORKS_ON")
            self.graph.add_edge(
                paper_node,
                concept_node,
                relation=relation,
                source=entity.get("source", "gliner"),
                match_type="zero_shot_ner",
                matched_text=label,
                score=float(entity.get("score") or 0.0),
                canonical_label=resolved.get("canonical_label", ""),
                canonical_key=resolved.get("canonical_key", ""),
                metric_value=safe_str(resolved.get("metric_value", "")),
                metric_unit=resolved.get("metric_unit", ""),
                resolution_source=resolved.get("resolution_source", ""),
                provenance=json.dumps(
                    {
                        "extractor": entity.get("source", "gliner"),
                        "label": entity.get("label", ""),
                        "paper_id": doc_id,
                        "start": entity.get("start"),
                        "end": entity.get("end"),
                        "canonical_label": resolved.get("canonical_label", ""),
                        "canonical_key": resolved.get("canonical_key", ""),
                        "resolution_source": resolved.get("resolution_source", ""),
                    },
                    ensure_ascii=False,
                ),
            )
            self.stats[relation] += 1

        for relation in extraction.get("relationships", []):
            head_node = entity_node_by_text.get(normalize_text(relation.get("head")))
            tail_node = entity_node_by_text.get(normalize_text(relation.get("tail")))
            if not head_node or not tail_node or head_node == tail_node:
                continue
            rel_type = canonical_relation(relation.get("relation"))
            self.graph.add_edge(
                head_node,
                tail_node,
                relation=rel_type,
                source=relation.get("source", "glirel"),
                match_type="zero_shot_re",
                matched_text=relation.get("label", ""),
                score=float(relation.get("score") or 0.0),
                provenance=json.dumps(
                    {
                        "extractor": relation.get("source", "glirel"),
                        "label": relation.get("label", ""),
                        "paper_id": doc_id,
                    },
                    ensure_ascii=False,
                ),
            )
            self.stats[rel_type] += 1

    def _add_ieee_relations_between_used_concepts(self) -> None:
        uri_to_node = {
            data.get("ieee_uri"): node_id
            for node_id, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Concept" and data.get("ieee_uri")
        }
        initially_used_uris = set(uri_to_node)

        for source_uri, target_uri, relation in self.ieee_index.uri_relations:
            src = uri_to_node.get(source_uri)
            tgt = uri_to_node.get(target_uri)
            if src and not tgt and source_uri in initially_used_uris:
                tgt = self._add_ieee_neighbor_concept(target_uri)
                if tgt:
                    uri_to_node[target_uri] = tgt
            if tgt and not src and target_uri in initially_used_uris:
                src = self._add_ieee_neighbor_concept(source_uri)
                if src:
                    uri_to_node[source_uri] = src
            if src and tgt:
                self.graph.add_edge(src, tgt, relation=relation, source="ieee_skos")
                self.stats[relation] += 1

    def _add_ieee_neighbor_concept(self, uri: str) -> str:
        label = self.ieee_index.uri_to_label.get(uri)
        if not label:
            return ""
        concept_type = infer_concept_type(label)
        if concept_type in {"Problem", "ResearchTopic"}:
            concept_type = "Domain"
        resolved = self.concept_resolver.resolve(
            label=label,
            concept_type=concept_type,
            ieee_uri=uri,
            source="ieee_skos_neighbor",
        )
        return self._add_or_update_concept_node(resolved, source="ieee_skos_neighbor", ieee_uri=uri)

    def validate(self) -> dict[str, Any]:
        node_type_counts = Counter(data.get("node_type", "Unknown") for _, data in self.graph.nodes(data=True))
        edge_counts = Counter(data.get("relation", "UNKNOWN") for _, _, data in self.graph.edges(data=True))
        concept_source_counts = Counter(
            data.get("source", "unknown") or "unknown"
            for _, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Concept"
        )
        concept_type_counts = Counter(
            data.get("concept_type", "unknown") or "unknown"
            for _, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Concept"
        )
        concepts_with_ieee_uri = sum(
            1
            for _, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Concept" and data.get("ieee_uri")
        )
        paper_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "Publication"]
        papers_without_concepts = []
        papers_without_authors = []

        for paper_node in paper_nodes:
            outgoing_relations = [data.get("relation") for _, _, data in self.graph.out_edges(paper_node, data=True)]
            incoming_relations = [data.get("relation") for _, _, data in self.graph.in_edges(paper_node, data=True)]
            if not any(canonical_relation(rel) in CONCEPT_RELATIONS for rel in outgoing_relations):
                papers_without_concepts.append(paper_node)
            has_author = any(canonical_relation(rel) == "HAS_AUTHOR" for rel in outgoing_relations) or any(
                canonical_relation(rel) == "PUBLISHES" for rel in incoming_relations
            )
            if not has_author:
                papers_without_authors.append(paper_node)

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_type_counts": dict(node_type_counts),
            "edge_counts": dict(edge_counts),
            "concept_type_counts": dict(concept_type_counts),
            "concept_source_counts": dict(concept_source_counts),
            "concepts_with_ieee_uri": concepts_with_ieee_uri,
            "concepts_without_ieee_uri": int(node_type_counts.get("Concept", 0) - concepts_with_ieee_uri),
            "papers_without_concepts": papers_without_concepts,
            "papers_without_authors": papers_without_authors,
        }


def graph_to_frames(graph: nx.MultiDiGraph) -> tuple[pd.DataFrame, pd.DataFrame]:
    node_rows = []
    for node_id, data in graph.nodes(data=True):
        row = {"id": node_id, **data}
        node_rows.append(row)

    edge_rows = []
    for source, target, key, data in graph.edges(keys=True, data=True):
        row = {"source": source, "target": target, "key": key}
        for attr, value in data.items():
            # Preserve source/target as graph endpoint columns in CSV exports.
            safe_attr = f"edge_{attr}" if attr in row else attr
            row[safe_attr] = value
        edge_rows.append(row)

    return pd.DataFrame(node_rows), pd.DataFrame(edge_rows)


def _serialise_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def serialisable_graph_copy(graph: nx.MultiDiGraph) -> nx.MultiDiGraph:
    cleaned = nx.MultiDiGraph()
    for node_id, data in graph.nodes(data=True):
        cleaned.add_node(node_id, **{key: _serialise_value(value) for key, value in data.items()})
    for source, target, key, data in graph.edges(keys=True, data=True):
        cleaned.add_edge(
            source,
            target,
            key=key,
            **{attr: _serialise_value(value) for attr, value in data.items()},
        )
    return cleaned


def export_graph_artifacts(graph: nx.MultiDiGraph, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    nodes_df, edges_df = graph_to_frames(graph)

    paths = {
        "nodes_csv": output_dir / "academic_kg_nodes.csv",
        "edges_csv": output_dir / "academic_kg_edges.csv",
        "node_link_json": output_dir / "academic_kg_node_link.json",
        "graphml": output_dir / "academic_kg.graphml",
        "summary_json": output_dir / "academic_kg_summary.json",
    }

    nodes_df.to_csv(paths["nodes_csv"], index=False, encoding="utf-8")
    edges_df.to_csv(paths["edges_csv"], index=False, encoding="utf-8")

    from networkx.readwrite import json_graph

    serialisable = serialisable_graph_copy(graph)
    paths["node_link_json"].write_text(
        json.dumps(json_graph.node_link_data(serialisable), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    nx.write_graphml(serialisable, paths["graphml"])

    summary = {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "node_type_counts": dict(Counter(d.get("node_type", "Unknown") for _, d in graph.nodes(data=True))),
        "edge_counts": dict(Counter(canonical_relation(d.get("relation", "UNKNOWN")) for _, _, d in graph.edges(data=True))),
    }
    paths["summary_json"].write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return paths


def academicrag_storage_plan() -> dict[str, Any]:
    """Describe the adapted AcademicRAG storage layout for this thesis project."""
    return {
        "artifact_store": {
            "backend": "Notebook output files and Supabase source tables",
            "purpose": "Rebuildable source/artifact layer, analogous to the document/KV side of AcademicRAG.",
            "stores": [
                "academic_kg_nodes.csv and academic_kg_edges.csv",
                "academic_kg_node_link.json and academic_kg.graphml",
                "Supabase papers, lecturers, and paper_lecturers source tables",
            ],
        },
        "graph_store": {
            "backend": "Neo4j/AuraDB",
            "purpose": "Authoritative property graph for structural and semantic relations.",
            "stores": [
                "Lecturer, Publication, Venue, Year, Keyword, Institution, and Concept nodes",
                "WRITES, PUBLISHED_IN_YEAR, PUBLISHED_IN_VENUE, HAS_KEYWORD, and concept relations",
                "IEEE SKOS grounding edges and provenance attributes",
            ],
        },
        "vector_store": {
            "backend": "Milvus/Zilliz Cloud",
            "purpose": "Approximate semantic retrieval for GraphRAG context assembly.",
            "collections": {
                "PaperChunk": "Publication-level text units: title, TLDR, abstract, keywords, concepts, authors.",
                "EntityEmbedding": "Searchable node/entity descriptions from the KG.",
                "RelationshipEmbedding": "Searchable relationship descriptions from graph triples.",
                "ContentKeyword": "Controlled keyword strings per paper for topic-level retrieval.",
            },
        },
        "query_modes": {
            "subgraph": "Use low-level keywords to match entities, then retrieve a Neo4j shortest-path subgraph.",
            "naive": "Use Milvus PaperChunk similarity search.",
            "global": "Use high-level keywords to retrieve RelationshipEmbedding records for broader graph context.",
            "hybrid": "Fuse subgraph and global relationship retrieval.",
            "mix": "Fuse chunk retrieval, content keyword clues, subgraph retrieval, and global edge retrieval.",
        },
    }


def _truncate_utf8(value: Any, max_bytes: int, *, suffix: str = "...") -> str:
    """Return text that fits a byte-oriented VARCHAR limit.

    Milvus validates VARCHAR lengths in UTF-8 bytes, not Python characters.
    Slicing the Unicode string directly can therefore still exceed the schema
    limit when the value contains curly quotes, dashes, or non-ASCII text.
    """
    text = safe_str(value)
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    suffix_bytes = suffix.encode("utf-8")
    if len(suffix_bytes) >= max_bytes:
        return encoded[:max_bytes].decode("utf-8", errors="ignore")

    budget = max_bytes - len(suffix_bytes)
    prefix = encoded[:budget].decode("utf-8", errors="ignore").rstrip()
    while len((prefix + suffix).encode("utf-8")) > max_bytes:
        prefix = prefix[:-1]
    return prefix + suffix


def _truncate_milvus(collection_name: str, field_name: str, value: Any) -> str:
    text = safe_str(value)
    limit = MILVUS_VARCHAR_LIMITS.get(collection_name, {}).get(field_name)
    return _truncate_utf8(text, limit) if limit else text


def _validate_milvus_varchar_records(
    records_by_collection: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Fail before embedding or destructive writes when a row violates schema."""
    checked_fields = 0
    maximum_bytes: dict[str, dict[str, int]] = {}
    violations: list[dict[str, Any]] = []

    for collection_name, rows in records_by_collection.items():
        limits = MILVUS_VARCHAR_LIMITS.get(collection_name, {})
        collection_maximum: dict[str, int] = {field: 0 for field in limits}
        for row_index, row in enumerate(rows):
            for field_name, limit in limits.items():
                length = len(safe_str(row.get(field_name)).encode("utf-8"))
                checked_fields += 1
                collection_maximum[field_name] = max(collection_maximum[field_name], length)
                if length > limit:
                    violations.append(
                        {
                            "collection": collection_name,
                            "row": row_index,
                            "field": field_name,
                            "bytes": length,
                            "limit": limit,
                        }
                    )
        maximum_bytes[collection_name] = collection_maximum

    if violations:
        preview = ", ".join(
            f"{item['collection']}[{item['row']}].{item['field']}={item['bytes']}>{item['limit']}"
            for item in violations[:10]
        )
        raise ValueError(f"Milvus VARCHAR preflight failed: {preview}")

    return {
        "collections": len(records_by_collection),
        "rows": sum(len(rows) for rows in records_by_collection.values()),
        "checked_fields": checked_fields,
        "maximum_bytes": maximum_bytes,
    }


def _embedding_cache_path() -> Path | None:
    configured = os.getenv("YUNESA_EMBEDDING_CACHE_PATH", "").strip()
    if configured.lower() in {"0", "off", "false", "none", "disabled"}:
        return None
    if configured:
        return Path(configured)
    if Path("/app/data").is_dir():
        return Path("/app/data/kg/cache/embeddings.sqlite3")
    return None


class _EmbeddingCache:
    """Small persistent SQLite cache keyed by provider, model, and text hash."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.connection: sqlite3.Connection | None = None
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                cache_key TEXT PRIMARY KEY,
                dimension INTEGER NOT NULL,
                vector BLOB NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self.connection.commit()

    @staticmethod
    def key(provider: str, model_name: str, text: str) -> str:
        payload = f"{provider}\0{model_name}\0{text}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def get_many(self, keys: list[str]) -> dict[str, list[float]]:
        if self.connection is None or not keys:
            return {}
        result: dict[str, list[float]] = {}
        for start in range(0, len(keys), 500):
            batch = keys[start : start + 500]
            placeholders = ",".join("?" for _ in batch)
            query = f"SELECT cache_key, dimension, vector FROM embeddings WHERE cache_key IN ({placeholders})"
            for cache_key, dimension, blob in self.connection.execute(query, batch):
                values = array("f")
                values.frombytes(blob)
                if len(values) == int(dimension):
                    result[str(cache_key)] = [float(value) for value in values]
        return result

    def put_many(self, values: dict[str, list[float]]) -> None:
        if self.connection is None or not values:
            return
        rows = []
        now = time.time()
        for cache_key, vector in values.items():
            packed = array("f", (float(value) for value in vector)).tobytes()
            rows.append((cache_key, len(vector), packed, now))
        self.connection.executemany(
            "INSERT OR REPLACE INTO embeddings(cache_key, dimension, vector, created_at) VALUES (?, ?, ?, ?)",
            rows,
        )
        self.connection.commit()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __enter__(self) -> "_EmbeddingCache":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def _node_label(data: dict[str, Any], node_id: str) -> str:
    return field_value(data, "label", "name", "title", "nama_norm", default=node_id)


def _node_source_id(data: dict[str, Any], node_id: str) -> str:
    return field_value(
        data,
        "paper_id",
        "nip",
        "scopus_id",
        "scholar_id",
        "ieee_uri",
        "value",
        default=node_id,
    )


def _node_description(node_id: str, data: dict[str, Any]) -> str:
    node_type = field_value(data, "node_type", default="KGNode")
    label = _node_label(data, node_id)
    parts = [f"{node_type}: {label}"]

    if node_type == "Publication":
        for key in ["title", "tldr", "abstract", "keywords", "document_type", "year", "venue"]:
            value = field_value(data, key)
            if value:
                parts.append(f"{key}: {value}")
    elif node_type == "Lecturer":
        for key in ["nama_dosen", "prodi", "nidn", "scopus_id", "scholar_id", "sinta_id"]:
            value = field_value(data, key)
            if value:
                parts.append(f"{key}: {value}")
    elif node_type == "Concept":
        for key in ["concept_type", "source", "ieee_uri"]:
            value = field_value(data, key)
            if value:
                parts.append(f"{key}: {value}")
    else:
        for key in ["name", "value", "institution_type", "source"]:
            value = field_value(data, key)
            if value:
                parts.append(f"{key}: {value}")

    return " | ".join(parts)


def _publication_concept_labels(graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
    labels: list[str] = []
    for _, target, data in graph.out_edges(paper_node, data=True):
        if canonical_relation(data.get("relation")) not in CONCEPT_RELATIONS:
            continue
        target_data = graph.nodes[target]
        label = _node_label(target_data, target)
        if label:
            labels.append(label)
    return list(dict.fromkeys(labels))


def _publication_author_labels(graph: nx.MultiDiGraph, paper_node: str) -> list[str]:
    labels: list[str] = []
    for _, target, data in graph.out_edges(paper_node, data=True):
        if canonical_relation(data.get("relation")) != "HAS_AUTHOR":
            continue
        target_data = graph.nodes[target]
        label = _node_label(target_data, target)
        if label:
            labels.append(label)
    for source, _, data in graph.in_edges(paper_node, data=True):
        if canonical_relation(data.get("relation")) not in {"PUBLISHES", "WRITES"}:
            continue
        source_data = graph.nodes[source]
        label = _node_label(source_data, source)
        if label:
            labels.append(label)
    return list(dict.fromkeys(labels))


def _publication_document_payload(graph: nx.MultiDiGraph, paper_node: str) -> dict[str, Any]:
    data = graph.nodes[paper_node]
    concepts = _publication_concept_labels(graph, paper_node)
    authors = _publication_author_labels(graph, paper_node)
    keywords = split_list_field(field_value(data, "keywords"))
    doc_text = "\n".join(
        part
        for part in [
            f"Title: {field_value(data, 'title', 'label')}",
            f"TLDR: {field_value(data, 'tldr')}",
            f"Abstract: {field_value(data, 'abstract')}",
            f"Keywords: {', '.join(keywords)}",
            f"Concepts: {', '.join(concepts)}",
            f"Authors: {', '.join(authors)}",
            f"Document type: {field_value(data, 'document_type')}",
            f"DOI: {field_value(data, 'doi')}",
            f"Link: {field_value(data, 'link')}",
        ]
        if not part.endswith(": ")
    )
    doc_id = field_value(data, "paper_id", default=paper_node)
    return {
        "doc_id": doc_id,
        "paper_node": paper_node,
        "title": field_value(data, "title", "label"),
        "content": doc_text,
        "content_hash": content_hash(doc_text),
        "year": field_value(data, "year"),
        "paperUrl": field_value(data, "link", "doi"),
        "authors": ", ".join(authors),
        "keywords": ", ".join(keywords),
        "concepts": ", ".join(concepts),
    }


def build_academicrag_document_records(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Build document status and text chunk records analogous to AcademicRAG KV stores."""
    full_docs: list[dict[str, Any]] = []
    text_chunks: list[dict[str, Any]] = []
    doc_status: list[dict[str, Any]] = []

    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != "Publication":
            continue
        payload = _publication_document_payload(graph, node_id)
        chunks = semantic_text_chunks(payload["content"])
        full_docs.append(
            {
                "doc_id": payload["doc_id"],
                "paper_node": node_id,
                "content": payload["content"],
                "content_hash": payload["content_hash"],
                "title": payload["title"],
                "source": "supabase.papers",
            }
        )
        doc_status.append(
            {
                "doc_id": payload["doc_id"],
                "content_hash": payload["content_hash"],
                "status": "processed",
                "chunks_count": len(chunks),
                "content_length": len(payload["content"]),
                "source": "notebook_kg_construction",
            }
        )
        for index, chunk in enumerate(chunks):
            chunk_id = stable_id("chunk", f"{payload['doc_id']}:{index}:{chunk}")
            text_chunks.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": payload["doc_id"],
                    "paper_node": node_id,
                    "chunk_order_index": index,
                    "content": chunk,
                    "content_hash": content_hash(chunk),
                    "tokens_estimate": max(1, len(chunk.split())),
                    "source": "notebook_kg_construction",
                }
            )

    return {
        "full_docs": full_docs,
        "text_chunks": text_chunks,
        "doc_status": doc_status,
    }


def summarize_academicrag_document_records(records: dict[str, Any]) -> dict[str, int]:
    return {key: len(value) for key, value in records.items()}


def _paper_chunk_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != "Publication":
            continue
        payload = _publication_document_payload(graph, node_id)
        for index, chunk in enumerate(semantic_text_chunks(payload["content"])):
            content = (
                f"doc_id: {payload['doc_id']} | chunk_order_index: {index} | "
                f"content_hash: {content_hash(chunk)} | {chunk}"
            )
            rows.append(
                {
                    "graphName": _truncate_milvus("PaperChunk", "graphName", graph_name),
                    "title": _truncate_milvus("PaperChunk", "title", payload["title"]),
                    "content": _truncate_milvus("PaperChunk", "content", content),
                    "year": _truncate_milvus("PaperChunk", "year", payload["year"]),
                    "paperUrl": _truncate_milvus("PaperChunk", "paperUrl", payload["paperUrl"]),
                    "authors": _truncate_milvus("PaperChunk", "authors", payload["authors"]),
                    "_embedding_text": content,
                }
            )
    return rows


def _entity_embedding_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        node_type = field_value(data, "concept_type", "node_type", default="KGNode")
        if data.get("node_type") == "Year":
            continue
        label = _node_label(data, node_id)
        description = _node_description(node_id, data)
        rows.append(
            {
                "graphName": _truncate_milvus("EntityEmbedding", "graphName", graph_name),
                "entityName": _truncate_milvus("EntityEmbedding", "entityName", label),
                "entityType": _truncate_milvus("EntityEmbedding", "entityType", node_type),
                "description": _truncate_milvus("EntityEmbedding", "description", description),
                "nodeId": _truncate_milvus("EntityEmbedding", "nodeId", node_id),
                "sourceId": _truncate_milvus("EntityEmbedding", "sourceId", _node_source_id(data, node_id)),
                "_embedding_text": description,
            }
        )
    return rows


def _relationship_embedding_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source, target, key, data in graph.edges(keys=True, data=True):
        source_data = graph.nodes[source]
        target_data = graph.nodes[target]
        rel_type = canonical_relation(field_value(data, "relation", default="RELATED_TO"))
        source_label = _node_label(source_data, source)
        target_label = _node_label(target_data, target)
        provenance = field_value(data, "provenance", "source")
        description = (
            f"{source_label} ({source_data.get('node_type', 'Node')}) "
            f"-[{rel_type}]-> "
            f"{target_label} ({target_data.get('node_type', 'Node')})"
        )
        if provenance:
            description += f" | provenance: {provenance}"
        rows.append(
            {
                "graphName": _truncate_milvus("RelationshipEmbedding", "graphName", graph_name),
                "srcId": _truncate_milvus("RelationshipEmbedding", "srcId", source),
                "tgtId": _truncate_milvus("RelationshipEmbedding", "tgtId", target),
                "relType": _truncate_milvus("RelationshipEmbedding", "relType", rel_type),
                "description": _truncate_milvus("RelationshipEmbedding", "description", description),
                "sourceId": _truncate_milvus(
                    "RelationshipEmbedding",
                    "sourceId",
                    f"{_node_source_id(source_data, source)}::{_node_source_id(target_data, target)}::{key}",
                ),
                "_embedding_text": description,
            }
        )
    return rows


def _content_keyword_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node_id, data in graph.nodes(data=True):
        if data.get("node_type") != "Publication":
            continue
        title = field_value(data, "title", "label", default=node_id)
        terms = split_list_field(field_value(data, "keywords"))
        terms.extend(_publication_concept_labels(graph, node_id))
        terms = list(dict.fromkeys(term for term in terms if safe_str(term)))
        if not terms:
            continue
        keywords = ", ".join(terms)
        rows.append(
            {
                "graphName": _truncate_milvus("ContentKeyword", "graphName", graph_name),
                "keywords": _truncate_milvus("ContentKeyword", "keywords", keywords),
                "sourcePaper": _truncate_milvus("ContentKeyword", "sourcePaper", title),
                "_embedding_text": f"{title}: {keywords}",
            }
        )
    return rows


def build_milvus_index_records(graph: nx.MultiDiGraph, *, graph_name: str = "") -> dict[str, list[dict[str, Any]]]:
    """Build Milvus rows without embeddings for previewing and deterministic export."""
    return {
        "PaperChunk": _paper_chunk_records(graph, graph_name=graph_name),
        "EntityEmbedding": _entity_embedding_records(graph, graph_name=graph_name),
        "RelationshipEmbedding": _relationship_embedding_records(graph, graph_name=graph_name),
        "ContentKeyword": _content_keyword_records(graph, graph_name=graph_name),
    }


def summarize_milvus_records(records_by_collection: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    return {collection: len(rows) for collection, rows in records_by_collection.items()}


@lru_cache(maxsize=4)
def _load_sentence_transformer_model(model_name: str):
    try:
        from huggingface_hub.utils import disable_progress_bars

        disable_progress_bars()
    except Exception:
        pass
    try:
        from transformers.utils import logging as transformers_logging

        transformers_logging.set_verbosity_error()
    except Exception:
        pass
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install sentence-transformers first.") from exc
    return SentenceTransformer(model_name)


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _positive_env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _siliconflow_embeddings(
    texts: list[str],
    *,
    model_name: str,
    split_depth: int = 0,
) -> list[list[float]]:
    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        raise ValueError("Set SILICONFLOW_API_KEY first for SiliconFlow embeddings.")

    import requests

    url = os.getenv("SILICONFLOW_EMBEDDING_URL", "https://api.siliconflow.com/v1/embeddings")
    timeout = _positive_env_float("SILICONFLOW_EMBEDDING_TIMEOUT", 120.0)
    max_attempts = _positive_env_int("SILICONFLOW_EMBEDDING_MAX_ATTEMPTS", 5)
    base_delay = _positive_env_float("SILICONFLOW_EMBEDDING_RETRY_BASE_SECONDS", 2.0)
    max_delay = _positive_env_float("SILICONFLOW_EMBEDDING_RETRY_MAX_SECONDS", 30.0)
    max_split_depth = _positive_env_int("SILICONFLOW_EMBEDDING_MAX_SPLIT_DEPTH", 2)
    retry_statuses = {408, 409, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        request_started = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model_name, "input": texts},
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = sorted(payload.get("data") or [], key=lambda item: int(item.get("index", 0)))
            vectors = [item.get("embedding") for item in data]
            if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
                raise RuntimeError(
                    f"SiliconFlow returned {len(vectors)} valid embeddings for {len(texts)} texts."
                )
            return vectors
        except requests.RequestException as exc:
            last_error = exc
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            retryable = status is None or status in retry_statuses
            elapsed = time.perf_counter() - request_started
            if retryable and attempt < max_attempts:
                retry_after = 0.0
                if response is not None:
                    try:
                        retry_after = float(response.headers.get("Retry-After", "0") or 0)
                    except (TypeError, ValueError):
                        retry_after = 0.0
                exponential = min(max_delay, base_delay * (2 ** (attempt - 1)))
                delay = max(retry_after, exponential * random.uniform(0.8, 1.2))
                logger.warning(
                    "embedding.provider.retry | provider=siliconflow | model=%s | status=%s | "
                    "attempt=%s/%s | batch_size=%s | elapsed_seconds=%.3f | delay_seconds=%.3f",
                    model_name,
                    status or "network_error",
                    attempt,
                    max_attempts,
                    len(texts),
                    elapsed,
                    delay,
                )
                time.sleep(delay)
                continue

            if (
                status in {500, 502, 503, 504}
                and len(texts) > 1
                and split_depth < max_split_depth
            ):
                midpoint = len(texts) // 2
                logger.warning(
                    "embedding.provider.split | provider=siliconflow | model=%s | status=%s | "
                    "batch_size=%s | split_depth=%s",
                    model_name,
                    status,
                    len(texts),
                    split_depth + 1,
                )
                return _siliconflow_embeddings(
                    texts[:midpoint], model_name=model_name, split_depth=split_depth + 1
                ) + _siliconflow_embeddings(
                    texts[midpoint:], model_name=model_name, split_depth=split_depth + 1
                )
            raise
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_attempts:
                delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
                logger.warning(
                    "embedding.provider.invalid_response | provider=siliconflow | model=%s | "
                    "attempt=%s/%s | batch_size=%s | error_type=%s | delay_seconds=%.3f",
                    model_name,
                    attempt,
                    max_attempts,
                    len(texts),
                    type(exc).__name__,
                    delay,
                )
                time.sleep(delay)
                continue
            raise

    raise RuntimeError("SiliconFlow embedding request exhausted retries.") from last_error


def _embed_texts(
    texts: list[str],
    *,
    provider: str,
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool = False,
    progress_label: str = "",
) -> list[list[float]]:
    provider = normalize_text(provider).replace("-", "_") or DEFAULT_EMBEDDING_PROVIDER
    if provider in {"siliconflow", "silicon_flow"}:
        started = time.perf_counter()
        text_keys = [_EmbeddingCache.key(provider, model_name, text) for text in texts]
        unique_text_by_key = dict(zip(text_keys, texts))
        cache_path = _embedding_cache_path()
        progress_every = _positive_env_int("YUNESA_EMBEDDING_PROGRESS_EVERY_BATCHES", 25)

        with _EmbeddingCache(cache_path) as cache:
            vectors_by_key = cache.get_many(list(unique_text_by_key))
            missing_keys = [key for key in unique_text_by_key if key not in vectors_by_key]
            total_batches = (len(missing_keys) + batch_size - 1) // batch_size
            if progress_label:
                logger.info(
                    "embedding.collection.start | collection=%s | provider=%s | model=%s | "
                    "rows=%s | unique_texts=%s | cache_hits=%s | cache_misses=%s | "
                    "batch_size=%s | api_batches=%s | cache_path=%s",
                    progress_label,
                    provider,
                    model_name,
                    len(texts),
                    len(unique_text_by_key),
                    len(vectors_by_key),
                    len(missing_keys),
                    batch_size,
                    total_batches,
                    cache_path or "disabled",
                )

            for batch_index, start in enumerate(range(0, len(missing_keys), batch_size), start=1):
                batch_keys = missing_keys[start : start + batch_size]
                batch_texts = [unique_text_by_key[key] for key in batch_keys]
                batch_started = time.perf_counter()
                batch_vectors = _siliconflow_embeddings(batch_texts, model_name=model_name)
                new_values = dict(zip(batch_keys, batch_vectors))
                vectors_by_key.update(new_values)
                cache.put_many(new_values)

                if progress_label and (
                    batch_index == 1
                    or batch_index == total_batches
                    or batch_index % progress_every == 0
                ):
                    logger.info(
                        "embedding.collection.progress | collection=%s | batch=%s/%s | "
                        "embedded=%s/%s | batch_seconds=%.3f | elapsed_seconds=%.3f",
                        progress_label,
                        batch_index,
                        total_batches,
                        min(start + len(batch_keys), len(missing_keys)),
                        len(missing_keys),
                        time.perf_counter() - batch_started,
                        time.perf_counter() - started,
                    )

            missing_after = [key for key in text_keys if key not in vectors_by_key]
            if missing_after:
                raise RuntimeError(f"Embedding cache/result missing {len(missing_after)} vectors.")
            result = [vectors_by_key[key] for key in text_keys]

        if progress_label:
            logger.info(
                "embedding.collection.done | collection=%s | rows=%s | cache_hits=%s | "
                "api_embeddings=%s | duration_seconds=%.3f",
                progress_label,
                len(texts),
                len(unique_text_by_key) - len(missing_keys),
                len(missing_keys),
                time.perf_counter() - started,
            )
        return result

    if provider in {"sentence_transformers", "sentence_transformer", "local"}:
        model = _load_sentence_transformer_model(model_name)
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=normalize_embeddings,
        )
        return [vector.astype("float32").tolist() for vector in vectors]

    raise ValueError(f"Unsupported embedding provider: {provider}")


def _embed_milvus_records(
    records_by_collection: dict[str, list[dict[str, Any]]],
    *,
    provider: str,
    model_name: str,
    batch_size: int,
    normalize_embeddings: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    embedded: dict[str, list[dict[str, Any]]] = {}
    for collection_name, rows in records_by_collection.items():
        if not rows:
            embedded[collection_name] = []
            continue
        texts = [safe_str(row.get("_embedding_text")) for row in rows]
        vectors = _embed_texts(
            texts,
            provider=provider,
            model_name=model_name,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            progress_label=collection_name,
        )
        embedded_rows = []
        for row, vector in zip(rows, vectors):
            clean_row = {key: value for key, value in row.items() if not key.startswith("_")}
            clean_row["embedding"] = [float(value) for value in vector]
            embedded_rows.append(clean_row)
        embedded[collection_name] = embedded_rows
    return embedded


def _milvus_client(config: MilvusVectorIndexConfig):
    try:
        from pymilvus import MilvusClient
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install pymilvus first: pip install pymilvus") from exc

    kwargs = {"uri": config.uri, "token": config.token}
    if config.db_name:
        kwargs["db_name"] = config.db_name
    try:
        return MilvusClient(**kwargs)
    except TypeError:
        kwargs.pop("db_name", None)
        client = MilvusClient(**kwargs)
        if config.db_name and hasattr(client, "using_database"):
            client.using_database(config.db_name)
        return client


def _create_collection_schema(collection_name: str, embedding_dim: int):
    from pymilvus import DataType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    for field_name, max_length in MILVUS_VARCHAR_LIMITS[collection_name].items():
        schema.add_field(field_name=field_name, datatype=DataType.VARCHAR, max_length=max_length)
    schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=embedding_dim)
    return schema


def _ensure_milvus_collection(
    client: Any,
    *,
    collection_name: str,
    embedding_dim: int,
    metric_type: str,
    clear_existing: bool,
) -> None:
    exists = bool(client.has_collection(collection_name))
    if exists:
        field_names = _milvus_field_names(client, collection_name)
        if "graphName" not in field_names:
            if clear_existing:
                client.drop_collection(collection_name)
                exists = False
            else:
                raise RuntimeError(
                    f"Milvus collection {collection_name!r} uses an old schema without graphName. "
                    "Run with clear_existing=True once to rebuild it safely."
                )
        else:
            existing_dim = _milvus_embedding_dim(client, collection_name)
            if existing_dim is not None and existing_dim != embedding_dim:
                if clear_existing:
                    client.drop_collection(collection_name)
                    exists = False
                else:
                    raise RuntimeError(
                        f"Milvus collection {collection_name!r} uses embedding dim {existing_dim}, "
                        f"but current config requires {embedding_dim}. "
                        "Run with clear_existing=True once to rebuild the collection schema."
                    )
            if not exists:
                pass
            else:
                return

    if exists:
        return

    schema = _create_collection_schema(collection_name, embedding_dim)
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="AUTOINDEX",
        metric_type=metric_type,
    )
    client.create_collection(
        collection_name=collection_name,
        schema=schema,
        index_params=index_params,
    )


def _milvus_embedding_dim(client: Any, collection_name: str) -> int | None:
    try:
        desc = client.describe_collection(collection_name)
    except Exception:
        return None
    for field in desc.get("fields", []):
        if field.get("name") != "embedding":
            continue
        params = field.get("params") or {}
        dim = params.get("dim") or params.get("dimension")
        try:
            return int(dim)
        except (TypeError, ValueError):
            return None
    return None


def _milvus_field_names(client: Any, collection_name: str) -> set[str]:
    try:
        desc = client.describe_collection(collection_name)
    except Exception:
        return set()
    return {safe_str(field.get("name")) for field in desc.get("fields", []) if field.get("name")}


def _milvus_string_filter(field_name: str, value: str) -> str:
    safe_value = safe_str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'{field_name} == "{safe_value}"'


def _delete_milvus_graph_records(client: Any, collection_name: str, graph_name: str) -> dict[str, Any]:
    if not graph_name:
        return {"skipped": True, "reason": "graph_name_empty"}
    try:
        result = client.delete(
            collection_name=collection_name,
            filter=_milvus_string_filter("graphName", graph_name),
        )
        return {"skipped": False, "result": result}
    except Exception as exc:
        return {"skipped": False, "error_type": type(exc).__name__, "error": str(exc)}


def _count_milvus_graph_records(client: Any, collection_name: str, graph_name: str) -> dict[str, Any]:
    if not graph_name:
        return {"skipped": True, "reason": "graph_name_empty"}
    limit = 16384
    try:
        rows = client.query(
            collection_name=collection_name,
            filter=_milvus_string_filter("graphName", graph_name),
            output_fields=["graphName"],
            limit=limit,
        )
        return {"skipped": False, "count": len(rows), "limit": limit, "exact": len(rows) < limit}
    except Exception as exc:
        return {"skipped": False, "error_type": type(exc).__name__, "error": str(exc)}


def write_vector_index_to_milvus(
    graph: nx.MultiDiGraph,
    *,
    config: MilvusVectorIndexConfig | None = None,
    clear_existing: bool = False,
    normalize_embeddings: bool = False,
    graph_name: str = "yunesa_academic_kg",
) -> dict[str, Any]:
    """Write AcademicRAG-style vector indexes to Milvus/Zilliz Cloud.

    The graph remains the source of truth. Milvus stores rebuildable semantic
    indexes for chunk, entity, relationship, and keyword retrieval.
    """
    config = config or milvus_config_from_env()
    records = build_milvus_index_records(graph, graph_name=graph_name)
    preflight = _validate_milvus_varchar_records(records)
    logger.info(
        "milvus.preflight.passed | graph_name=%s | collections=%s | rows=%s | checked_fields=%s",
        graph_name,
        preflight["collections"],
        preflight["rows"],
        preflight["checked_fields"],
    )
    logger.info(
        "milvus.embedding.plan | graph_name=%s | provider=%s | model=%s | dimension=%s | "
        "batch_size=%s | rows=%s",
        graph_name,
        config.embedding_provider,
        config.embedding_model,
        config.embedding_dim,
        config.batch_size,
        {name: len(rows) for name, rows in records.items()},
    )
    embedded_records = _embed_milvus_records(
        records,
        provider=config.embedding_provider,
        model_name=config.embedding_model,
        batch_size=config.batch_size,
        normalize_embeddings=normalize_embeddings,
    )
    client = _milvus_client(config)

    report: dict[str, Any] = {
        "uri_configured": bool(config.uri),
        "db_name": config.db_name or "",
        "embedding_model": config.embedding_model,
        "embedding_provider": config.embedding_provider,
        "embedding_dim": config.embedding_dim,
        "metric_type": config.metric_type,
        "graph_name": graph_name,
        "varchar_preflight": preflight,
        "collections": {},
    }

    try:
        for collection_name, rows in embedded_records.items():
            collection_started = time.perf_counter()
            logger.info(
                "milvus.collection.start | collection=%s | rows=%s | clear_existing=%s",
                collection_name,
                len(rows),
                clear_existing,
            )
            _ensure_milvus_collection(
                client,
                collection_name=collection_name,
                embedding_dim=config.embedding_dim,
                metric_type=config.metric_type,
                clear_existing=clear_existing,
            )
            deleted_report: dict[str, Any] = {}
            if clear_existing:
                deleted_report = _delete_milvus_graph_records(client, collection_name, graph_name)
            inserted = 0
            total_batches = (len(rows) + config.batch_size - 1) // config.batch_size
            progress_every = _positive_env_int("YUNESA_MILVUS_PROGRESS_EVERY_BATCHES", 25)
            for batch_index, start in enumerate(range(0, len(rows), config.batch_size), start=1):
                batch = rows[start : start + config.batch_size]
                if not batch:
                    continue
                client.insert(collection_name=collection_name, data=batch)
                inserted += len(batch)
                if batch_index == 1 or batch_index == total_batches or batch_index % progress_every == 0:
                    logger.info(
                        "milvus.collection.progress | collection=%s | batch=%s/%s | inserted=%s/%s | "
                        "elapsed_seconds=%.3f",
                        collection_name,
                        batch_index,
                        total_batches,
                        inserted,
                        len(rows),
                        time.perf_counter() - collection_started,
                    )
            try:
                client.flush(collection_name)
            except Exception:
                pass
            try:
                client.load_collection(collection_name)
            except Exception:
                pass
            try:
                stats = client.get_collection_stats(collection_name)
            except Exception:
                stats = {}
            graph_row_count = _count_milvus_graph_records(client, collection_name, graph_name)
            report["collections"][collection_name] = {
                "prepared_rows": len(records.get(collection_name, [])),
                "inserted_rows": inserted,
                "deleted_existing_graph_rows": deleted_report,
                "graph_row_count": graph_row_count,
                "stats": stats,
            }
            logger.info(
                "milvus.collection.done | collection=%s | inserted=%s | graph_row_count=%s | "
                "duration_seconds=%.3f",
                collection_name,
                inserted,
                graph_row_count.get("count", "unknown"),
                time.perf_counter() - collection_started,
            )
        logger.info(
            "milvus.write.done | graph_name=%s | collections=%s | inserted_rows=%s",
            graph_name,
            len(report["collections"]),
            sum(item.get("inserted_rows", 0) for item in report["collections"].values()),
        )
        return report
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def write_dual_index_to_storage(
    graph: nx.MultiDiGraph,
    *,
    graph_name: str = "yunesa_academic_kg",
    write_neo4j: bool = True,
    write_milvus: bool = True,
    clear_neo4j: bool = False,
    clear_milvus: bool = False,
    milvus_config: MilvusVectorIndexConfig | None = None,
) -> dict[str, Any]:
    """Write KG to Neo4j and vector indexes to Milvus in one notebook call."""
    result: dict[str, Any] = {
        "storage_plan": academicrag_storage_plan(),
        "neo4j": None,
        "milvus": None,
    }
    if write_neo4j:
        result["neo4j"] = write_graph_to_neo4j(
            graph,
            graph_name=graph_name,
            clear_existing=clear_neo4j,
        )
    if write_milvus:
        result["milvus"] = write_vector_index_to_milvus(
            graph,
            config=milvus_config,
            clear_existing=clear_milvus,
            graph_name=graph_name,
        )
    return result


def _neo4j_label(value: Any) -> str:
    label = re.sub(r"[^A-Za-z0-9_]", "", safe_str(value))
    if not label:
        return "KGNode"
    if label[0].isdigit():
        label = f"N{label}"
    return label


def _neo4j_relation(value: Any) -> str:
    relation = canonical_relation(value)
    relation = re.sub(r"[^A-Za-z0-9_]", "_", relation.upper()).strip("_")
    return relation or "RELATED_TO"


def neo4j_credential_status() -> dict[str, bool]:
    """Return non-secret Neo4j credential availability for notebook debugging."""
    return {
        "NEO4J_URI": bool(os.getenv("NEO4J_URI")),
        "NEO4J_USERNAME": bool(os.getenv("NEO4J_USERNAME")),
        "NEO4J_PASSWORD": bool(os.getenv("NEO4J_PASSWORD")),
        "NEO4J_DATABASE": bool(os.getenv("NEO4J_DATABASE")),
    }


def neo4j_uri_for_driver(uri: str | None = None) -> str:
    """Return Neo4j URI adjusted for local SSL inspection when explicitly enabled."""
    uri = uri or os.getenv("NEO4J_URI") or ""
    trust_self_signed = os.getenv("NEO4J_TRUST_SELF_SIGNED", "0") == "1"
    if trust_self_signed:
        uri = uri.replace("neo4j+s://", "neo4j+ssc://").replace("bolt+s://", "bolt+ssc://")
    return uri


def write_graph_to_neo4j(
    graph: nx.MultiDiGraph,
    *,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    graph_name: str = "yunesa_academic_kg",
    clear_existing: bool = False,
    batch_size: int = 500,
) -> dict[str, int]:
    """Write the NetworkX graph to Neo4j/AuraDB.

    Credentials are read from explicit arguments or environment variables:
    NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, and optional NEO4J_DATABASE.
    """
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver(uri)
    username = username or os.getenv("NEO4J_USERNAME")
    password = password or os.getenv("NEO4J_PASSWORD")
    database = database or os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        raise ValueError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD first.")

    serialisable = serialisable_graph_copy(graph)
    node_rows_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, data in serialisable.nodes(data=True):
        node_type = _neo4j_label(data.get("node_type", "KGNode"))
        props = {"id": node_id, "graph_name": graph_name, **data}
        node_rows_by_label[node_type].append(props)

    edge_rows_by_relation: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source, target, key, data in serialisable.edges(keys=True, data=True):
        relation = _neo4j_relation(data.get("relation", "RELATED_TO"))
        edge_rows_by_relation[relation].append(
            {
                "source": source,
                "target": target,
                "edge_key": str(key),
                "graph_name": graph_name,
                "props": {**data, "graph_name": graph_name, "edge_key": str(key)},
            }
        )

    def chunks(rows: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
        for start in range(0, len(rows), batch_size):
            yield rows[start : start + batch_size]

    driver = GraphDatabase.driver(uri, auth=(username, password))
    logger.info(
        "neo4j.write.plan | graph_name=%s | nodes=%s | edges=%s | labels=%s | relation_types=%s | "
        "batch_size=%s | clear_existing=%s",
        graph_name,
        serialisable.number_of_nodes(),
        serialisable.number_of_edges(),
        len(node_rows_by_label),
        len(edge_rows_by_relation),
        batch_size,
        clear_existing,
    )
    try:
        with driver.session(database=database) as session:
            if clear_existing:
                logger.info("neo4j.clear.start | graph_name=%s", graph_name)
                session.run(
                    "MATCH (n:KGNode {graph_name: $graph_name}) DETACH DELETE n",
                    graph_name=graph_name,
                )
                logger.info("neo4j.clear.done | graph_name=%s", graph_name)

            session.run("CREATE CONSTRAINT kg_node_id IF NOT EXISTS FOR (n:KGNode) REQUIRE n.id IS UNIQUE")
            session.run(
                "CREATE INDEX kg_node_graph_name IF NOT EXISTS "
                "FOR (n:KGNode) ON (n.graph_name)"
            )
            session.run(
                "CREATE INDEX kg_publication_year IF NOT EXISTS "
                "FOR (n:Publication) ON (n.year)"
            )

            nodes_written = 0
            for label, rows in node_rows_by_label.items():
                label_started = time.perf_counter()
                query = (
                    f"UNWIND $rows AS row "
                    f"MERGE (n:KGNode:{label} {{id: row.id}}) "
                    f"SET n += row"
                )
                for batch in chunks(rows):
                    session.run(query, rows=batch)
                    nodes_written += len(batch)
                logger.info(
                    "neo4j.nodes.done | label=%s | rows=%s | total_written=%s | duration_seconds=%.3f",
                    label,
                    len(rows),
                    nodes_written,
                    time.perf_counter() - label_started,
                )

            edges_written = 0
            for relation, rows in edge_rows_by_relation.items():
                relation_started = time.perf_counter()
                query = (
                    f"UNWIND $rows AS row "
                    f"MATCH (s:KGNode {{id: row.source, graph_name: row.graph_name}}) "
                    f"MATCH (t:KGNode {{id: row.target, graph_name: row.graph_name}}) "
                    f"MERGE (s)-[r:{relation} {{edge_key: row.edge_key, graph_name: row.graph_name}}]->(t) "
                    f"SET r += row.props"
                )
                for batch in chunks(rows):
                    session.run(query, rows=batch)
                    edges_written += len(batch)
                logger.info(
                    "neo4j.edges.done | relation=%s | rows=%s | total_written=%s | duration_seconds=%.3f",
                    relation,
                    len(rows),
                    edges_written,
                    time.perf_counter() - relation_started,
                )

        logger.info(
            "neo4j.write.done | graph_name=%s | nodes_written=%s | edges_written=%s",
            graph_name,
            nodes_written,
            edges_written,
        )
        return {"nodes_written": nodes_written, "edges_written": edges_written}
    finally:
        driver.close()


def build_academic_kg_from_supabase(sample_size: int = 50) -> dict[str, Any]:
    config = KGConfig.default(sample_size=sample_size)
    load_project_env(config.project_root)

    papers_df, lecturers_df, links_df = fetch_supabase_sample(sample_size=sample_size)
    ieee_index = IeeeSemanticIndex.from_files(
        config.thesaurus_path,
        config.taxonomy_path,
        max_terms=config.max_ieee_terms,
    )

    concept_resolver = AcademicConceptResolver.from_path(config.concept_aliases_path)
    builder = AcademicKGBuilder(ieee_index, concept_resolver=concept_resolver, graph_name="yunesa_academic_kg")
    graph = builder.build(
        papers_df=papers_df,
        lecturers_df=lecturers_df,
        links_df=links_df,
        max_concepts_per_paper=config.max_concepts_per_paper,
    )
    artifacts = export_graph_artifacts(graph, config.output_dir)

    return {
        "config": config,
        "papers_df": papers_df,
        "lecturers_df": lecturers_df,
        "links_df": links_df,
        "ieee_summary": ieee_index.summary(),
        "entity_resolution": concept_resolver.summary(),
        "graph": graph,
        "validation": builder.validate(),
        "artifacts": artifacts,
    }


def entity_resolution_report(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Summarize concept canonicalization quality and remaining review targets."""
    concept_nodes = [
        (node_id, data)
        for node_id, data in graph.nodes(data=True)
        if data.get("node_type") == "Concept"
    ]
    merged_nodes: list[dict[str, Any]] = []
    unresolved_local: list[dict[str, Any]] = []
    acronym_like: list[dict[str, Any]] = []

    for node_id, data in concept_nodes:
        raw_labels = split_list_field(data.get("raw_labels", ""))
        resolution_source = safe_str(data.get("resolution_source"))
        label = _node_label(data, node_id)
        concept_type = safe_str(data.get("concept_type"))
        canonical_key = safe_str(data.get("canonical_key"))
        if len({normalize_text(item) for item in raw_labels}) > 1:
            merged_nodes.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "canonical_key": canonical_key,
                    "raw_labels": raw_labels,
                    "resolution_source": resolution_source,
                }
            )
        if canonical_key.startswith("local:"):
            unresolved_local.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "source": safe_str(data.get("source")),
                    "canonical_key": canonical_key,
                }
            )
        if re.fullmatch(r"[A-Z0-9]{2,8}", safe_str(label)):
            acronym_like.append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": concept_type,
                    "canonical_key": canonical_key,
                    "resolution_source": resolution_source,
                }
            )

    duplicate_candidates: list[dict[str, Any]] = []
    by_compact: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, data in concept_nodes:
        label = _node_label(data, node_id)
        compact = re.sub(r"[^a-z0-9]", "", normalize_text(label))
        if len(compact) >= 3:
            by_compact[compact].append(
                {
                    "id": node_id,
                    "label": label,
                    "concept_type": safe_str(data.get("concept_type")),
                    "canonical_key": safe_str(data.get("canonical_key")),
                }
            )
    for compact, items in by_compact.items():
        keys = {item["canonical_key"] for item in items}
        if len(items) > 1 and len(keys) > 1:
            duplicate_candidates.append({"compact_label": compact, "items": items[:10]})

    resolution_sources = Counter(
        data.get("resolution_source", "unknown") or "unknown"
        for _, data in concept_nodes
    )
    return {
        "concept_nodes": len(concept_nodes),
        "resolution_source_counts": dict(resolution_sources),
        "merged_canonical_nodes": len(merged_nodes),
        "merged_examples": merged_nodes[:20],
        "unresolved_local_concepts": len(unresolved_local),
        "unresolved_examples": unresolved_local[:30],
        "acronym_like_concepts": len(acronym_like),
        "acronym_like_examples": acronym_like[:20],
        "duplicate_candidate_groups": len(duplicate_candidates),
        "duplicate_candidate_examples": duplicate_candidates[:20],
    }


def _json_value_from_text(text: Any) -> Any:
    content = safe_str(text)
    if not content:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        content = fenced.group(1)
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = content.find(opener)
        end = content.rfind(closer)
        if start >= 0 and end > start:
            try:
                return json.loads(content[start : end + 1])
            except Exception:
                continue
    try:
        return json.loads(content)
    except Exception:
        return None


def _candidate_terms_for_llm_review(report: dict[str, Any], *, max_candidates: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in report.get("duplicate_candidate_examples") or []:
        for concept in item.get("items") or []:
            label = safe_str(concept.get("label"))
            key = normalize_text(label)
            if label and key not in seen:
                seen.add(key)
                candidates.append(
                    {
                        "label": label,
                        "concept_type": safe_str(concept.get("concept_type")),
                        "source": "duplicate_candidate",
                        "canonical_key": safe_str(concept.get("canonical_key")),
                    }
                )

    for item in report.get("acronym_like_examples") or []:
        label = safe_str(item.get("label"))
        key = normalize_text(label)
        if label and key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "label": label,
                    "concept_type": safe_str(item.get("concept_type")),
                    "source": "acronym_like",
                    "canonical_key": safe_str(item.get("canonical_key")),
                }
            )

    for item in report.get("unresolved_examples") or []:
        label = safe_str(item.get("label"))
        key = normalize_text(label)
        if label and key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "label": label,
                    "concept_type": safe_str(item.get("concept_type")),
                    "source": "unresolved_local",
                    "canonical_key": safe_str(item.get("canonical_key")),
                }
            )

    return candidates[:max_candidates]


def _groq_alias_suggestions(
    candidates: list[dict[str, Any]],
    *,
    model: str,
    min_confidence: float,
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install groq first.") from exc

    prompt = {
        "task": "Review unresolved academic KG concepts and propose canonical alias mappings.",
        "strict_rules": [
            "Return JSON only.",
            "Do not invent papers, results, authors, datasets, or metrics.",
            "Only propose exact synonyms, acronym expansions, metric canonicalization, or obvious spelling variants.",
            "Do not merge broader/narrower/related concepts. Mark those as related_only.",
            "For metric values such as 'AUC of 0.9', use canonical_label 'AUC' and action 'metric_value'.",
            "Confidence must be between 0 and 1.",
            f"Only mark review_status='auto_candidate' when confidence >= {min_confidence}.",
        ],
        "allowed_actions": ["exact_synonym", "metric_value", "spelling_variant", "related_only", "keep_separate", "noise"],
        "output_schema": {
            "suggestions": [
                {
                    "raw_label": "input label",
                    "suggested_canonical_label": "canonical label or empty",
                    "suggested_canonical_key": "snake_case key or empty",
                    "concept_type": "Model|Dataset|Metric|Method|Task|Domain|ResearchTopic|Result|Innovation|Problem",
                    "action": "one allowed action",
                    "confidence": 0.0,
                    "aliases": ["optional exact aliases"],
                    "review_status": "auto_candidate|needs_review|reject",
                    "rationale": "short factual reason",
                }
            ]
        },
        "candidates": candidates,
    }
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an entity-resolution reviewer for an academic knowledge graph. "
                    "You are conservative: exact synonyms can merge, related concepts cannot."
                ),
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        temperature=0.0,
        max_tokens=1800,
    )
    parsed = _json_value_from_text(response.choices[0].message.content)
    if isinstance(parsed, list):
        parsed = {"suggestions": parsed}
    if not isinstance(parsed, dict):
        parsed = {"suggestions": [], "parse_error": safe_str(response.choices[0].message.content)}
    parsed.setdefault("suggestions", [])
    return parsed


def generate_llm_alias_suggestions(
    report: dict[str, Any],
    *,
    config: LLMAliasSuggestionConfig | None = None,
) -> dict[str, Any]:
    """Generate LLM-assisted alias suggestions from an entity resolution report."""
    config = config or LLMAliasSuggestionConfig.from_env()
    provider = normalize_text(config.provider)
    candidates = _candidate_terms_for_llm_review(report, max_candidates=config.max_candidates)
    suggestions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for start in range(0, len(candidates), max(1, config.batch_size)):
        batch = candidates[start : start + max(1, config.batch_size)]
        if not batch:
            continue
        try:
            if provider == "groq":
                result = _groq_alias_suggestions(
                    batch,
                    model=config.model,
                    min_confidence=config.min_confidence_for_auto_candidate,
                )
            else:
                raise ValueError(f"Unsupported entity resolution LLM provider: {config.provider}")
            for item in result.get("suggestions") or []:
                if isinstance(item, dict):
                    suggestions.append(item)
        except Exception as exc:
            errors.append(
                {
                    "batch_start": start,
                    "batch_size": len(batch),
                    "error_type": type(exc).__name__,
                    "error": safe_str(exc),
                }
            )

    return {
        "provider": config.provider,
        "model": config.model,
        "candidate_count": len(candidates),
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
        "errors": errors,
        "policy": {
            "auto_candidate_threshold": config.min_confidence_for_auto_candidate,
            "auto_merge": False,
            "requires_human_review": True,
        },
    }


def write_llm_alias_suggestions(
    report_path: Path,
    output_path: Path,
    *,
    config: LLMAliasSuggestionConfig | None = None,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    result = generate_llm_alias_suggestions(report, config=config)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def graph_quality_report(graph: nx.MultiDiGraph) -> dict[str, Any]:
    """Return thesis-oriented quality gates for the constructed graph."""
    node_type_counts = Counter(data.get("node_type", "Unknown") for _, data in graph.nodes(data=True))
    edge_counts = Counter(canonical_relation(data.get("relation", "UNKNOWN")) for _, _, data in graph.edges(data=True))
    paper_nodes = [node_id for node_id, data in graph.nodes(data=True) if data.get("node_type") == "Publication"]

    missing: dict[str, list[str]] = {
        "title": [],
        "abstract": [],
        "tldr": [],
        "keywords": [],
        "authors": [],
        "concepts": [],
    }
    for paper_node in paper_nodes:
        data = graph.nodes[paper_node]
        if not field_value(data, "title", "label"):
            missing["title"].append(paper_node)
        if not field_value(data, "abstract"):
            missing["abstract"].append(paper_node)
        if not field_value(data, "tldr"):
            missing["tldr"].append(paper_node)
        if not field_value(data, "keywords"):
            missing["keywords"].append(paper_node)
        if not _publication_author_labels(graph, paper_node):
            missing["authors"].append(paper_node)
        if not _publication_concept_labels(graph, paper_node):
            missing["concepts"].append(paper_node)

    concept_type_counts = Counter(
        data.get("concept_type", "unknown")
        for _, data in graph.nodes(data=True)
        if data.get("node_type") == "Concept"
    )
    non_ontology_edges = {
        relation: count
        for relation, count in edge_counts.items()
        if relation not in ONTOLOGY_RELATIONS and not relation.startswith("SKOS_")
    }

    vector_records = build_milvus_index_records(graph)
    return {
        "total_nodes": graph.number_of_nodes(),
        "total_edges": graph.number_of_edges(),
        "node_type_counts": dict(node_type_counts),
        "edge_counts": dict(edge_counts),
        "concept_type_counts": dict(concept_type_counts),
        "missing_counts": {key: len(value) for key, value in missing.items()},
        "missing_examples": {key: value[:10] for key, value in missing.items() if value},
        "non_ontology_edges": non_ontology_edges,
        "entity_resolution": entity_resolution_report(graph),
        "milvus_prepared_rows": summarize_milvus_records(vector_records),
        "quality_gates": {
            "has_publications": node_type_counts.get("Publication", 0) > 0,
            "all_publications_have_concepts": len(missing["concepts"]) == 0,
            "all_publications_have_authors": len(missing["authors"]) == 0,
            "all_publications_have_tldr": len(missing["tldr"]) == 0,
            "relations_are_ontology_aligned": not non_ontology_edges,
        },
    }


def inspect_neo4j_graph(
    *,
    uri: str | None = None,
    username: str | None = None,
    password: str | None = None,
    database: str | None = None,
    graph_name: str | None = None,
) -> dict[str, Any]:
    """Read storage counts from Neo4j/AuraDB without mutating data."""
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver(uri)
    username = username or os.getenv("NEO4J_USERNAME")
    password = password or os.getenv("NEO4J_PASSWORD")
    database = database or os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        raise ValueError("Set NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD first.")

    graph_filter = "WHERE n.graph_name = $graph_name" if graph_name else ""
    publication_filter = "WHERE p.graph_name = $graph_name" if graph_name else ""
    rel_filter = "WHERE r.graph_name = $graph_name" if graph_name else ""
    params = {"graph_name": graph_name}

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            node_count = session.run(
                f"MATCH (n:KGNode) {graph_filter} RETURN count(n) AS count",
                **params,
            ).single()["count"]
            rel_count = session.run(
                f"MATCH (:KGNode)-[r]->(:KGNode) {rel_filter} RETURN count(r) AS count",
                **params,
            ).single()["count"]
            label_rows = session.run(
                f"""
                MATCH (n:KGNode)
                {graph_filter}
                UNWIND labels(n) AS label
                WITH label, count(*) AS count
                WHERE label <> 'KGNode'
                RETURN label, count
                ORDER BY count DESC, label
                """,
                **params,
            ).data()
            relationship_rows = session.run(
                f"""
                MATCH (:KGNode)-[r]->(:KGNode)
                {rel_filter}
                RETURN type(r) AS relation, count(*) AS count
                ORDER BY count DESC, relation
                """,
                **params,
            ).data()
            sample_publications = session.run(
                f"""
                MATCH (p:KGNode:Publication)
                {publication_filter}
                RETURN p.id AS id, p.title AS title, p.tldr AS tldr, p.keywords AS keywords
                LIMIT 5
                """,
                **params,
            ).data()
        return {
            "database": database,
            "graph_name": graph_name or "",
            "nodes": node_count,
            "relationships": rel_count,
            "label_counts": label_rows,
            "relationship_counts": relationship_rows,
            "sample_publications": sample_publications,
        }
    finally:
        driver.close()


def inspect_milvus_collections(config: MilvusVectorIndexConfig | None = None) -> dict[str, Any]:
    """Read collection schemas and row counts from Milvus/Zilliz Cloud."""
    config = config or milvus_config_from_env()
    client = _milvus_client(config)
    try:
        collections = client.list_collections()
        report: dict[str, Any] = {
            "db_name": config.db_name or "",
            "collections": {},
        }
        for collection_name in collections:
            try:
                stats = client.get_collection_stats(collection_name)
            except Exception:
                stats = {}
            try:
                desc = client.describe_collection(collection_name)
            except Exception:
                desc = {}
            fields = []
            for field in desc.get("fields", []):
                fields.append(
                    {
                        "name": field.get("name"),
                        "type": str(field.get("type")),
                        "params": field.get("params", {}),
                    }
                )
            try:
                sample = client.query(collection_name=collection_name, filter="", limit=1, output_fields=["*"])
                sample_keys = sorted(sample[0].keys()) if sample else []
            except Exception:
                sample_keys = []
            report["collections"][collection_name] = {
                "stats": stats,
                "fields": fields,
                "sample_keys": sample_keys,
            }
        return report
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


@dataclass(frozen=True)
class GraphRAGQueryParam:
    """AcademicRAG-inspired retrieval parameters for local development."""

    mode: str = "mix"
    top_k: int = 5
    graph_name: str = "yunesa_academic_kg_local"
    include_vector: bool = True
    include_graph: bool = True
    use_keyword_decomposition: bool = True
    keyword_top_k: int = 8
    keyword_provider: str = "heuristic"
    keyword_model: str = "llama-3.1-8b-instant"
    keyword_cache_path: str = ""
    max_keyword_terms: int = 8
    local_path_depth: int = 4


@dataclass(frozen=True)
class GraphRAGGenerationParam:
    """Groq generation settings for AcademicRAG-style answer synthesis."""

    model: str = "llama-3.3-70b-versatile"
    temperature: float = 0.1
    max_tokens: int = 360
    context_max_chars: int = 7000
    response_language: str = "auto"


def _embed_query(
    text: str,
    *,
    provider: str = DEFAULT_EMBEDDING_PROVIDER,
    model_name: str = DEFAULT_EMBEDDING_MODEL,
) -> list[float]:
    vectors = _embed_texts(
        [safe_str(text)],
        provider=provider,
        model_name=model_name,
        batch_size=1,
        normalize_embeddings=False,
    )
    return vectors[0]


def _milvus_search(
    query: str,
    collection_name: str,
    *,
    output_fields: list[str],
    top_k: int = 5,
    config: MilvusVectorIndexConfig | None = None,
    graph_name: str = "",
) -> list[dict[str, Any]]:
    config = config or milvus_config_from_env()
    client = _milvus_client(config)
    try:
        try:
            client.load_collection(collection_name)
        except Exception:
            pass
        vector = _embed_query(
            query,
            provider=config.embedding_provider,
            model_name=config.embedding_model,
        )
        graph_filter = ""
        if graph_name:
            safe_graph_name = safe_str(graph_name).replace("\\", "\\\\").replace('"', '\\"')
            graph_filter = f'graphName == "{safe_graph_name}"'
        raw_hits = client.search(
            collection_name=collection_name,
            data=[vector],
            anns_field="embedding",
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": config.metric_type},
            filter=graph_filter,
        )
        results: list[dict[str, Any]] = []
        for hit in raw_hits[0] if raw_hits else []:
            if isinstance(hit, dict):
                entity = hit.get("entity") or {}
                distance = hit.get("distance", hit.get("score"))
                hit_id = hit.get("id")
            else:
                entity = getattr(hit, "entity", {}) or {}
                distance = getattr(hit, "distance", None)
                hit_id = getattr(hit, "id", None)
            row = dict(entity)
            row["id"] = row.get("id", hit_id)
            row["distance"] = distance
            results.append(row)
        return results
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _keyword_cache_path(path_value: str = "") -> Path | None:
    raw = safe_str(path_value) or safe_str(os.getenv("YUNESA_GRAPHRAG_KEYWORD_CACHE"))
    if not raw:
        return None
    return Path(raw).expanduser()


def _cache_lookup(path: Path | None, key: str) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    value = data.get(key)
    return value if isinstance(value, dict) else None


def _cache_store(path: Path | None, key: str, value: dict[str, Any]) -> None:
    if not path:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        data[key] = value
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def _dedupe_terms(terms: Iterable[Any], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for term in terms:
        text = re.sub(r"\s+", " ", safe_str(term)).strip(" ,.;:")
        if not text:
            continue
        key = normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _content_keyword_terms(keyword_rows: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for row in keyword_rows:
        terms.extend(split_list_field(row.get("keywords")))
        source_paper = safe_str(row.get("sourcePaper"))
        if source_paper:
            terms.append(source_paper)
    return _dedupe_terms(terms, limit=64)


def _query_terms(query: str, *, limit: int = 8) -> list[str]:
    text = safe_str(query)
    stopwords = {
        "apa",
        "siapa",
        "yang",
        "dengan",
        "dan",
        "atau",
        "untuk",
        "pada",
        "paper",
        "publikasi",
        "model",
        "dataset",
        "metode",
        "digunakan",
        "membahas",
        "which",
        "what",
        "who",
        "where",
        "when",
        "why",
        "how",
        "papers",
        "publications",
        "publication",
        "use",
        "uses",
        "used",
        "using",
        "discuss",
        "discusses",
        "about",
        "show",
        "shows",
        "list",
        "give",
        "find",
        "related",
        "relation",
        "between",
        "in",
        "on",
        "for",
        "the",
        "a",
        "an",
        "of",
        "to",
        "by",
    }

    def clean_candidate(value: str) -> str:
        words = re.split(r"\s+", safe_str(value).strip(" ?.,;:"))
        while words and normalize_text(words[0]) in stopwords:
            words.pop(0)
        while words and normalize_text(words[-1]) in stopwords:
            words.pop()
        cleaned = " ".join(words).strip(" ?.,;:")
        if not cleaned or normalize_text(cleaned) in stopwords:
            return ""
        return cleaned

    technical_terms = re.findall(
        r"\b(?:[A-Z][A-Za-z0-9+/.-]{1,}|[A-Za-z]+[A-Za-z0-9+/.-]*\d+[A-Za-z0-9+/.-]*)"
        r"(?:[-\s][A-Za-z0-9+/.-]{2,}){0,4}\b",
        text,
    )
    chunks = re.split(
        r"\b(?:apa|siapa|yang|dengan|dan|atau|untuk|pada|paper|publikasi|model|dataset|metode|digunakan|membahas|"
        r"which|what|who|where|when|why|how|papers|publications?|use[sd]?|using|discuss(?:es)?|about|show[sd]?|"
        r"list|give|find|related|relation|between|in|on|for|the|a|an|of|to|by)\b",
        text,
        flags=re.IGNORECASE,
    )
    phrase_terms = [clean_candidate(chunk) for chunk in chunks if len(clean_candidate(chunk)) >= 4]
    technical_terms = [clean_candidate(term) for term in technical_terms if clean_candidate(term)]
    return _dedupe_terms([*technical_terms, *phrase_terms], limit=limit)


def _overlap_score(term: str, query: str) -> float:
    term_tokens = set(normalize_text(term).split())
    query_tokens = set(normalize_text(query).split())
    if not term_tokens or not query_tokens:
        return 0.0
    return len(term_tokens & query_tokens) / max(1, len(term_tokens))


def _heuristic_keyword_decomposition(
    query: str,
    keyword_rows: list[dict[str, Any]],
    *,
    max_terms: int = 8,
) -> dict[str, Any]:
    clue_terms = _content_keyword_terms(keyword_rows)
    query_norm = normalize_text(query)
    low_candidates: list[str] = []
    high_candidates: list[str] = []

    for term in clue_terms:
        term_norm = normalize_text(term)
        if term_norm and (term_norm in query_norm or _overlap_score(term, query) >= 0.5):
            low_candidates.append(term)
        else:
            high_candidates.append(term)

    low_keywords = _dedupe_terms([*_query_terms(query, limit=max_terms), *low_candidates], limit=max_terms)
    high_keywords = _dedupe_terms(high_candidates, limit=max_terms)

    if not low_keywords:
        low_keywords = _dedupe_terms([query], limit=1)
    if not high_keywords:
        high_keywords = _dedupe_terms(clue_terms[:max_terms] or low_keywords, limit=max_terms)

    return {
        "provider": "heuristic",
        "high_level_keywords": high_keywords,
        "low_level_keywords": low_keywords,
        "content_keyword_clues": clue_terms[:max_terms],
        "cache_hit": False,
    }


def _json_object_from_text(text: str) -> dict[str, Any]:
    raw = safe_str(text)
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _groq_keyword_decomposition(
    query: str,
    keyword_rows: list[dict[str, Any]],
    *,
    model: str,
    max_terms: int,
) -> dict[str, Any]:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY is not set.")
    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install groq first.") from exc

    clues = _content_keyword_terms(keyword_rows)[: max(max_terms * 2, 10)]
    prompt = (
        "Generate retrieval keywords for AcademicRAG over a YUNESA academic knowledge graph.\n"
        "Return JSON only with keys high_level_keywords and low_level_keywords.\n"
        "High-level keywords are broad themes/domains. Low-level keywords are exact entities, methods, models, "
        "datasets, metrics, authors, or paper-specific terms.\n"
        "Use only the user query and the provided content keyword clues. Do not invent terms.\n"
        f"Maximum {max_terms} terms per list.\n\n"
        f"User query: {query}\n"
        f"Content keyword clues: {', '.join(clues)}\n"
    )
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a precise AcademicRAG keyword decomposition component."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=220,
    )
    content = safe_str(response.choices[0].message.content)
    parsed = _json_object_from_text(content)
    high_keywords = _dedupe_terms(parsed.get("high_level_keywords") or [], limit=max_terms)
    low_keywords = _dedupe_terms(parsed.get("low_level_keywords") or [], limit=max_terms)
    if not high_keywords or not low_keywords:
        fallback = _heuristic_keyword_decomposition(query, keyword_rows, max_terms=max_terms)
        high_keywords = high_keywords or fallback["high_level_keywords"]
        low_keywords = low_keywords or fallback["low_level_keywords"]
    return {
        "provider": "groq",
        "model": model,
        "high_level_keywords": high_keywords,
        "low_level_keywords": low_keywords,
        "content_keyword_clues": clues[:max_terms],
        "cache_hit": False,
    }


def decompose_query_keywords(
    query: str,
    keyword_rows: list[dict[str, Any]],
    *,
    param: GraphRAGQueryParam | None = None,
) -> dict[str, Any]:
    """AcademicRAG-style clue-guided high/low keyword decomposition."""
    param = param or GraphRAGQueryParam()
    provider = normalize_text(os.getenv("YUNESA_GRAPHRAG_KEYWORD_PROVIDER", param.keyword_provider)) or "heuristic"
    clue_fingerprint = "|".join(_content_keyword_terms(keyword_rows)[: max(param.keyword_top_k, 1)])
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "query": query,
                "provider": provider,
                "model": param.keyword_model,
                "clues": clue_fingerprint,
                "max_terms": param.max_keyword_terms,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    cache_path = _keyword_cache_path(param.keyword_cache_path)
    cached = _cache_lookup(cache_path, cache_key)
    if cached:
        cached["cache_hit"] = True
        return cached

    if provider == "groq":
        try:
            result = _groq_keyword_decomposition(
                query,
                keyword_rows,
                model=param.keyword_model,
                max_terms=param.max_keyword_terms,
            )
        except Exception as exc:
            result = _heuristic_keyword_decomposition(query, keyword_rows, max_terms=param.max_keyword_terms)
            result["provider"] = "heuristic_fallback"
            result["fallback_reason"] = f"{type(exc).__name__}: {exc}"
    else:
        result = _heuristic_keyword_decomposition(query, keyword_rows, max_terms=param.max_keyword_terms)

    _cache_store(cache_path, cache_key, result)
    return result


def _keyword_query(keywords: Iterable[Any], fallback: str) -> str:
    terms = _dedupe_terms(keywords, limit=16)
    return ", ".join(terms) if terms else fallback


def _neo4j_neighborhood(
    node_ids: list[str],
    *,
    graph_name: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver()
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password or not node_ids:
        return []

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            rows = session.run(
                """
                UNWIND $node_ids AS node_id
                MATCH (n:KGNode {id: node_id})
                WHERE $graph_name = '' OR n.graph_name = $graph_name
                OPTIONAL MATCH (n)-[r]-(m:KGNode)
                WHERE r IS NULL OR $graph_name = '' OR r.graph_name = $graph_name
                RETURN
                    n.id AS center_id,
                    coalesce(n.label, n.title, n.name, n.nama_norm, n.id) AS center,
                    labels(n) AS center_labels,
                    type(r) AS relation,
                    m.id AS neighbor_id,
                    coalesce(m.label, m.title, m.name, m.nama_norm, m.id) AS neighbor,
                    labels(m) AS neighbor_labels,
                    properties(r) AS relation_props
                LIMIT $limit
                """,
                node_ids=node_ids,
                graph_name=graph_name,
                limit=limit,
            ).data()
        return rows
    finally:
        driver.close()


def _neo4j_shortest_path_subgraph(
    node_ids: list[str],
    *,
    graph_name: str,
    limit: int = 40,
    max_depth: int = 4,
) -> list[dict[str, Any]]:
    """Retrieve a compact shortest-path subgraph between matched entity nodes."""
    node_ids = _dedupe_terms(node_ids, limit=8)
    if len(node_ids) < 2:
        return _neo4j_neighborhood(node_ids, graph_name=graph_name, limit=limit)

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver()
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        return []

    depth = max(1, min(int(max_depth or 4), 6))
    pairs = [
        {"source": source, "target": target}
        for index, source in enumerate(node_ids)
        for target in node_ids[index + 1 :]
        if source != target
    ]
    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            rows = session.run(
                f"""
                UNWIND $pairs AS pair
                MATCH (a:KGNode {{id: pair.source}}), (b:KGNode {{id: pair.target}})
                WHERE ($graph_name = '' OR a.graph_name = $graph_name)
                  AND ($graph_name = '' OR b.graph_name = $graph_name)
                MATCH path = shortestPath((a)-[*..{depth}]-(b))
                WITH path
                LIMIT $path_limit
                UNWIND relationships(path) AS r
                WITH DISTINCT startNode(r) AS s, r, endNode(r) AS t
                WHERE $graph_name = '' OR r.graph_name = $graph_name
                RETURN
                    s.id AS center_id,
                    coalesce(s.label, s.title, s.name, s.nama_norm, s.id) AS center,
                    labels(s) AS center_labels,
                    type(r) AS relation,
                    t.id AS neighbor_id,
                    coalesce(t.label, t.title, t.name, t.nama_norm, t.id) AS neighbor,
                    labels(t) AS neighbor_labels,
                    properties(r) AS relation_props
                LIMIT $limit
                """,
                pairs=pairs,
                graph_name=graph_name,
                path_limit=max(1, limit // 2),
                limit=limit,
            ).data()
        if rows:
            return rows
    finally:
        driver.close()

    return _neo4j_neighborhood(node_ids, graph_name=graph_name, limit=limit)


def _is_overview_query(query: str) -> bool:
    text = normalize_text(query)
    overview_markers = [
        "topik riset",
        "research topic",
        "topic overview",
        "overview",
        "apa saja",
        "semua topik",
        "graph sample",
        "sample ini",
    ]
    return any(marker in text for marker in overview_markers)


def _neo4j_publication_overview(*, graph_name: str, limit: int = 20) -> list[dict[str, Any]]:
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install neo4j first: pip install neo4j") from exc

    uri = neo4j_uri_for_driver()
    username = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    database = os.getenv("NEO4J_DATABASE") or "neo4j"
    if not uri or not username or not password:
        return []

    driver = GraphDatabase.driver(uri, auth=(username, password))
    try:
        with driver.session(database=database) as session:
            rows = session.run(
                """
                MATCH (p:KGNode:Publication)
                WHERE $graph_name = '' OR p.graph_name = $graph_name
                OPTIONAL MATCH (p)-[r]->(c:KGNode:Concept)
                WHERE type(r) IN [
                    'HAS_TOPIC',
                    'BELONGS_TO_DOMAIN',
                    'USES_METHOD',
                    'USES_MODEL',
                    'USES_DATASET',
                    'EVALUATED_WITH'
                ]
                WITH p, collect(DISTINCT {
                    relation: type(r),
                    concept: coalesce(c.label, c.name, c.id),
                    concept_type: c.concept_type
                }) AS concepts
                OPTIONAL MATCH (p)-[:HAS_AUTHOR]-(a:KGNode:Lecturer)
                WITH p, concepts, collect(DISTINCT coalesce(a.label, a.name, a.nama_dosen, a.nama_norm, a.id)) AS authors
                RETURN
                    p.id AS id,
                    p.title AS title,
                    p.tldr AS tldr,
                    p.year AS year,
                    authors AS authors,
                    p.keywords AS keywords,
                    concepts AS concepts
                ORDER BY p.year DESC, p.title
                LIMIT $limit
                """,
                graph_name=graph_name,
                limit=limit,
            ).data()
        return rows
    finally:
        driver.close()


def retrieval_observability_summary(retrieval: dict[str, Any]) -> dict[str, Any]:
    keyword_decomposition = retrieval.get("keyword_decomposition") or {}
    return {
        "mode": retrieval.get("mode"),
        "top_k": retrieval.get("top_k"),
        "graph_name": retrieval.get("graph_name"),
        "paper_chunks": len(retrieval.get("paper_chunks", []) or []),
        "text_units": len(retrieval.get("text_units", []) or []),
        "keywords": len(retrieval.get("keywords", []) or []),
        "entities": len(retrieval.get("entities", []) or []),
        "relationships": len(retrieval.get("relationships", []) or []),
        "subgraph_edges": len(retrieval.get("subgraph", []) or []),
        "overview_publications": len(retrieval.get("overview_publications", []) or []),
        "keyword_provider": keyword_decomposition.get("provider"),
        "keyword_cache_hit": keyword_decomposition.get("cache_hit"),
        "high_level_keywords": keyword_decomposition.get("high_level_keywords", []),
        "low_level_keywords": keyword_decomposition.get("low_level_keywords", []),
    }


def graphrag_retrieve(
    query: str,
    *,
    param: GraphRAGQueryParam | None = None,
    milvus_config: MilvusVectorIndexConfig | None = None,
) -> dict[str, Any]:
    """Retrieve GraphRAG context and log an optional Opik retrieval span."""
    param = param or GraphRAGQueryParam()
    started_at = time.perf_counter()
    with opik_span(
        "academic_graphrag.retrieve",
        type="tool",
        input={
            "query": query,
            "mode": param.mode,
            "top_k": param.top_k,
            "graph_name": param.graph_name,
            "keyword_provider": param.keyword_provider,
        },
        metadata={
            "include_vector": param.include_vector,
            "include_graph": param.include_graph,
            "keyword_top_k": param.keyword_top_k,
            "local_path_depth": param.local_path_depth,
        },
        tags=["retrieval", f"mode:{param.mode}"],
    ) as span:
        result = _graphrag_retrieve_impl(query, param=param, milvus_config=milvus_config)
        set_observation_output(
            span,
            output=retrieval_observability_summary(result),
            metadata={"duration_seconds": round(time.perf_counter() - started_at, 3)},
        )
        return result


def _graphrag_retrieve_impl(
    query: str,
    *,
    param: GraphRAGQueryParam | None = None,
    milvus_config: MilvusVectorIndexConfig | None = None,
) -> dict[str, Any]:
    """Retrieve GraphRAG context using AcademicRAG-style modes.

    Modes:
    - naive: PaperChunk vector search only.
    - subgraph: low-level keyword entity search plus Neo4j shortest-path subgraph.
    - global: high-level keyword relationship search.
    - hybrid: subgraph + global.
    - mix: naive + content keyword clues + subgraph + global.
    """
    param = param or GraphRAGQueryParam()
    mode = normalize_text(param.mode)
    if mode not in {"naive", "subgraph", "global", "hybrid", "mix"}:
        raise ValueError("mode must be one of: naive, subgraph, global, hybrid, mix")

    result: dict[str, Any] = {
        "query": query,
        "mode": mode,
        "top_k": param.top_k,
        "graph_name": param.graph_name,
        "keyword_decomposition": {},
        "local_query": query,
        "global_query": query,
        "paper_chunks": [],
        "keywords": [],
        "text_units": [],
        "entities": [],
        "relationships": [],
        "subgraph": [],
        "overview_publications": [],
    }

    keyword_rows: list[dict[str, Any]] = []
    if param.include_vector and param.use_keyword_decomposition and mode in {"subgraph", "global", "hybrid", "mix"}:
        keyword_rows = _milvus_search(
            query,
            "ContentKeyword",
            output_fields=["graphName", "keywords", "sourcePaper"],
            top_k=param.keyword_top_k,
            config=milvus_config,
            graph_name=param.graph_name,
        )
        result["keywords"] = keyword_rows
        result["keyword_decomposition"] = decompose_query_keywords(query, keyword_rows, param=param)

    keyword_decomposition = result.get("keyword_decomposition") or {}
    low_level_keywords = keyword_decomposition.get("low_level_keywords") or []
    high_level_keywords = keyword_decomposition.get("high_level_keywords") or []
    local_query = _keyword_query(low_level_keywords, query)
    global_query = _keyword_query(high_level_keywords, query)
    fused_text_query = _keyword_query([*low_level_keywords, *high_level_keywords], query)
    result["local_query"] = local_query
    result["global_query"] = global_query

    if param.include_vector and mode in {"naive", "mix"}:
        result["paper_chunks"] = _milvus_search(
            query,
            "PaperChunk",
            output_fields=["graphName", "title", "content", "year", "paperUrl", "authors"],
            top_k=param.top_k,
            config=milvus_config,
            graph_name=param.graph_name,
        )
    if param.include_vector and mode in {"subgraph", "global", "hybrid"}:
        result["text_units"] = _milvus_search(
            fused_text_query,
            "PaperChunk",
            output_fields=["graphName", "title", "content", "year", "paperUrl", "authors"],
            top_k=param.top_k,
            config=milvus_config,
            graph_name=param.graph_name,
        )
    if param.include_vector and mode in {"subgraph", "hybrid", "mix"}:
        entities = _milvus_search(
            local_query,
            "EntityEmbedding",
            output_fields=["graphName", "entityName", "entityType", "description", "nodeId", "sourceId"],
            top_k=param.top_k,
            config=milvus_config,
            graph_name=param.graph_name,
        )
        result["entities"] = entities
        node_ids = [safe_str(row.get("nodeId")) for row in entities if safe_str(row.get("nodeId"))]
        if param.include_graph:
            result["subgraph"] = _neo4j_shortest_path_subgraph(
                node_ids,
                graph_name=param.graph_name,
                limit=param.top_k * 10,
                max_depth=param.local_path_depth,
            )
    if param.include_vector and mode in {"global", "hybrid", "mix"}:
        result["relationships"] = _milvus_search(
            global_query,
            "RelationshipEmbedding",
            output_fields=["graphName", "srcId", "tgtId", "relType", "description", "sourceId"],
            top_k=param.top_k * 2 if mode in {"global", "hybrid", "mix"} else param.top_k,
            config=milvus_config,
            graph_name=param.graph_name,
        )[: param.top_k]
    if param.include_graph and mode in {"hybrid", "mix"} and _is_overview_query(query):
        result["overview_publications"] = _neo4j_publication_overview(
            graph_name=param.graph_name,
            limit=max(param.top_k * 4, 12),
        )
    return result


def format_graphrag_context(retrieval: dict[str, Any], max_chars: int = 8000) -> str:
    """Format retrieved context for inspection or optional LLM answering."""
    sections: list[str] = [f"Query: {retrieval.get('query', '')}", f"Mode: {retrieval.get('mode', '')}"]
    keyword_decomposition = retrieval.get("keyword_decomposition") or {}
    if keyword_decomposition:
        sections.append("\n[Query Keyword Decomposition]")
        sections.append(
            "provider="
            f"{keyword_decomposition.get('provider')} | "
            f"cache_hit={keyword_decomposition.get('cache_hit')} | "
            f"local_query={retrieval.get('local_query')} | "
            f"global_query={retrieval.get('global_query')}"
        )
        sections.append(
            "high_level_keywords="
            + ", ".join(safe_str(term) for term in keyword_decomposition.get("high_level_keywords", []) if safe_str(term))
        )
        sections.append(
            "low_level_keywords="
            + ", ".join(safe_str(term) for term in keyword_decomposition.get("low_level_keywords", []) if safe_str(term))
        )
        fallback_reason = safe_str(keyword_decomposition.get("fallback_reason"))
        if fallback_reason:
            sections.append(f"fallback_reason={fallback_reason}")

    def add_rows(title: str, rows: list[dict[str, Any]], fields: list[str]) -> None:
        if not rows:
            return
        sections.append(f"\n[{title}]")
        for index, row in enumerate(rows, 1):
            parts = []
            for field in fields:
                value = row.get(field)
                if value not in (None, ""):
                    parts.append(f"{field}={value}")
            distance = row.get("distance")
            if distance is not None:
                parts.append(f"distance={distance}")
            sections.append(f"{index}. " + " | ".join(parts))

    add_rows("Paper Chunks", retrieval.get("paper_chunks", []), ["title", "year", "authors", "content"])
    add_rows("Text Units", retrieval.get("text_units", []), ["title", "year", "authors", "content"])
    add_rows("Keywords", retrieval.get("keywords", []), ["sourcePaper", "keywords"])
    add_rows("Entities", retrieval.get("entities", []), ["entityName", "entityType", "description", "nodeId"])
    add_rows("Relationship Embeddings", retrieval.get("relationships", []), ["srcId", "relType", "tgtId", "description"])
    add_rows("Neo4j Subgraph", retrieval.get("subgraph", []), ["center", "relation", "neighbor"])
    overview_rows = retrieval.get("overview_publications", []) or []
    if overview_rows:
        sections.append("\n[Graph Publication Overview]")
        for index, row in enumerate(overview_rows, 1):
            concepts = []
            for concept in row.get("concepts") or []:
                relation = safe_str(concept.get("relation"))
                label = safe_str(concept.get("concept"))
                concept_type = safe_str(concept.get("concept_type"))
                if label:
                    concepts.append(f"{relation}:{label} ({concept_type})" if relation or concept_type else label)
            sections.append(
                f"{index}. title={row.get('title')} | year={row.get('year')} | "
                f"authors={row.get('authors')} | keywords={row.get('keywords')} | "
                f"tldr={row.get('tldr')} | concepts={'; '.join(concepts[:18])}"
            )

    text = "\n".join(sections)
    if len(text) > max_chars:
        return text[: max(0, max_chars - 3)].rstrip() + "..."
    return text


def summarize_graphrag_sources(retrieval: dict[str, Any]) -> dict[str, Any]:
    """Build a compact, non-secret source summary for answer audit."""
    paper_titles: list[str] = []
    for row in [*(retrieval.get("paper_chunks", []) or []), *(retrieval.get("text_units", []) or [])]:
        title = safe_str(row.get("title"))
        if title and title not in paper_titles:
            paper_titles.append(title)
    for row in retrieval.get("overview_publications", []) or []:
        title = safe_str(row.get("title"))
        if title and title not in paper_titles:
            paper_titles.append(title)

    entities: list[str] = []
    for row in retrieval.get("entities", []) or []:
        name = safe_str(row.get("entityName"))
        entity_type = safe_str(row.get("entityType"))
        label = f"{name} ({entity_type})" if entity_type else name
        if name and label not in entities:
            entities.append(label)

    relationships: list[str] = []
    for row in retrieval.get("relationships", []) or []:
        rel = safe_str(row.get("relType"))
        src = safe_str(row.get("srcId"))
        tgt = safe_str(row.get("tgtId"))
        label = f"{src} -[{rel}]-> {tgt}" if src and tgt and rel else safe_str(row.get("description"))
        if label and label not in relationships:
            relationships.append(label)

    subgraph_relations: list[str] = []
    for row in retrieval.get("subgraph", []) or []:
        center = safe_str(row.get("center"))
        relation = safe_str(row.get("relation"))
        neighbor = safe_str(row.get("neighbor"))
        label = f"{center} -[{relation}]- {neighbor}" if center and relation and neighbor else ""
        if label and label not in subgraph_relations:
            subgraph_relations.append(label)

    keyword_decomposition = retrieval.get("keyword_decomposition") or {}
    return {
        "paper_titles": paper_titles,
        "high_level_keywords": keyword_decomposition.get("high_level_keywords", []),
        "low_level_keywords": keyword_decomposition.get("low_level_keywords", []),
        "entities": entities,
        "relationships": relationships,
        "subgraph_relations": subgraph_relations,
    }


def build_graphrag_generation_messages(
    query: str,
    retrieval: dict[str, Any],
    *,
    param: GraphRAGGenerationParam | None = None,
) -> list[dict[str, str]]:
    """Create a strict evidence-grounded prompt for Groq answer synthesis."""
    param = param or GraphRAGGenerationParam()
    context = format_graphrag_context(retrieval, max_chars=param.context_max_chars)
    language_rule = (
        "Answer in the same language as the user question."
        if param.response_language == "auto"
        else f"Answer in {param.response_language}."
    )
    system_prompt = (
        "You are an Academic GraphRAG assistant for a YUNESA academic knowledge graph. "
        "Write like a concise research chatbot, not a raw retrieval report. "
        "Use ONLY the provided evidence from vector search and graph traversal. "
        "Do not invent paper titles, authors, datasets, metrics, methods, models, or years. "
        "Treat Paper Chunks as the strongest evidence, then use Keywords, Entities, Relationships, "
        "and Subgraph Relations only to support or disambiguate those papers. "
        "Treat query keyword decomposition as retrieval hints, not source evidence; cite those terms only "
        "when the same term appears in the direct paper evidence. "
        "Before naming a paper as an answer, verify that the paper evidence matches the user's "
        "main task/domain and required method/model terms; do not include merely related papers. "
        "If multiple evidence chunks have the same paper title, treat them as one paper and merge "
        "their details into a single bullet. Never list the same paper twice. "
        "If a retrieved paper only shares a broad keyword but does not match the requested task/domain, omit it. "
        "Do not add a related-work paragraph and do not mention papers that are only indirectly related. "
        "When the evidence is insufficient or contradictory, say that the KG evidence is insufficient; "
        "otherwise do not add a generic disclaimer. "
        "Do not mention limitations at all when the evidence is sufficient; do not write phrases like "
        "'no limitation section is needed' or 'the evidence is sufficient'. "
        "Prefer concrete entities from the ontology: ResearchTopic, Task, Domain, Method, Model, Dataset, Metric. "
        "Cite evidence inline using paper titles or relation names when possible. "
        f"{language_rule}"
    )
    user_prompt = (
        "Evidence:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{query}\n\n"
        "Write the answer using this exact policy:\n"
        "- Keep the whole answer short and readable for an end user.\n"
        "- Use this format only:\n"
        "  `Ringkasan:` one sentence.\n"
        "  `Paper relevan:` up to 3 bullets, each bullet contains title, author/year, and why it matches.\n"
        "  `Catatan:` one short sentence only if evidence is weak or the query wording is ambiguous.\n"
        "- Include only papers that directly match the question.\n"
        "- Merge duplicate chunks from the same paper into one bullet.\n"
        "- Cite only entities/relations/keywords that are present in the direct-answer paper evidence.\n"
        "- Do not mention unrelated or partially related retrieved papers.\n"
        "- Do not expose raw retrieval fields, graph IDs, token usage, or JSON.\n"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def clean_graphrag_answer_text(answer: str) -> str:
    """Remove generic non-informative notes while preserving weak-evidence warnings."""
    lines = []
    for line in safe_str(answer).splitlines():
        normalized = normalize_text(line)
        if normalized.startswith("catatan") and any(
            phrase in normalized
            for phrase in (
                "bukti yang ditemukan cukup kuat",
                "bukti yang ditemukan cukup relevan",
                "evidence is sufficient",
                "evidence cukup",
                "evidence yang ditemukan cukup",
                "cukup kuat untuk menjawab",
                "cukup relevan dengan pertanyaan",
                "tidak perlu catatan",
                "tidak ada catatan",
                "no limitation",
            )
        ):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def generate_graphrag_answer_with_groq(
    query: str,
    retrieval: dict[str, Any],
    *,
    param: GraphRAGGenerationParam | None = None,
) -> dict[str, Any]:
    """Generate a grounded answer and log an optional Opik LLM span."""
    param = param or GraphRAGGenerationParam()
    context_preview = format_graphrag_context(retrieval, max_chars=min(param.context_max_chars, 4000))
    started_at = time.perf_counter()
    with opik_span(
        "academic_graphrag.generate",
        type="llm",
        input={
            "query": query,
            "retrieval": retrieval_observability_summary(retrieval),
            "context_preview": context_preview,
        },
        metadata={
            "context_max_chars": param.context_max_chars,
            "max_tokens": param.max_tokens,
            "temperature": param.temperature,
            "response_language": param.response_language,
        },
        tags=["generation", "groq"],
        model=param.model,
        provider="groq",
    ) as span:
        result = _generate_graphrag_answer_with_groq_impl(query, retrieval, param=param)
        set_observation_output(
            span,
            output={
                "answer": result.get("answer"),
                "sources": result.get("sources"),
            },
            metadata={"duration_seconds": round(time.perf_counter() - started_at, 3)},
            usage=result.get("usage") or None,
        )
        return result


def _generate_graphrag_answer_with_groq_impl(
    query: str,
    retrieval: dict[str, Any],
    *,
    param: GraphRAGGenerationParam | None = None,
) -> dict[str, Any]:
    """Generate an evidence-grounded answer using Groq's OpenAI-compatible chat API."""
    param = param or GraphRAGGenerationParam()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise ValueError("Set GROQ_API_KEY first.")

    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - notebook dependency guard
        raise ImportError("Install groq first.") from exc

    messages = build_graphrag_generation_messages(query, retrieval, param=param)
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=param.model,
        messages=messages,
        temperature=param.temperature,
        max_tokens=param.max_tokens,
    )
    choice = response.choices[0]
    usage = getattr(response, "usage", None)
    return {
        "query": query,
        "model": param.model,
        "answer": clean_graphrag_answer_text(safe_str(choice.message.content)),
        "sources": summarize_graphrag_sources(retrieval),
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        },
    }


def graphrag_answer(
    query: str,
    *,
    retrieval_param: GraphRAGQueryParam | None = None,
    generation_param: GraphRAGGenerationParam | None = None,
    milvus_config: MilvusVectorIndexConfig | None = None,
) -> dict[str, Any]:
    """Run retrieval plus Groq answer synthesis."""
    retrieval_param = retrieval_param or GraphRAGQueryParam()
    generation_param = generation_param or GraphRAGGenerationParam()
    started_at = time.perf_counter()
    with opik_trace(
        "academic_graphrag.answer",
        input={
            "query": query,
            "retrieval_mode": retrieval_param.mode,
            "graph_name": retrieval_param.graph_name,
            "model": generation_param.model,
        },
        metadata={
            "retrieval_top_k": retrieval_param.top_k,
            "generation_max_tokens": generation_param.max_tokens,
            "keyword_provider": retrieval_param.keyword_provider,
        },
        tags=["answer", f"mode:{retrieval_param.mode}", "groq"],
    ) as trace:
        retrieval = graphrag_retrieve(query, param=retrieval_param, milvus_config=milvus_config)
        generation = generate_graphrag_answer_with_groq(query, retrieval, param=generation_param)
        result = {
            "retrieval": retrieval,
            "generation": generation,
            "context": format_graphrag_context(
                retrieval,
                max_chars=generation_param.context_max_chars,
            ),
        }
        set_observation_output(
            trace,
            output={
                "answer": generation.get("answer"),
                "retrieval": retrieval_observability_summary(retrieval),
                "sources": generation.get("sources"),
            },
            metadata={"duration_seconds": round(time.perf_counter() - started_at, 3)},
            usage=generation.get("usage") or None,
        )
        return result


def write_run_manifest(
    *,
    output_dir: Path,
    config: KGConfig,
    validation: dict[str, Any],
    quality: dict[str, Any],
    storage_reports: dict[str, Any] | None = None,
    artifacts: dict[str, Path] | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config": {
            "project_root": str(config.project_root),
            "build_graph_dir": str(config.build_graph_dir),
            "output_dir": str(config.output_dir),
            "sample_size": config.sample_size,
            "max_concepts_per_paper": config.max_concepts_per_paper,
        },
        "credential_status": {
            "supabase": supabase_credential_status(),
            "neo4j": neo4j_credential_status(),
            "milvus": milvus_credential_status(),
        },
        "validation": validation,
        "quality": quality,
        "storage_reports": storage_reports or {},
        "artifacts": {key: str(value) for key, value in (artifacts or {}).items()},
    }
    path = output_dir / "run_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def run_local_kg_pipeline(
    *,
    sample_size: int = 50,
    source: str = "supabase",
    graph_name: str = "yunesa_academic_kg_local",
    write_neo4j: bool = False,
    write_milvus: bool = False,
    clear_neo4j: bool = False,
    clear_milvus: bool = False,
    use_extraction: bool | None = None,
    use_gliner: bool | None = None,
    use_glirel: bool | None = None,
) -> dict[str, Any]:
    """Build and optionally write the KG locally for repeatable debugging."""
    config = KGConfig.default(sample_size=sample_size)
    load_project_env(config.project_root)

    source = normalize_text(source) or "supabase"
    try:
        if source == "local_csv":
            raise RuntimeError("forced local CSV source")
        papers_df, lecturers_df, links_df = fetch_supabase_sample(sample_size=sample_size)
        data_source = "supabase"
    except Exception:
        papers_df, lecturers_df, links_df = load_local_csv_sample(config.project_root / "notebooks", sample_size=sample_size)
        data_source = "local_csv"

    extraction_config = AcademicExtractionConfig.from_env()
    gliner_enabled = extraction_config.use_gliner
    glirel_enabled = extraction_config.use_glirel
    if use_extraction is not None:
        # In this KG schema, ontology edges are deterministic from NER concept
        # types. GLiREL remains an explicit ablation path, not the default.
        gliner_enabled = use_extraction
        if not use_extraction:
            glirel_enabled = False
    if use_gliner is not None:
        gliner_enabled = use_gliner
    if use_glirel is not None:
        glirel_enabled = use_glirel
    if not gliner_enabled:
        glirel_enabled = False
    extraction_config = AcademicExtractionConfig(
        use_gliner=gliner_enabled,
        use_glirel=glirel_enabled,
        gliner_model=extraction_config.gliner_model,
        glirel_model=extraction_config.glirel_model,
        entity_threshold=extraction_config.entity_threshold,
        relation_threshold=extraction_config.relation_threshold,
        max_text_chars=extraction_config.max_text_chars,
        max_entities_per_paper=extraction_config.max_entities_per_paper,
        max_relations_per_paper=extraction_config.max_relations_per_paper,
    )
    extracted_elements = extract_academic_elements_with_gliner_glirel(papers_df, extraction_config)

    ieee_index = IeeeSemanticIndex.from_files(
        config.thesaurus_path,
        config.taxonomy_path,
        max_terms=config.max_ieee_terms,
    )
    concept_resolver = AcademicConceptResolver.from_path(config.concept_aliases_path)
    builder = AcademicKGBuilder(
        ieee_index,
        concept_resolver=concept_resolver,
        extracted_elements=extracted_elements,
        graph_name=graph_name,
    )
    graph = builder.build(
        papers_df=papers_df,
        lecturers_df=lecturers_df,
        links_df=links_df,
        max_concepts_per_paper=config.max_concepts_per_paper,
    )
    artifacts = export_graph_artifacts(graph, config.output_dir)
    validation = builder.validate()
    quality = graph_quality_report(graph)

    storage_reports: dict[str, Any] = {
        "data_source": data_source,
        "input_rows": {
            "papers": len(papers_df),
            "lecturers": len(lecturers_df),
            "links": len(links_df),
        },
        "extraction": summarize_extracted_elements(extracted_elements),
        "entity_resolution": concept_resolver.summary(),
    }
    if write_neo4j:
        storage_reports["neo4j_write"] = write_graph_to_neo4j(
            graph,
            graph_name=graph_name,
            clear_existing=clear_neo4j,
        )
        storage_reports["neo4j_inspect"] = inspect_neo4j_graph(graph_name=graph_name)
    if write_milvus:
        storage_reports["milvus_write"] = write_vector_index_to_milvus(
            graph,
            clear_existing=clear_milvus,
            graph_name=graph_name,
        )
        storage_reports["milvus_inspect"] = inspect_milvus_collections()

    manifest_path = write_run_manifest(
        output_dir=config.output_dir,
        config=config,
        validation=validation,
        quality=quality,
        storage_reports=storage_reports,
        artifacts=artifacts,
    )

    return {
        "config": config,
        "graph": graph,
        "validation": validation,
        "quality": quality,
        "storage_reports": storage_reports,
        "artifacts": artifacts,
        "manifest_path": manifest_path,
    }
