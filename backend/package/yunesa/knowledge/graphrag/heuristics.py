import re
from typing import Any
from .query_planner import AcademicQueryPlanner

ACADEMIC_STOPWORDS = {
    "using", "linear", "regression", "learning", "classification",
    "clustering", "network", "framework", "analysis", "system",
    "model", "algorithm", "prediction", "predicting", "performance",
    "student", "students", "education", "educational", "based",
    "method", "methods", "data", "mining", "validation", "sampling"
}

class AcademicHeuristics:
    """Heuristic query intent classification and entity extraction."""

    @classmethod
    def _query_terms(cls, query_text: str, *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.query_terms(query_text, max_terms=max_terms)

    @classmethod
    def _dedupe_terms(cls, values: list[Any], *, max_terms: int = 8) -> list[str]:
        return AcademicQueryPlanner.dedupe_terms(values, max_terms=max_terms)

    @classmethod
    def _is_author_publication_query(cls, query_text: str) -> bool:
        terms = set(cls._query_terms(query_text, max_terms=24))
        text = str(query_text or "").casefold()
        query_markers = (
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
        has_marker = bool(terms & AcademicQueryPlanner.AUTHOR_PUBLICATION_QUERY_MARKERS) or any(
            marker in text for marker in query_markers
        )
        has_person_hint = bool(
            re.search(r"\b[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)+", query_text or "")
            or cls._extract_author_name_candidates(query_text)
        )
        return has_marker and has_person_hint

    @classmethod
    def _is_author_publication_enumeration_query(cls, query_text: str) -> bool:
        if not cls._is_author_publication_query(query_text):
            return False

        text = re.sub(r"\s+", " ", str(query_text or "").casefold()).strip()
        return any(
            marker in text
            for marker in (
                "apa saja paper",
                "paper apa saja",
                "apa saja publikasi",
                "publikasi apa saja",
                "apa saja penelitian",
                "daftar paper",
                "daftar publikasi",
                "daftar penelitian",
                "list paper",
                "list publikasi",
                "papers by",
                "publications by",
                "papers written by",
                "publications written by",
            )
        )

    @classmethod
    def _extract_author_name_candidates(cls, query_text: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        candidates: list[str] = []
        for match in re.finditer(
            r"\b([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,4})\b",
            text,
        ):
            value = match.group(1).strip()
            if value.casefold() in AcademicQueryPlanner.GRAPH_STOPWORDS:
                continue
            candidates.append(value)

        # Indonesian queries often mention names in lowercase.
        lowered = text.casefold()
        for prefix in ("oleh ", "ditulis oleh ", "paper yang ditulis oleh ", "publikasi "):
            if prefix in lowered:
                raw = text[lowered.index(prefix) + len(prefix) :]
                raw = re.split(
                    r"[?.!,;()]| pada | tahun | dengan | tentang | yang | dkk\b| et al\b",
                    raw,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                if raw.strip():
                    candidates.append(raw.strip())

        # Suffix matching for lowercase name before collaboration keywords
        for suffix in (" berkolaborasi", " kolaborasi", " co-author", " coauthor", " kerja sama"):
            if suffix in lowered:
                raw = text[: lowered.index(suffix)]
                words = raw.strip().split()
                if words:
                    name_words = []
                    for word in reversed(words):
                        if word.lower() in ACADEMIC_STOPWORDS or word.lower() in AcademicQueryPlanner.GRAPH_STOPWORDS:
                            break
                        name_words.insert(0, word)

                    if name_words:
                        candidates.append(name_words[-1])
                        if len(name_words) >= 2:
                            candidates.append(" ".join(name_words[-2:]))
                        if len(name_words) >= 3:
                            candidates.append(" ".join(name_words[-3:]))

        # Prefix matching for lowercase name after collaboration keywords
        for prefix in ("kolaborasi ", "kolaborator ", "kerja sama "):
            if prefix in lowered:
                raw = text[lowered.index(prefix) + len(prefix) :]
                raw = re.split(
                    r"[?.!,;()]| pada | tahun | dengan | tentang | yang | dkk\b| et al\b",
                    raw,
                    maxsplit=1,
                    flags=re.IGNORECASE,
                )[0]
                words = raw.strip().split()
                if words:
                    name_words = []
                    for word in words:
                        if word.lower() in ACADEMIC_STOPWORDS or word.lower() in AcademicQueryPlanner.GRAPH_STOPWORDS:
                            break
                        name_words.append(word)

                    if name_words:
                        candidates.append(name_words[0])
                        if len(name_words) >= 2:
                            candidates.append(" ".join(name_words[:2]))
                        if len(name_words) >= 3:
                            candidates.append(" ".join(name_words[:3]))

        return cls._dedupe_terms(candidates, max_terms=5)

    @classmethod
    def _is_lecturer_topic_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        terms = set(cls._query_terms(query_text, max_terms=32))
        has_lecturer_intent = bool(terms & AcademicQueryPlanner.LECTURER_TOPIC_QUERY_MARKERS) or any(
            marker in text
            for marker in (
                "dosen",
                "penulis",
                "siapa",
                "lecturer",
                "author",
                "researcher",
            )
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
        return has_lecturer_intent and has_topic_intent

    @classmethod
    def _is_topic_frequency_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        has_topic = any(
            marker in text
            for marker in ("topik", "topic", "tema", "theme", "research area", "bidang riset")
        )
        has_frequency = any(
            re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text)
            for marker in AcademicQueryPlanner.TOPIC_FREQUENCY_QUERY_MARKERS
        )
        return has_topic and has_frequency

    @classmethod
    def _extract_publication_title_candidates(cls, query_text: str) -> list[str]:
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        candidates: list[str] = []
        for match in re.finditer(r"""["“']([^"”']{12,240})["”']""", text):
            candidates.append(match.group(1).strip())

        # Fallback heuristic if no quoted title was found
        if not candidates:
            lowered = text.casefold()
            author_names = cls._extract_author_name_candidates(query_text)
            sorted_authors = sorted(author_names, key=len, reverse=True)
            for kw in ("paper ", "publikasi ", "penelitian ", "artikel "):
                if kw in lowered:
                    idx = lowered.index(kw)
                    raw = text[idx + len(kw) :]
                    title_split_pattern = (
                        r"(?i)\b(?:oleh|ditulis|ditulis oleh|berkolaborasi|dengan|siapa|who|by|written by|"
                        r"published|tahun|year|pada|in|at)\b|[?.!,;()]"
                    )
                    parts = re.split(title_split_pattern, raw, maxsplit=1)
                    title_candidate = parts[0].strip()

                    for author in sorted_authors:
                        pattern = re.compile(rf"\b{re.escape(author)}\b", re.IGNORECASE)
                        title_candidate = pattern.sub("", title_candidate).strip()

                    title_candidate = re.sub(r"(?i)\b(?:oleh|ditulis|dan|and)\b", "", title_candidate).strip()
                    title_candidate = re.sub(r"\s+", " ", title_candidate).strip()

                    if len(title_candidate) >= 12:
                        candidates.append(title_candidate)

        return cls._dedupe_terms(candidates, max_terms=4)

    @classmethod
    def _has_specific_publication_reference(cls, query_text: str) -> bool:
        """Detect a concrete publication reference, not a generic paper search."""
        text = re.sub(r"\s+", " ", str(query_text or "")).strip()
        lowered = text.casefold()
        if re.search(r"""["â€œ'][^"â€ ']{12,240}["â€ ']""", text):
            return True
        if any(marker in lowered for marker in ("berjudul", "judul ", "entitled", "title ")):
            return bool(cls._extract_publication_title_candidates(query_text))
        if any(
            marker in lowered
            for marker in (
                "paper apa",
                "apa paper",
                "publikasi apa",
                "apa publikasi",
                "penelitian apa",
                "apa penelitian",
                "membahas",
                "tentang",
                "carikan",
                "cari ",
                "find ",
                "which paper",
                "what paper",
            )
        ):
            return False
        return bool(cls._extract_publication_title_candidates(query_text))

    @classmethod
    def _department_terms(cls, query_text: str) -> list[str]:
        text = str(query_text or "").casefold()
        values: list[str] = []
        if "s2 informatika" in text:
            values.extend(["s2 informatika", "informatika"])
        elif "infokom" in text:
            values.extend(["infokom", "teknik informatika", "sistem informasi", "pendidikan teknologi informasi"])
        elif "informatika" in text:
            values.append("informatika")
        return cls._dedupe_terms(values, max_terms=4)

    @classmethod
    def _topic_terms_for_neo4j(cls, query_text: str) -> list[str]:
        text = str(query_text or "").casefold()
        ignored = {
            "apa", "saja", "siapa", "mana", "dosen", "lecturer", "lecturers",
            "author", "authors", "penulis", "paper", "papers", "publikasi",
            "publication", "publications", "tentang", "bidang", "menulis",
            "ditulis", "s2", "informatika",
        }
        terms: list[str] = []
        phrase_map = {
            "machine learning": ["machine learning"],
            "deep learning": ["deep learning"],
            "artificial intelligence": ["artificial intelligence", "ai"],
            " ai ": ["artificial intelligence", "ai"],
            "data mining": ["data mining"],
            "pendidikan": ["education", "educational", "student", "students", "learning"],
            "mahasiswa": ["student", "students", "student performance"],
            "siswa": ["student", "students", "student performance"],
            "education": ["education", "educational", "student", "students"],
        }
        for marker, mapped_terms in phrase_map.items():
            if marker in text:
                terms.extend(mapped_terms)

        for term in cls._query_terms(query_text, max_terms=24):
            if term in ignored or term in AcademicQueryPlanner.GRAPH_STOPWORDS:
                continue
            terms.append(term)

        return cls._dedupe_terms(terms, max_terms=12)

    @classmethod
    def _is_collaboration_query(cls, query_text: str) -> bool:
        text = str(query_text or "").casefold()
        return any(
            marker in text
            for marker in (
                "berkolaborasi", "kolaborasi", "kolaborator", "collaborat",
                "co-author", "coauthor", "co author", "kerja sama",
            )
        )
