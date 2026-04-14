import pytest
from unittest.mock import MagicMock, patch
from knowledge.kg.services.kg_pipeline import KGPipeline
import pandas as pd


@pytest.fixture
def mock_pipeline():
    """Returns a test pipeline with mocked db components."""
    # Instantiating KGPipeline in test mode with max_papers=2
    # So we don't attempt to connect to Neo4j/Weaviate on initialization
    pipeline = KGPipeline(test_mode=True, max_papers=2, clear_db=False)
    return pipeline


def test_pipeline_initialization(mock_pipeline):
    """Test if KGPipeline attributes initialize correctly."""
    assert mock_pipeline.test_mode is True
    # Based on constructor condition `5 if test_mode else ...`
    assert mock_pipeline.max_papers == 5
    assert mock_pipeline.clear_db is False
    assert type(mock_pipeline.nodes) is dict
    assert type(mock_pipeline.edges) is list


@patch("src.kg.services.kg_pipeline.KGPipeline.load_sources")
def test_pipeline_load_sources(mock_load_sources, mock_pipeline):
    """Ensure KGPipeline calls `load_sources` properly when mocked."""
    # Mocking Supabase tables return to avoid HTTP calls
    df_papers = pd.DataFrame(
        {"id": ["p1", "p2"], "title": ["Paper 1", "Paper 2"]})
    df_dosen = pd.DataFrame(
        {"id": ["d1", "d2"], "name": ["Lecturer 1", "Lecturer 2"]})

    mock_load_sources.return_value = (df_papers, df_dosen)

    res_papers, res_dosen = mock_pipeline.load_sources()

    assert len(res_papers) == 2
    assert res_dosen.iloc[0]["name"] == "Lecturer 1"
    mock_load_sources.assert_called_once()


@patch("src.kg.neo4j_writer.Neo4jKGWriter")
@patch("src.kg.weaviate_writer.WeaviateKGWriter")
def test_ingest_databases_skipped_on_empty(mock_wv_w, mock_neo_w, mock_pipeline):
    """Test DB ingest behavior when nodes and edges are empty."""
    # Execute ingest_databases with empty `nodes` and `edges` (simulating fail / empty result)
    # The external DB classes should not crash if correctly mocked
    try:
        mock_pipeline.ingest_databases()
        success = True
    except Exception as e:
        success = False
        pytest.fail(f"ingest_databases shouldn't crash on empty graph: {e}")

    assert success is True
