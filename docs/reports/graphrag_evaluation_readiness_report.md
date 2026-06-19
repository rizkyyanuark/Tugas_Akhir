# Audit Kesiapan Evaluasi Hybrid GraphRAG YUNESA

Tanggal audit: 2026-06-16

## Kesimpulan Singkat

Hasil testing yang terlihat mirip bukan berarti seluruh sistem gagal. Integrasi dasar sudah berjalan: retrieval dapat memanggil indeks vektor, graf dapat dipakai untuk subgraph retrieval, dan tool `query_kb` sudah mengembalikan evidence ke agent. Namun, sistem belum layak dipakai untuk klaim evaluasi akhir seperti "Hybrid GraphRAG lebih baik dari Vector RAG" atau "sistem berhasil menurunkan halusinasi" tanpa perbaikan tambahan.

Status yang lebih tepat saat ini:

| Area | Status | Catatan |
|---|---|---|
| Retrieval awal | Layak untuk smoke test | Ada sinyal graph membantu kueri relasional, tetapi belum stabil. |
| Answer generation | Belum layak untuk klaim final | Beberapa jawaban masih terlalu umum, tidak lengkap, atau salah secara faktual. |
| Evaluasi anti-halusinasi | Belum cukup | Layer 2 belum memakai RAGAS penuh dan Layer 4 terlalu kecil. |
| UI/agent production behavior | Perlu regresi khusus | Evidence tersedia, tetapi jawaban final belum selalu memakai evidence dengan rapi. |
| Bab 4 skripsi | Bisa ditulis sebagai hasil sementara | Klaim harus dibatasi: struktural/fungsional, bukan keunggulan final. |

## Bukti Utama dari Artefak Evaluasi

### 1. Retrieval graph memang membantu, tetapi efeknya belum besar

Pada `eval_layer1_report.md`, hasil semua kategori adalah:

| Mode | n | MRR | Hit@5 | Latency |
|---|---:|---:|---:|---:|
| naive | 56 | 0.6369 | 0.6786 | 2.68s |
| subgraph | 56 | 0.6409 | 0.7500 | 7.71s |
| hybrid | 56 | 0.6447 | 0.7500 | 10.19s |
| mix | 56 | 0.6268 | 0.6607 | 10.32s |

Interpretasi:

- `subgraph` dan `hybrid` naik pada Hit@5 dibanding `naive`, tetapi kenaikannya belum besar.
- `mix` justru lebih rendah dari `naive` pada MRR dan Hit@5 keseluruhan.
- Latensi graph mode jauh lebih tinggi dari `naive`, sehingga peningkatan kualitas harus cukup jelas agar layak secara sistem.

### 2. Per kategori, pola mode terbaik berbeda

Kategori A faktual:

| Mode | MRR | Hit@5 |
|---|---:|---:|
| naive | 0.9250 | 0.9500 |
| subgraph | 0.8333 | 0.8500 |
| hybrid | 0.8833 | 0.9000 |
| mix | 0.9250 | 0.9500 |

Kategori B relasional:

| Mode | MRR | Hit@5 |
|---|---:|---:|
| naive | 0.5014 | 0.5667 |
| subgraph | 0.5700 | 0.7667 |
| hybrid | 0.5400 | 0.7333 |
| mix | 0.4793 | 0.5333 |

Kategori C multi-hop:

| Mode | MRR | Hit@10 |
|---|---:|---:|
| naive | 0.3542 | 0.5000 |
| subgraph | 0.3542 | 0.5000 |
| hybrid | 0.3727 | 0.6667 |
| mix | 0.3708 | 0.6667 |

Interpretasi:

- Untuk pertanyaan faktual, vector retrieval sudah kuat. Graph tidak otomatis membuat jawaban lebih baik.
- Untuk pertanyaan relasional, `subgraph` lebih baik dari `naive`. Ini sinyal positif untuk rumusan masalah Hybrid Vector-Graph Retrieval.
- Untuk multi-hop, `hybrid` dan `mix` mulai membantu pada Hit@10, tetapi MRR masih rendah. Artinya kandidat benar sering muncul terlalu bawah.
- Karena setiap kategori punya mode dominan berbeda, default tunggal `mix` tidak cukup.

