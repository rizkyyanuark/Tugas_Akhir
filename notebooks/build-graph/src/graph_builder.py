"""
graph_builder.py — UNESA Academic Knowledge Graph Builder
=========================================================
Mengonversi output dari DataLoader, TaxonomyEngine, dan NLPParser 
menjadi NetworkX MultiDiGraph sesuai ontologi yang telah disetujui.

Ontology:
  - 8 Node Types: LECTURER, PAPER, DEPARTMENT, TOPIC, CHUNK, ENTITY, VENUE, EXTERNAL_AUTHOR
  - 10 Edge Types: AUTHORED, BELONGS_TO, HAS_TOPIC, PUBLISHED_IN, BROADER, NARROWER, RELATED, 
                   MENTIONED_IN, MAPS_TO, CO_OCCURS

Strategy:
  - Phase 1 (Structural): LECTURER + PAPER + DEPARTMENT + VENUE + EXTERNAL_AUTHOR nodes & edges
  - Phase 2 (Semantic):    TOPIC nodes from IEEE Thesaurus via TaxonomyEngine + HAS_TOPIC edges
  - Phase 3 (Lexical):     CHUNK + ENTITY nodes from NLPParser + MENTIONED_IN/CO_OCCURS edges
  - Phase 4 (Embedding):   Delegated to embedding.py (LanceDB + Word2Vec)
"""

import re
import logging
import json
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter

