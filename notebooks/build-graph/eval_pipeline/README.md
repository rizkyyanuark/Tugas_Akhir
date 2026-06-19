# Evaluation Pipeline

Pipeline ini dipakai untuk mengevaluasi sistem Hybrid GraphRAG YUNESA.
Strukturnya sengaja dipisah antara data evaluasi, kode evaluator, dan output run.

## Struktur

| Path | Fungsi |
| --- | --- |
| `data/eval_cases_ranked_56.json` | 56 pertanyaan evaluasi utama untuk retrieval dan answer quality. |
| `data/eval_cases_guardrail_4.json` | 4 pertanyaan out-of-scope untuk menguji refusal/grounding. |
| `eval_dataset.py` | Loader kompatibel untuk semua layer evaluasi. |
| `layer1_retrieval_metrics.py` | Retrieval quality: Hit@K, MRR, Precision@K. |
| `layer2_ragas_quality.py` | Answer quality: RAGAS jika tersedia, fallback heuristic. |
| `layer3_mode_comparison.py` | Perbandingan mode: vector/subgraph/global/hybrid/mix. |
| `layer4_llm_judge.py` | LLM judge pairwise untuk faithfulness, traceability, dan comprehensiveness. |
| `bab4_artifact_export.py` | Ekspor tabel LaTeX dan figure PGFPlots untuk Bab 4. |
| `run_all_layers.py` | Runner terpusat untuk menjalankan layer evaluasi. |

## Dataset

Total dataset: 60 case.

- Ranked cases: 56
  - Category A: factual-hard
  - Category B: relational
  - Category C: multi-hop
- Guardrail cases: 4
  - Category G: out-of-scope

Data 56 case utama tidak boleh dihapus karena menjadi dasar evaluasi Bab 4.
Jika perlu revisi, edit JSON di `data/` dan jalankan ulang layer evaluasi.

## Command Utama

Dari root repo:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 1
```

Untuk langsung memperbarui tabel/figure Bab 4 setelah layer selesai:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 1 --export-bab4
```

Untuk hanya export ulang artefak Bab 4 dari hasil evaluasi yang sudah ada:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\bab4_artifact_export.py
```

Untuk subset LLM judge yang tidak menimpa output utama:

```powershell
notebooks\.venv\Scripts\python.exe notebooks\build-graph\eval_pipeline\run_all_layers.py --only-layer 4 --max-cases 6 --no-write-main
```

Untuk cek dataset tanpa menjalankan evaluasi:

```powershell
notebooks\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'notebooks/build-graph'); from eval_pipeline.eval_dataset import dataset_summary; print(dataset_summary())"
```

## Output

Semua output run disimpan ke:

```text
notebooks/build-graph/outputs/evaluation/
```

Artefak Bab 4 yang sudah diformat disimpan ke:

```text
notebooks/build-graph/outputs/evaluation/bab4_artifacts/
docs/proposal tugas akhir/generated/bab4_eval/
```

File penting hasil export:

- `bab4_eval_all.tex`: include semua tabel/figure generated.
- `bab4_tables_all.tex`: include semua tabel.
- `bab4_figures_includegraphics.tex`: include semua PNG figure yang disalin ke folder naskah.
- `manifest.json`: status input, output, dataset, dan file yang hilang.

PNG figure yang sudah final disalin ke:

```text
docs/proposal tugas akhir/Gambar/
```

Dari `docs/proposal tugas akhir/Skripsi.tex` atau file Bab 4, include file
generated dapat dipanggil dengan:

```tex
\input{generated/bab4_eval/bab4_eval_all.tex}
```

Jangan menjadikan file output sebagai dataset evaluasi. Source of truth dataset
tetap berada di `eval_pipeline/data/`.