## Kenapa Hasilnya Mirip-Mirip

### 1. Banyak pertanyaan evaluasi masih bisa dijawab oleh vector retrieval

Kategori A faktual berisi pertanyaan yang targetnya sering muncul langsung di judul, abstrak, TLDR, atau keyword. Pada tipe ini, `naive` memang kuat. Jika mayoritas evaluasi atau UI test berisi pertanyaan faktual, hasil graph dan vector akan tampak mirip.

Ini bukan cacat, tetapi konsekuensi desain dataset. Graph baru terlihat penting saat pertanyaan membutuhkan relasi, misalnya:

- dosen ke publikasi,
- dosen ke topik,
- kolaborator,
- venue,
- afiliasi,
- paper yang menghubungkan metode, dataset, dan author.

### 2. Mode `mix` belum menjadi fusion yang benar-benar unggul

Saat ini `mix` menggabungkan:

- raw vector query,
- content keyword clues,
- entity retrieval,
- relationship retrieval,
- shortest-path/subgraph,
- structured rows dari Neo4j.

Masalahnya, penggabungan banyak evidence belum otomatis berarti lebih baik. Pada hasil Layer 1, `mix` kalah dari `subgraph` untuk kategori relasional dan kalah dari `hybrid` untuk multi-hop. Ini menunjukkan bahwa fusion/reranking belum cukup ketat.

Indikasi teknis:

- evidence vector dapat mendominasi konteks graph,
- kandidat yang relevan bisa terdorong turun,
- relasi graph yang benar belum selalu diterjemahkan menjadi jawaban final yang tegas,
- deduplikasi dan prioritas evidence belum cukup kuat untuk semua jenis pertanyaan.

### 3. Routing pertanyaan belum category-aware

Kode sudah punya mode `vector`, `keyword`, `subgraph`, `global`, `hybrid`, dan `mix`. Namun penggunaan agent cenderung mengarah ke `mix` sebagai default. Data evaluasi menunjukkan:

- faktual: `naive` atau `mix` cukup,
- relasional: `subgraph` paling kuat,
- multi-hop: `hybrid` atau `mix` lebih cocok,
- agregasi/statistik: perlu structured query khusus, bukan hanya vector atau subgraph biasa.

Tanpa router yang memilih mode berdasarkan intent, sistem akan terlihat tidak konsisten.

### 4. Layer 2 belum evaluasi RAGAS penuh

Layer 2 hanya membandingkan `subgraph` dan `mix`, bukan semua mode. Nilainya juga memakai heuristic lokal untuk faithfulness dan answer relevancy:

| Mode | n | Faithfulness | Answer Relevancy | Context Precision | Context Recall |
|---|---:|---:|---:|---:|---:|
| subgraph | 15 | 0.8211 | 0.7410 | - | - |
| mix | 15 | 0.8206 | 0.7511 | - | - |

Karena Context Precision dan Context Recall kosong, Layer 2 belum bisa dipakai untuk klaim final retrieval quality atau grounding quality. Nilai yang mirip di sini lebih banyak menunjukkan evaluator belum cukup diskriminatif.

### 5. Layer 4 terlalu kecil dan hanya faktual

Layer 4 memakai pairwise LLM judge, tetapi sampelnya hanya 5 dan yang tampil hanya kategori A faktual. Hasilnya:

| Mode vs Naive | n | Faithfulness | Traceability | Comprehensiveness | Overall |
|---|---:|---:|---:|---:|---:|
| Subgraph | 5 | 50.0% | 55.0% | 40.0% | 55.0% |
| Hybrid | 5 | 50.0% | 50.0% | 50.0% | 50.0% |
| Mix | 5 | 50.0% | 40.0% | 40.0% | 40.0% |

Ini belum cukup untuk menyimpulkan bahwa graph mode menang atau kalah. Sampelnya terlalu kecil dan belum mewakili pertanyaan relasional/multi-hop, padahal di situlah graph seharusnya unggul.

## Permasalahan yang Ditemukan

### P0 - Evaluasi belum siap untuk klaim final

Masalah:

