## Knowledge Graph Construction

Notebook utama untuk eksperimen konstruksi Academic Knowledge Graph ada di:

- `build-graph/yunesa_academic_kg_construction.ipynb`

Sebelum menjalankan notebook, pastikan dependency notebook sudah tersinkron:

```powershell
uv sync --project notebooks
```

Untuk Google Colab:

1. Buka `build-graph/yunesa_academic_kg_construction.ipynb` di Colab.
2. Jalankan cell pertama. Cell tersebut akan clone atau refresh repo dan install dependency minimal bila berjalan di Colab.
3. Simpan secret berikut di Colab Secrets, bukan di notebook:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` atau `SUPABASE_KEY`
4. Default branch yang dipakai di Colab adalah `master`. Jika ingin mencoba branch lain,
   set environment variable `YUNESA_REPO_BRANCH` sebelum cell bootstrap dijalankan.
5. GPU Colab belum wajib untuk versi ini karena concept extraction masih deterministik berbasis
   IEEE taxonomy/thesaurus, keyword, dan regex. GPU baru berguna jika nanti ditambah GLiNER,
   sentence-transformers, atau model NER lain.

Notebook tersebut bersifat eksperimen/offline dan tidak mengubah pipeline ETL production.
Sumber data utama adalah tabel Supabase `papers`, `lecturers`, dan `paper_lecturers`.
Jika koneksi Supabase tidak tersedia, notebook akan fallback ke CSV lokal di
`notebooks/scraping/file_tabulars`.

Output graph disimpan ke:

- `notebooks/build-graph/outputs/academic_kg/academic_kg_nodes.csv`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_edges.csv`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_node_link.json`
- `notebooks/build-graph/outputs/academic_kg/academic_kg.graphml`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_summary.json`

Konsep semantik dibangun dari `title + tldr + abstract + keywords`, lalu digrounding
ke IEEE `ieee-thesaurus.ttl` dan `ieee-taxonomy.ttl`. Setiap edge concept menyimpan
provenance agar keputusan ekstraksi bisa diaudit.
