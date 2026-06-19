# Panduan Evaluasi Hybrid GraphRAG untuk Bab 4

Dokumen ini menjelaskan cara mengevaluasi sistem Hybrid Vector-Graph Retrieval
YUNESA agar hasilnya bisa dipakai pada Bab 4. Fokusnya mengikuti rancangan Bab
3: membandingkan Vector RAG, Subgraph Retrieval, Hybrid Retrieval, dan mode
gabungan Mix.

## 1. Tujuan Evaluasi

Evaluasi tidak hanya melihat apakah sistem bisa menjawab pertanyaan, tetapi juga
menilai apakah konteks yang diambil benar, apakah jawaban tetap bersumber pada
data akademik, dan apakah mode Hybrid GraphRAG memberi manfaat dibanding Vector
RAG biasa.

Secara praktis, evaluasi dibagi menjadi empat lapis:

| Lapis | Tujuan | Relevansi Bab 4 |
| --- | --- | --- |
| Layer 1 | Mengukur kualitas retrieval dengan Hit@K, MRR, Precision@K, dan latensi | Menjawab apakah mode graph/hybrid membantu menemukan bukti yang benar |
| Layer 2 | Mengukur kualitas jawaban dengan RAGAS atau heuristik lokal | Menilai faithfulness dan relevansi jawaban |
| Layer 3 | Membuat visualisasi perbandingan mode retrieval | Dipakai untuk grafik Bab 4 |
| Layer 4 | Pairwise LLM judge terhadap Vector RAG | Dipakai sebagai audit awal traceability dan comprehensiveness |

## 2. Dataset Evaluasi

Dataset evaluasi berada di:

```text
notebooks/build-graph/eval_pipeline/eval_dataset.py
```

Distribusi dataset saat ini:

| Kategori | Jenis pertanyaan | Jumlah |
| --- | --- | ---: |
| A | Faktual | 20 |
| B | Relasional | 30 |
| C | Multi-hop | 6 |
| G | Guardrail | 4 |
| Total | Seluruh pertanyaan evaluasi | 60 |

Kategori A menguji pencarian bukti faktual dari publikasi. Kategori B menguji
relasi dosen, publikasi, keyword, venue, dan institusi. Kategori C menguji
pertanyaan yang membutuhkan lebih dari satu hop pada graf. Kategori G menguji
apakah sistem menolak pertanyaan di luar cakupan data akademik.

## 3. Mode yang Dibandingkan

Mode evaluasi disesuaikan dengan konsep AcademicRAG, tetapi diterapkan pada data
akademik UNESA.

| Mode | Makna dalam sistem | Fungsi evaluasi |
| --- | --- | --- |
| `naive` | Vector RAG baseline | Pembanding utama tanpa traversal graf |
| `subgraph` | Retrieval berbasis entitas dan jalur graf lokal | Menguji manfaat subgraph retrieval |
| `hybrid` | Subgraph + relationship/global evidence | Menguji kombinasi bukti lokal dan relasi |
| `mix` | Paper chunk + keyword + graph evidence | Menguji mode paling lengkap untuk aplikasi |

Untuk klaim akademik, gunakan `naive` sebagai baseline. Jangan langsung
menyimpulkan `mix` paling baik hanya karena konteksnya paling lengkap. Mode yang
lebih lengkap bisa punya recall tinggi, tetapi juga bisa membawa konteks yang
tidak relevan.

## 4. Cara Menjalankan Evaluasi

Jalankan dari folder berikut:

```powershell
cd notebooks/build-graph
```

Evaluasi retrieval utama:

```powershell
python -m eval_pipeline.run_all_layers --only-layer 1
```

Evaluasi kualitas jawaban tanpa RAGAS, lebih cepat:

```powershell
python -m eval_pipeline.run_all_layers --only-layer 2 --no-ragas
```

Evaluasi mode comparison dan visualisasi:

```powershell
python -m eval_pipeline.run_all_layers --only-layer 3
```

Evaluasi LLM judge. Untuk hasil final, gunakan seluruh kasus yang relevan,
bukan `--max-cases 5`:

