"""
builder.py — UNESA Academic Knowledge Graph Builder
====================================================
Constructs thesis-aligned property graph as a NetworkX MultiDiGraph and provides graph export utilities.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any
import networkx as nx
import pandas as pd

from yunesa.knowledge.constants import (
    CONCEPT_EDGE_BY_TYPE,
    CONCEPT_RELATIONS,
    CONCEPT_TYPE_PRIORITY,
    MILVUS_VARCHAR_LIMITS,
)
from yunesa.knowledge.utils.text_processing import (
    safe_str,
    normalize_text,
    slugify,
    stable_id,
    canonical_document_type,
    canonical_venue_name,
    canonical_relation,
    canonical_concept_type,
    field_value,
    split_list_field,
    academic_document_id,
)
from yunesa.knowledge.graphs.relation_ops import (
    has_relation,
    add_or_merge_relation,
    deduplicate_graph_relations,
    duplicate_relation_report,
)
from yunesa.knowledge.utils.ieee_semantic import IeeeSemanticIndex
from yunesa.knowledge.utils.concept_resolver import (
    AcademicConceptResolver,
    infer_concept_type,
    extract_concepts_for_paper,
)


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
        merged_edges = deduplicate_graph_relations(self.graph)
        if merged_edges:
            self.stats["DEDUPLICATED_RELATION_EDGES"] += merged_edges
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
                graph_name=self.graph_name,
            )
            self.stats["Lecturer"] += 1

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
            document_type=canonical_document_type(field_value(paper, "document_type", "Document Type")),
            doi=field_value(paper, "doi", "DOI"),
            link=field_value(paper, "link", "Link"),
            graph_name=self.graph_name,
        )
        self.stats["Publication"] += 1
        return node_id

    def _add_publication_dimensions(self, paper_node: str, paper: pd.Series) -> None:
        venue_raw = field_value(paper, "journal", "Journal")
        if venue_raw:
            venue_clean = canonical_venue_name(venue_raw)
            if venue_clean:
                venue_node = stable_id("venue", venue_clean)
                self.graph.add_node(
                    venue_node,
                    node_type="Venue",
                    label=venue_clean,
                    name=venue_clean,
                    graph_name=self.graph_name,
                )
                self.graph.add_edge(
                    paper_node,
                    venue_node,
                    relation="PUBLISHED_IN_VENUE",
                    source="paper_metadata",
                    graph_name=self.graph_name,
                )
                self.stats["Venue"] += 1
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
            self.graph.add_edge(paper_node, lecturer_node, relation="HAS_AUTHOR", source=source, graph_name=self.graph_name)
            self.stats["HAS_AUTHOR"] += 1
        if not has_relation(self.graph, lecturer_node, paper_node, "PUBLISHES"):
            self.graph.add_edge(lecturer_node, paper_node, relation="PUBLISHES", source=source, graph_name=self.graph_name)
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
            if not normalize_text(keyword):
                continue
            resolved = self.concept_resolver.resolve(
                label=keyword,
                concept_type="Keyword",
                source="author_keyword",
            )
            concept_node = self._add_or_update_concept_node(resolved, source="author_keyword")
            created = add_or_merge_relation(
                self.graph,
                paper_node,
                concept_node,
                "HAS_KEYWORD",
                source="paper_metadata",
                matched_text=keyword,
                graph_name=self.graph_name,
            )
            if created:
                self.stats["HAS_KEYWORD"] += 1

    def _add_or_update_concept_node(self, resolved: dict[str, Any], *, source: Any = "", ieee_uri: Any = "") -> str:
        label = safe_str(resolved.get("canonical_label") or resolved.get("label") or resolved.get("raw_label"))
        norm_key = slugify(normalize_text(label))
        concept_node = stable_id("concept", norm_key)
        new_concept_type = canonical_concept_type(resolved.get("concept_type"), fallback_label=label)
        new_ieee_uri = safe_str(resolved.get("ieee_uri") or ieee_uri)
        resolution_source = safe_str(resolved.get("resolution_source") or source or "author_keyword")
        canonical_key = safe_str(resolved.get("canonical_key") or norm_key)

        if self.graph.has_node(concept_node):
            existing = self.graph.nodes[concept_node]
            current_type = existing.get("concept_type", "Keyword")
            # Upgrade concept_type if new type has higher priority
            if CONCEPT_TYPE_PRIORITY.get(new_concept_type, 1) > CONCEPT_TYPE_PRIORITY.get(current_type, 1):
                self.graph.nodes[concept_node]["concept_type"] = new_concept_type
            if not existing.get("ieee_uri") and new_ieee_uri:
                self.graph.nodes[concept_node]["ieee_uri"] = new_ieee_uri
            if existing.get("resolution_source") == "author_keyword" and resolution_source != "author_keyword":
                self.graph.nodes[concept_node]["resolution_source"] = resolution_source
        else:
            self.graph.add_node(
                concept_node,
                node_type="Concept",
                concept_type=new_concept_type,
                label=label,
                canonical_key=canonical_key,
                ieee_uri=new_ieee_uri,
                resolution_source=resolution_source,
                graph_name=self.graph_name,
            )
            self.stats["Concept"] += 1
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
            relation = canonical_relation(CONCEPT_EDGE_BY_TYPE[concept_type])
            created = add_or_merge_relation(
                self.graph,
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
            if created:
                self.stats[relation] += 1
            else:
                self.stats[f"{relation}_EVIDENCE_MERGED"] += 1

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
            relation = canonical_relation(CONCEPT_EDGE_BY_TYPE.get(resolved_type, "WORKS_ON"))
            created = add_or_merge_relation(
                self.graph,
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
            if created:
                self.stats[relation] += 1
            else:
                self.stats[f"{relation}_EVIDENCE_MERGED"] += 1

        for relation in extraction.get("relationships", []):
            head_node = entity_node_by_text.get(normalize_text(relation.get("head")))
            tail_node = entity_node_by_text.get(normalize_text(relation.get("tail")))
            if not head_node or not tail_node or head_node == tail_node:
                continue
            rel_type = canonical_relation(relation.get("relation"))
            created = add_or_merge_relation(
                self.graph,
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
            if created:
                self.stats[rel_type] += 1
            else:
                self.stats[f"{rel_type}_EVIDENCE_MERGED"] += 1

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
                created = add_or_merge_relation(self.graph, src, tgt, relation=relation, source="ieee_skos")
                if created:
                    self.stats[relation] += 1
                else:
                    self.stats[f"{relation}_EVIDENCE_MERGED"] += 1

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

        duplicates = duplicate_relation_report(self.graph)
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
            "duplicate_relations": duplicates,
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
