# ETL Pipelines and Task Mapping

This package uses a single ETL worker image with pipeline-specific task groups.
Each DAG should only reference tasks from its own pipeline.

## Papers pipeline (unesa_papers_etl)

- Module: knowledge.etl.pipelines.unesa_papers
- Task prefix: paper\_
- Tasks:
  - paper_extract_scopus
  - paper_extract_scholar
  - paper_transform
  - paper_load
  - paper_notify

## Lecturers pipeline (unesa_lecturers_etl)

- Module: knowledge.etl.pipelines.unesa_lecturers
- Task prefix: lec\_
- Tasks:
  - lec_extract_web
  - lec_extract_pddikti
  - lec_merge
  - lec_enrich
  - lec_transform
  - lec_load

## Adding a new pipeline

1. Create a new module under knowledge.etl.pipelines.
2. Export a TASKS dictionary with task name -> handler function.
3. Add tasks to the DAG using DockerOperator.

Notes:

- Keep heavy imports inside handler functions so task discovery stays fast.

See:

- pipelines/README.md
- services/README.md

## Scaffold helper

Generate a new pipeline module and DAG:

python scripts/new_etl_pipeline.py --pipeline research --tasks extract,transform,load
