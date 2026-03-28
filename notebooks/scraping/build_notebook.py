"""Build KG construction notebook by reading cell source from .py files."""
import json, os, glob

CELLS_DIR = os.path.join(os.path.dirname(__file__), 'pipeline_cells')
OUTPUT = os.path.join(os.path.dirname(__file__), 'kg_construction.ipynb')

cells = []

# Markdown header
cells.append({
    "cell_type": "markdown", "metadata": {}, "source": [
        "# Knowledge Graph Construction Pipeline\n",
        "## Strwythura-Adapted Academic ERKG\n",
        "\n",
        "**Logging:** All steps log to `logs/kg_pipeline_<timestamp>.log` (DEBUG) and console (INFO).\n",
        "\n",
        "| Cell | Strwythura Part | Purpose |\n",
        "|---|---|---|\n",
        "| 1 | Setup | Ontology + GLiNER + spaCy + Logging |\n",
        "| 2 | Part 1 (ER) | Backbone from structured CSV |\n",
        "| 3 | Part 3 (Parse) | spaCy + GLiNER + lemma-key entity store |\n",
        "| 4 | Part 1+4 | Entity Resolution (3-layer) |\n",
        "| 5 | Part 4 (HITL) | LLM Curation (validate + enrich) |\n",
        "| 6 | Part 5 (Distil) | Distillation + Entity Embeddings |\n",
        "| 7 | Part 6 (DB) | Neo4j + Weaviate ingestion |\n",
        "| 8 | Verification | 10 Cypher test queries |"
    ]
})

# Read each cell .py file
for i in range(1, 9):
    cell_file = os.path.join(CELLS_DIR, f'cell{i}.py')
    with open(cell_file, 'r', encoding='utf-8') as f:
        source = f.read()
    # Convert to list of lines with newlines
    lines = [line + "\n" for line in source.split("\n")]
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": lines
    })

# Build notebook JSON
nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": ".venv", "language": "python", "name": "python3"},
        "language_info": {"name": "python", "version": "3.11.9"}
    },
    "nbformat": 4,
    "nbformat_minor": 5
}

with open(OUTPUT, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print(f'SUCCESS: {len(cells)} cells written to {OUTPUT}')
