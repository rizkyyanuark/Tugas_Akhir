"""Backward-compatible graph upload service.

This module keeps the old ``UploadGraphService`` import path available for
legacy tests and callers while the main graph implementation lives in
``core_graph_service.py``.
"""

from __future__ import annotations

from typing import Any

from yunesa import config
from yunesa.knowledge.graphs.adapters.base import Neo4jConnectionManager


def _entity_name_and_props(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        props = dict(value)
        name = str(props.pop("name", props.pop("id", ""))).strip()
        if not name:
            raise ValueError("entity object must contain name or id")
        return name, props
    return str(value), {}


def _relationship_type_and_props(value: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(value, dict):
        props = dict(value)
        rel_type = str(props.pop("type", props.pop("name", ""))).strip()
        if not rel_type:
            raise ValueError("relationship object must contain type or name")
        return rel_type, props
    return str(value), {}


class UploadGraphService:
    """Legacy upload service for simple triple ingestion."""

    def __init__(self, db_manager: Neo4jConnectionManager | Any = None):
        self.connection = db_manager or Neo4jConnectionManager()
        self.driver = self.connection.driver
        self.embed_model_name = getattr(config, "embed_model", None)

    async def txt_add_vector_entity(self, triples: list[dict[str, Any]]) -> None:
        """Insert triples in the legacy Upload graph format.

        The method accepts both the old ``{"h": "A", "r": "REL", "t": "B"}``
        shape and the extended object shape with properties.
        """

        if self.driver is None:
            raise RuntimeError("Neo4j driver is not configured")

        def _merge_triple(
            tx,
            *,
            h_name: str,
            h_props: dict[str, Any],
            r_type: str,
            r_props: dict[str, Any],
            t_name: str,
            t_props: dict[str, Any],
        ) -> None:
            tx.run(
                """
                MERGE (h:Entity:Upload {name: $h_name})
                SET h += $h_props
                MERGE (t:Entity:Upload {name: $t_name})
                SET t += $t_props
                MERGE (h)-[r:UPLOAD_RELATION {type: $r_type}]->(t)
                SET r += $r_props
                """,
                h_name=h_name,
                h_props=h_props,
                r_type=r_type,
                r_props=r_props,
                t_name=t_name,
                t_props=t_props,
            )

        with self.driver.session() as session:
            for triple in triples or []:
                h_name, h_props = _entity_name_and_props(triple.get("h"))
                t_name, t_props = _entity_name_and_props(triple.get("t"))
                r_type, r_props = _relationship_type_and_props(triple.get("r"))

                session.execute_write(
                    _merge_triple,
                    h_name=h_name,
                    h_props=h_props,
                    r_type=r_type,
                    r_props=r_props,
                    t_name=t_name,
                    t_props=t_props,
                )
