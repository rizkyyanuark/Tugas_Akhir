import pytest
from pathlib import Path

# Provide a safe import guard, so if we run tests locally on Windows
# without Apache Airflow installed, it skips these instead of crashing.
try:
    from airflow.models import DagBag
    HAS_AIRFLOW = True
except ImportError:
    HAS_AIRFLOW = False

# Path to your DAGs directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DAGS_DIR = PROJECT_ROOT / "dags"


@pytest.fixture(scope="module")
def dagbag():
    """Load the Airflow DagBag to parse all DAG files."""
    if not HAS_AIRFLOW:
        pytest.skip(
            "Apache Airflow is not installed in this environment. Skipping DAG tests.")
    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


@pytest.mark.skipif(not HAS_AIRFLOW, reason="Requires Apache Airflow")
def test_dagbag_import_errors(dagbag):
    """
    Test that all DAG files can be processed without syntax
    or import errors by the Airflow scheduler.
    """
    assert len(dagbag.import_errors) == 0, \
        f"DAG import failures: {dagbag.import_errors}"


@pytest.mark.skipif(not HAS_AIRFLOW, reason="Requires Apache Airflow")
def test_expected_dags_loaded(dagbag):
    """Ensure our primary DAGs are successfully recognized."""
    dags_in_bag = dagbag.dags.keys()

    # Assert specific DAG IDs exist
    assert "unesa_papers_etl" in dags_in_bag, "DAG 'unesa_papers_etl' not found!"
    assert "unesa_kg_pipeline" in dags_in_bag, "DAG 'unesa_kg_pipeline' not found!"


@pytest.mark.skipif(not HAS_AIRFLOW, reason="Requires Apache Airflow")
def test_unesa_kg_dag_not_paused_by_default(dagbag):
    """Check that the KG pipeline is unpaused immediately upon creation."""
    kg_dag = dagbag.get_dag("unesa_kg_pipeline")
    assert getattr(kg_dag, "is_paused_upon_creation", None) is False, \
        "KG Pipeline MUST be unpaused upon creation to allow triggering from ETL."
