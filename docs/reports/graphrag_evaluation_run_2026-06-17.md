# Status Eksekusi Evaluasi GraphRAG - 2026-06-17

## Ringkasan

Evaluasi sistem sudah memiliki struktur yang sesuai dengan rancangan Bab 3 dan
arah AcademicRAG: membandingkan baseline `naive` dengan mode `subgraph`,
`hybrid`, dan `mix`. Namun, hasil yang bisa dipakai sebagai klaim final masih
berbeda tingkat kematangannya.

Status paling kuat saat ini adalah **Layer 1 Retrieval Quality** karena sudah
berjalan pada 56 pertanyaan teranking. **Layer 2 Answer Quality** masih bersifat
awal karena hanya tersedia pada 15 kasus dan memakai heuristik lokal. **Layer 4
LLM Judge** belum dapat dijalankan penuh karena quota harian Gemini free tier
untuk `gemini-2.5-flash-lite` habis pada batas 20 request/hari.

## Pemetaan terhadap AcademicRAG

| Konsep evaluasi | Mode sistem YUNESA | Peran |
| --- | --- | --- |
| Naive / vector retrieval | `naive` | Baseline Vector RAG tanpa traversal graf |
| Subgraph retrieval | `subgraph` | Menguji manfaat entity dan local graph traversal |
| Global / relationship-aware retrieval | `hybrid` | Menguji bukti relasional dan traversal graf |
| Academic-style mixed retrieval | `mix` | Menggabungkan vector chunk, keyword clue, dan graph evidence |

Pemetaan ini sudah tepat untuk skripsi, tetapi interpretasinya harus kategori
per kategori. Graph retrieval tidak wajib menang pada pertanyaan faktual yang
jawabannya sudah jelas di chunk teks. Manfaat graph seharusnya paling terlihat
pada pertanyaan relasional dan multi-hop.

## Layer 1 - Retrieval Quality

Sumber: `notebooks/build-graph/outputs/evaluation/eval_layer1_report.md`

| Mode | n | MRR | Hit@1 | Hit@5 | Hit@10 | P@5 | Latensi |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `naive` | 56 | 0.6369 | 0.5893 | 0.6786 | 0.7857 | 0.3429 | 2.68 s |
| `subgraph` | 56 | 0.6409 | 0.5714 | 0.7500 | 0.8036 | 0.3964 | 7.71 s |
| `hybrid` | 56 | 0.6447 | 0.5714 | 0.7500 | 0.8393 | 0.3929 | 10.19 s |
| `mix` | 56 | 0.6268 | 0.5714 | 0.6607 | 0.8393 | 0.3357 | 10.32 s |

Interpretasi yang aman:

- `hybrid` memiliki MRR tertinggi secara keseluruhan, tetapi selisih terhadap
  `naive` masih kecil.
- `subgraph` dan `hybrid` menaikkan Hit@5 dibanding `naive`, sehingga ada bukti
  bahwa graph membantu memperluas kandidat relevan.
- Latensi mode berbasis graph lebih tinggi. Ini perlu ditulis sebagai trade-off.

Per kategori:

| Kategori | Temuan utama |
| --- | --- |
| A - Faktual | `naive` dan `mix` sama-sama kuat dengan MRR 0.9250 dan Hit@5 0.9500. |
| B - Relasional | `subgraph` unggul dari `naive` pada MRR (0.5700 vs 0.5014) dan Hit@5 (0.7667 vs 0.5667). |
| C - Multi-hop | `hybrid` dan `mix` membantu pada Hit@10 (0.6667 vs 0.5000), tetapi MRR masih rendah. |

## Layer 2 - Answer Quality

Sumber: `notebooks/build-graph/outputs/evaluation/eval_layer2_report.md`

| Mode | n | Faithfulness | Answer Relevancy | Context Precision | Context Recall | Latensi |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `subgraph` | 15 | 0.8211 | 0.7410 | - | - | 9.0451 s |
| `mix` | 15 | 0.8206 | 0.7511 | - | - | 10.7040 s |

Interpretasi yang aman:

- Layer 2 belum final karena hanya 15 kasus.
- Nilai faithfulness dan relevancy berasal dari heuristik lokal ketika RAGAS
  penuh tidak tersedia.
- Context Precision dan Context Recall belum terisi, sehingga Layer 2 belum
  cukup untuk klaim penurunan halusinasi.

## Layer 3 - Mode Comparison

Sumber: `notebooks/build-graph/outputs/evaluation/eval_layer3_report.md`

Layer 3 sudah berguna untuk visualisasi Bab 4 karena menggabungkan hasil Layer 1
dan Layer 2. Kesimpulan teknisnya sama dengan Layer 1: mode graph paling
bermanfaat pada kategori relasional, sedangkan pertanyaan faktual masih kuat
dengan vector retrieval.

