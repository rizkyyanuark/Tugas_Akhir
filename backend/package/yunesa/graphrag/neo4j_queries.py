import asyncio
import os
from typing import Any
from yunesa.utils import logger
from .heuristics import AcademicHeuristics

def _academic_graph_name(graph_name: str | None = None) -> str:
    return (
        str(graph_name or "").strip()
        or os.getenv("YUNESA_NEO4J_GRAPH_NAME")
        or os.getenv("YUNESA_GRAPH_NAME")
        or "yunesa_academic_kg"
    )

async def _run_neo4j_query(cypher: str, params: dict[str, Any], graph_name: str | None) -> list[dict[str, Any]]:
    try:
        from yunesa import graph_base
        if hasattr(graph_base, "start") and not graph_base.is_running():
            graph_base.start()
        if not graph_base.is_running() or not getattr(graph_base, "driver", None):
            return []

        resolved_graph_name = _academic_graph_name(graph_name)
        full_params = dict(params)
        full_params["graph_name"] = resolved_graph_name

        def run_query() -> list[dict[str, Any]]:
            with graph_base.driver.session(database=graph_base._neo4j_database()) as session:
                rows = session.run(cypher, **full_params)
                return [dict(row) for row in rows]

        return await asyncio.to_thread(run_query)
    except Exception as exc:
        logger.warning(
            f"Neo4j query execution failed: {type(exc).__name__}: {exc}"
        )
        return []

