# KG Construction and AcademicRAG Alignment Report

Tanggal: 2026-06-17

## Ringkasan

Pipeline konstruksi KG saat ini sudah layak sebagai baseline GraphRAG akademik
dan sudah dapat dijalankan dengan jalur ekstraksi aktif GLiNER pada sampel 50
publikasi. Baseline metadata, keyword, regex, dan IEEE SKOS tetap penting
sebagai pembanding, sedangkan GLiNER menambah entitas dari teks tidak
terstruktur. GLiREL tidak dijadikan default karena relasi utama sudah dapat
ditentukan secara deterministik dari tipe entitas dan schema ontologi.

Status faktual dari artefak lokal terbaru setelah rebuild extraction-active
tanpa cloud write:

| Komponen | Nilai |
|---|---:|
| Publikasi | 50 |
| Dosen | 128 |
| Relasi dosen-publikasi | 131 |
| Node KG | 1.432 |
| Relasi KG | 2.224 |
| Concept node | 1.014 |
| Concept dengan URI IEEE | 629 |
| Concept tanpa URI IEEE | 385 |
| PaperChunk prepared rows | 82 |
| EntityEmbedding prepared rows | 1.420 |
| RelationshipEmbedding prepared rows | 2.224 |
| ContentKeyword prepared rows | 50 |
| GLiNER extraction | 50 dokumen, 325 entitas |
| GLiREL extraction | Tidak aktif; 0 relasi |

Catatan: angka di atas berasal dari build lokal pada 2026-06-17 dan belum
ditulis ulang ke AuraDB/Zilliz. Manifest cloud write sebelumnya mencatat 1.253
node dan 1.970 relasi. Untuk Bab 4 final, gunakan satu sumber angka yang sama:
hasil inspeksi cloud setelah rebuild final, atau artefak lokal final jika belum
menulis ulang cloud.

## Perbandingan dengan AcademicRAG

AcademicRAG referensi membangun retrieval dengan pola clue-guided retrieval:
query dipecah menjadi high-level dan low-level keywords, lalu digunakan untuk
mengambil konteks dari graph dan vector store. Sistem Yunesa sudah mengikuti
arah tersebut pada sisi retrieval, tetapi berbeda pada sisi konstruksi graph.

Perbedaan utama:

| Area | AcademicRAG referensi | Sistem Yunesa saat ini |
|---|---|---|
| Sumber dokumen | Dokumen akademik umum | Supabase: publikasi, dosen, relasi dosen-publikasi |
| Ekstraksi entity/relation | LLM extraction | Metadata + keyword + regex + IEEE SKOS, GLiNER untuk NER, GLiREL opsional |
| Graph store | Graph storage abstraction | Neo4j AuraDB property graph |
| Vector store | Entity, relationship, keyword, chunk vectors | Zilliz/Milvus: PaperChunk, EntityEmbedding, RelationshipEmbedding, ContentKeyword |
| Query process | Keyword/clue extraction, subgraph/global retrieval | naive, subgraph, global, hybrid, mix |
| Evaluasi | QA/evaluator berbasis LLM | Layered eval tersedia, LLM judge sedang dibuat provider-agnostic |

Kesimpulan: sistem ini tidak perlu dibuat sama persis dengan AcademicRAG.
Yang perlu dijaga adalah kesamaan prinsip retrieval: clue decomposition,
subgraph retrieval, global relationship retrieval, context fusion, dan judge
berbasis jawaban. Pada sisi konstruksi, sistem Yunesa lebih tepat jika tetap
memakai ontologi akademik sendiri dan controlled vocabulary IEEE.

## Jawaban atas Pertanyaan Neo4j

### Kenapa warna node di Neo4j terlihat sama?

Itu bukan indikasi schema KG rusak. Saat penulisan ke Neo4j, setiap node dibuat
dengan label umum `KGNode` ditambah label tipenya, misalnya `Lecturer`,
`Publication`, `Concept`, dan `Institution`.

Contoh pola tulis:

```cypher
MERGE (n:KGNode:Lecturer {id: row.id})
```

