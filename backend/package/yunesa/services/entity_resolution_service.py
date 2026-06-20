import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_root() -> Path:
    # Inside Docker, /app/data is the shared volume — use /app as root.
    docker_data = Path("/app/data")
    if docker_data.is_dir():
        return Path("/app")
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "notebooks" / "build-graph").exists() and (parent / "backend").exists():
            return parent
    return current.parents[4]


def _default_paths() -> dict[str, Path]:
    root = _workspace_root()
    er_dir = root / "data" / "kg" / "entity_resolution"
    suggestion_candidates = [
        Path(os.getenv("YUNESA_ALIAS_SUGGESTIONS_PATH", "")) if os.getenv("YUNESA_ALIAS_SUGGESTIONS_PATH") else None,
        er_dir / "concept_alias_suggestions.json",
        root / "data" / "kg_pipeline_test" / "kg" / "output" / "concept_alias_suggestions.json",
        root / "notebooks" / "build-graph" / "outputs" / "entity_resolution" / "concept_alias_suggestions.json",
    ]
    suggestion_path = next((path for path in suggestion_candidates if path and path.exists()), suggestion_candidates[-1])
    return {
        "store": Path(os.getenv("YUNESA_ALIAS_CURATION_STORE", er_dir / "alias_curation_store.json")),
        "suggestions": Path(suggestion_path),
        "base_aliases": Path(os.getenv("YUNESA_BASE_CONCEPT_ALIASES_PATH", root / "notebooks" / "build-graph" / "config" / "concept_aliases.yml")),
        "approved_aliases": Path(os.getenv("YUNESA_APPROVED_CONCEPT_ALIASES_PATH", er_dir / "concept_aliases.approved.yml")),
    }


