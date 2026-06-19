import json

import yaml

from yunesa.services.entity_resolution_service import EntityResolutionCurationStore


def test_entity_resolution_store_sync_approve_and_export(tmp_path):
    source_path = tmp_path / "suggestions.json"
    store_path = tmp_path / "store.json"
    base_aliases_path = tmp_path / "concept_aliases.yml"
    export_path = tmp_path / "concept_aliases.approved.yml"

    source_path.write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "raw_label": "SVM",
                        "suggested_canonical_label": "Support Vector Machine",
                        "suggested_canonical_key": "support_vector_machine",
                        "concept_type": "Model",
                        "action": "exact_synonym",
                        "confidence": 0.99,
                        "aliases": ["SVM"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    base_aliases_path.write_text(
        yaml.safe_dump(
            {
                "aliases": {
                    "auc": {
                        "canonical_label": "AUC",
                        "concept_type": "Metric",
                        "aliases": ["AUC", "area under the curve"],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    store = EntityResolutionCurationStore(store_path=store_path)
    result = store.sync_suggestions(source_path=source_path)

    assert result["imported"] == 1
    listed = store.list_suggestions()
    assert listed["total"] == 1
    suggestion = listed["items"][0]

    approved = store.approve(
        suggestion["id"],
        canonical_label="Support Vector Machine",
        canonical_key="support_vector_machine",
        concept_type="Model",
        aliases=["SVM", "support vector machine"],
        reviewer="pytest",
    )

    assert approved["decision"]["status"] == "approved"
    export = store.export_aliases(output_path=export_path, base_path=base_aliases_path)
    exported = yaml.safe_load(export_path.read_text(encoding="utf-8"))

    assert export["approved_count"] == 1
    assert "auc" in exported["aliases"]
    assert exported["aliases"]["support_vector_machine"]["source"] == "ui_approved_alias"
    assert "SVM" in exported["aliases"]["support_vector_machine"]["aliases"]