Artefak visual tersedia:

- `eval_layer3_hit_curves.png`
- `eval_layer3_mrr_by_category.png`
- `eval_layer3_scorecard.png`
- `eval_layer3_latency_quality.png`

## Layer 4 - LLM Judge

Perbaikan yang dilakukan:

- Judge sekarang memakai Gemini melalui `GEMINI_API_KEY_JUDGE`.
- Kasus judge gagal ditandai `judge_failed=true` dan dikeluarkan dari agregasi.
- Jika seluruh judge gagal, output utama tidak ditimpa.
- Run parsial dapat disimpan ke folder terpisah dengan `--no-write-main`.
- Daily quota Gemini tidak lagi menunggu retry panjang; proses gagal cepat.

Run valid yang berhasil:

```text
notebooks/build-graph/outputs/evaluation/layer4_subset_6cases/
```

Hasilnya hanya mencakup 6 kasus pertama, semuanya kategori A. Karena itu hasil
ini **tidak layak dipakai sebagai evaluasi final**, tetapi berguna sebagai smoke
test bahwa pipeline judge, cache jawaban, agregasi, dan visualisasi berjalan.

Ringkasan smoke test tersebut:

| Mode vs Naive | n valid | Faithfulness | Traceability | Comprehensiveness | Overall |
| --- | ---: | ---: | ---: | ---: | ---: |
| Subgraph | 6 | 50.0% | 50.0% | 50.0% | 50.0% |
| Hybrid | 6 | 50.0% | 50.0% | 50.0% | 50.0% |
| Mix | 6 | 41.7% | 33.3% | 41.7% | 33.3% |

Run representatif `A01 B01 C01` menunjukkan quota harian Gemini habis:

```text
Quota exceeded for metric:
generativelanguage.googleapis.com/generate_content_free_tier_requests
limit: 20
model: gemini-2.5-flash-lite
quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier
```

Kesimpulan: kegagalan Layer 4 penuh saat ini adalah batas layanan evaluator,
bukan bukti bahwa retrieval GraphRAG gagal.

## Implikasi untuk Bab 4

Klaim yang aman ditulis:

- Pipeline konstruksi KG sudah terverifikasi secara struktural.
- Dual indexing Neo4j dan Zilliz/Milvus sudah terverifikasi secara fungsional.
- Pada evaluasi retrieval 56 kasus, `subgraph` dan `hybrid` menunjukkan
  peningkatan terutama pada kategori relasional.
- Mode graph memiliki biaya latensi lebih tinggi.
- Evaluasi answer faithfulness dan LLM judge masih preliminary.

Klaim yang belum aman ditulis:

- "Hybrid GraphRAG terbukti mengurangi halusinasi."
- "Mode `mix` adalah mode terbaik secara keseluruhan."
- "GraphRAG selalu lebih baik daripada Vector RAG."

Kalimat Bab 4 yang disarankan:

> Hasil evaluasi retrieval menunjukkan bahwa mode berbasis graf memberi manfaat
> paling jelas pada pertanyaan relasional, terutama melalui peningkatan Hit@5.
> Namun, pada pertanyaan faktual, baseline vector retrieval masih sangat kuat.
> Oleh karena itu, integrasi graf pada sistem ini lebih tepat dipahami sebagai
> penguat untuk pertanyaan yang membutuhkan relasi antarentitas, bukan sebagai
> pengganti penuh pencarian vektor.

Untuk klaim halusinasi:

> Evaluasi awal terhadap kualitas jawaban menunjukkan bahwa sistem sudah
> memiliki mekanisme keterlacakan melalui paper chunk, entity evidence,
> relationship evidence, dan graph triples. Akan tetapi, efektivitas sistem
> dalam menurunkan halusinasi belum dapat disimpulkan secara final karena
> evaluasi LLM judge penuh masih terhambat oleh batas quota evaluator.

## Rekomendasi Eksekusi Final

1. Gunakan Layer 1 dan Layer 3 sebagai bukti utama untuk rumusan masalah Hybrid
   Vector-Graph Retrieval.
2. Jalankan Layer 4 penuh ketika quota evaluator tersedia, atau gunakan provider
   judge berbayar/stabil.
3. Jika harus memakai subset, gunakan subset stratified dan tulis eksplisit
   jumlah kasus per kategori.
4. Jangan memakai `layer4_subset_6cases` sebagai hasil final karena hanya
   mewakili kategori faktual.
5. Untuk Bab 4 sementara, letakkan Layer 4 sebagai "evaluasi awal" atau
   "smoke test kualitas jawaban", bukan sebagai kesimpulan final.