def _stable_id(item: dict[str, Any]) -> str:
    raw = "|".join(
        str(item.get(key, "") or "")
        for key in ("raw_label", "suggested_canonical_label", "suggested_canonical_key", "action")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _safe_alias_key(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return text or "alias"


def _unique_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


class EntityResolutionCurationStore:
    """File-backed curation store for KG concept alias suggestions.

    This keeps alias review outside the production relational schema while still
    producing a YAML artifact that the KG construction pipeline can consume.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        paths = _default_paths()
        self.paths = paths
        self.store_path = Path(store_path or paths["store"])

    def _empty_store(self) -> dict[str, Any]:
        return {
            "version": 1,
            "updated_at": _utc_now(),
            "suggestions": {},
        }

    def _load_store(self) -> dict[str, Any]:
        if not self.store_path.exists():
            return self._empty_store()
        try:
            data = json.loads(self.store_path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty_store()
        if not isinstance(data, dict):
            return self._empty_store()
        data.setdefault("version", 1)
        data.setdefault("updated_at", _utc_now())
        data.setdefault("suggestions", {})
        if not isinstance(data["suggestions"], dict):
            data["suggestions"] = {}
        return data

    def _save_store(self, data: dict[str, Any]) -> None:
        data["updated_at"] = _utc_now()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_suggestion(self, item: dict[str, Any], source_path: Path) -> dict[str, Any]:
        suggestion = deepcopy(item)
        suggestion_id = str(suggestion.get("id") or _stable_id(suggestion))
        suggestion["id"] = suggestion_id
        suggestion["raw_label"] = str(suggestion.get("raw_label") or "").strip()
        suggestion["suggested_canonical_label"] = str(suggestion.get("suggested_canonical_label") or "").strip()
        suggestion["suggested_canonical_key"] = str(suggestion.get("suggested_canonical_key") or "").strip()
        suggestion["concept_type"] = str(suggestion.get("concept_type") or "ResearchTopic").strip()
        suggestion["action"] = str(suggestion.get("action") or "").strip()
        suggestion["aliases"] = _unique_strings(suggestion.get("aliases") or [])
        suggestion["source_path"] = str(source_path)
        suggestion.setdefault("confidence", 0)
        suggestion.setdefault("review_status", "needs_review")
        suggestion.setdefault("rationale", "")
        return suggestion

    def sync_suggestions(self, source_path: Path | None = None) -> dict[str, Any]:
        source = Path(source_path or self.paths["suggestions"])
        data = self._load_store()
        imported = 0
        updated = 0

        if not source.exists():
            self._save_store(data)
            return {
                "imported": imported,
                "updated": updated,
                "source_path": str(source),
                "store_path": str(self.store_path),
                "missing_source": True,
            }

        payload = json.loads(source.read_text(encoding="utf-8"))
        suggestions = payload.get("suggestions", []) if isinstance(payload, dict) else []
        if not isinstance(suggestions, list):
            suggestions = []

        store_suggestions = data["suggestions"]
        for raw_item in suggestions:
            if not isinstance(raw_item, dict):
                continue
            item = self._normalize_suggestion(raw_item, source)
            existing = store_suggestions.get(item["id"])
            if existing is None:
                item["created_at"] = _utc_now()
                item["updated_at"] = _utc_now()
                item["decision"] = {
                    "status": "pending",
                    "reviewed_at": "",
                    "reviewer": "",
                }
                store_suggestions[item["id"]] = item
                imported += 1
                continue

            decision = existing.get("decision") or {"status": "pending"}
            existing.update(item)
            existing["decision"] = decision
            existing["updated_at"] = _utc_now()
            updated += 1

        self._save_store(data)
        return {
            "imported": imported,
            "updated": updated,
            "source_path": str(source),
            "store_path": str(self.store_path),
            "missing_source": False,
        }

    def list_suggestions(self, status: str | None = None) -> dict[str, Any]:
        data = self._load_store()
        if not data["suggestions"] and self.paths["suggestions"].exists():
            self.sync_suggestions()
            data = self._load_store()

        items = list(data["suggestions"].values())
        if status and status != "all":
            items = [
                item
                for item in items
                if (item.get("decision") or {}).get("status", "pending") == status
            ]

        items.sort(
            key=lambda item: (
                (item.get("decision") or {}).get("status", "pending") != "pending",
                -float(item.get("confidence") or 0),
                item.get("raw_label", "").casefold(),
            )
        )

        counts = {"pending": 0, "approved": 0, "rejected": 0}
        for item in data["suggestions"].values():
            item_status = (item.get("decision") or {}).get("status", "pending")
            counts[item_status] = counts.get(item_status, 0) + 1

        return {
            "items": items,
            "counts": counts,
            "total": len(data["suggestions"]),
            "store_path": str(self.store_path),
            "suggestions_path": str(self.paths["suggestions"]),
            "export_path": str(self.paths["approved_aliases"]),
        }

    def approve(
        self,
        suggestion_id: str,
        *,
        canonical_label: str | None = None,
        canonical_key: str | None = None,
        concept_type: str | None = None,
        aliases: list[str] | None = None,
        rationale: str | None = None,
        reviewer: str = "",
    ) -> dict[str, Any]:
        data = self._load_store()
        item = data["suggestions"].get(suggestion_id)
        if item is None:
            raise KeyError(suggestion_id)

        label = (canonical_label or item.get("suggested_canonical_label") or item.get("raw_label") or "").strip()
        key = (canonical_key or item.get("suggested_canonical_key") or _safe_alias_key(label)).strip()
        item_aliases = _unique_strings([item.get("raw_label"), *(item.get("aliases") or []), *(aliases or []), label])
        item["decision"] = {
            "status": "approved",
            "canonical_label": label,
            "canonical_key": key,
            "concept_type": (concept_type or item.get("concept_type") or "ResearchTopic").strip(),
            "aliases": item_aliases,
            "rationale": (rationale if rationale is not None else item.get("rationale", "")),
            "reviewed_at": _utc_now(),
            "reviewer": reviewer,
        }
        item["updated_at"] = _utc_now()
        self._save_store(data)
        return item

    def reject(self, suggestion_id: str, *, reason: str = "", reviewer: str = "") -> dict[str, Any]:
        data = self._load_store()
        item = data["suggestions"].get(suggestion_id)
        if item is None:
            raise KeyError(suggestion_id)
        item["decision"] = {
            "status": "rejected",
            "reason": reason,
            "reviewed_at": _utc_now(),
            "reviewer": reviewer,
        }
        item["updated_at"] = _utc_now()
        self._save_store(data)
        return item

    def _load_base_aliases(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {"aliases": {}}
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return {"aliases": {}}
        aliases = data.get("aliases", data)
        if not isinstance(aliases, dict):
            aliases = {}
        return {"aliases": deepcopy(aliases)}

    def export_aliases(self, output_path: Path | None = None, base_path: Path | None = None) -> dict[str, Any]:
        data = self._load_store()
        base_alias_path = Path(base_path or self.paths["base_aliases"])
        export_path = Path(output_path or self.paths["approved_aliases"])
        payload = self._load_base_aliases(base_alias_path)
        aliases = payload.setdefault("aliases", {})
        approved_count = 0

        for item in data["suggestions"].values():
            decision = item.get("decision") or {}
            if decision.get("status") != "approved":
                continue
            canonical_label = str(decision.get("canonical_label") or "").strip()
            if not canonical_label:
                continue
            canonical_key = _safe_alias_key(str(decision.get("canonical_key") or canonical_label))
            aliases[canonical_key] = {
                "canonical_label": canonical_label,
                "canonical_key": str(decision.get("canonical_key") or canonical_key),
                "concept_type": str(decision.get("concept_type") or "ResearchTopic"),
                "aliases": _unique_strings(decision.get("aliases") or []),
                "source": "ui_approved_alias",
            }
            approved_count += 1

        export_path.parent.mkdir(parents=True, exist_ok=True)
        export_path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return {
            "approved_count": approved_count,
            "export_path": str(export_path),
            "base_aliases_path": str(base_alias_path),
        }


entity_resolution_curation_store = EntityResolutionCurationStore()
