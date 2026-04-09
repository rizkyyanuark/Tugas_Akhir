import pytest

try:
    from airflow.models import DagBag
    HAS_AIRFLOW = True
except ImportError:
    HAS_AIRFLOW = False


@pytest.fixture(scope="module")
def dagbag():
    """Load the Airflow DAGs from the dags folder."""
    if not HAS_AIRFLOW:
        pytest.skip(
            "Apache Airflow is not installed in this environment. Skipping pipeline flow tests.")
    return DagBag(dag_folder='dags/', include_examples=False)


@pytest.mark.skipif(not HAS_AIRFLOW, reason="Requires Apache Airflow")
def test_etl_to_kg_orchestration(dagbag):
    """
    Test that the ETL pipeline seamlessly triggers the Knowledge Graph Construction.
    This ensures our system automatically proceeds to building the KG after loading data.
    """
    papers_dag = dagbag.get_dag(dag_id="unesa_papers_etl")
    assert papers_dag is not None, "unesa_papers_etl DAG should exist."

    # Check that the trigger task exists
    trigger_task = papers_dag.get_task("trigger_kg_construction")
    assert trigger_task is not None, "trigger_kg_construction task must exist in the ETL DAG."

    # Check that it triggers the correct downstream DAG
    assert trigger_task.trigger_dag_id == "unesa_kg_pipeline", \
        "trigger_kg_construction must trigger the 'unesa_kg_pipeline' DAG."

    # Check that the trigger happens after the load task
    assert "load_data" in trigger_task.upstream_task_ids or "load_papers" in trigger_task.upstream_task_ids or any(t.startswith("load") for t in trigger_task.upstream_task_ids), \
        "The trigger to build KG should happen after the load step."


@pytest.mark.skipif(not HAS_AIRFLOW, reason="Requires Apache Airflow")
def test_kg_construction_sequence(dagbag):
    """
    Test the sequential execution of the Knowledge Graph construction inside Airflow.
    Ensures that data transformation steps execute in the exact correct order
    before being ingested into Neo4j and Weaviate.
    """
    kg_dag = dagbag.get_dag(dag_id="unesa_kg_pipeline")
    assert kg_dag is not None, "unesa_kg_pipeline DAG should exist."

    # We expect these tasks in this sequential order
    expected_sequence = [
        "build_backbone",
        "extract_entities",
        "resolve_entities",
        "curate_entities",
        "ingest_databases"
    ]

    # Verify each task exists and upstream/downstream flow is linear
    for i in range(len(expected_sequence) - 1):
        task_id = expected_sequence[i]
        next_task_id = expected_sequence[i+1]

        task = kg_dag.get_task(task_id)
        next_task = kg_dag.get_task(next_task_id)

        assert task is not None, f"Task {task_id} is missing in KG DAG."
        assert next_task is not None, f"Task {next_task_id} is missing in KG DAG."

        # Next task must consider current task as upstream
        assert task_id in next_task.upstream_task_ids, \
            f"'{next_task_id}' must execute immediately after '{task_id}'."
