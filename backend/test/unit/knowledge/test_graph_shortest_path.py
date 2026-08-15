from __future__ import annotations

import asyncio

from yunesa.knowledge.graphs.adapters.core import CoreGraphAdapter
from yunesa.knowledge.graphs.adapters.lightrag import LightRAGGraphAdapter
from yunesa.knowledge.graphs.core_graph_service import CoreGraphService
from yunesa.graphrag.storage import MilvusVectorStorage, Neo4jGraphStorage


class FakeNode(dict):
    def __init__(self, node_id: str, name: str, label: str) -> None:
        super().__init__(id=node_id, label=name, graph_name="yunesa_academic_kg")
        self.element_id = f"element-{node_id}"
        self.labels = {"KGNode", label}


class FakeRelationship(dict):
    def __init__(
        self,
        edge_id: str,
        source: FakeNode,
        target: FakeNode,
        relation: str,
    ) -> None:
        super().__init__(graph_name="yunesa_academic_kg")
        self.element_id = edge_id
        self.start_node = source
        self.end_node = target
        self.type = relation


class FakeResult:
    def __init__(self, record):
        self.record = record

    def single(self):
        return self.record


class FakeTransaction:
    def __init__(self, records):
        self.records = list(records)
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult(self.records.pop(0))


class FakeSession:
    def __init__(self, transaction: FakeTransaction):
        self.transaction = transaction

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute_read(self, callback):
        return callback(self.transaction)


class FakeDriver:
    def __init__(self, transaction: FakeTransaction):
        self.transaction = transaction
        self.database = None

    def session(self, database=None):
        self.database = database
        return FakeSession(self.transaction)


class FakeConnection:
    status = "open"

    def __init__(self, driver: FakeDriver):
        self.driver = driver

    def is_running(self):
        return True


def make_service(records):
    transaction = FakeTransaction(records)
    service = CoreGraphService.__new__(CoreGraphService)
    service.connection = FakeConnection(FakeDriver(transaction))
    service.kgdb_name = "neo4j"
    return service, transaction


def test_core_graph_service_shortest_path_validates_limits_and_namespace() -> None:
    publication = FakeNode("paper-1", "Paper One", "Publication")
    lecturer = FakeNode("lecturer-1", "Yuni Yamasari", "Lecturer")
    relation = FakeRelationship(
        "rel-1",
        publication,
        lecturer,
        "HAS_AUTHOR",
    )
    service, transaction = make_service(
        [{"nodes": [publication, lecturer], "rels": [relation]}]
    )

    result = service.get_shortest_path(
        ["paper-1", "lecturer-1", "paper-1", "ignored-1", "ignored-2",
         "ignored-3", "ignored-4", "ignored-5", "ignored-6"],
        graph_name="yunesa_academic_kg",
        max_hops=99,
        max_nodes=999,
    )

    query, params = transaction.calls[0]
    assert "shortestPath((source)-[*..6]-(target))" in query
    assert "rel.graph_name = $graph_name" in query
    assert params["graph_name"] == "yunesa_academic_kg"
    assert params["node_limit"] == 80
    assert len(params["node_ids"]) == 8
    assert {node["id"] for node in result["nodes"]} == {
        "paper-1",
        "lecturer-1",
    }
    assert result["edges"][0]["type"] == "HAS_AUTHOR"


def test_core_graph_service_falls_back_to_resolved_seed_nodes() -> None:
    publication = FakeNode("paper-1", "Paper One", "Publication")
    service, transaction = make_service(
        [
            None,
            {"nodes": [publication], "rels": []},
        ]
    )

    result = service.get_shortest_path(
        ["paper-1", "missing-node"],
        graph_name="yunesa_academic_kg",
    )

    assert len(transaction.calls) == 2
    assert "node.id IN $node_ids" in transaction.calls[1][0]
    assert [node["id"] for node in result["nodes"]] == ["paper-1"]
    assert result["edges"] == []


def test_core_graph_adapter_delegates_shortest_path_in_worker_thread() -> None:
    class FakeService:
        def __init__(self):
            self.kwargs = {}

        def is_running(self):
            return True

        def get_shortest_path(self, **kwargs):
            self.kwargs = kwargs
            return {
                "nodes": [
                    {
                        "id": "paper-1",
                        "name": "Paper One",
                        "type": "Publication",
                        "labels": ["Publication"],
                        "properties": {},
                    }
                ],
                "edges": [],
            }

    service = FakeService()
    adapter = CoreGraphAdapter(
        graph_db_instance=service,
        config={"graph_name": "yunesa_academic_kg"},
    )

    result = asyncio.run(
        adapter.get_shortest_path(
            ["paper-1"],
            max_hops=2,
            max_nodes=20,
        )
    )

    assert service.kwargs == {
        "node_ids": ["paper-1"],
        "graph_name": "yunesa_academic_kg",
        "max_hops": 2,
        "max_nodes": 20,
    }
    assert result["nodes"][0]["id"] == "paper-1"