Neo4j Browser sering memberi warna berdasarkan label yang dominan atau style
aktif. Karena semua node memiliki label `KGNode`, warna dapat terlihat seragam.
Di sisi data, label tipe tetap ada. Hal ini terlihat dari hasil overview yang
menampilkan `KGNode`, `Lecturer`, `Institution`, dan label lain secara bersamaan.

Perbaikan yang disarankan:

- Untuk eksplorasi Neo4j Browser, atur style per label (`Lecturer`,
  `Publication`, `Concept`, dll.).
- Untuk visualisasi aplikasi/Bab 4, pakai properti `node_type`, bukan warna
  default Neo4j Browser.
- Tidak perlu menghapus label `KGNode`, karena label ini berguna untuk constraint,
  namespace graph, dan operasi clear/rebuild.

### Kenapa ada SKOS_BROADER, SKOS_NARROWER, SKOS_RELATED?

Relasi SKOS berasal dari IEEE Thesaurus dan IEEE Taxonomy. Fungsinya bukan untuk
menyatakan bahwa paper secara langsung membahas semua konsep tersebut, melainkan
untuk memberi konteks controlled vocabulary.

Makna relasi:

| Relasi | Makna |
|---|---|
| `SKOS_BROADER` | Konsep target lebih umum dari konsep asal |
| `SKOS_NARROWER` | Konsep target lebih spesifik dari konsep asal |
| `SKOS_RELATED` | Konsep memiliki keterkaitan asosiatif |
| `SKOS_EXACT_MATCH` | Konsep dianggap ekuivalen/lintas kosakata |

Catatan penting: relasi SKOS harus diperlakukan sebagai konteks pendukung, bukan
bukti utama jawaban. Bukti utama tetap harus berasal dari `Publication`,
`PaperChunk`, keyword penulis, atau relasi langsung publikasi-konsep.

## Status GLiNER dan GLiREL

Kode sudah memiliki jalur GLiNER dan GLiREL:

- `AcademicExtractionConfig`
- `extract_academic_elements_with_gliner_glirel(...)`
- `_load_gliner_model(...)`
- `_load_glirel_model(...)`
- integrasi hasil ekstraksi ke `AcademicKGBuilder._add_extracted_element_edges(...)`

Run extraction-active lokal 50 publikasi menunjukkan:

```json
"extraction": {
  "documents": 50,
  "entities": 325,
  "relationships": 0,
  "keywords": 229
}
```

Artinya, secara teknis jalur GLiNER sudah dapat berjalan pada korpus Supabase.
Relasi tidak diambil dari GLiREL, melainkan dipetakan dari tipe konsep ke schema
ontologi. Misalnya `Model` menjadi `USES_MODEL`, `Dataset` menjadi
`USES_DATASET`, `Metric` menjadi `EVALUATED_WITH`, dan `Method` menjadi
`USES_METHOD`. Hasil ini masih local build dan belum ditulis ulang ke cloud
graph/vector store. Kalimat yang aman untuk Bab 4:

> Jalur GLiNER telah diuji pada 50 publikasi dan menghasilkan tambahan entitas
> dari teks abstrak/TLDR. Relasi ke publikasi dibentuk secara deterministik
> berdasarkan schema ontologi, sehingga GLiREL ditempatkan sebagai jalur
> eksperimental, bukan komponen utama.

## Catatan Runtime Lokal

Percobaan awal sempat gagal saat import dependency GLiNER karena Windows
melaporkan blokir pada `pyarrow.dataset`. Setelah preflight ringan dan model
terunduh/ter-load, smoke test 2 publikasi dan run 50 publikasi berhasil.
Jika error serupa muncul lagi, penyebab yang perlu dicek adalah:

- status `extraction_runtime_status()`
- import `pyarrow.dataset`
- cache Hugging Face model GLiNER/GLiREL
- kebijakan Windows Application Control terhadap DLL Python

Untuk eksperimen final, lebih aman menjalankan extraction-active build di
runtime yang stabil, lalu baru menulis ulang AuraDB dan Zilliz.

## Perubahan yang Sudah Dilakukan

