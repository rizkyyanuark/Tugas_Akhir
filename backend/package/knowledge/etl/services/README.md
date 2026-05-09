# Services

This folder contains ETL domain logic and reusable functions.

Purpose:

- Implement extract, transform, and load logic.
- Remain reusable outside Airflow (tests, notebooks, CLI).

Rules:

- No task routing here; handlers live in pipelines.
- Keep functions composable and side effects explicit.
- Avoid coupling to Airflow-specific objects.

Example:

- unesa_papers.py implements paper ETL steps.
- unesa_lecturers.py wraps the lecturer scraping pipeline.
