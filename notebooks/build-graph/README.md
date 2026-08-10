# YUNESA Academic KG Workspace

Folder ini adalah workspace canonical untuk konstruksi knowledge graph,
dual-indexing, GraphRAG development, dan evaluasi.

## Entry Points

| Kebutuhan | File | Catatan |
| --- | --- | --- |
| Build KG resmi dan write ke Neo4j/Zilliz | `run_local_kg_pipeline.py` | Eksekusi repeatable dengan quality gate. |
| **Eksplorasi & eksperimen KG** | `constuction_knowledge_graph.ipynb` | Notebook canonical: inline construction, PyVis visualisasi, Dual-Index Storage. |
| Development GraphRAG | `yunesa_academic_graphrag_dev.ipynb` | Cek retrieval context, subgraph, evidence, dan jawaban. |
| Smoke/demo GraphRAG lokal | `run_local_graphrag_demo.py` | Runner terminal sederhana. |
| Evaluasi retrieval dan jawaban | `eval_pipeline/` | Dataset, layer evaluasi, dan export artefak Bab 4. |
| Core logic | `src/yunesa_academic_kg.py` | Source of truth untuk KG construction dan local GraphRAG. |

## Build KG Lokal

Preflight dependency GLiNER:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\run_local_kg_pipeline.py --use-gliner --preflight-only
```

Build tanpa menulis ke cloud:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\run_local_kg_pipeline.py --sample-size 50 --source supabase --graph-name yunesa_academic_kg_local --use-gliner
```

Build dan tulis ulang ke Neo4j + Zilliz:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\run_local_kg_pipeline.py --sample-size 50 --source supabase --graph-name yunesa_academic_kg --use-gliner --write-neo4j --write-milvus --clear-neo4j --clear-milvus
```

Catatan: `--use-gliner` mengaktifkan NER. Relasi ontology tetap dipetakan
secara deterministik dari tipe entitas. `--use-glirel` hanya untuk eksperimen
ablation, bukan jalur production construction.

## Evaluation Pipeline

Dataset evaluasi utama sudah dipisah dari kode:

- `eval_pipeline/data/eval_cases_ranked_56.json`
- `eval_pipeline/data/eval_cases_guardrail_4.json`

Workflow evaluasi yang disarankan:

1. Jalankan Layer 1 untuk retrieval quality.
2. Jalankan Layer 3 untuk visualisasi mode comparison.
3. Jalankan Layer 4 subset/full untuk LLM judge jika quota sudah siap.
4. Export artefak Bab 4.

Menjalankan evaluasi retrieval dan langsung export artefak Bab 4:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 1 --export-bab4
```

Menjalankan evaluasi mode comparison dan memperbarui gambar Bab 4:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 3 --export-bab4
```

Menjalankan LLM judge subset kecil tanpa menimpa hasil utama:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 4 --max-cases 6 --no-write-main
```

Export ulang artefak Bab 4 dari output yang sudah ada:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\bab4_artifact_export.py
```

Output evaluasi berada di `outputs/evaluation/`. Artefak teknis hasil export
disimpan ke `outputs/evaluation/bab4_artifacts/`, sedangkan artefak LaTeX yang
siap dipakai naskah juga disalin ke `docs/proposal tugas akhir/generated/bab4_eval/`.

## Output Policy

`outputs/` adalah hasil run, bukan source of truth. Data input evaluasi ada di
`eval_pipeline/data/`, sedangkan kode evaluasi ada di `eval_pipeline/`.

Gambar final untuk naskah disalin ke:

```text
docs/proposal tugas akhir/Gambar/
```

Jangan mengedit hasil di `outputs/` secara manual kecuali sedang debugging.
