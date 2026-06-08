## Knowledge Graph Construction

Notebook utama untuk eksperimen konstruksi Academic Knowledge Graph ada di:

- `build-graph/yunesa_academic_kg_construction.ipynb`

Entrypoint kode canonical adalah `build-graph/src/yunesa_academic_kg.py`. Modul lama
seperti `graph_builder.py`, `embedding.py`, `graphrag.py`, `nlp_parser.py`, dan
`data_loader.py` dipertahankan hanya untuk kompatibilitas notebook historis.

Default embedding untuk Academic KG sekarang memakai SiliconFlow
`Qwen/Qwen3-Embedding-0.6B` dengan dimensi 1024. Konfigurasi ini hidup sebagai
default code/notebook, bukan sebagai environment variable production. `.env`
cukup menyimpan credential seperti `SILICONFLOW_API_KEY`.

Model embedding saat menulis index ke Zilliz dan saat query dari UI agent harus
sama. Jika mengganti model/dimensi untuk eksperimen, ubah parameter notebook
atau konfigurasi code, lalu rebuild bersih collection Zilliz atau buat
namespace `GRAPH_NAME` baru.

Sebelum menjalankan notebook, pastikan dependency notebook sudah tersinkron:

```powershell
uv sync --project notebooks
```

Jika dijalankan dari VS Code lokal, pilih kernel dari `notebooks/.venv`.
Jika dijalankan memakai runtime Google Colab atau VS Code Colab extension, cell pertama
akan mendeteksi runtime Colab dan meng-install dependency minimal secara otomatis.
Di Colab, source project dari Google Drive disalin dulu ke `/content/Tugas_Akhir_runtime`
agar eksekusi tidak bergantung terus-menerus pada mount Google Drive yang kadang putus.
Untuk VS Code Colab extension, gunakan `.env` di Google Drive. Colab Secrets API hanya
stabil saat notebook dijalankan dari Colab UI browser. Jika memang menjalankan dari Colab UI
dan ingin membaca Colab Secrets, set `YUNESA_USE_COLAB_SECRETS=1` sebelum bootstrap cell.

Untuk Google Colab:

1. Buka `build-graph/yunesa_academic_kg_construction.ipynb` di Colab.
2. Jika tidak ingin clone GitHub dari runtime Colab, sinkronkan folder repo ke Google Drive:
   `MyDrive/Tugas_Akhir`.
3. Jalankan cell pertama. Cell tersebut akan mencari source code di Google Drive atau
   path `YUNESA_PROJECT_DIR`, lalu install dependency minimal bila berjalan di Colab.
