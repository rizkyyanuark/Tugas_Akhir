# Tugas Akhir - Academic Data Analysis & Graph Knowledge Systems

This is an Indonesian academic research project focusing on building knowledge graphs from university data, specifically UNESA (Universitas Negeri Surabaya) academic datasets, with AI-powered research area extraction and graph-based analytics.

## 🏗️ Architecture Overview

### Core Components

- **Data Scraping Pipeline** (`scraping/`): Web scraping from PDDIKTI (Indonesian Higher Education Database) using `pddiktipy` library
- **Graph Database** (`docker-compose.yml`): Neo4j 5 with Graph Data Science library for knowledge graph storage and analytics
- **AI Research Extraction** (`notebook/genai-workshop/talent/`): Multiple approaches including Gemini AI, BERT, SentenceTransformers for research area classification
- **Visualization & Analysis**: Jupyter notebooks with matplotlib, seaborn, plotly for comprehensive data analysis

### Data Flow

1. **Scraping** → PDDIKTI API → CSV files (`scraping/file_tabulars/`)
2. **Processing** → Research area extraction → Neo4j graph database
3. **Analysis** → Graph queries + ML analytics → Visualizations

## 🔧 Environment Setup Patterns

### Configuration Files

- Primary config: `notebook/genai-workshop/talent/ws.env` (main environment file)
- Template: `notebook/genai-workshop/customers-and-products/ws.env.template`
- Docker: Local Neo4j via `docker-compose.yml` with credentials `neo4j/testpassword`

### Required Environment Variables

```bash
# Neo4j Database
NEO4J_URI="neo4j://localhost:7687"
NEO4J_USERNAME="neo4j"
NEO4J_PASSWORD="rizkyyk123"
NEO4J_DATABASE="datascience"

# AI APIs
GEMINI_API_KEY="AIzaSy..."  # Google Gemini for research extraction
GITHUB_TOKEN="ghp_..."      # For fetching research data from GitHub

# Model Configuration
LLM="gemini-2.5-flash"
EMBEDDINGS_MODEL="gemini-embedding-001"
```

### Environment Loading Pattern

```python
env_file = 'ws.env'
if os.path.exists(env_file):
    load_dotenv(env_file, override=True)
    HOST = os.getenv('NEO4J_URI')
    USERNAME = os.getenv('NEO4J_USERNAME')
    # ... load other variables
```

## 🎯 Key Development Workflows

### Data Scraping Workflow (`scraping/`)

1. Configure target programs in `program_studi_config.txt`
2. Run `scrapy_pddikti.ipynb` to scrape PDDIKTI data
3. Outputs to `file_tabulars/` as CSV files: `dosen.csv`, `penelitian.csv`, `pengabdian.csv`, etc.

### AI Research Area Extraction

**Problem**: Gemini API rate limits (429 errors) occur frequently
**Solutions implemented**:

1. **Primary**: SentenceTransformers (`paraphrase-multilingual-MiniLM-L12-v2`) - FREE, multilingual
2. **Fallback**: Enhanced keyword matching + TF-IDF clustering
3. **Backup**: Hugging Face zero-shot classification

### Neo4j Development

- Start database: `docker-compose up neo4j`
- Access browser: http://localhost:7474 (neo4j/testpassword)
- Connection pattern: Use GraphDataScience client for advanced analytics

## 📊 Research Area Classification System

### 12 Computer Science Categories

```python
cs_categories = [
    "Machine Learning & Artificial Intelligence",
    "Computer Vision & Image Processing",
    "Natural Language Processing",
    "Data Science & Analytics",
    "Software Engineering & Web Development",
    "Database Systems & Information Management",
    "Educational Technology & E-Learning",
    "Healthcare Informatics & Medical AI",
    "Cybersecurity & Information Security",
    "Mobile Computing & Applications",
    "Network Analysis & Social Media",
    "Signal Processing & Multimedia"
]
```

### Multilingual Keyword Mapping

- **Indonesian terms**: 'machine learning' → 'pembelajaran mesin', 'citra' → computer vision
- **Academic context**: Research titles often mix Indonesian and English terminology
- **Enhanced scoring**: Longer keywords (>5 chars) get higher relevance scores

## 🔍 Project-Specific Patterns

### Notebook Cell Organization

- **Environment Setup** → **Data Loading** → **AI Extraction** → **Visualization** → **Analysis**
- Functions defined in dedicated cells, execution in separate cells
- Fallback mechanisms for missing APIs/libraries

### Error Handling Philosophy

- **Graceful degradation**: If Gemini API fails → SentenceTransformers → keyword matching
- **Rate limit handling**: Batch processing with delays, retry mechanisms
- **Library availability**: Try-catch imports with feature flags (`TRANSFORMERS_AVAILABLE`)

### Data Processing Conventions

- **CSV naming**: `{entity}.csv` in `file_tabulars/` (e.g., `penelitian.csv` for research data)
- **DataFrame patterns**: `penelitian_df` for research, `dosen_df` for faculty data
- **Column conventions**: `judul_kegiatan` for research titles, `nama_dosen` for faculty names

### Visualization Standards

- **Matplotlib/Seaborn**: Bar charts for research area distribution
- **Color schemes**: `plt.cm.Set3` for category visualization
- **Bilingual labels**: Indonesian titles with English technical terms
- **Interactive fallback**: Text-based visualizations when matplotlib unavailable

## 🚨 Common Issues & Solutions

### Rate Limiting (429 Errors)

- **Cause**: Gemini API free tier limits (~15 requests/minute)
- **Solution**: Switch to offline models (SentenceTransformers recommended)

### Missing Dependencies

- **Optional imports**: Use try-catch with feature flags
- **Fallback chains**: AI model → Classical ML → Rule-based

### Environment Configuration

- **Check pattern**: Always test environment setup with dedicated validation functions
- **Flexible paths**: Support both absolute and relative paths for environment files

### Neo4j Connection Issues

- **Docker first**: Ensure Neo4j container is running before notebook execution
- **Connection validation**: Test database connectivity before data operations

This codebase prioritizes **robustness over performance** - multiple fallback strategies ensure the system works even with missing APIs, offline environments, or limited resources.
