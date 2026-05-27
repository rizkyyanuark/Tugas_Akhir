"""Study-program configuration for lecturer extraction."""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Final

from .core import ETL_PACKAGE_DIR

logger = logging.getLogger(__name__)

PROGRAM_CONFIG_PATH: Final[Path] = ETL_PACKAGE_DIR / "clients" / "program_studi_config.txt"


def default_siakadu_url(prodi_name: str) -> str:
    """Build the public SIAKADU prodi URL from a study-program name."""
    name = re.sub(r"^(S[123]|D[34]|Profesi)\s+", "", prodi_name.strip(), flags=re.I)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"https://siakadu.unesa.ac.id/prodi/{slug}" if slug else ""


def load_prodi_config(
    config_path: Path = PROGRAM_CONFIG_PATH,
) -> tuple[list[tuple[str, str, str, str, str]], dict[str, str], set[str], dict[str, str]]:
    """Load active study-program metadata from ``program_studi_config.txt``."""
    web_config: list[tuple[str, str, str, str, str]] = []
    sinta_depts: dict[str, str] = {}
    siakadu_urls: dict[str, str] = {}
    target_names: set[str] = set()

    if not config_path.exists():
        logger.error("Study program config not found at: %s", config_path)
        return web_config, sinta_depts, target_names, siakadu_urls

    try:
        with config_path.open(mode="r", encoding="utf-8") as file:
            lines = [line for line in file if line.strip() and not line.lstrip().startswith("#")]
            reader = csv.DictReader(lines)

            for row in reader:
                if row.get("enabled") != "1":
                    continue

                name = (row.get("nama_prodi") or "").strip()
                if not name:
                    continue

                web_config.append(
                    (
                        row.get("kode_prodi", "").strip(),
                        name,
                        row.get("web_url", "").strip(),
                        row.get("pddikti_keyword", "").strip(),
                        row.get("parser_key", "").strip(),
                    )
                )

                sinta_url = (row.get("sinta_url") or "").strip()
                if sinta_url:
                    sinta_depts[name] = sinta_url

                siakadu_url = (row.get("siakadu_url") or "").strip()
                siakadu_urls[name] = siakadu_url or default_siakadu_url(name)
                target_names.add(name)

        logger.info("Loaded %s active study programs from config.", len(web_config))
    except Exception:
        logger.exception("Failed to load study program config: %s", config_path)

    return web_config, sinta_depts, target_names, siakadu_urls


PRODI_WEB_CONFIG, SINTA_DEPTS, TARGET_PRODI_NAMES, SIAKADU_PRODI_URLS = load_prodi_config()

