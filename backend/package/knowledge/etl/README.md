# Yunesa ETL

This package contains the Airflow-triggered ETL worker for lecturer and paper
data ingestion.

## Layout

- `run_worker.py` is the stable CLI entrypoint used by Airflow and Docker:
  `python -m knowledge.etl.run_worker <task>`.
- `worker/` contains worker internals: runtime config and task registry
  discovery.
- `settings/` contains environment-driven settings, program-study metadata,
  storage selection, crawler options, and static cleaning constants.
- `config.py` is a compatibility facade. Existing imports from
  `knowledge.etl.config` should keep working.
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
