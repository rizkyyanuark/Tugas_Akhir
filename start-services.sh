#!/bin/bash

# Neo4j Academic Data Analysis - Startup Script
# Tugas Akhir - UNESA Computer Science

echo "🚀 Starting Neo4j Academic Data Analysis System..."
echo "================================================="

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ Error: docker-compose is not installed"
    echo "Please install Docker and Docker Compose first"
    exit 1
fi

# Check if Docker daemon is running
if ! docker info &> /dev/null; then
    echo "❌ Error: Docker daemon is not running"
    echo "Please start Docker daemon first"
    exit 1
fi

echo "📦 Building and starting services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be ready..."
sleep 10

echo ""
echo "🔍 Checking service status..."
docker-compose ps

echo ""
echo "✅ Services are starting up!"
echo ""
echo "📋 Access Information:"
echo "  🗄️  Neo4j Browser:  http://localhost:7474"
echo "      Username: neo4j"
echo "      Password: neo4jpassword"
echo "      Database: datascience"
echo ""
echo "  📊 Grafana Dashboard: http://localhost:3000"
echo "      Username: admin"
echo "      Password: admin"
echo ""
echo "  📈 Prometheus:        http://localhost:9090"
echo ""
echo "  🔧 Container Stats:   http://localhost:8081 (cAdvisor)"
echo ""

echo "📝 Next Steps:"
echo "  1. Wait 1-2 minutes for Neo4j to fully initialize"
echo "  2. Access Neo4j Browser to verify database connection"
echo "  3. Run Jupyter notebooks in notebook/build-graph/talent/"
echo "  4. Check monitoring dashboards for system metrics"
echo ""

echo "🛑 To stop all services:"
echo "  docker-compose down"
echo ""

echo "🔄 To restart services:"
echo "  docker-compose restart"
echo ""

echo "📋 To view logs:"
echo "  docker-compose logs -f neo4j"
echo ""