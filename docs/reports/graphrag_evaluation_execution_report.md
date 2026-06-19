# Laporan Audit dan Status Eksekusi Evaluasi GraphRAG

Tanggal audit: 2026-06-16

## Ringkasan

Pipeline evaluasi sudah memiliki struktur yang sesuai untuk Bab 4: retrieval
quality, answer quality, mode comparison, dan LLM-as-a-judge. Namun, hasil yang
boleh dipakai sebagai klaim final belum semuanya setara tingkat kematangannya.

Status paling kuat saat ini adalah **Layer 1** dan **Layer 3**, karena keduanya
berbasis retrieval dan agregasi dari hasil yang sudah tersedia. **Layer 2** dan
**Layer 4** masih perlu diperlakukan sebagai evaluasi awal apabila belum
dijalankan ulang penuh, karena output yang tersedia masih terbatas.

## Perbandingan dengan AcademicRAG

AcademicRAG mengevaluasi sistem dengan membandingkan beberapa strategi
retrieval, bukan hanya melihat satu jawaban chatbot. Untuk konteks sistem ini,
pemetaan yang paling tepat adalah:

| AcademicRAG / baseline konseptual | Mode pada sistem YUNESA | Fungsi evaluasi |
| --- | --- | --- |
| Naive/vector retrieval | `naive` | Baseline Vector RAG tanpa traversal graf |
| Subgraph retrieval | `subgraph` | Menguji manfaat entity dan local graph traversal |
| Global/relationship-aware retrieval | `hybrid` | Menguji bukti relasional dan struktur graf |
| Academic-style mixed retrieval | `mix` | Menggabungkan vector chunks, keyword clues, dan graph evidence |

Dengan pemetaan ini, Bab 4 dapat menjawab rumusan masalah secara lebih rapi:

- RM konstruksi KG dijawab dengan statistik node, edge, provenance, dan quality
  gate.
- RM Hybrid Vector-Graph Retrieval dijawab dengan Layer 1 dan Layer 3.
- RM traceability/halusinasi dijawab dengan Layer 2, Layer 4, dan audit contoh
  jawaban.

## Status Output yang Tersedia

Output evaluasi tersedia di:

```text
notebooks/build-graph/outputs/evaluation/
```

Ringkasan status:

| Layer | File utama | Status | Catatan |
| --- | --- | --- | --- |
| Layer 1 | `eval_layer1_report.md` | Layak dipakai | 56 ranked cases, 4 mode retrieval |
| Layer 2 | `eval_layer2_report.md` | Preliminary | Output tersedia baru 15 kasus dan memakai local heuristic |
| Layer 3 | `eval_layer3_report.md` | Layak dipakai sebagai visualisasi komparatif | Berdasarkan agregasi Layer 1 dan Layer 2 |
| Layer 4 | `eval_layer4_report.md` | Preliminary | Output tersedia `n=5`, belum cukup untuk klaim final |
| Bab 4 artifacts | `bab4_artifacts/` | Siap dipakai lokal | Folder output di-ignore git, perlu regenerate/copy untuk final |

## Hasil Retrieval yang Sudah Tersedia

Layer 1 membandingkan 56 pertanyaan teranking pada empat mode.