def test_storage_adapters_delegate_without_owning_business_logic() -> None:
    class FakeGraphAdapter:
        async def query_nodes(self, keyword, **kwargs):
            return {"nodes": [{"id": keyword}], "edges": []}

        async def get_shortest_path(self, node_ids, max_hops=3, **kwargs):
            return {
                "nodes": [{"id": node_id} for node_id in node_ids],
                "edges": [],
                "max_hops": max_hops,
            }

    graph_storage = Neo4jGraphStorage(
        adapter=FakeGraphAdapter(),
        graph_name="yunesa_academic_kg",
    )
    graph_result = asyncio.run(
        graph_storage.get_shortest_path(["a", "b"], max_hops=2)
    )
    assert graph_result["max_hops"] == 2

    captured = {}

    async def fake_search(**kwargs):
        captured.update(kwargs)
        return [{"entityName": "EfficientNet"}]

    vector_storage = MilvusVectorStorage(fake_search)
    vector_result = asyncio.run(
        vector_storage.query(
            "efficientnet",
            collection_name="EntityEmbedding",
            output_fields=["entityName"],
            text_fields=["entityName"],
            top_k=5,
            graph_name="yunesa_academic_kg",
        )
    )
    assert vector_result == [{"entityName": "EfficientNet"}]
    assert captured["collection_name"] == "EntityEmbedding"


class LightNode(dict):
    def __init__(self, element_id: str, entity_id: str, kb_id: str) -> None:
        super().__init__(entity_id=entity_id)
        self.element_id = element_id
        self.labels = {"Entity", kb_id}

    def items(self):
        return super().items()


class LightRelationship(dict):
    def __init__(
        self,
        element_id: str,
        source: LightNode,
        target: LightNode,
        relation: str,
    ) -> None:
        super().__init__()
        self.element_id = element_id
        self.start_node = source
        self.end_node = target
        self.type = relation

    def items(self):
        return super().items()


class LightSession:
    def __init__(self, records):
        self.records = list(records)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))
        return FakeResult(self.records.pop(0))


class LightDriver:
    def __init__(self, session: LightSession):
        self._session = session

    def session(self):
        return self._session


def make_lightrag_adapter(records):
    kb_id = "kb_academic"
    session = LightSession(records)
    adapter = LightRAGGraphAdapter.__new__(LightRAGGraphAdapter)
    adapter.config = {"kb_id": kb_id}
    adapter.kb_id = kb_id
    adapter._db = type("FakeDatabase", (), {"driver": LightDriver(session)})()
    return adapter, session


def test_lightrag_shortest_path_is_undirected_and_namespaced() -> None:
    lecturer = LightNode("lecturer-1", "Yuni Yamasari", "kb_academic")
    publication = LightNode("paper-1", "Psychomotor Domain", "kb_academic")
    relation = LightRelationship(
        "edge-1",
        lecturer,
        publication,
        "PUBLISHES",
    )
    adapter, session = make_lightrag_adapter(
        [{"nodes": [lecturer, publication], "rels": [relation]}]
    )

    result = asyncio.run(
        adapter.get_shortest_path(
            ["lecturer-1", "paper-1"],
            max_hops=99,
            max_nodes=999,
        )
    )

    query, params = session.calls[0]
    assert "shortestPath((source)-[*..6]-(target))" in query
    assert "source:`kb_academic`" in query
    assert params["node_limit"] == 80
    assert {node["id"] for node in result["nodes"]} == {
        "lecturer-1",
        "paper-1",
    }
    assert result["edges"][0]["type"] == "PUBLISHES"


def test_lightrag_shortest_path_falls_back_to_seed_nodes() -> None:
    publication = LightNode("paper-1", "Psychomotor Domain", "kb_academic")
    adapter, session = make_lightrag_adapter(
        [
            None,
            {"nodes": [publication], "rels": []},
        ]
    )

    result = asyncio.run(
        adapter.get_shortest_path(
            ["paper-1", "missing"],
            max_hops=3,
        )
    )

    assert len(session.calls) == 2
    assert "node.entity_id IN $node_ids" in session.calls[1][0]
    assert [node["id"] for node in result["nodes"]] == ["paper-1"]
    assert result["edges"] == []
