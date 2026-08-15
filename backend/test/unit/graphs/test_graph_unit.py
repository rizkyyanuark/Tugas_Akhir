import pytest
from unittest.mock import MagicMock, patch
import os
import sys

sys.path.append(os.getcwd())

from yunesa.knowledge.graphs.adapters.base import neo4j_uri_for_driver
from yunesa.knowledge.graphs.core_graph_service import CoreGraphService


def test_neo4j_uri_uses_explicit_self_signed_mode(monkeypatch):
    monkeypatch.setenv("NEO4J_TRUST_SELF_SIGNED", "1")

    assert (
        neo4j_uri_for_driver("neo4j+s://example.databases.neo4j.io")
        == "neo4j+ssc://example.databases.neo4j.io"
    )


def test_neo4j_uri_keeps_verified_tls_by_default(monkeypatch):
    monkeypatch.delenv("NEO4J_TRUST_SELF_SIGNED", raising=False)

    assert (
        neo4j_uri_for_driver("neo4j+s://example.databases.neo4j.io")
        == "neo4j+s://example.databases.neo4j.io"
    )


def test_core_graph_service_initialization():
    with patch("yunesa.knowledge.graphs.core_graph_service.Neo4jConnectionManager") as mock_mgr:
        mock_instance = MagicMock()
        mock_mgr.return_value = mock_instance
        service = CoreGraphService(db_manager=mock_instance)
        assert service.connection == mock_instance
        assert service.kgdb_name == "neo4j"
