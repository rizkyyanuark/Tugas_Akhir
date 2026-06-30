"""AcademicRAG-style query planning for the YUNESA academic graph.

The upstream AcademicRAG pipeline first extracts high-level and low-level
keywords, then uses those keywords to choose local/subgraph and global
relationship retrieval paths. This module keeps that backbone explicit while
adding YUNESA-specific intent adapters for structured institutional questions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
from typing import Any, Literal


AcademicMode = Literal["subgraph", "global", "hybrid", "naive", "mix"]


GRAPH_STOPWORDS = {
    "about",
    "after",
    "again",
    "against",
    "antara",
    "apakah",
    "apa",
    "based",
    "before",
    "berikan",
    "dari",
    "dalam",
    "dan",
    "dengan",
    "dosen",
    "ditulis",
    "from",
    "gimana",
    "hasil",
    "membahas",
    "menggunakan",
    "oleh",
    "pada",
    "paper",
    "penelitian",
    "penulis",
    "siapa",
    "show",
    "saja",
    "system",
    "that",
    "tahun",
    "this",
    "untuk",
    "using",
    "what",
    "yang",
}

AUTHOR_PUBLICATION_QUERY_MARKERS = {
    "author",
    "authors",
    "paper",
    "papers",
    "penelitian",
    "publikasi",
    "publication",
    "publications",
    "ditulis",
    "menulis",
    "penulis",
    "wrote",
    "written",
}

LECTURER_TOPIC_QUERY_MARKERS = {
    "author",
    "authors",
    "dosen",
    "lecturer",
    "lecturers",
    "penulis",
    "researcher",
    "researchers",
    "siapa",
}

TOPIC_FREQUENCY_QUERY_MARKERS = {
    "frequent",
    "frequently",
    "most",
    "paling",
    "sering",
    "terbanyak",
    "top",
}

KEYWORD_EXTRACTION_EXAMPLES = [
    {
        "query": "Paper apa yang membahas retinopati diabetik dengan EfficientNet dan dataset APTOS?",
        "high_level_keywords": [
            "medical image analysis",
            "diabetic retinopathy",
            "deep learning",
        ],
        "low_level_keywords": ["EfficientNet", "APTOS", "retinopati diabetik"],
    },
    {
        "query": "Dosen S2 Informatika mana yang menulis paper tentang machine learning di bidang pendidikan?",
        "high_level_keywords": [
            "machine learning",
            "education",
            "student performance",
        ],
        "low_level_keywords": ["S2 Informatika", "dosen", "paper"],
    },
    {
        "query": (
            "Metode optimasi apa saja yang dibandingkan dalam paper ANN tingkat "
            "stres mahasiswa oleh Yuni Yamasari?"
        ),
        "high_level_keywords": [
            "artificial neural network",
            "student stress classification",
            "optimization method",
        ],
        "low_level_keywords": ["Yuni Yamasari", "ANN", "optimizer"],
    },
]

KEYWORDS_EXTRACTION_CLUES_PROMPT = """---Role---

You are a helpful assistant tasked with identifying both high-level and low-level
keywords in the user's query and conversation history.

---Goal---

Given the query, content keywords from the database, and conversation history,
list both high-level and low-level keywords. High-level keywords focus on
overarching concepts or themes. Low-level keywords focus on specific entities,
details, names, datasets, methods, venues, years, and concrete terms.

---Instructions---

- Consider both the current query and relevant conversation history.
- Prefer terms that exist in the supplied database content keywords when useful.
- Preserve exact named entities, paper titles, lecturer names, datasets, models,
  methods, and years as low-level keywords.
- Output JSON only, with these keys:
  - "high_level_keywords"
  - "low_level_keywords"

######################
-Examples-
######################
{examples}

#############################
-Real Data-
######################
Conversation History:
{history}

Current Query: {query}

Database Content Keywords: {content_keywords}

