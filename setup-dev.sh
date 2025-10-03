#!/bin/bash

# Development Environment Setup Script
# Tugas Akhir - Neo4j Academic Data Analysis

echo "🛠️  Setting up Development Environment..."
echo "========================================"

# Create necessary directories
echo "📁 Creating workspace directories..."
mkdir -p logs
mkdir -p data/imports
mkdir -p data/exports

# Check environment file
if [ ! -f "notebook/build-graph/talent/ws.env" ]; then
    echo "📝 Creating environment file..."
    cat > notebook/build-graph/talent/ws.env << EOF
# Neo4j Database Configuration
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=neo4jpassword
NEO4J_URI=neo4j://localhost:7687
NEO4J_DATABASE=datascience

# AI API Keys (Optional - add your own keys)
GEMINI_API_KEY=your-gemini-api-key-here
OPENAI_API_KEY=your-openai-api-key-here
GITHUB_TOKEN=your-github-token-here

# Model Configuration  
LLM=gemini-2.5-flash
EMBEDDINGS_MODEL=gemini-embedding-001
EOF
    echo "✅ Environment file created at notebook/build-graph/talent/ws.env"
    echo "📝 Please edit it with your API keys if needed"
else
    echo "✅ Environment file already exists"
fi

# Check Python environment
echo ""
echo "🐍 Checking Python environment..."
if command -v python3 &> /dev/null; then
    echo "✅ Python3 found: $(python3 --version)"
else
    echo "❌ Python3 not found. Please install Python 3.8+"
fi

# Check pip
if command -v pip3 &> /dev/null; then
    echo "✅ pip3 found"
else
    echo "❌ pip3 not found"
fi

# Check Jupyter
if command -v jupyter &> /dev/null; then
    echo "✅ Jupyter found"
else
    echo "⚠️  Jupyter not found. Install with: pip install jupyter"
fi

echo ""
echo "📦 Recommended Python packages:"
echo "  pip install pandas numpy matplotlib seaborn plotly"
echo "  pip install neo4j graphdatascience"
echo "  pip install sentence-transformers"
echo "  pip install python-dotenv"
echo "  pip install scrapy requests beautifulsoup4"
echo ""

echo "🚀 Development Setup Complete!"
echo ""
echo "📋 Next Steps:"
echo "  1. Start services: ./start-services.sh"
echo "  2. Install Python packages (see above)"
echo "  3. Edit environment file with your API keys"
echo "  4. Open Jupyter notebooks in notebook/build-graph/talent/"
echo ""