- Layer 1 mengukur retrieval berdasarkan judul paper, bukan kualitas jawaban.
- Layer 2 belum menjalankan RAGAS penuh atau belum mengisi Context Precision/Recall.
- Layer 4 hanya 5 kasus dan tidak mencakup kategori relasional/multi-hop secara cukup.
- Ada riwayat bug extractor yang sempat membuat `subgraph = 0` karena `text_units[*].title` belum dibaca.

Dampak:

- Angka evaluasi dapat menyesatkan jika langsung dipakai sebagai bukti final.
- Klaim "Hybrid GraphRAG mengurangi halusinasi" belum aman.

Rekomendasi:

- Bekukan dataset evaluasi final minimal 40 pertanyaan.
- Pastikan setiap pertanyaan punya:
  - query,
  - tipe pertanyaan,
  - expected paper titles,
  - expected answer facts,
  - expected graph evidence,
  - status answerable/unanswerable.
- Tambahkan unit test untuk extractor retrieval agar `paper_chunks`, `text_units`, `overview_publications`, dan structured rows terbaca konsisten.

### P0 - Answer generation masih salah atau terlalu umum pada query relasional

Contoh dari Layer 2:

- Jawaban menyebut "Yuni Yamasari tidak memiliki kolaborator yang sering disebutkan", padahal graph memiliki relasi kolaborasi.
- Jawaban menyebut "Ricky Eka Putra memiliki satu publikasi yang relevan", padahal ini berisiko tidak lengkap.
- Jawaban metrik/frekuensi menyatakan "tidak dapat ditentukan", padahal seharusnya bisa memakai topic/model/metric frequency jika datanya tersedia.
- Jawaban afiliasi menyatakan "tidak dapat diidentifikasi secara langsung", padahal graph memiliki `HAS_AFFILIATION`.

Dampak:

- Evidence tersedia, tetapi tidak selalu diterjemahkan menjadi jawaban yang benar.
- UI bisa terlihat seperti chatbot umum, bukan GraphRAG yang grounded.

Rekomendasi:

- Untuk query enumeratif, jangan serahkan seluruhnya ke LLM. Gunakan structured answer builder sebelum LLM.
- Tipe query yang perlu deterministic path:
  - daftar publikasi dosen,
  - author dari paper tertentu,
  - kolaborator dosen,
  - afiliasi dosen,
  - venue publikasi,
  - topik/metode/model/metrik terbanyak,
  - paper berdasarkan dosen dan topik.
- LLM cukup dipakai untuk merapikan narasi, bukan menentukan fakta utama.

### P1 - `mix` belum punya reranking yang cukup kuat

Masalah:

- `mix` seharusnya menjadi mode paling lengkap, tetapi pada Layer 1:
  - kalah dari `naive` pada overall MRR,
  - kalah dari `subgraph` pada kategori relasional,
  - tidak unggul jelas pada multi-hop.

Dampak:

- Default `mix` di UI/agent dapat menghasilkan pengalaman yang tampak lebih buruk daripada mode yang lebih sederhana.

Rekomendasi:

- Terapkan reranking berbasis intent:
  - exact author match boost,
  - exact title match boost,
  - year match boost,
  - graph relation match boost,
  - publication-detail rows lebih tinggi dari vector chunks untuk pertanyaan spesifik.
- Gunakan Reciprocal Rank Fusion atau weighted fusion:
  - factual: vector weight lebih tinggi,
  - relational: graph/structured weight lebih tinggi,
  - multi-hop: shortest-path dan relationship embedding lebih tinggi.
- Batasi kandidat vector yang terlalu umum agar tidak mencemari evidence.

### P1 - Router intent perlu dibuat eksplisit

Masalah:

Sistem memiliki mode, tetapi belum cukup otomatis memilih mode terbaik berdasarkan jenis pertanyaan.

Rekomendasi routing:

| Jenis pertanyaan | Mode utama | Catatan |
|---|---|---|
| Paper berdasarkan metode/dataset/model | vector atau mix | Vector kuat untuk factual content. |
| Paper dari dosen tertentu | subgraph + structured query | Jangan hanya semantic search. |
| Dosen yang menulis topik tertentu | subgraph | Perlu Lecturer -> Publication -> Concept/Keyword. |
| Kolaborator dosen | subgraph/structured | Gunakan `COLLABORATES_WITH`. |
| Topik/metrik paling sering | structured aggregation | Jangan pakai LLM untuk menghitung. |
| Multi-hop dosen-topik-venue-tahun | hybrid | Butuh path dan relasi global. |
| Out-of-scope | reject grounded | Jangan jawab dari prior knowledge. |