1. Pesan error GLiNER/GLiREL diperjelas agar tidak lagi menyesatkan sebagai
   sekadar "install gliner/glirel".
2. Evaluator Layer 4 dibuat provider-agnostic:
   - default `YUNESA_JUDGE_PROVIDER=groq`
   - model default `llama-3.3-70b-versatile`
   - tetap mendukung `gemini`
   - mendukung `openai_compatible`, `deepseek`, atau `openai`
3. Metadata evaluasi sekarang mencatat `judge_provider` dan `judge_model`.

## Rekomendasi Pipeline Final

### 1. Baseline KG

Gunakan pipeline saat ini sebagai baseline:

- metadata Supabase
- keyword penulis
- regex concept extraction
- IEEE thesaurus/taxonomy SKOS
- Neo4j + Zilliz dual indexing

Tujuannya: menjadi pembanding terhadap KG dengan ekstraksi aktif.

### 2. GLiNER-Active KG

Jalankan ulang pipeline dengan:

```powershell
$env:YUNESA_USE_GLINER="1"
$env:YUNESA_USE_GLIREL="0"
```

atau melalui parameter:

```python
run_local_kg_pipeline(
    sample_size=50,
    source="supabase",
    graph_name="yunesa_academic_kg",
    use_extraction=True,
    use_glirel=False,
    write_neo4j=True,
    write_milvus=True,
    clear_neo4j=True,
    clear_milvus=True,
)
```

Syarat: jalankan pada runtime yang GLiNER import-nya bersih. GLiREL hanya
diaktifkan untuk eksperimen ablation jika memang ingin menguji relasi bebas
antarentitas.

### 3. Evaluasi Concept dan Relation Quality

Sebelum dipakai untuk klaim Bab 4, hasil GLiNER perlu dinilai:

- jumlah entitas per kategori ontologi
- persentase entitas duplikat
- precision sampel entitas berdasarkan LLM-as-judge atau anotasi manual
- validitas pemetaan tipe entitas ke relasi ontologi
- perbandingan retrieval baseline KG vs extraction-active KG

### 4. Evaluasi GraphRAG

Bandingkan minimal:

| Mode | Fungsi |
|---|---|
| `naive` | Vector RAG baseline |
| `subgraph` | Graph-only/local subgraph retrieval |
| `hybrid` | Subgraph + relationship retrieval |
| `mix` | Vector + graph + keyword clues |

Judge default sekarang dapat memakai Groq:

```powershell
$env:YUNESA_JUDGE_PROVIDER="groq"
$env:YUNESA_JUDGE_MODEL="llama-3.3-70b-versatile"
```

Untuk DeepSeek R1/OpenAI-compatible nanti:

```powershell
$env:YUNESA_JUDGE_PROVIDER="deepseek"
$env:YUNESA_JUDGE_MODEL="deepseek-reasoner"
$env:YUNESA_JUDGE_API_KEY="..."
$env:YUNESA_JUDGE_BASE_URL="https://api.deepseek.com"
```

## Kesimpulan Teknis

KG construction saat ini sudah cukup baik untuk baseline Hybrid GraphRAG dan
sudah berhasil dijalankan dengan GLiNER pada 50 publikasi secara lokal. Namun,
hasil extraction-active ini belum otomatis menjadi klaim akhir karena belum
ditulis ulang ke cloud store dan belum dinilai kualitas entitas serta pemetaan
relasinya.
IEEE SKOS tetap relevan, tetapi harus diposisikan sebagai controlled vocabulary
dan query-expansion layer, bukan sebagai bukti utama jawaban.

Langkah paling defensible untuk skripsi:

1. Pertahankan baseline KG yang sudah stabil.
2. Audit sampel entitas GLiNER dan pemetaan relasinya sebelum rebuild produksi.
3. Jika kualitasnya cukup, tulis ulang AuraDB dan Zilliz dengan GLiNER-active KG.
4. Bandingkan Vector RAG vs Hybrid GraphRAG dengan judge provider yang stabil.
5. Di Bab 4, pisahkan klaim “terverifikasi struktural” dari klaim “lebih baik
   secara retrieval/faithfulness”.
