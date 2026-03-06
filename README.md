# Tugas Akhir - Academic Data Analysis & Graph Knowledge Systems

Sistem analisis data akademik menggunakan Neo4j Graph Database untuk data UNESA (Universitas Negeri Surabaya) dengan ekstraksi bidang riset menggunakan AI dan analitik berbasis graf.

## 🏗️ Arsitektur Sistem

### Komponen Utama

- **Data Scraping Pipeline** (`scraping/`): Web scraping dari PDDIKTI menggunakan library `pddiktipy`
- **Graph Database**: Neo4j 5 dengan Graph Data Science library untuk penyimpanan dan analitik knowledge graph
- **AI Research Extraction** (`notebook/`): Menggunakan Gemini AI, BERT, SentenceTransformers untuk klasifikasi bidang riset
- **Monitoring Stack**: Prometheus + Grafana untuk monitoring Neo4j database

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.8+

### 1. Setup Database Neo4j

```bash
# Start Neo4j database dan monitoring stack
docker-compose up -d

# Verifikasi status
docker-compose ps
```

### 2. Akses Neo4j Browser

- URL: http://localhost:7474
- Username: `neo4j`
- Password: `rizkyyk123`
- Database: `datascience`

### 3. Akses Monitoring

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090

### 4. Setup Environment

```bash
# Copy environment template
cp notebook/build-graph/talent/ws.env.template notebook/build-graph/talent/ws.env

# Edit dengan kredensial Anda
# NEO4J_URI=neo4j://localhost:7687
# NEO4J_USERNAME=neo4j
# NEO4J_PASSWORD=rizkyyk123
# NEO4J_DATABASE=datascience
```

## 📊 Data Pipeline

### 1. Data Scraping (`scraping/`)

```bash
# Konfigurasi program studi
vim scraping/program_studi_config.txt

# Jalankan scraping
jupyter notebook scraping/scrapy_pddikti.ipynb
```

Output: CSV files di `scraping/file_tabulars/`:

- `dosen.csv` - Data dosen
- `penelitian.csv` - Data penelitian
- `pengabdian.csv` - Data pengabdian
- `karya.csv` - Data karya ilmiah

### 2. Graph Database Processing (`notebook/build-graph/talent/`)

```bash
# Jalankan ETL pipeline
jupyter notebook notebook/build-graph/talent/graph_basics.ipynb
```

Pipeline memproses:

- Node: Dosen, MataKuliah, Course, Kelas, ProgramStudi
- Relationships: MENGAJAR, PERNAH_MENGAJAR, TELAH_MENGAJAR, dll.

### 3. AI Research Area Extraction

```bash
# Ekstraksi bidang riset dengan AI
jupyter notebook notebook/build-graph/talent/graphrag_agent.ipynb
```

Menggunakan multiple AI approaches:

1. **Primary**: SentenceTransformers (offline, multilingual)
2. **Fallback**: Enhanced keyword matching + TF-IDF
3. **Backup**: Hugging Face zero-shot classification

## 🔧 Konfigurasi

### Neo4j Environment Variables

```bash
NEO4J_URI="neo4j://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="rizkyyk123"
NEO4J_DATABASE="datascience"
```

### AI APIs (Optional)

```bash
GEMINI_API_KEY="your-gemini-key"
OPENAI_API_KEY="your-openai-key"
LLM="gemini-2.5-flash"
EMBEDDINGS_MODEL="gemini-embedding-001"
```

## 📈 Monitoring

### Neo4j Metrics

- Database connections
- Query performance
- Memory usage
- Transaction statistics
- GDS algorithm metrics

### Access Points

- **Neo4j Browser**: http://localhost:7474
- **Grafana Dashboard**: http://localhost:3000
- **Prometheus Metrics**: http://localhost:9090

## 🛠️ Development

### Struktur Notebook

- **Environment Setup** → **Data Loading** → **AI Extraction** → **Visualization**
- Functions dalam cell terpisah untuk modularitas
- Fallback mechanisms untuk missing APIs

### Research Area Classification

12 kategori Computer Science:

- Machine Learning & Artificial Intelligence
- Computer Vision & Image Processing
- Natural Language Processing
- Data Science & Analytics
- Software Engineering & Web Development
- Database Systems & Information Management
- Educational Technology & E-Learning
- Healthcare Informatics & Medical AI
- Cybersecurity & Information Security
- Mobile Computing & Applications
- Network Analysis & Social Media
- Signal Processing & Multimedia

## 🔍 Troubleshooting

### Common Issues

1. **Neo4j Connection**: Pastikan container running

   ```bash
   docker-compose logs neo4j
   ```

2. **Rate Limiting APIs**: Gunakan offline models

   ```python
   # Fallback ke SentenceTransformers
   from sentence_transformers import SentenceTransformer
   ```

3. **Environment Issues**: Validasi setup
   ```python
   # Test koneksi
   from neo4j import GraphDatabase
   driver = GraphDatabase.driver(uri, auth=(user, password))
   ```

## 📚 Documentation

- [Neo4j Monitoring Setup](monitoring/neo4j/README.md)
- [Copilot Instructions](.github/copilot-instructions.md)
- [Financial Documents Workshop](notebook/build-graph/financial_documents/README.md)

## 🤝 Contributing

1. Fork repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request

## 📄 License

Academic research project - UNESA Computer Science Department

---

**Catatan**: Sistem ini mengutamakan **robustness over performance** dengan multiple fallback strategies untuk memastikan sistem berjalan meski dengan missing APIs atau resource terbatas.