Output:
"""


@dataclass(slots=True)
class AcademicKeywordPlan:
    """AcademicRAG-style keyword plan plus YUNESA routing hints."""

    provider: str = "heuristic"
    high_level_keywords: list[str] = field(default_factory=list)
    low_level_keywords: list[str] = field(default_factory=list)
    content_keyword_clues: list[str] = field(default_factory=list)
    prompt: str = ""
    intents: dict[str, bool] = field(default_factory=dict)
    raw_response: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "high_level_keywords": self.high_level_keywords,
            "low_level_keywords": self.low_level_keywords,
            "content_keyword_clues": self.content_keyword_clues,
            "prompt": self.prompt,
            "intents": self.intents,
            "raw_response": self.raw_response,
        }


@dataclass(slots=True)
class AcademicQueryParam:
    """AcademicRAG-compatible query parameters for the YUNESA runtime.

    Upstream AcademicRAG exposes `QueryParam` with modes:
    `subgraph`, `global`, `hybrid`, `naive`, and `mix`. The YUNESA backend keeps
    additional runtime aliases (`vector`, `keyword`, `graph`) for existing tool
    calls, but this object records the upstream mode explicitly.
    """

    mode: AcademicMode = "hybrid"
    runtime_mode: str = "hybrid"
    only_need_context: bool = False
    only_need_prompt: bool = False
    response_type: str = "Multiple Paragraphs"
    stream: bool = False
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "8")))
    keyword_top_k: int = field(
        default_factory=lambda: int(os.getenv("YUNESA_ACADEMIC_GRAPHRAG_KEYWORD_TOP_K", "8"))
    )
    max_token_for_text_unit: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOKEN_TEXT_CHUNK", "4000"))
    )
    max_token_for_global_context: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOKEN_RELATION_DESC", "4000"))
    )
    max_token_for_local_context: int = field(
        default_factory=lambda: int(os.getenv("MAX_TOKEN_ENTITY_DESC", "4000"))
    )
    high_level_keywords: list[str] = field(default_factory=list)
    low_level_keywords: list[str] = field(default_factory=list)
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    history_turns: int = 3
    ids: list[str] | None = None
    max_tokens: int = field(default_factory=lambda: int(os.getenv("LLM_RESPONSE_MAX_TOKENS", "4096")))
    temperature: float = field(default_factory=lambda: float(os.getenv("LLM_TEMPERATURE", "1.0")))
    use_reranker: bool = True
    use_rrf: bool = True

    @classmethod
    def from_runtime(
        cls,
        mode: str | None,
        *,
        include_graph: bool = False,
        top_k: int | None = None,
        keyword_top_k: int | None = None,
    ) -> AcademicQueryParam:
        defaults = cls()
        runtime_mode = cls.normalize_runtime_mode(mode, include_graph=include_graph)
        return cls(
            mode=cls.to_academic_mode(runtime_mode),
            runtime_mode=runtime_mode,
            top_k=top_k if top_k is not None else defaults.top_k,
            keyword_top_k=keyword_top_k if keyword_top_k is not None else defaults.keyword_top_k,
        )

    @staticmethod
    def normalize_runtime_mode(mode: str | None, *, include_graph: bool = False) -> str:
        value = str(mode or "").strip().lower() or "hybrid"
        aliases = {
            "naive": "vector",
            "bm25": "keyword",
            "local": "subgraph",
            "academic": "hybrid",
            "academic_graphrag": "hybrid",
            "graphrag": "hybrid",
            "mix": "hybrid",
        }
        normalized = aliases.get(value, value)
        if normalized not in {"vector", "keyword", "subgraph", "global", "graph", "hybrid", "mix"}:
            normalized = "hybrid"
        if include_graph and normalized in {"vector", "keyword"}:
            normalized = "hybrid"
        return normalized

    @staticmethod
    def to_academic_mode(runtime_mode: str) -> AcademicMode:
        if runtime_mode == "vector":
            return "naive"
        if runtime_mode == "keyword":
            return "naive"
        if runtime_mode == "graph":
            return "hybrid"
        if runtime_mode in {"subgraph", "global", "hybrid", "mix"}:
            return runtime_mode  # type: ignore[return-value]
        return "hybrid"

    def with_keywords(
        self,
        *,
        high_level_keywords: list[str] | None,
        low_level_keywords: list[str] | None,
    ) -> AcademicQueryParam:
        self.high_level_keywords = list(high_level_keywords or [])
        self.low_level_keywords = list(low_level_keywords or [])
        return self

    @property
    def needs_clues(self) -> bool:
        return self.runtime_mode in {"keyword", "subgraph", "global", "graph", "hybrid", "mix"}

    @property
    def needs_raw_vector(self) -> bool:
        return self.runtime_mode in {"vector", "mix", "hybrid"}

    @property
    def needs_fused_vector(self) -> bool:
        return self.runtime_mode == "keyword"

    def resolved_kg_mode(self) -> AcademicMode:
        """Resolve KG mode using upstream AcademicRAG keyword fallback rules."""
        has_low = bool(self.low_level_keywords)
        has_high = bool(self.high_level_keywords)
        if self.mode == "mix":
            if has_low and has_high:
                return "hybrid"
            if has_low:
                return "subgraph"
            if has_high:
                return "global"
            return "hybrid"
        if self.mode == "hybrid":
            if has_low and has_high:
                return "hybrid"
            if has_low:
                return "subgraph"
            if has_high:
                return "global"
        if self.mode == "subgraph" and not has_low and has_high:
            return "global"
        if self.mode == "global" and not has_high and has_low:
            return "subgraph"
        return self.mode

    def retrieval_layers(self) -> dict[str, bool]:
        kg_mode = self.resolved_kg_mode()
        return {
            "clues": self.needs_clues,
            "raw_vector": self.needs_raw_vector,
            "fused_vector": self.needs_fused_vector,
            "local": kg_mode in {"subgraph", "hybrid"},
            "global": kg_mode in {"global", "hybrid"},
            "rrf": self.use_rrf,
            "rerank": self.use_reranker,
        }

    def context_template(self) -> str:
        if self.mode == "naive":
            return "naive_rag_response"
        if self.mode in {"subgraph", "global", "hybrid"}:
            return "rag_response"
        return "mix_rag_response"

    def route_plan(self) -> dict[str, Any]:
        """Return an explicit AcademicRAG-style retrieval route.

        This mirrors upstream control flow:
        - `naive` uses vector chunks and `naive_rag_response`
        - `subgraph` uses low-level keywords and entity/subgraph retrieval
        - `global` uses high-level keywords and relationship retrieval
        - `hybrid` combines subgraph and global retrieval
        - `mix` combines KG retrieval with vector chunks and `mix_rag_response`
        """
        layers = self.retrieval_layers()
        steps: list[str] = []
        if layers["clues"]:
            steps.extend(["content_keyword_query", "keyword_extraction"])
        if layers["raw_vector"]:
            steps.append("naive_vector_query")
        if layers["fused_vector"]:
            steps.append("fused_vector_query")
        if layers["local"]:
            steps.append("subgraph_entity_query")
        if layers["global"]:
            steps.append("global_relationship_query")
        if layers.get("rrf"):
            steps.append("rrf_fusion")
        if layers.get("rerank"):
            steps.append("cross_encoder_rerank")
        steps.append(self.context_template())
        return {
            "mode": self.mode,
            "runtime_mode": self.runtime_mode,
            "kg_mode": self.resolved_kg_mode(),
            "layers": layers,
            "steps": steps,
            "context_template": self.context_template(),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "runtime_mode": self.runtime_mode,
            "kg_mode": self.resolved_kg_mode(),
            "top_k": self.top_k,
            "keyword_top_k": self.keyword_top_k,
            "high_level_keywords": self.high_level_keywords,
            "low_level_keywords": self.low_level_keywords,
            "route_plan": self.route_plan(),
        }


class AcademicQueryPlanner:
    """Plan AcademicRAG retrieval while preserving YUNESA-specific semantics."""

    GRAPH_STOPWORDS = GRAPH_STOPWORDS
    AUTHOR_PUBLICATION_QUERY_MARKERS = AUTHOR_PUBLICATION_QUERY_MARKERS
    LECTURER_TOPIC_QUERY_MARKERS = LECTURER_TOPIC_QUERY_MARKERS
    TOPIC_FREQUENCY_QUERY_MARKERS = TOPIC_FREQUENCY_QUERY_MARKERS
    KEYWORDS_EXTRACTION_CLUES_PROMPT = KEYWORDS_EXTRACTION_CLUES_PROMPT

    @classmethod
    def query_terms(cls, query_text: str, *, max_terms: int = 8) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9_+.-]{2,}", query_text or ""):
            normalized = token.strip().lower()
            if normalized in cls.GRAPH_STOPWORDS:
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= max_terms:
                break
        return terms

    @staticmethod
    def dedupe_terms(values: list[Any], *, max_terms: int = 8) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;|[]'\"")
            normalized = text.casefold()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            terms.append(text)
            if len(terms) >= max_terms:
                break
        return terms

    @classmethod
    def content_keyword_terms(
        cls,
        rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 16,
    ) -> list[str]:
        values: list[str] = []
        for row in rows or []:
            raw = row.get("keywords")
            if isinstance(raw, (list, tuple, set)):
                values.extend(str(item) for item in raw)
            else:
                values.extend(re.split(r"[,;|\n]", str(raw or "").strip("[]")))
        return cls.dedupe_terms(values, max_terms=max_terms)

    @classmethod
    def keyword_prompt(
        cls,
        query_text: str,
        content_keywords: list[str],
        *,
        history: str = "",
    ) -> str:
        examples = "\n".join(
            json.dumps(example, ensure_ascii=False, indent=2)
            for example in KEYWORD_EXTRACTION_EXAMPLES
        )
        return cls.KEYWORDS_EXTRACTION_CLUES_PROMPT.format(
            examples=examples,
            history=history or "",
            query=query_text,
            content_keywords=", ".join(content_keywords),
        )

    @staticmethod
    def _json_list(value: Any) -> list[str]:
        if isinstance(value, str):
            values = re.split(r"[,;\n]", value)
        elif isinstance(value, (list, tuple, set)):
            values = list(value)
        else:
            values = []
        return AcademicQueryPlanner.dedupe_terms(values, max_terms=32)

    @classmethod
    def parse_keyword_json(cls, raw_response: str) -> tuple[list[str], list[str]]:
        """Parse AcademicRAG keyword JSON from an LLM response.

        Upstream AcademicRAG extracts the first JSON object from the model
        response and reads `high_level_keywords` / `low_level_keywords`. Keep
        that behavior here so the backend can use the same prompt contract while
        still falling back to deterministic extraction when parsing fails.
        """
        raw_text = str(raw_response or "").strip()
        if not raw_text:
            return [], []
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            return [], []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return [], []
        return (
            cls._json_list(data.get("high_level_keywords")),
            cls._json_list(data.get("low_level_keywords")),
        )

    @classmethod
    def plan_from_model_response(
        cls,
        *,
        query_text: str,
        keyword_rows: list[dict[str, Any]] | None,
        raw_response: str,
        max_terms: int = 8,
        history: str = "",
    ) -> AcademicKeywordPlan | None:
        high_level, low_level = cls.parse_keyword_json(raw_response)
        if not high_level and not low_level:
            return None

        clue_terms = cls.content_keyword_terms(keyword_rows, max_terms=max_terms * 2)
        return AcademicKeywordPlan(
            provider="academicrag_llm",
            high_level_keywords=cls.dedupe_terms(high_level, max_terms=max_terms),
            low_level_keywords=cls.dedupe_terms(low_level, max_terms=max_terms),
            content_keyword_clues=clue_terms[:max_terms],
            prompt=cls.keyword_prompt(query_text, clue_terms[:max_terms], history=history),
            intents=cls.classify_intents(query_text),
            raw_response=str(raw_response or ""),
        )

    @classmethod
    def decompose_keywords(
        cls,
        query_text: str,
        keyword_rows: list[dict[str, Any]] | None,
        *,
        max_terms: int = 8,
        history: str = "",
    ) -> AcademicKeywordPlan:
        """Create high/low keyword clues using the AcademicRAG backbone.

        Upstream AcademicRAG obtains this split via an LLM prompt. The production
        YUNESA query tool cannot add a second LLM hop without increasing latency
        and cost, so this deterministic implementation mirrors the same output
        contract and keeps the prompt text available for traceability.
        """
        query_terms = cls.query_terms(query_text, max_terms=max_terms)
        query_tokens = set(query_terms)
        clue_terms = cls.content_keyword_terms(keyword_rows, max_terms=max_terms * 2)
        low_level: list[str] = []
        high_level: list[str] = []

        for clue in clue_terms:
            clue_tokens = set(cls.query_terms(clue, max_terms=max_terms))
            overlap = len(query_tokens & clue_tokens) / max(len(clue_tokens), 1)
            if clue.casefold() in query_text.casefold() or overlap >= 0.5:
                low_level.append(clue)
            else:
                high_level.append(clue)

        low_level = cls.dedupe_terms(
            [*low_level, *query_terms] or [query_text],
            max_terms=max_terms,
        )
        high_level = cls.dedupe_terms(
            high_level or clue_terms or low_level,
            max_terms=max_terms,
        )
        return AcademicKeywordPlan(
            provider="academicrag_heuristic",
            high_level_keywords=high_level,
            low_level_keywords=low_level,
            content_keyword_clues=clue_terms[:max_terms],
            prompt=cls.keyword_prompt(query_text, clue_terms[:max_terms], history=history),
            intents=cls.classify_intents(query_text),
        )

    @classmethod
    def classify_intents(cls, query_text: str) -> dict[str, bool]:
        text = str(query_text or "").casefold()
        terms = set(cls.query_terms(query_text, max_terms=32))
        author_markers = (
            "paper",
            "papers",
            "penelitian",
            "publikasi",
            "publication",
            "publications",
            "ditulis",
            "menulis",
            "penulis",
            "author",
            "authors",
        )
        has_author_marker = bool(terms & cls.AUTHOR_PUBLICATION_QUERY_MARKERS) or any(
            marker in text for marker in author_markers
        )
        has_name_hint = bool(
            re.search(r"\b[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+", query_text or "")
            or any(prefix in text for prefix in ("oleh ", "ditulis oleh "))
        )
        has_lecturer_intent = bool(terms & cls.LECTURER_TOPIC_QUERY_MARKERS) or any(
            marker in text
            for marker in ("dosen", "penulis", "siapa", "lecturer", "author", "researcher")
        )
        has_topic_intent = any(
            marker in text
            for marker in (
                "tentang",
                "membahas",
                "topik",
                "topic",
                "using",
                "menggunakan",
                "machine learning",
                "pendidikan",
                "education",
            )
        )
        has_frequency_topic = any(
            marker in text for marker in ("topik", "topic", "tema", "theme", "research area")
        )
        has_frequency = any(
            re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text)
            for marker in cls.TOPIC_FREQUENCY_QUERY_MARKERS
        )
        has_collaboration = any(
            marker in text
            for marker in (
                "berkolaborasi",
                "kolaborasi",
                "kolaborator",
                "collaborat",
                "co-author",
                "coauthor",
                "co author",
                "kerja sama",
            )
        )
        return {
            "author_publications": has_author_marker and has_name_hint,
            "lecturer_topic_publications": has_lecturer_intent and has_topic_intent,
            "topic_frequencies": has_frequency_topic and has_frequency,
            "collaborations": has_collaboration,
        }