### P1 - Grounding policy sudah ada, tetapi belum cukup mengikat output

Tool `query_kb` sudah membawa `answer_policy`, evidence text, graph, chunks, dan structured rows. Namun output final masih dapat:

- membuat daftar terlalu umum,
- mengulang paper yang sama,
- menyebut graph internals,
- tidak menjawab intent secara langsung,
- menjawab dari pengetahuan umum saat evidence lemah.

Rekomendasi:

- Perketat prompt agent untuk memaksa format jawaban berdasarkan intent.
- Untuk daftar publikasi, pakai tabel: No, Judul, Tahun, Venue/DOI, Alasan relevansi.
- Untuk pertanyaan "apa metode", jawab langsung dengan metode dulu, baru evidence.
- Untuk query tidak ditemukan, jawab "tidak ditemukan pada KG", bukan memberi strategi Google Scholar.
- Sertakan jumlah evidence yang dipakai dan apakah hasil capped.

### P2 - KG coverage dan normalisasi data masih memengaruhi retrieval

Masalah potensial:

- Korpus saat ini masih kecil, sekitar 51 publikasi pada artefak verifikasi.
- Relasi sitasi tidak tersedia, jadi pertanyaan citation tidak bisa dijawab.
- GLiNER/GLiREL belum aktif sebagai hasil terverifikasi.
- Concept dari IEEE SKOS memperluas cakupan, tetapi dapat membawa konsep yang terlalu umum.
- Beberapa artefak evaluasi masih menunjukkan mojibake pada karakter kutip/dash, yang dapat mengganggu pencocokan teks dan kualitas laporan.

Rekomendasi:

- Jangan jadikan GLiNER/GLiREL sebagai klaim hasil utama jika pipeline final belum memakai ekstraksi aktif.
- Audit concept mapping dengan sampel manual.
- Bersihkan encoding sebelum laporan final dan visualisasi Bab 4.
- Pisahkan concept langsung dari paper dan concept hasil ekspansi SKOS.

### P2 - Observability sudah berguna, tetapi perlu trace yang lebih terstruktur

Masalah:

- Trace Opik akan lebih berguna jika setiap query menyimpan:
  - chosen mode,
  - detected intent,
  - high/low keywords,
  - retrieved paper ids,
  - graph node ids,
  - relationship signatures,
  - final evidence ids yang benar-benar masuk prompt,
  - answer citation ids.

Rekomendasi:

- Jadikan Opik trace sebagai alat debugging, bukan hanya log.
- Buat trace tags per mode: `vector`, `subgraph`, `hybrid`, `mix`, `structured`.
- Simpan route decision dan reason agar bisa menjelaskan kenapa sistem memilih mode tertentu.

## Apakah Sistem Masih Cacat?

Jawaban teknisnya: sistem belum "cacat total", tetapi belum matang untuk evaluasi akhir.

Yang sudah benar:

- Infrastruktur dual indexing sudah ada.
- Mode retrieval utama sudah tersedia.
- Ada sinyal graph membantu pertanyaan relasional.
- Evidence graph dan vector sudah bisa masuk ke tool payload.
- Evaluasi mulai dipisah per layer.

Yang belum benar:

- Default mode belum adaptif.
- `mix` belum terbukti menjadi mode terbaik.
- Answer generation belum cukup grounded untuk query relasional dan agregatif.
- Evaluasi quality belum cukup kuat untuk klaim ilmiah.
- Beberapa jawaban masih terdengar seperti LLM umum, bukan sistem berbasis KG.

## Keputusan Kesiapan Evaluasi

| Jenis evaluasi | Status | Alasan |
|---|---|---|
| Smoke test integrasi | Siap | Sistem dapat retrieve dan menjawab. |
| Evaluasi retrieval per mode | Hampir siap | Perlu validasi extractor dan dataset final. |
| Evaluasi answer quality final | Belum siap | RAGAS/context metrics belum lengkap. |
| Evaluasi anti-halusinasi | Belum siap | Perlu faithfulness berbasis klaim dan judge lebih besar. |
| Klaim Bab 4 sementara | Siap dengan batasan | Gunakan bahasa "terverifikasi fungsional", bukan "terbukti unggul". |

