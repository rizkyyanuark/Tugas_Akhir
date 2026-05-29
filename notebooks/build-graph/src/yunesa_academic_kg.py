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
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import networkx as nx
import pandas as pd


try:
    import rdflib
    from rdflib.namespace import RDF, RDFS, SKOS
except ImportError:  # pragma: no cover - notebook dependency guard
    rdflib = None
    RDF = RDFS = SKOS = None


STRUCTURAL_NODE_TYPES = {
    "Dosen",
    "Publikasi",
    "Venue",
    "Tahun",
    "Keyword",
}

CONCEPT_TYPES = {
    "ResearchTopic",
    "Task",
    "Domain",
    "Method",
    "Model",
    "Dataset",
    "Metric",
}

CONCEPT_EDGE_BY_TYPE = {
    "ResearchTopic": "MEMBAHAS_TOPIK",
    "Task": "MEMBAHAS_TOPIK",
    "Domain": "BERADA_PADA_DOMAIN",
    "Method": "MENGGUNAKAN_METODE",
    "Model": "MENGGUNAKAN_MODEL",
    "Dataset": "MENGGUNAKAN_DATASET",
    "Metric": "DIEVALUASI_DENGAN",
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
    r"\bsvm\b",
    r"\brandom forest\b",
    r"\bnaive bayes\b",
]

METHOD_PATTERNS = [
    r"\balgorithm\b",
    r"\bmethod\b",
    r"\bapproach\b",
    r"\btechnique\b",
    r"\bframework\b",
    r"\boptimization\b",
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
    r"\bsoftware engineering\b",
    r"\binformation system\b",
    r"\bpower system\b",
    r"\bnetwork\b",
    r"\bcybersecurity\b",
]


@dataclass(frozen=True)
class KGConfig:
    """Runtime configuration for the notebook pipeline."""

    project_root: Path
    build_graph_dir: Path
    output_dir: Path
    thesaurus_path: Path
    taxonomy_path: Path
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
        return cls(
            project_root=project_root,
            build_graph_dir=build_graph_dir,
            output_dir=output_dir,
            thesaurus_path=build_graph_dir / "ieee-thesaurus.ttl",
            taxonomy_path=build_graph_dir / "ieee-taxonomy.ttl",
            sample_size=sample_size,
        )


def load_project_env(project_root: Path) -> None:
    """Load runtime secrets from local .env or Google Colab user secrets."""
    if "google.colab" in sys.modules:
        try:
            from google.colab import userdata
        except Exception:
            userdata = None

        if userdata is not None:
            for name in [
                "SUPABASE_URL",
                "SUPABASE_SERVICE_ROLE_KEY",
                "SUPABASE_KEY",
                "NEO4J_URI",
                "NEO4J_USERNAME",
                "NEO4J_PASSWORD",
                "NEO4J_DATABASE",
            ]:
                if os.getenv(name):
                    continue
                try:
                    value = userdata.get(name)
                except Exception:
                    value = None
                if value:
                    os.environ[name] = value

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    load_dotenv(project_root / ".env", override=False)


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


