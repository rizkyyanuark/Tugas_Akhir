# Yunesa ETL

This package contains the Airflow-triggered ETL worker for lecturer and paper
data ingestion.

## Layout

- `run_worker.py` is the stable CLI entrypoint used by Airflow and Docker:
  `python -m yunesa.yunesa.knowledge.etl.run_worker <task>`.
- `worker/` contains worker internals: runtime config and task registry
  discovery.
- `settings/` contains environment-driven settings, program-study metadata,
  storage selection, crawler options, and static cleaning constants.
- `config.py` is a compatibility facade. Existing imports from
  `yunesa.yunesa.knowledge.etl.config` should keep working.
- `pipelines/` defines task handlers and task names consumed by Airflow DAGs.
- `services/` contains orchestration-level business logic for lecturers,
  papers, and source-specific enrichment.
- `clients/` contains external-source adapters such as PDDIKTI, SIAKADU,
  Scholar, Scopus, SciVal, SINTA, and Supabase.
- `extract/`, `transform/`, and `load/` contain stage-level ETL helpers.
- `utils/` contains storage, identity, hashing, and CSV helpers.

## Design Rule

Airflow owns scheduling and environment injection. The worker owns task
dispatch. Pipeline modules own business steps. Source clients only know how to
talk to one external system.

## Manual Paper Enrichment Smoke Test

Use this when you want to test paper enrichment and Groq TLDR generation on a
small, fixed number of papers without triggering the full Airflow DAG.

```powershell
$env:PYTHONPATH = "backend/package"
notebooks\.venv\Scripts\python.exe -m yunesa.yunesa.knowledge.etl.scripts.sample_paper_enrichment `
  --source data/papers_sample.csv `
  --limit 5 `
  --out-dir data/manual_tests/groq_5_paper_test
```

The script writes isolated CSV files under `data/manual_tests/...` and does not
overwrite the main ETL paper artifacts.

## Airflow Paper DAG Runtime Modes

`unesa_papers_etl` reads its run mode from the deployment environment:

- local Compose defaults to `sample` mode for a 5-paper scrape, enrich, and
  load smoke test,
- production Compose defaults to `incremental` mode,
- `full` mode forces source extraction when a controlled backfill is needed.

The paper DAG schedule refreshes source extraction weekly. In incremental mode,
Scopus and Scholar extraction reuse fresh source artifacts inside the configured
freshness window. A manual rerun after a downstream failure therefore does not
re-scrape those sources unless the checkpoint is stale or extraction is forced.

Runtime paper artifacts are stored as Parquet under the ETL storage root:

- `papers/raw/` keeps raw source extraction checkpoints,
- `papers/processed/` keeps transformed source and merged artifacts,
- `papers/checkpoints/` keeps resumable enrichment checkpoints,
- `papers/state/paper_enrichment_checkpoint.json` keeps small enrichment state
  metadata for operations and debugging.

Paper enrichment checkpoints after each batch. On rerun, completed enriched
rows are restored from the enriched Parquet checkpoint by stable paper title key
and only pending rows are sent back through Semantic Scholar, OpenAlex,
BrightData, and Groq enrichment. Existing flat CSV paper artifacts remain read
fallbacks during migration, while new runtime writes use Parquet.