import networkx as nx
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    """Converts text to a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '_', slug)
    return slug

def _fuzzy_match_author(author_name: str, lecturers: List[Dict], threshold: float = 0.75) -> Optional[str]:
    """
    Fuzzy-match an author name to a lecturer using SequenceMatcher.
    Returns the NIP of the matched lecturer if the score is above threshold, else None.
    """
    author_lower = author_name.strip().lower()
    best_score = 0.0
    best_nip = None

    for lec in lecturers:
        lec_name = lec.get("nama_norm", lec.get("name", "")).strip().lower()
        if not lec_name:
            continue

        score = SequenceMatcher(None, author_lower, lec_name).ratio()
        if score > best_score:
            best_score = score
            best_nip = lec.get("nip") or lec.get("id")

    if best_score >= threshold:
        return best_nip
    return None


# ──────────────────────────────────────────────────────────────────────
# GraphBuilder
# ──────────────────────────────────────────────────────────────────────

class GraphBuilder:
    """
    Builds an in-memory NetworkX MultiDiGraph following the UNESA Academic KG ontology.
    Designed for incremental construction — call each phase method in order.
    """

    def __init__(self):
        self.G = nx.MultiDiGraph()
        self._stats = Counter()
        logger.info("GraphBuilder initialized (empty MultiDiGraph).")

    # ──────────────────────────────────────────────────────────────────
    # Phase 1 — Structural Layer
    # ──────────────────────────────────────────────────────────────────

    def build_structural_layer(self, lecturers: List[Dict], papers: List[Dict]) -> Dict[str, int]:
        """
        Creates LECTURER, PAPER, DEPARTMENT, VENUE, and EXTERNAL_AUTHOR nodes,
        plus AUTHORED, BELONGS_TO, PUBLISHED_IN edges.

        Returns a stats dict for logging.
        """
        logger.info("═══ Phase 1: Building Structural Layer ═══")

        # ── LECTURER + DEPARTMENT nodes ──
        departments_seen = set()
        for lec in lecturers:
            nip = str(lec.get("nip") or lec.get("id"))
            lec_iri = f"unesa:lecturer/{nip}"

            self.G.add_node(lec_iri,
                node_type="LECTURER",
                nip=nip,
                name=lec.get("name", ""),
                nama_norm=lec.get("nama_norm", lec.get("name", "")),
                prodi=lec.get("prodi", ""),
                scopus_id=lec.get("scopus_id", ""),
                scholar_id=lec.get("scholar_id", ""),
            )
            self._stats["LECTURER"] += 1

            # DEPARTMENT
            prodi = lec.get("prodi", "")
            if prodi and prodi not in departments_seen:
                dept_iri = f"unesa:dept/{_slugify(prodi)}"
                self.G.add_node(dept_iri,
                    node_type="DEPARTMENT",
                    name=prodi,
                )
                self._stats["DEPARTMENT"] += 1
                departments_seen.add(prodi)

            # BELONGS_TO edge
            if prodi:
                dept_iri = f"unesa:dept/{_slugify(prodi)}"
                self.G.add_edge(lec_iri, dept_iri, edge_type="BELONGS_TO")
                self._stats["BELONGS_TO"] += 1

        # ── PAPER + VENUE + AUTHORED + PUBLISHED_IN ──
        venues_seen = set()
        for paper in papers:
            paper_id = str(paper.get("id") or paper.get("paper_id", ""))
            paper_iri = f"unesa:paper/{paper_id}"

            self.G.add_node(paper_iri,
                node_type="PAPER",
                paper_id=paper_id,
                title=paper.get("title", ""),
                doi=paper.get("doi", ""),
                year=paper.get("year", ""),
                document_type=paper.get("document_type", ""),
                abstract=paper.get("abstract", ""),
                tldr=paper.get("tldr", ""),
                keywords_raw=paper.get("keywords", ""),
            )
            self._stats["PAPER"] += 1

            # VENUE
            venue_name = paper.get("venue_clean", "Unknown Venue")
            if venue_name and venue_name != "Unknown Venue":
                venue_slug = _slugify(venue_name)
                venue_iri = f"unesa:venue/{venue_slug}"
                if venue_name not in venues_seen:
                    self.G.add_node(venue_iri,
                        node_type="VENUE",
                        name=venue_name,
                    )
                    self._stats["VENUE"] += 1
                    venues_seen.add(venue_name)

                self.G.add_edge(paper_iri, venue_iri, edge_type="PUBLISHED_IN")
                self._stats["PUBLISHED_IN"] += 1

            # AUTHORED edges  (fuzzy match author → lecturer)
            authors_list = paper.get("authors_list", [])
            for author_name in authors_list:
                matched_nip = _fuzzy_match_author(author_name, lecturers)
                if matched_nip:
                    lec_iri = f"unesa:lecturer/{matched_nip}"
                    self.G.add_edge(lec_iri, paper_iri, edge_type="AUTHORED")
                    self._stats["AUTHORED"] += 1
                else:
                    # EXTERNAL_AUTHOR node
                    ext_slug = _slugify(author_name)
                    ext_iri = f"unesa:external_author/{ext_slug}"
                    if not self.G.has_node(ext_iri):
                        self.G.add_node(ext_iri,
                            node_type="EXTERNAL_AUTHOR",
                            name=author_name,
                        )
                        self._stats["EXTERNAL_AUTHOR"] += 1

                    self.G.add_edge(ext_iri, paper_iri, edge_type="AUTHORED")
                    self._stats["AUTHORED"] += 1

        stats = self._phase_stats("Phase 1 — Structural")
        return stats

    # ──────────────────────────────────────────────────────────────────
    # Phase 2 — Semantic Layer
    # ──────────────────────────────────────────────────────────────────

    def build_semantic_layer(self, papers: List[Dict], taxonomy_engine) -> Dict[str, int]:
        """
        Maps each paper's keywords → IEEE Thesaurus terms via TaxonomyEngine.
        Creates TOPIC nodes and HAS_TOPIC edges.
        Also adds BROADER / NARROWER / RELATED edges from the Thesaurus graph.

        Args:
            papers: List of paper dicts (with 'keywords_clean' field).
            taxonomy_engine: An initialized TaxonomyEngine instance.

        Returns a stats dict for logging.
        """
        logger.info("═══ Phase 2: Building Semantic Layer ═══")

        mapping_log = []   # for reporting
        topics_seen = set()

        for paper in papers:
            paper_id = str(paper.get("id") or paper.get("paper_id", ""))
            paper_iri = f"unesa:paper/{paper_id}"

            keywords = paper.get("keywords_clean", [])
            for kw in keywords:
                mapped_term, rule = taxonomy_engine.map_keyword(kw)
                mapping_log.append({"keyword": kw, "mapped": mapped_term, "rule": rule})

                if mapped_term == "UNMAPPED":
                    # Still create a TOPIC node for unmapped terms (for review)
                    topic_iri = f"ieee:unmapped/{_slugify(kw)}"
                    if kw not in topics_seen:
                        self.G.add_node(topic_iri,
                            node_type="TOPIC",
                            prefLabel=kw,
                            source="unmapped",
                        )
                        self._stats["TOPIC"] += 1
                        topics_seen.add(kw)
                else:
                    topic_iri = f"ieee:{_slugify(mapped_term)}"
                    if mapped_term not in topics_seen:
                        self.G.add_node(topic_iri,
                            node_type="TOPIC",
                            prefLabel=mapped_term,
                            source=rule,
                        )
                        self._stats["TOPIC"] += 1
                        topics_seen.add(mapped_term)

                # HAS_TOPIC edge
                self.G.add_edge(paper_iri, topic_iri, edge_type="HAS_TOPIC", keyword=kw, rule=rule)
                self._stats["HAS_TOPIC"] += 1

        # ── Add BROADER / NARROWER / RELATED edges from IEEE Thesaurus ──
        import rdflib
        from rdflib.namespace import SKOS

        thesaurus_graph = taxonomy_engine.graph
        skos_rels = [
            (SKOS.broader, "BROADER"),
            (SKOS.narrower, "NARROWER"),
            (SKOS.related, "RELATED"),
        ]

        for skos_pred, edge_label in skos_rels:
            for subj, obj in thesaurus_graph.subject_objects(skos_pred):
                subj_pref = list(thesaurus_graph.objects(subj, SKOS.prefLabel))
                obj_pref = list(thesaurus_graph.objects(obj, SKOS.prefLabel))
                if not subj_pref or not obj_pref:
                    continue

                subj_label = str(subj_pref[0])
                obj_label = str(obj_pref[0])

                # Only add relations for topics already in our graph
                subj_iri = f"ieee:{_slugify(subj_label)}"
                obj_iri = f"ieee:{_slugify(obj_label)}"

                if self.G.has_node(subj_iri) and self.G.has_node(obj_iri):
                    if not self.G.has_edge(subj_iri, obj_iri):
                        self.G.add_edge(subj_iri, obj_iri, edge_type=edge_label)
                        self._stats[edge_label] += 1

        # Log mapping report
        mapped_count = sum(1 for m in mapping_log if m["mapped"] != "UNMAPPED")
        total_kw = len(mapping_log)
        coverage = (mapped_count / total_kw * 100) if total_kw > 0 else 0
        logger.info(f"Taxonomy Mapping Coverage: {mapped_count}/{total_kw} ({coverage:.1f}%)")

        for entry in mapping_log:
            logger.debug(f"  '{entry['keyword']}' → '{entry['mapped']}' ({entry['rule']})")

        stats = self._phase_stats("Phase 2 — Semantic")
        return stats

    # ──────────────────────────────────────────────────────────────────
    # Phase 3 — Lexical Layer
    # ──────────────────────────────────────────────────────────────────

    def build_lexical_layer(self, papers: List[Dict], nlp_parser) -> Dict[str, int]:
        """
        Runs NLPParser on each paper's text (tldr/abstract).
        Creates CHUNK and ENTITY nodes, plus MENTIONED_IN, CO_OCCURS, and MAPS_TO edges.

        Args:
            papers: List of paper dicts.
            nlp_parser: An initialized NLPParser instance.

        Returns a stats dict for logging.
        """
        logger.info("═══ Phase 3: Building Lexical Layer ═══")

        entity_registry = {}   # { entity_text: entity_iri }

        for paper in papers:
            paper_id = str(paper.get("id") or paper.get("paper_id", ""))
            paper_iri = f"unesa:paper/{paper_id}"

            tldr = paper.get("tldr", "")
            abstract = paper.get("abstract", "")

            chunks, entities, co_occurrences = nlp_parser.parse_document(tldr, abstract)

            # ── CHUNK nodes ──
            for idx, chunk_text in enumerate(chunks):
                chunk_iri = f"unesa:chunk/{paper_id}_{idx}"
                self.G.add_node(chunk_iri,
                    node_type="CHUNK",
                    text=chunk_text,
                    paper_id=paper_id,
                    chunk_index=idx,
                )
                self._stats["CHUNK"] += 1

            # ── ENTITY nodes + MENTIONED_IN edges ──
            for ent in entities:
                ent_text = ent["text"]
                ent_label = ent["label"]
                ent_chunk = ent["chunk"]
                ent_iri = f"unesa:entity/{_slugify(ent_text)}"

                if ent_text not in entity_registry:
                    self.G.add_node(ent_iri,
                        node_type="ENTITY",
                        label=ent_text,
                        entity_type=ent_label,
                        mention_count=1,
                    )
                    self._stats["ENTITY"] += 1
                    entity_registry[ent_text] = ent_iri
                else:
                    # Increment mention count
                    ent_iri = entity_registry[ent_text]
                    current_count = self.G.nodes[ent_iri].get("mention_count", 0)
                    self.G.nodes[ent_iri]["mention_count"] = current_count + 1

                # MENTIONED_IN: ENTITY → CHUNK
                # Find the chunk IRI matching this chunk text
                for idx, chunk_text in enumerate(chunks):
                    if chunk_text == ent_chunk:
                        chunk_iri = f"unesa:chunk/{paper_id}_{idx}"
                        self.G.add_edge(ent_iri, chunk_iri, edge_type="MENTIONED_IN")
                        self._stats["MENTIONED_IN"] += 1
                        break

            # ── CO_OCCURS edges ──
            for ent_a, ent_b in co_occurrences:
                iri_a = entity_registry.get(ent_a)
                iri_b = entity_registry.get(ent_b)
                if iri_a and iri_b and iri_a != iri_b:
                    self.G.add_edge(iri_a, iri_b, edge_type="CO_OCCURS")
                    self._stats["CO_OCCURS"] += 1

            # ── MAPS_TO: try aligning each ENTITY → nearest TOPIC ──
            for ent_text, ent_iri in entity_registry.items():
                topic_iri = f"ieee:{_slugify(ent_text)}"
                if self.G.has_node(topic_iri):
                    # Only add if not already linked
                    existing_edges = [
                        d for _, _, d in self.G.edges(ent_iri, data=True) if d.get("edge_type") == "MAPS_TO"
                    ]
                    if not existing_edges:
                        self.G.add_edge(ent_iri, topic_iri, edge_type="MAPS_TO")
                        self._stats["MAPS_TO"] += 1

        stats = self._phase_stats("Phase 3 — Lexical")
        return stats

    # ──────────────────────────────────────────────────────────────────
    # Validation & Export
    # ──────────────────────────────────────────────────────────────────

    def validate(self) -> Dict[str, Any]:
        """
        Validates graph integrity. Returns a report dict.
        Checks: orphan nodes, correct node_type labels, edge_type labels.
        """
        logger.info("═══ Validating Graph Integrity ═══")
        report = {
            "total_nodes": self.G.number_of_nodes(),
            "total_edges": self.G.number_of_edges(),
            "node_type_counts": {},
            "edge_type_counts": {},
            "orphan_nodes": [],
            "issues": [],
        }

        # Node type counts
        for node, data in self.G.nodes(data=True):
            nt = data.get("node_type", "UNKNOWN")
            report["node_type_counts"][nt] = report["node_type_counts"].get(nt, 0) + 1

        # Edge type counts
        for u, v, data in self.G.edges(data=True):
            et = data.get("edge_type", "UNKNOWN")
            report["edge_type_counts"][et] = report["edge_type_counts"].get(et, 0) + 1

        # Orphan nodes (no edges at all)
        for node in self.G.nodes():
            if self.G.degree(node) == 0:
                report["orphan_nodes"].append(node)

        if report["orphan_nodes"]:
            report["issues"].append(f"{len(report['orphan_nodes'])} orphan nodes found.")

        # Log summary
        logger.info(f"  Nodes: {report['total_nodes']}")
        logger.info(f"  Edges: {report['total_edges']}")
        for nt, cnt in sorted(report["node_type_counts"].items()):
            logger.info(f"    {nt}: {cnt}")
        for et, cnt in sorted(report["edge_type_counts"].items()):
            logger.info(f"    {et}: {cnt}")

        if report["orphan_nodes"]:
            logger.warning(f"  ⚠ Orphan nodes: {len(report['orphan_nodes'])}")
        else:
            logger.info("  ✓ No orphan nodes.")

        if not report["issues"]:
            logger.info("  ✓ Graph validation PASSED.")
        else:
            for issue in report["issues"]:
                logger.warning(f"  ⚠ {issue}")

        return report

    def export_to_json(self, filepath: str):
        """Serializes the graph to a JSON node-link file."""
        from networkx.readwrite import json_graph
        data = json_graph.node_link_data(self.G)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        logger.info(f"Graph exported to JSON: {filepath}")

    def generate_neo4j_cypher(self) -> str:
        """
        Generates Cypher CREATE/MERGE statements for loading the graph into Neo4j.
        Returns a Cypher script as a string.
        """
        lines = []
        lines.append("// ──── UNESA Academic KG — Neo4j Cypher Import ────")
        lines.append("// Auto-generated by graph_builder.py\n")

        # Nodes
        for node, data in self.G.nodes(data=True):
            node_type = data.get("node_type", "Node")
            props = {k: v for k, v in data.items() if k != "node_type" and v is not None}
            # Escape strings
            props_str = ", ".join(f'{k}: "{str(v).replace(chr(34), chr(92)+chr(34))}"' for k, v in props.items())
            safe_id = node.replace(":", "_").replace("/", "_")
            lines.append(f'MERGE ({safe_id}:{node_type} {{{props_str}}})')

        lines.append("")

        # Edges
        for u, v, data in self.G.edges(data=True):
            edge_type = data.get("edge_type", "RELATED_TO")
            safe_u = u.replace(":", "_").replace("/", "_")
            safe_v = v.replace(":", "_").replace("/", "_")
            extra_props = {k: v2 for k, v2 in data.items() if k != "edge_type"}
            if extra_props:
                props_str = ", ".join(f'{k}: "{str(v2)}"' for k, v2 in extra_props.items())
                lines.append(f'MERGE ({safe_u})-[:{edge_type} {{{props_str}}}]->({safe_v})')
            else:
                lines.append(f'MERGE ({safe_u})-[:{edge_type}]->({safe_v})')

        return "\n".join(lines)

    def get_summary(self) -> str:
        """Returns a human-readable graph summary string."""
        summary_lines = [
            "+==================================================+",
            "|         UNESA Academic Knowledge Graph            |",
            "+==================================================+",
            f"|  Total Nodes: {self.G.number_of_nodes():<35}|",
            f"|  Total Edges: {self.G.number_of_edges():<35}|",
            "+--------------------------------------------------+",
        ]

        # Node breakdown
        node_counts = Counter()
        for _, data in self.G.nodes(data=True):
            node_counts[data.get("node_type", "UNKNOWN")] += 1
        for nt in sorted(node_counts.keys()):
            summary_lines.append(f"|  {nt:<18}: {node_counts[nt]:<28}|")

        summary_lines.append("+--------------------------------------------------+")

        # Edge breakdown
        edge_counts = Counter()
        for _, _, data in self.G.edges(data=True):
            edge_counts[data.get("edge_type", "UNKNOWN")] += 1
        for et in sorted(edge_counts.keys()):
            summary_lines.append(f"|  {et:<18}: {edge_counts[et]:<28}|")

        summary_lines.append("+==================================================+")
        return "\n".join(summary_lines)

    # ──────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _phase_stats(self, phase_name: str) -> Dict[str, int]:
        """Log and return current cumulative stats."""
        stats = dict(self._stats)
        logger.info(f"  [{phase_name}] Cumulative stats: {dict(stats)}")
        logger.info(f"  [{phase_name}] Total nodes={self.G.number_of_nodes()}, edges={self.G.number_of_edges()}")
        return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # Quick smoke test with dummy data
    builder = GraphBuilder()

    dummy_lecturers = [
        {"nip": "001", "name": "Dr. Ahmad", "nama_norm": "Ahmad", "prodi": "Teknik Informatika", "scopus_id": "", "scholar_id": ""},
        {"nip": "002", "name": "Dr. Budi", "nama_norm": "Budi", "prodi": "Sistem Informasi", "scopus_id": "", "scholar_id": ""},
    ]
    dummy_papers = [
        {
            "id": "p1",
            "title": "Deep Learning for Image Classification",
            "doi": "10.1234/test",
            "year": "2025",
            "document_type": "Conference",
            "abstract": "This paper presents a deep learning model.",
            "tldr": "A deep learning model for image classification.",
            "keywords": "",
            "keywords_clean": ["deep learning", "image classification"],
            "authors_list": ["Ahmad", "John Doe"],
            "venue_clean": "IEEE Conference on AI",
            "journal": "IEEE Conference on AI",
        }
    ]

    builder.build_structural_layer(dummy_lecturers, dummy_papers)
    print(builder.get_summary())

    report = builder.validate()
    print(f"\nValidation issues: {report['issues']}")
