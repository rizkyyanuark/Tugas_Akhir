"""Backward-compatible ETL configuration facade.

Historically, ETL modules imported constants from ``knowledge.etl.config``.
The implementation now lives under ``knowledge.etl.settings`` so the settings
surface is easier to maintain, but this file remains the stable import path for
existing clients, pipelines, and tests.
"""

from knowledge.etl.settings import *  # noqa: F401,F403