| Mode | n | MRR | Hit@1 | Hit@5 | Hit@10 | P@5 | Latensi |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive` | 56 | 0.6369 | 0.5893 | 0.6786 | 0.7857 | 0.3429 | 2.68 s |
| `subgraph` | 56 | 0.6409 | 0.5714 | 0.7500 | 0.8036 | 0.3964 | 7.71 s |
| `hybrid` | 56 | 0.6447 | 0.5714 | 0.7500 | 0.8393 | 0.3929 | 10.19 s |
| `mix` | 56 | 0.6268 | 0.5714 | 0.6607 | 0.8393 | 0.3357 | 10.32 s |

Interpretasi awal:

- Untuk seluruh pertanyaan, `hybrid` memiliki MRR tertinggi, tetapi selisihnya
  kecil terhadap `naive`.
- Pada pertanyaan relasional, `subgraph` unggul atas `naive` pada MRR
  (`0.5700` vs `0.5014`) dan Hit@5 (`0.7667` vs `0.5667`).
- Pada pertanyaan faktual, `naive` dan `mix` tetap kuat karena bukti dapat
  ditemukan langsung dari potongan teks.
- Mode berbasis graf lebih mahal secara latensi. Ini perlu dilaporkan sebagai
  trade-off, bukan disembunyikan.

## Masalah yang Ditemukan

### 1. Layer 4 dapat menyesatkan jika rate limit dianggap seri

Sebelumnya, jika judge LLM gagal total karena quota/rate limit, hasilnya dapat
berakhir sebagai nilai `0.5` atau seri. Ini berbahaya secara metodologis karena
seri seolah-olah berarti kedua jawaban setara, padahal sebenarnya evaluasi
gagal.

Perbaikan yang sudah dilakukan:

- Kasus judge gagal sekarang ditandai dengan `judge_failed=true`.
- Kasus gagal tidak ikut dihitung dalam agregasi.
- Jumlah gagal disimpan sebagai `failed`.
- Jawaban tiap mode disimpan ke `eval_layer4_answer_cache.json`, sehingga
  rerun judge tidak perlu mengulang semua panggilan Groq.
- Model judge dapat dioverride dengan `YUNESA_JUDGE_MODEL`.
- API key judge dapat dibaca dari `GEMINI_API_KEY_JUDGE`, `GEMINI_API_KEY`, atau
  `GOOGLE_API_KEY`.

### 2. Layer 2 output saat ini belum final

Output Layer 2 yang tersedia berisi `n=15` untuk `subgraph` dan `mix`. Ini
berguna sebagai smoke test, tetapi belum cukup untuk klaim final terhadap
faithfulness atau answer relevancy seluruh dataset.

Untuk Bab 4, tulis sebagai evaluasi awal kecuali sudah dijalankan ulang pada
semua pertanyaan non-guardrail.

### 3. Beberapa teks output lama masih mojibake

Pada report lama masih terlihat karakter mojibake akibat perbedaan encoding.
Ini tidak mengubah metrik, tetapi tidak layak langsung disalin ke skripsi.
Untuk Bab 4, gunakan artefak `.tex` yang diekspor atau tulis ulang narasinya
secara manual.

### 4. Full rerun belum dapat dilakukan pada sesi ini

Rerun Layer 1 melalui virtualenv membutuhkan proses escalated karena interpreter
notebook memakai UV trampoline. Approval otomatis untuk proses itu ditolak
karena limit usage sesi. Karena itu, tidak dilakukan workaround untuk memaksa
running. Hasil yang dianalisis pada report ini berasal dari output evaluasi yang
sudah tersedia di folder `outputs/evaluation`.

## Evaluasi yang Disarankan untuk Bab 4

Gunakan urutan berikut agar hasil Bab 4 rapi dan defensible.

### Evaluasi 1: Retrieval Quality

Dipakai untuk menjawab apakah Hybrid Vector-Graph Retrieval bekerja.

Metrik:

- Hit@1
- Hit@5
- Hit@10
- MRR
- Precision@5
- Latensi rata-rata

Mode:

- `naive`
- `subgraph`
- `hybrid`
- `mix`

Tabel/gambar:

- `bab4_table_retrieval_overall.tex`
- `bab4_table_retrieval_by_category.tex`
- `bab4_fig_mrr_by_category.tex`
- `bab4_fig_latency_hit.tex`

### Evaluasi 2: Answer Quality

Dipakai untuk menilai kualitas jawaban, tetapi jangan dijadikan klaim final jika
belum memakai RAGAS/LLM judge penuh.

Metrik:

- Faithfulness
- Answer Relevancy
- Context Precision
- Context Recall

Catatan:

- Jika RAGAS tidak dijalankan, sebut sebagai heuristik lokal.
- Jika RAGAS dijalankan, laporkan model evaluator dan jumlah sampel.

### Evaluasi 3: Pairwise LLM Judge

Dipakai untuk membandingkan jawaban Vector RAG melawan mode berbasis KG.

Dimensi:

- Faithfulness
- Traceability
- Comprehensiveness
- Overall

Untuk hasil final, jangan memakai `--max-cases 5`. Minimal gunakan seluruh
kasus non-guardrail atau subset yang dijelaskan alasannya secara eksplisit.

### Evaluasi 4: Guardrail

Guardrail perlu dipisah dari retrieval ranking karena tidak memiliki dokumen
relevan. Evaluasinya bukan Hit@K, melainkan apakah sistem menolak pertanyaan di
luar cakupan.

Metrik sederhana:

- refusal accuracy
- jumlah kasus out-of-scope yang tetap dijawab secara spekulatif
- contoh jawaban yang benar menolak

## Command Final yang Disarankan

Jalankan dari:

```powershell
cd notebooks/build-graph
```

Retrieval:

```powershell
..\.venv\Scripts\python.exe -m eval_pipeline.run_all_layers --only-layer 1
```

Answer quality tanpa RAGAS:

```powershell
..\.venv\Scripts\python.exe -m eval_pipeline.run_all_layers --only-layer 2 --no-ragas
```

Mode comparison:

```powershell
..\.venv\Scripts\python.exe -m eval_pipeline.run_all_layers --only-layer 3
```

LLM judge final:

```powershell
$env:YUNESA_JUDGE_MODEL = "gemini-1.5-flash"
$env:YUNESA_JUDGE_RATE_LIMIT_SLEEP_SECONDS = "65"
..\.venv\Scripts\python.exe -m eval_pipeline.run_all_layers --only-layer 4 --trials 3
```

Jika hanya ingin melanjutkan dari jawaban yang sudah pernah dibuat:

```powershell
..\.venv\Scripts\python.exe -m eval_pipeline.run_all_layers --only-layer 4 --from-cache --trials 3
```

Setelah semua output selesai:

```powershell
..\.venv\Scripts\python.exe -m eval_pipeline.bab4_artifact_export
```

## Kesimpulan Audit

Sistem evaluasi sudah cukup untuk menghasilkan Bab 4, tetapi klaimnya perlu
dibatasi:

- Retrieval dan mode comparison sudah layak dibahas.
- Answer quality masih perlu full run jika ingin klaim lebih kuat.
- LLM judge tidak boleh dipakai sebagai hasil final jika masih `n=5`.
- Rate limit judge tidak boleh dianggap seri; kode sudah diperbaiki untuk
  menandai kegagalan sebagai data gagal.

Dengan demikian, sistem bukan "tidak layak evaluasi", tetapi evaluasi final
harus dijalankan dengan kontrol kuota, cache, dan pemisahan jelas antara hasil
retrieval, hasil generasi, dan hasil judge.