class AcademicNeo4jQueries:
    """Consolidated Neo4j query operations for institutional Academic GraphRAG."""

    @classmethod
    async def query_collaborations(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if extracted_entities is not None:
            if "collaboration" not in (sub_intents or []):
                return []
            lecturer_candidates = extracted_entities.get("author_names") or []
            if not lecturer_candidates:
                return []
            topic_terms = extracted_entities.get("topics") or []
        else:
            if not skip_intent_check and not AcademicHeuristics._is_collaboration_query(query_text):
                return []
            lecturer_candidates = AcademicHeuristics._extract_author_name_candidates(query_text)
            if not lecturer_candidates:
                return []
            topic_terms = AcademicHeuristics._topic_terms_for_neo4j(query_text)

        cypher = """
            UNWIND $lecturer_candidates AS lecturer_name
            MATCH (lecturer:Lecturer)
            WHERE lecturer.graph_name = $graph_name
              AND (
                toLower(coalesce(lecturer.label, '')) CONTAINS toLower(lecturer_name)
                OR toLower(coalesce(lecturer.name, '')) CONTAINS toLower(lecturer_name)
                OR toLower(coalesce(lecturer.nama_dosen, '')) CONTAINS toLower(lecturer_name)
                OR toLower(coalesce(lecturer.nama_norm, '')) CONTAINS toLower(lecturer_name)
              )
            MATCH (lecturer)-[collab_rel:COLLABORATES_WITH]-(collaborator:Lecturer)
            WHERE collaborator.graph_name = $graph_name
            OPTIONAL MATCH (lecturer)-[:PUBLISHES]->(paper:Publication)<-[:PUBLISHES]-(collaborator)
            WHERE paper.graph_name = $graph_name
            WITH DISTINCT lecturer, collaborator, collab_rel, collect(DISTINCT paper) AS papers
            WITH
              lecturer,
              collaborator,
              collab_rel,
              [
                paper IN papers |
                {
                  paper_id: paper.paper_id,
                  title: coalesce(paper.title, paper.label, paper.name),
                  year: paper.year,
                  doi: paper.doi,
                  text: toLower(
                    toString(coalesce(paper.title, '')) + ' ' +
                    toString(coalesce(paper.abstract, '')) + ' ' +
                    toString(coalesce(paper.tldr, '')) + ' ' +
                    toString(coalesce(paper.keywords, ''))
                  )
                }
              ] AS paper_items
            WITH
              lecturer,
              collaborator,
              collab_rel,
              CASE
                WHEN size($topic_terms) = 0 THEN paper_items
                ELSE [
                  item IN paper_items
                  WHERE any(term IN $topic_terms WHERE item.text CONTAINS toLower(term))
                ]
              END AS matched_papers,
              paper_items
            WHERE size($topic_terms) = 0 OR size(matched_papers) > 0
            RETURN
              coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS lecturer,
              coalesce(
                collaborator.label,
                collaborator.nama_norm,
                collaborator.nama_dosen,
                collaborator.name
              ) AS collaborator,
              CASE
                WHEN size(matched_papers) > 0 THEN size(matched_papers)
                ELSE coalesce(collab_rel.paper_count, size(paper_items))
              END AS paper_count,
              [item IN matched_papers | item.paper_id][0..12] AS paper_ids,
              [item IN matched_papers | item.title][0..12] AS paper_titles,
              [item IN matched_papers | item.year][0..12] AS years,
              [item IN matched_papers | item.doi][0..12] AS dois
            ORDER BY paper_count DESC, toLower(collaborator) ASC
            LIMIT $limit
        """

        params = {
            "lecturer_candidates": lecturer_candidates,
            "topic_terms": topic_terms,
            "limit": limit
        }
        return await _run_neo4j_query(cypher, params, graph_name)

    @classmethod
    async def query_author_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 60,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if extracted_entities is not None:
            author_candidates = extracted_entities.get("author_names") or []
        else:
            if not skip_intent_check and not AcademicHeuristics._is_author_publication_query(query_text):
                return []
            author_candidates = AcademicHeuristics._extract_author_name_candidates(query_text)

        if not author_candidates:
            return []

        cypher = """
            UNWIND $author_candidates AS author_name
            MATCH (lecturer:Lecturer)
            WHERE lecturer.graph_name = $graph_name
              AND (
                toLower(coalesce(lecturer.label, '')) CONTAINS toLower(author_name)
                OR toLower(coalesce(lecturer.name, '')) CONTAINS toLower(author_name)
                OR toLower(coalesce(lecturer.nama_dosen, '')) CONTAINS toLower(author_name)
                OR toLower(coalesce(lecturer.nama_norm, '')) CONTAINS toLower(author_name)
              )
            MATCH (lecturer)-[:PUBLISHES|HAS_AUTHOR]-(paper:Publication)
            WHERE paper.graph_name = $graph_name
            WITH DISTINCT lecturer, paper
            OPTIONAL MATCH (paper)<-[:PUBLISHES]-(coauthor:Lecturer)
            WHERE coauthor.graph_name = $graph_name
            WITH lecturer, paper,
                 collect(DISTINCT coalesce(
                   coauthor.label,
                   coauthor.nama_norm,
                   coauthor.nama_dosen,
                   coauthor.name
                 )) AS connected_authors
            RETURN
              coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS author,
              paper.paper_id AS paper_id,
              coalesce(paper.title, paper.label, paper.name) AS title,
              paper.year AS year,
              CASE
                WHEN size(connected_authors) > 0 THEN connected_authors
                ELSE paper.authors
              END AS authors,
              paper.doi AS doi,
              paper.venue AS venue,
              paper.tldr AS tldr,
              paper.abstract AS abstract,
              paper.link AS link
            ORDER BY toInteger(coalesce(paper.year, '0')) DESC, title ASC
            LIMIT $limit
        """

        params = {
            "author_candidates": author_candidates,
            "limit": limit
        }
        return await _run_neo4j_query(cypher, params, graph_name)

    @classmethod
    async def query_publication_details(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 12,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if extracted_entities is not None:
            title_candidates = [extracted_entities.get("publication_title")] if extracted_entities.get("publication_title") else []
        else:
            title_candidates = AcademicHeuristics._extract_publication_title_candidates(query_text)

        if not title_candidates:
            return []

        cypher = """
            UNWIND $title_candidates AS title_candidate
            MATCH (paper:Publication)
            WHERE paper.graph_name = $graph_name
              AND toLower(coalesce(paper.title, paper.label, paper.name, ''))
                  CONTAINS toLower(title_candidate)
            OPTIONAL MATCH (paper)<-[:PUBLISHES]-(author:Lecturer)
            WHERE author.graph_name = $graph_name
            WITH DISTINCT paper,
                 collect(DISTINCT coalesce(
                   author.label,
                   author.nama_norm,
                   author.nama_dosen,
                   author.name
                 )) AS connected_authors
            OPTIONAL MATCH (paper)-[
              relation:HAS_KEYWORD|HAS_TOPIC|SOLVES_PROBLEM|WORKS_ON_TASK|PROPOSES_INNOVATION|USES_METHOD|USES_MODEL|
              USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN|HAS_RESULT
            ]->(concept)
            WITH paper, connected_authors,
                 collect(DISTINCT {
                   relation: type(relation),
                   value: coalesce(concept.label, concept.name, concept.id)
                 }) AS concepts
            RETURN
              paper.paper_id AS paper_id,
              coalesce(paper.title, paper.label, paper.name) AS title,
              paper.year AS year,
              CASE
                WHEN size(connected_authors) > 0 THEN connected_authors
                ELSE paper.authors
              END AS authors,
              paper.doi AS doi,
              paper.venue AS venue,
              paper.tldr AS tldr,
              paper.abstract AS abstract,
              paper.link AS link,
              concepts AS concepts
            ORDER BY toInteger(toString(coalesce(paper.year, '0'))) DESC, title ASC
            LIMIT $limit
        """

        params = {
            "title_candidates": title_candidates,
            "limit": limit
        }
        return await _run_neo4j_query(cypher, params, graph_name)

    @classmethod
    async def query_topic_frequencies(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 15,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if extracted_entities is not None:
            if "topic_frequency" not in (sub_intents or []):
                return []
        else:
            if not skip_intent_check and not AcademicHeuristics._is_topic_frequency_query(query_text):
                return []

        cypher = """
            MATCH (paper:Publication)-[
              relation:HAS_TOPIC|SOLVES_PROBLEM|WORKS_ON_TASK|PROPOSES_INNOVATION|HAS_KEYWORD|BELONGS_TO_DOMAIN|
              USES_METHOD|USES_MODEL|USES_DATASET
            ]->(concept)
            WHERE paper.graph_name = $graph_name
              AND concept.graph_name = $graph_name
            WITH
              coalesce(concept.label, concept.name, concept.id) AS topic,
              coalesce(concept.concept_type, labels(concept)[0], 'Concept') AS concept_type,
              count(DISTINCT paper) AS publication_count,
              collect(DISTINCT coalesce(paper.title, paper.label, paper.name))[0..5]
                AS sample_titles
            WHERE topic IS NOT NULL AND trim(toString(topic)) <> ''
            RETURN topic, concept_type, publication_count, sample_titles
            ORDER BY publication_count DESC, toLower(toString(topic)) ASC
            LIMIT $limit
        """

        params = {
            "limit": limit
        }
        return await _run_neo4j_query(cypher, params, graph_name)

    @classmethod
    async def query_lecturer_topic_publications(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        skip_intent_check: bool = False,
        extracted_entities: dict[str, Any] | None = None,
        sub_intents: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if extracted_entities is not None:
            if "lecturer_topic" not in (sub_intents or []):
                return []
            topic_terms = extracted_entities.get("topics") or []
            if not topic_terms:
                return []
            dept = extracted_entities.get("department")
            department_terms = [dept] if dept else []
        else:
            if not skip_intent_check and not AcademicHeuristics._is_lecturer_topic_query(query_text):
                return []
            topic_terms = AcademicHeuristics._topic_terms_for_neo4j(query_text)
            if not topic_terms:
                return []
            department_terms = AcademicHeuristics._department_terms(query_text)
        min_match_count = min(2, len(topic_terms))

        cypher = """
            MATCH (paper:Publication)
            WHERE paper.graph_name = $graph_name
              AND (
                any(term IN $topic_terms WHERE toLower(coalesce(paper.title, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.label, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.abstract, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.tldr, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.keywords, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.authors, '')) CONTAINS toLower(term))
                OR EXISTS {
                    MATCH (paper)-[:HAS_KEYWORD|HAS_TOPIC|SOLVES_PROBLEM|WORKS_ON_TASK|PROPOSES_INNOVATION|USES_METHOD|USES_MODEL|USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN]->(concept)
                    WHERE any(term IN $topic_terms WHERE toLower(coalesce(concept.label, '')) CONTAINS toLower(term) OR toLower(coalesce(concept.name, '')) CONTAINS toLower(term))
                }
              )
            MATCH (lecturer:Lecturer)-[:PUBLISHES]->(paper)
            WHERE lecturer.graph_name = $graph_name
            OPTIONAL MATCH (lecturer)-[:HAS_AFFILIATION]->(affiliation:Institution)
            WITH lecturer, paper, collect(DISTINCT affiliation) AS affiliations
            OPTIONAL MATCH (paper)-[
              :HAS_KEYWORD|HAS_TOPIC|SOLVES_PROBLEM|WORKS_ON_TASK|PROPOSES_INNOVATION|USES_METHOD|USES_MODEL|
              USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN
            ]->(concept)
            WITH lecturer, paper, affiliations, collect(DISTINCT concept) AS concepts
            WITH
              lecturer,
              paper,
              affiliations,
              concepts,
              toLower(
                toString(coalesce(paper.title, '')) + ' ' +
                toString(coalesce(paper.label, '')) + ' ' +
                toString(coalesce(paper.abstract, '')) + ' ' +
                toString(coalesce(paper.tldr, '')) + ' ' +
                toString(coalesce(paper.keywords, '')) + ' ' +
                toString(coalesce(paper.authors, ''))
              ) AS paper_text,
              [
                c IN concepts |
                toLower(
                  toString(coalesce(c.label, '')) + ' ' +
                  toString(coalesce(c.name, '')) + ' ' +
                  toString(coalesce(c.description, '')) + ' ' +
                  toString(coalesce(c.concept_type, ''))
                )
              ] AS concept_texts,
              [
                a IN affiliations |
                coalesce(a.label, a.name, a.id, '')
              ] AS affiliation_names,
              toLower(
                coalesce(lecturer.label, '') + ' ' +
                coalesce(lecturer.name, '') + ' ' +
                coalesce(lecturer.nama_dosen, '') + ' ' +
                coalesce(lecturer.nama_norm, '') + ' ' +
                coalesce(lecturer.prodi, '') + ' ' +
                coalesce(lecturer.jurusan, '') + ' ' +
                coalesce(lecturer.fakultas, '') + ' ' +
                reduce(s = '', a IN affiliations | s + ' ' + coalesce(a.label, a.name, a.id, ''))
              ) AS lecturer_text
            WHERE size($department_terms) = 0
               OR any(term IN $department_terms WHERE lecturer_text CONTAINS toLower(term))
            WITH
              lecturer,
              paper,
              affiliation_names,
              [
                term IN $topic_terms
                WHERE paper_text CONTAINS toLower(term)
                   OR any(concept_text IN concept_texts WHERE concept_text CONTAINS toLower(term))
              ] AS matched_terms
            WHERE size(matched_terms) >= $min_match_count
            WITH DISTINCT lecturer, paper, affiliation_names, matched_terms
            OPTIONAL MATCH (paper)<-[:PUBLISHES]-(coauthor:Lecturer)
            WHERE coauthor.graph_name = $graph_name
            WITH lecturer, paper, affiliation_names, matched_terms,
                 collect(DISTINCT coalesce(
                   coauthor.label,
                   coauthor.nama_norm,
                   coauthor.nama_dosen,
                   coauthor.name
                 )) AS connected_authors
            RETURN
              coalesce(lecturer.label, lecturer.nama_norm, lecturer.nama_dosen, lecturer.name) AS lecturer,
              affiliation_names AS affiliations,
              paper.paper_id AS paper_id,
              coalesce(paper.title, paper.label, paper.name) AS title,
              paper.year AS year,
              CASE
                WHEN size(connected_authors) > 0 THEN connected_authors
                ELSE paper.authors
              END AS authors,
              paper.doi AS doi,
              paper.venue AS venue,
              paper.tldr AS tldr,
              paper.abstract AS abstract,
              paper.link AS link,
              matched_terms AS matched_terms,
              size(matched_terms) AS score
            ORDER BY score DESC, toInteger(toString(coalesce(paper.year, '0'))) DESC, lecturer ASC, title ASC
            LIMIT $limit
        """

        params = {
            "topic_terms": topic_terms,
            "department_terms": department_terms,
            "min_match_count": min_match_count,
            "limit": limit
        }
        rows = await _run_neo4j_query(cypher, params, graph_name)
        
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            affiliations = data.pop("affiliations", []) or []
            data["affiliation"] = ", ".join(
                str(item) for item in affiliations if item
            )
            normalized_rows.append(data)
        return normalized_rows

    @classmethod
    async def query_papers_by_topic(
        cls,
        query_text: str,
        *,
        graph_name: str | None = None,
        limit: int = 40,
        start_year: int | None = None,
        end_year: int | None = None,
        skip_intent_check: bool = False,
    ) -> list[dict[str, Any]]:
        topic_terms = AcademicHeuristics._topic_terms_for_neo4j(query_text)
        if not topic_terms:
            return []

        cypher = """
            MATCH (paper:Publication)
            WHERE paper.graph_name = $graph_name
              AND (
                any(term IN $topic_terms WHERE toLower(coalesce(paper.title, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.label, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.abstract, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.tldr, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.keywords, '')) CONTAINS toLower(term))
                OR any(term IN $topic_terms WHERE toLower(coalesce(paper.authors, '')) CONTAINS toLower(term))
                OR EXISTS {
                    MATCH (paper)-[:HAS_KEYWORD|HAS_TOPIC|SOLVES_PROBLEM|WORKS_ON_TASK|PROPOSES_INNOVATION|USES_METHOD|USES_MODEL|USES_DATASET|EVALUATED_WITH|BELONGS_TO_DOMAIN]->(concept)
                    WHERE any(term IN $topic_terms WHERE toLower(coalesce(concept.label, '')) CONTAINS toLower(term) OR toLower(coalesce(concept.name, '')) CONTAINS toLower(term))
                }
              )
        """
        
        params = {
            "topic_terms": topic_terms,
            "limit": limit
        }
        if start_year is not None:
            cypher += "\n              AND toInteger(toString(coalesce(paper.year, '0'))) >= $start_year"
            params["start_year"] = int(start_year)
        if end_year is not None:
            cypher += "\n              AND toInteger(toString(coalesce(paper.year, '0'))) <= $end_year"
            params["end_year"] = int(end_year)
            
        cypher += """
            OPTIONAL MATCH (paper)<-[:PUBLISHES]-(coauthor:Lecturer)
            WHERE coauthor.graph_name = $graph_name
            WITH paper,
                 collect(DISTINCT coalesce(
                   coauthor.label,
                   coauthor.nama_norm,
                   coauthor.nama_dosen,
                   coauthor.name
                 )) AS connected_authors,
                 [
                   term IN $topic_terms
                   WHERE toLower(coalesce(paper.title, '')) CONTAINS toLower(term)
                      OR toLower(coalesce(paper.label, '')) CONTAINS toLower(term)
                      OR toLower(coalesce(paper.abstract, '')) CONTAINS toLower(term)
                 ] AS matched_terms
            RETURN
              paper.paper_id AS paper_id,
              coalesce(paper.title, paper.label, paper.name) AS title,
              paper.year AS year,
              CASE
                WHEN size(connected_authors) > 0 THEN connected_authors
                ELSE paper.authors
              END AS authors,
              paper.doi AS doi,
              paper.venue AS venue,
              paper.tldr AS tldr,
              paper.abstract AS abstract,
              paper.link AS link,
              matched_terms AS matched_terms,
              size(matched_terms) AS score
            ORDER BY score DESC, toInteger(toString(coalesce(paper.year, '0'))) DESC, title ASC
            LIMIT $limit
        """
        return await _run_neo4j_query(cypher, params, graph_name)