def infer_concept_type(label: str, evidence_text: str = "") -> str:
    text = normalize_text(f"{label} {evidence_text}")

    def has(patterns: Iterable[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    if has(DATASET_PATTERNS):
        return "Dataset"
    if has(METRIC_PATTERNS):
        return "Metric"
    if has(MODEL_PATTERNS):
        return "Model"
    if has(TASK_PATTERNS):
        return "Task"
    if has(METHOD_PATTERNS):
        return "Method"
    if has(DOMAIN_PATTERNS):
        return "Domain"
    return "ResearchTopic"


def extract_regex_concepts(text: str) -> list[dict[str, Any]]:
    """Extract high-value concepts not always covered by IEEE terms."""
    concepts: list[dict[str, Any]] = []
    norm = safe_str(text)

    named_patterns = {
        "Metric": [
            r"\b\d+(?:\.\d+)?\s*%\b",
            r"\b(?:accuracy|precision|recall|f1-score|f1|auc|rmse|mae|flops)\b(?:\s+(?:of|around|about|sebesar))?\s*\d*(?:\.\d+)?%?",
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
    return ordered[:max_concepts]


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

    def __init__(self, ieee_index: IeeeSemanticIndex | None = None) -> None:
        self.ieee_index = ieee_index or IeeeSemanticIndex()
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
        return f"dosen:{slugify(nip)}" if nip else stable_id("dosen", name)

    def _add_lecturers(self, lecturers_df: pd.DataFrame) -> None:
        for _, row in lecturers_df.iterrows():
            name = field_value(row, "nama_norm", "nama_dosen", "name", "Name")
            if not name:
                continue

            node_id = self._lecturer_node_id(row)
            self.graph.add_node(
                node_id,
                node_type="Dosen",
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
            self.stats["Dosen"] += 1

    def _add_paper(self, paper: pd.Series) -> str:
        paper_id = field_value(paper, "paper_id", "id")
        title = field_value(paper, "title", "Title")
        node_id = f"paper:{slugify(paper_id)}" if paper_id else stable_id("paper", title)

        self.graph.add_node(
            node_id,
            node_type="Publikasi",
            label=title,
            paper_id=paper_id or node_id,
            title=title,
            abstract=field_value(paper, "abstract", "Abstract"),
            tldr=field_value(paper, "tldr", "TLDR"),
            keywords=field_value(paper, "keywords", "Keywords"),
            year=field_value(paper, "year", "Year"),
            venue=field_value(paper, "journal", "Journal"),
            document_type=canonical_document_type(field_value(paper, "document_type", "Document Type")),
            doi=field_value(paper, "doi", "DOI"),
            link=field_value(paper, "link", "Link"),
        )
        self.stats["Publikasi"] += 1
        return node_id

    def _add_publication_dimensions(self, paper_node: str, paper: pd.Series) -> None:
        year = field_value(paper, "year", "Year")
        if year:
            year_value = safe_str(year)[:4]
            year_node = f"tahun:{slugify(year_value)}"
            self.graph.add_node(year_node, node_type="Tahun", label=year_value, value=year_value)
            self.graph.add_edge(paper_node, year_node, relation="TERBIT_PADA", source="paper_metadata")
            self.stats["TERBIT_PADA"] += 1

        venue = field_value(paper, "journal", "Journal")
        if venue:
            venue_clean = re.sub(r"\s+", " ", venue).strip(" ,.-")
            venue_node = stable_id("venue", venue_clean)
            self.graph.add_node(venue_node, node_type="Venue", label=venue_clean, name=venue_clean)
            self.graph.add_edge(paper_node, venue_node, relation="DITERBITKAN_DI", source="paper_metadata")
            self.stats["DITERBITKAN_DI"] += 1

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
                    self.graph.add_edge(lecturer_node, paper_node, relation="MENULIS", source="paper_lecturers")
                    self.stats["MENULIS"] += 1
                    linked = True

        author_ids = split_list_field(field_value(paper, "author_ids", "Author IDs"))
        for author_id in author_ids:
            lecturer_node = lecturer_by_author_id.get(author_id)
            if lecturer_node and not self.graph.has_edge(lecturer_node, paper_node):
                self.graph.add_edge(lecturer_node, paper_node, relation="MENULIS", source="author_id")
                self.stats["MENULIS"] += 1
                linked = True

        if linked:
            return

        for author_name in split_list_field(field_value(paper, "authors", "Authors")):
            lecturer_node = lecturer_by_name.get(normalize_text(author_name))
            if lecturer_node and not self.graph.has_edge(lecturer_node, paper_node):
                self.graph.add_edge(lecturer_node, paper_node, relation="MENULIS", source="author_name")
                self.stats["MENULIS"] += 1

    def _add_keyword_edges(self, paper_node: str, paper: pd.Series) -> None:
        for keyword in split_list_field(field_value(paper, "keywords", "Keywords")):
            key_node = stable_id("keyword", normalize_text(keyword))
            self.graph.add_node(key_node, node_type="Keyword", label=keyword, name=keyword)
            self.graph.add_edge(paper_node, key_node, relation="MEMILIKI_KEYWORD", source="paper_metadata")
            self.stats["MEMILIKI_KEYWORD"] += 1

    def _add_concept_edges(self, paper_node: str, paper: pd.Series, max_concepts: int) -> None:
        concepts = extract_concepts_for_paper(paper, self.ieee_index, max_concepts=max_concepts)
        for concept in concepts:
            concept_type = concept["concept_type"]
            if concept_type not in CONCEPT_TYPES:
                concept_type = "ResearchTopic"

            label = concept["label"]
            concept_node = stable_id("concept", f"{concept_type}:{normalize_text(label)}")
            self.graph.add_node(
                concept_node,
                node_type="Concept",
                concept_type=concept_type,
                label=label,
                name=label,
                ieee_uri=concept.get("uri", ""),
                source=concept.get("source", ""),
            )
            relation = CONCEPT_EDGE_BY_TYPE[concept_type]
            self.graph.add_edge(
                paper_node,
                concept_node,
                relation=relation,
                source=concept.get("source", ""),
                match_type=concept.get("match_type", ""),
                matched_text=concept.get("match", ""),
                score=float(concept.get("score", 0.0)),
                provenance=json.dumps(
                    {
                        "matched_label": concept.get("matched_label", ""),
                        "ieee_uri": concept.get("uri", ""),
                        "source": concept.get("source", ""),
                    },
                    ensure_ascii=False,
                ),
            )
            self.stats[relation] += 1

    def _add_ieee_relations_between_used_concepts(self) -> None:
        uri_to_node = {
            data.get("ieee_uri"): node_id
            for node_id, data in self.graph.nodes(data=True)
            if data.get("node_type") == "Concept" and data.get("ieee_uri")
        }

        for source_uri, target_uri, relation in self.ieee_index.uri_relations:
            src = uri_to_node.get(source_uri)
            tgt = uri_to_node.get(target_uri)
            if src and tgt:
                self.graph.add_edge(src, tgt, relation=relation, source="ieee_skos")
                self.stats[relation] += 1

    def validate(self) -> dict[str, Any]:
        node_type_counts = Counter(data.get("node_type", "Unknown") for _, data in self.graph.nodes(data=True))
        edge_counts = Counter(data.get("relation", "UNKNOWN") for _, _, data in self.graph.edges(data=True))
        paper_nodes = [n for n, d in self.graph.nodes(data=True) if d.get("node_type") == "Publikasi"]
        papers_without_concepts = []
        papers_without_authors = []

        for paper_node in paper_nodes:
            outgoing_relations = [data.get("relation") for _, _, data in self.graph.out_edges(paper_node, data=True)]
            incoming_relations = [data.get("relation") for _, _, data in self.graph.in_edges(paper_node, data=True)]
            if not any(rel in CONCEPT_EDGE_BY_TYPE.values() for rel in outgoing_relations):
                papers_without_concepts.append(paper_node)
            if "MENULIS" not in incoming_relations:
                papers_without_authors.append(paper_node)

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_type_counts": dict(node_type_counts),
            "edge_counts": dict(edge_counts),
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
        "edge_counts": dict(Counter(d.get("relation", "UNKNOWN") for _, _, d in graph.edges(data=True))),
    }
    paths["summary_json"].write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return paths


def build_academic_kg_from_supabase(sample_size: int = 50) -> dict[str, Any]:
    config = KGConfig.default(sample_size=sample_size)
    load_project_env(config.project_root)

    papers_df, lecturers_df, links_df = fetch_supabase_sample(sample_size=sample_size)
    ieee_index = IeeeSemanticIndex.from_files(
        config.thesaurus_path,
        config.taxonomy_path,
        max_terms=config.max_ieee_terms,
    )

    builder = AcademicKGBuilder(ieee_index)
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
        "graph": graph,
        "validation": builder.validate(),
        "artifacts": artifacts,
    }