## Prioritas Perbaikan

### Prioritas 0

1. Bekukan dataset evaluasi final.
2. Perbaiki dan test extractor semua evidence source.
3. Tambahkan structured answer path untuk query enumeratif.
4. Terapkan reject policy saat evidence kosong.
5. Jalankan ulang Layer 1 setelah data dan extractor stabil.

### Prioritas 1

1. Tambahkan intent router untuk memilih `vector`, `subgraph`, `hybrid`, atau structured query.
2. Perbaiki fusion/reranking `mix`.
3. Tambahkan format jawaban berbasis intent.
4. Tambahkan Opik metadata untuk route decision dan evidence ids.

### Prioritas 2

1. Jalankan RAGAS/LLM judge pada minimal 40 pertanyaan.
2. Bandingkan Vector RAG vs Hybrid GraphRAG per kategori.
3. Audit manual 10 sampai 15 jawaban untuk faithfulness klaim.
4. Laporkan latensi dan tradeoff kualitas.

## Rekomendasi Struktur Evaluasi Final

Dataset final sebaiknya tidak hanya berisi pertanyaan yang jawabannya paper title. Minimal ada lima kategori:

| Kategori | Tujuan | Contoh |
|---|---|---|
| A. Faktual konten | Menguji vector retrieval | Metode/dataset/model pada paper tertentu. |
| B. Relasional dosen-paper | Menguji traversal graph | Paper apa yang ditulis Yuni Yamasari. |
| C. Dosen-topik | Menguji Lecturer -> Publication -> Concept | Dosen S2 Informatika yang menulis machine learning pendidikan. |
| D. Multi-hop | Menguji path lebih dari satu relasi | Dosen, topik, venue, tahun dalam satu query. |
| E. Guardrail | Menguji penolakan | Pertanyaan di luar data KG. |

Metrik yang layak:

- Retrieval: MRR, Hit@K, Precision@K.
- Context: Context Precision, Context Recall.
- Generation: Answer Correctness, Faithfulness, Answer Relevancy.
- Operasional: latency, token usage, error rate.
- Traceability: persentase jawaban dengan sumber eksplisit yang benar.

## Implikasi untuk Bab 4

Narasi yang aman untuk Bab 4:

- "Pipeline telah terverifikasi secara struktural menghasilkan KG dan indeks ganda."
- "Graph retrieval menunjukkan keuntungan pada kategori relasional, terutama Hit@5."
- "Mode `mix` belum selalu menjadi mode terbaik, sehingga routing berdasarkan jenis pertanyaan diperlukan."
- "Evaluasi awal menunjukkan sistem sudah dapat menjawab dengan sumber, tetapi efektivitas penurunan halusinasi belum dapat disimpulkan sebelum evaluasi RAGAS final."

Narasi yang harus dihindari:

- "Hybrid GraphRAG terbukti lebih baik dari Vector RAG" jika hanya memakai hasil saat ini.
- "Sistem berhasil menurunkan halusinasi" tanpa faithfulness final.
- "GLiNER/GLiREL terbukti efektif" jika pipeline final belum mengaktifkannya.
- "Mix adalah mode terbaik" karena data saat ini tidak mendukung klaim itu.

## Rekomendasi Akhir

Sebelum evaluasi final, fokus perbaikan tidak perlu menyentuh semua bagian sistem. Yang paling menentukan adalah:

1. router intent,
2. structured answer path,
3. reranking `mix`,
4. evaluasi final yang benar-benar mengukur answer quality,
5. observability evidence-level melalui Opik.

Jika lima bagian ini dibenahi, hasil evaluasi tidak akan lagi terlihat "mirip-mirip" tanpa makna. Perbedaan antar mode akan lebih terbaca: vector kuat untuk faktual, graph kuat untuk relasional, hybrid kuat untuk multi-hop, dan mix hanya dipakai ketika fusion memang memberi nilai tambah.
