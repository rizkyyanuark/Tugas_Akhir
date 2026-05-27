from __future__ import annotations

import logging
import re
import time
from typing import Any, Mapping

import requests
import urllib3
from bs4 import BeautifulSoup

from ..config import (
    BD_PASS_UNLOCKER,
    BD_USER_UNLOCKER,
    BRIGHT_DATA_HOST,
    CRAWLER_MAX_RETRIES,
    CRAWLER_TIMEOUT,
    HEADERS,
    STRICT_AFFILIATION,
)
from ..utils.utils import clean_identifier, make_lecturer_entry, normalize_name

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


_LABEL_TO_FIELD = {
    "Nama": "nama_dosen",
    "JK": "gender",
    "NIP": "nip",
    "NIDN": "nidn",
    "NIM": "nim",
}


class SiakaduClient:
    """
    Client for SIAKADU public prodi pages.

    SIAKADU is used only as an identity source for lecturers. It provides
    public NIP/NIK and NIDN fields on prodi pages, while academic profile
    metadata still comes from the existing web/PDDIKTI/SINTA/SciVal sources.
    """

    def __init__(
        self,
        *,
        headers: Mapping[str, str] | None = None,
        timeout: int = CRAWLER_TIMEOUT,
        max_retries: int = CRAWLER_MAX_RETRIES,
    ) -> None:
        self.headers = dict(headers or HEADERS)
        self.timeout = timeout
        self.max_retries = max_retries

    def scrape(self, program_urls: Mapping[str, str], configs: list[tuple]) -> list[dict[str, Any]]:
        """
        Scrape SIAKADU pages for the configured study programs.

        Args:
            program_urls: Mapping from prodi name to SIAKADU URL.
            configs: Active PRODI_WEB_CONFIG tuples.

        Returns:
            Deduplicated lecturer identity records.
        """
        results: list[dict[str, Any]] = []

        for code, prodi_name, *_rest in configs:
            url = program_urls.get(prodi_name)
            if not url:
                logger.warning("SIAKADU URL missing for %s", prodi_name)
                continue

            logger.info("Scraping SIAKADU: %s (%s)", prodi_name, url)
            html = self._fetch_with_retry(url)
            if not html:
                continue

            entries = self.parse_lecturers(
                html,
                prodi_code=code,
                prodi_name=prodi_name,
                source_url=url,
            )
            logger.info("Parsed %d raw SIAKADU lecturer identity rows from %s", len(entries), prodi_name)
            results.extend(entries)

        deduplicated = self._deduplicate(results)
        logger.info("SIAKADU deduplicated identity rows: %d raw -> %d unique", len(results), len(deduplicated))
        return deduplicated

    def _fetch_with_retry(self, url: str) -> str | None:
        proxies = self._proxies()

        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    proxies=proxies,
                    timeout=self.timeout,
                    verify=False,
                )
                response.raise_for_status()
                return response.text
            except Exception as exc:
                if attempt < self.max_retries - 1:
                    wait_seconds = 5 * (attempt + 1)
                    logger.warning(
                        "SIAKADU fetch attempt %d failed for %s: %s. Retrying in %ss...",
                        attempt + 1,
                        url,
                        exc,
                        wait_seconds,
                    )
                    time.sleep(wait_seconds)
                else:
                    logger.error("SIAKADU fetch failed after %d attempts for %s: %s", self.max_retries, url, exc)
        return None

    @staticmethod
    def _proxies() -> dict[str, str] | None:
        if not (BD_USER_UNLOCKER and BD_PASS_UNLOCKER and BRIGHT_DATA_HOST):
            return None

        proxy_url = f"http://{BD_USER_UNLOCKER}:{BD_PASS_UNLOCKER}@{BRIGHT_DATA_HOST}"
        return {"http": proxy_url, "https": proxy_url}

    @classmethod
    def parse_lecturers(
        cls,
        html: str,
        *,
        prodi_code: str,
        prodi_name: str,
        source_url: str,
    ) -> list[dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        lines = cls._compact_label_lines(soup.get_text("\n", strip=True))

        records: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for line in lines:
            parsed = cls._parse_label_line(line)
            if not parsed:
                continue

            label, value = parsed
            field = _LABEL_TO_FIELD[label]

            if field == "nama_dosen":
                cls._append_record(records, current, prodi_code, prodi_name, source_url)
                current = {"nama_dosen": value}
                continue

            if current is None:
                continue

            current[field] = value

        cls._append_record(records, current, prodi_code, prodi_name, source_url)
        return records

    @staticmethod
    def _compact_label_lines(text: str) -> list[str]:
        raw_lines = [
            line.replace("\xa0", " ").strip()
            for line in text.splitlines()
            if line.replace("\xa0", " ").strip()
        ]

        lines: list[str] = []
        i = 0
        while i < len(raw_lines):
            line = raw_lines[i]

            if line in _LABEL_TO_FIELD and i + 1 < len(raw_lines) and raw_lines[i + 1] == ":":
                value = ""
                if i + 2 < len(raw_lines) and raw_lines[i + 2] not in _LABEL_TO_FIELD:
                    value = raw_lines[i + 2]
                    i += 3
                else:
                    i += 2
                lines.append(f"{line}: {value}".strip())
                continue

            inline = re.match(r"^(Nama|JK|NIP|NIDN|NIM)\s*:\s*(.*)$", line, flags=re.I)
            if inline:
                label = inline.group(1).upper()
                label = "Nama" if label == "NAMA" else label
                value = inline.group(2).strip()
                lines.append(f"{label}: {value}".strip())
                i += 1
                continue

            lines.append(line)
            i += 1

        return lines

    @staticmethod
    def _parse_label_line(line: str) -> tuple[str, str] | None:
        match = re.match(r"^(Nama|JK|NIP|NIDN|NIM)\s*:\s*(.*)$", line, flags=re.I)
        if not match:
            return None

        raw_label = match.group(1).upper()
        label = "Nama" if raw_label == "NAMA" else raw_label
        return label, match.group(2).strip()

    @staticmethod
    def _append_record(
        records: list[dict[str, Any]],
        current: dict[str, Any] | None,
        prodi_code: str,
        prodi_name: str,
        source_url: str,
    ) -> None:
        if not current:
            return

        # Student/person cards expose NIM instead of NIP/NIDN. Do not ingest them.
        if current.get("nim"):
            return

        nip = clean_identifier(current.get("nip"))
        nidn = clean_identifier(current.get("nidn"))
        if not nip and not nidn:
            return

        name = str(current.get("nama_dosen") or "").strip()
        if len(name) < 4:
            return

        entry = make_lecturer_entry(
            name,
            nip=nip,
            nidn=nidn,
        )
        if not entry:
            return

        entry.update(
            {
                "gender": clean_identifier(current.get("gender")),
                "prodi_code": prodi_code,
                "prodi_name": prodi_name,
                "source_url": source_url,
                "source": "SIAKADU",
                "affiliation": STRICT_AFFILIATION,
            }
        )
        records.append(entry)

    @staticmethod
    def _deduplicate(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}

        for record in records:
            key = (
                f"nidn:{record['nidn']}"
                if record.get("nidn")
                else f"nip:{record['nip']}"
                if record.get("nip")
                else f"name:{normalize_name(record.get('nama_dosen', ''))}:{record.get('prodi_name', '')}"
            )

            existing = by_key.get(key)
            if not existing:
                by_key[key] = record
                continue

            for field in ("nip", "nidn", "scholar_id", "scopus_id", "sinta_id", "gender"):
                if not existing.get(field) and record.get(field):
                    existing[field] = record[field]

            if record.get("source_url") and record["source_url"] not in str(existing.get("source_url", "")):
                existing["source_url"] = f"{existing.get('source_url', '')};{record['source_url']}".strip(";")

        return list(by_key.values())