```powershell
python -m eval_pipeline.run_all_layers --only-layer 4 --trials 3
```

Jika hanya ingin uji cepat:

```powershell
python -m eval_pipeline.run_all_layers --only-layer 4 --max-cases 5 --trials 2
```

Setelah output JSON tersedia, ekspor tabel dan gambar LaTeX untuk Bab 4:

```powershell
python -m eval_pipeline.bab4_artifact_export
```

## 5. Artefak untuk Bab 4

Artefak LaTeX dibuat di:

```text
notebooks/build-graph/outputs/evaluation/bab4_artifacts/
```

Catatan repo: folder `notebooks/build-graph/outputs/` diabaikan oleh git.
Artinya, file di folder ini adalah artefak lokal hasil evaluasi. Untuk penulisan
final, ada dua pilihan yang sama-sama aman: jalankan ulang exporter sebelum
compile LaTeX, atau salin file `.tex` yang sudah dipilih ke folder dokumen
skripsi jika ingin artefak tersebut ikut tersimpan di repository.

File yang dapat langsung diinput ke Bab 4:

| File | Kegunaan |
| --- | --- |
| `bab4_table_eval_dataset.tex` | Tabel distribusi pertanyaan evaluasi |
| `bab4_table_retrieval_overall.tex` | Ringkasan retrieval semua mode |
| `bab4_table_retrieval_by_category.tex` | Retrieval per kategori pertanyaan |
| `bab4_table_answer_quality.tex` | Kualitas jawaban Layer 2 |
| `bab4_table_llm_judge.tex` | Pairwise LLM judge terhadap Vector RAG |
| `bab4_fig_mrr_by_category.tex` | Grafik MRR per kategori |
| `bab4_fig_latency_hit.tex` | Grafik trade-off latensi dan Hit@5 |

Tambahkan paket ini di preamble LaTeX:

```tex
\usepackage{booktabs}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
```

Contoh pemanggilan tabel dari `docs/proposal tugas akhir/Skripsi.tex`:

```tex
\input{../../notebooks/build-graph/outputs/evaluation/bab4_artifacts/bab4_table_retrieval_overall.tex}
```

## 6. Cara Menulis Klaim di Bab 4

Klaim yang sudah cukup aman:

- Layer 1 dapat dipakai untuk menunjukkan perbedaan kualitas retrieval antar
  mode.
- Mode graph/hybrid dapat dianalisis berdasarkan kategori pertanyaan, terutama
  relasional dan multi-hop.
- Latensi perlu dilaporkan karena mode graph/hybrid biasanya lebih mahal
  daripada Vector RAG.

Klaim yang harus hati-hati:

- Jangan menyatakan Hybrid GraphRAG mengurangi halusinasi hanya dari Hit@K atau
  MRR. Metrik retrieval belum menguji kebenaran setiap klaim jawaban.
- Jika Layer 2 masih memakai heuristik lokal dan belum RAGAS penuh, tulis
  sebagai evaluasi awal.
- Jika Layer 4 baru dijalankan `n=5`, tulis sebagai uji awal, bukan kesimpulan
  final.

Kalimat yang lebih aman untuk Bab 4:

> Hasil ini menunjukkan bahwa sistem telah terverifikasi secara fungsional pada
> tahap retrieval dan generasi awal. Namun, klaim efektivitas terhadap penurunan
> halusinasi masih perlu dilihat melalui evaluasi faithfulness dan answer
> correctness pada seluruh dataset evaluasi.

## 7. Pemetaan ke Rumusan Masalah

| Rumusan masalah | Bukti evaluasi yang digunakan |
| --- | --- |
| Pipeline konstruksi knowledge graph | Statistik node, edge, relasi, provenance, dan quality gate KG |
| Hybrid Vector-Graph Retrieval | Layer 1, Layer 3, tabel retrieval per mode dan per kategori |
| Traceability dan halusinasi | Layer 2, Layer 4, audit jawaban, citation payload, dan evidence graph |

Dengan struktur ini, Bab 4 tidak hanya berisi tabel hasil, tetapi juga
menjawab apakah rancangan pada Bab 3 benar-benar bekerja pada data akademik
UNESA.
