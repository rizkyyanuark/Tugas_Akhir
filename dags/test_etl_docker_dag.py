"""
Airflow DAG: Test ETL Local Integration
=========================================
Runs the limited scope ETL test (1 lecturer, 5 papers) 
inside the Docker Airflow environment to verify dependencies.
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# Ensure the root directory is strictly in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Also ensure src is available
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def run_integration_test():
    """Wrapper to run the test_etl_local.py logic natively."""
    import test_etl_local
    test_etl_local.run_test()
    print("✅ Integration test completed successfully inside Airflow Docker.")


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 0,  # No retries for testing
}

with DAG(
    dag_id="test_etl_docker_integration",
    default_args=default_args,
    description="Test limited ETL pipeline locally inside Docker",
    schedule_interval=None,  # Manual trigger only
    start_date=datetime(2026, 3, 1),
    catchup=False,
    tags=["test", "etl", "qwen3.5"],
) as dag:

    test_task = PythonOperator(
        task_id="run_limited_etl",
        python_callable=run_integration_test,
    )

    test_task
