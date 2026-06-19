# Evaluation Dataset

Folder ini adalah source of truth untuk dataset evaluasi GraphRAG.

## Files

| File | Jumlah | Fungsi |
| --- | ---: | --- |
| `eval_cases_ranked_56.json` | 56 | Pertanyaan utama untuk evaluasi retrieval, mode comparison, answer quality, dan LLM judge. |
| `eval_cases_guardrail_4.json` | 4 | Pertanyaan out-of-scope untuk menguji grounding dan refusal. |

Total dataset yang dibaca `eval_dataset.py`: 60 case.

## Editing Rules

- Jangan hapus `eval_cases_ranked_56.json`.
- Tambah/revisi pertanyaan langsung di JSON, bukan di kode evaluator.
- Setiap case minimal memiliki:
  - `id`
  - `category`
  - `intent`
  - `query`
  - `relevant_titles`
  - `key_concepts`
  - `reference_answer`
- Setelah edit dataset, jalankan:

```powershell
notebooks\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'notebooks/build-graph'); from eval_pipeline.eval_dataset import dataset_summary; print(dataset_summary())"
```