4. Simpan secret berikut di Colab Secrets, bukan di notebook:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_ROLE_KEY` atau `SUPABASE_KEY`
5. Clone GitHub hanya dipakai jika kamu set `YUNESA_USE_GIT_CLONE=1`. Default-nya tidak clone.
6. Default branch untuk mode clone adalah `master`. Jika ingin mencoba branch lain,
   set environment variable `YUNESA_REPO_BRANCH` sebelum cell bootstrap dijalankan.
7. GPU Colab belum wajib untuk versi ini karena concept extraction masih deterministik berbasis
   IEEE taxonomy/thesaurus, keyword, dan regex. GPU baru berguna jika nanti ditambah GLiNER,
   GLiREL, atau model NER lain.

Notebook tersebut bersifat eksperimen/offline dan tidak mengubah pipeline ETL production.
Sumber data utama adalah tabel Supabase `papers`, `lecturers`, dan `paper_lecturers`.
Jika koneksi Supabase tidak tersedia, notebook akan fallback ke CSV lokal di
`notebooks/scraping/file_tabulars`.

Schema graph mengikuti ontology Bab 3 proposal dan memakai label relasi English:

- Structural nodes: `Lecturer`, `Publication`, `Venue`, `Year`, `Institution`, `Keyword`
- Concept nodes: `Problem`, `ResearchTopic`, `Task`, `Domain`, `Method`, `Model`,
  `Dataset`, `Metric`, `Result`, `Innovation`
- Publication-concept relations: `HAS_TOPIC`, `USES_METHOD`, `USES_MODEL`,
  `USES_DATASET`, `EVALUATED_WITH`, `HAS_RESULT`, `BELONGS_TO_DOMAIN`
- Lecturer/publication relations: `HAS_AUTHOR`, `PUBLISHES`, `COLLABORATES_WITH`

Relasi IEEE SKOS (`SKOS_BROADER`, `SKOS_NARROWER`, `SKOS_RELATED`, `SKOS_EXACT_MATCH`)
ditambahkan sebagai konteks satu-hop untuk concept yang berhasil digrounding ke IEEE URI.
Jumlah edge SKOS tidak harus sama dengan jumlah concept karena tidak semua concept berasal
dari IEEE term; sebagian concept berasal dari keyword asli dan regex teknis.

Output graph disimpan ke:

- `notebooks/build-graph/outputs/academic_kg/academic_kg_nodes.csv`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_edges.csv`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_node_link.json`
- `notebooks/build-graph/outputs/academic_kg/academic_kg.graphml`
- `notebooks/build-graph/outputs/academic_kg/academic_kg_summary.json`

Untuk menulis hasil ke Neo4j AuraDB, isi credential melalui `.env` atau Colab runtime:

```env
NEO4J_URI=neo4j+s://...
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=...
NEO4J_DATABASE=neo4j
```

Lalu jalankan optional cell `Neo4j AuraDB Load` di notebook. Jangan commit file credential
AuraDB ke Git atau Google Drive publik.

Konsep semantik dibangun dari `title + tldr + abstract + keywords`, lalu digrounding
ke IEEE `ieee-thesaurus.ttl` dan `ieee-taxonomy.ttl`. Setiap edge concept menyimpan
provenance agar keputusan ekstraksi bisa diaudit.
## Google Drive Sync for Colab

Untuk menjalankan KG construction di Colab tanpa clone GitHub, sinkronkan asset notebook KG ke Google Drive:

```powershell
.\scripts\sync-kg-notebook-to-gdrive.ps1 -Target "G:\My Drive\Tugas_Akhir"
```

Jika Google Drive Desktop tidak memakai drive `G:`, set target eksplisit sesuai path Drive kamu:

```powershell
$env:YUNESA_GDRIVE_PROJECT_DIR = "D:\GoogleDrive\My Drive\Tugas_Akhir"
.\scripts\sync-kg-notebook-to-gdrive.ps1
```

Untuk auto-sync setiap ada perubahan pada notebook KG, source KG, IEEE taxonomy/thesaurus, atau dependency notebook:

```powershell
.\scripts\watch-kg-notebook-sync-to-gdrive.ps1 -Target "G:\My Drive\Tugas_Akhir"
```

Jika Google Drive memiliki beberapa folder bernama `Tugas_Akhir`, gunakan root folder ID eksplisit agar link Colab yang benar ikut ter-update:

```powershell
.\scripts\watch-kg-notebook-sync-to-gdrive.ps1 `
  -Target "G:\My Drive\Tugas_Akhir" `
  -DriveRootFolderId "17-vS_wahCJcyek0-GsJDPwQy67YmQerb"
```

Script ini hanya menyalin asset yang dibutuhkan Colab dan tidak menyalin `.env`, AWS key, cache, venv, backend runtime data, atau output notebook. Jika benar-benar perlu membawa `.env` ke private Drive, jalankan dengan `-IncludeEnv`, tetapi default-nya sengaja dimatikan.

Secara default script juga mencoba meng-update file cloud Google Drive langsung lewat `gws` agar link Colab memakai revision terbaru, bukan hanya menunggu Google Drive Desktop meng-upload perubahan dari `G:\My Drive`. Jika ingin hanya menyalin ke DriveFS lokal tanpa Drive API, gunakan `-SkipGwsApi`.
