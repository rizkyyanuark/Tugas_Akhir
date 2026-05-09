# Pipelines

This folder contains task handlers used by the ETL worker.

Purpose:

- Map task names (command strings) to handler functions.
- Keep orchestration concerns (logging, task routing) separate from business logic.

Rules:

- Keep handlers thin; call functions from services.
- Do not put heavy imports at module top-level.
- Ensure each module exports a TASKS dict.

Example:

- unesa*papers.py defines TASKS for paper*\* commands.
- unesa*lecturers.py defines TASKS for lec*\* commands.
