#!/bin/bash
# Script untuk verifikasi monitoring setup
# UNESA Knowledge Graph - Monitoring Verification

echo "🔍 UNESA Knowledge Graph - Monitoring Verification"
echo "=================================================="
echo ""

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to check if service is running
check_service() {
    local service_name=$1
    local port=$2
    local endpoint=$3
    
    echo -n "Checking $service_name on port $port... "
    
    if curl -s -f "$endpoint" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ UP${NC}"
        return 0
    else
        echo -e "${RED}❌ DOWN${NC}"
        return 1
    fi
}

# Function to check metrics endpoint
check_metrics() {
    local service_name=$1
    local endpoint=$2
    local expected_metric=$3
    
    echo -n "  Checking $service_name metrics... "
    
    response=$(curl -s "$endpoint")
    if echo "$response" | grep -q "$expected_metric"; then
        echo -e "${GREEN}✅ Metrics available${NC}"
        # Show sample metric
        echo "    Sample: $(echo "$response" | grep "$expected_metric" | head -1)"
        return 0
    else
        echo -e "${RED}❌ Metrics not found${NC}"
        return 1
    fi
}

# Function to check Prometheus target
check_prometheus_target() {
    local job_name=$1
    
    echo -n "  Checking Prometheus target '$job_name'... "
    
    response=$(curl -s "http://localhost:9090/api/v1/targets")
    if echo "$response" | grep -q "\"job\":\"$job_name\"" && echo "$response" | grep -q "\"health\":\"up\""; then
        echo -e "${GREEN}✅ Target UP${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  Target may be down${NC}"
        return 1
    fi
}

echo "1️⃣  Checking Docker Containers"
echo "================================"
docker-compose ps
echo ""

echo "2️⃣  Checking Service Health"
echo "================================"

# Check Neo4j
check_service "Neo4j Browser" "7474" "http://localhost:7474"
check_service "Neo4j Metrics" "2004" "http://localhost:2004/metrics"
check_metrics "Neo4j" "http://localhost:2004/metrics" "neo4j_database_node_count"

# Check Weaviate
check_service "Weaviate API" "8080" "http://localhost:8080/v1/.well-known/ready"
check_service "Weaviate Metrics" "2112" "http://localhost:2112/metrics"
check_metrics "Weaviate" "http://localhost:2112/metrics" "weaviate_object_count_total"

# Check Prometheus
check_service "Prometheus" "9090" "http://localhost:9090/-/healthy"

# Check Grafana
check_service "Grafana" "3000" "http://localhost:3000/api/health"

echo ""
echo "3️⃣  Checking Prometheus Targets"
echo "================================"
check_prometheus_target "neo4j"
check_prometheus_target "weaviate"
check_prometheus_target "node"
check_prometheus_target "prometheus"

echo ""
echo "4️⃣  Checking Grafana Data Sources"
echo "================================"
echo -n "Querying Grafana data sources... "
datasources=$(curl -s -u admin:admin "http://localhost:3000/api/datasources")
if echo "$datasources" | grep -q "Prometheus"; then
    echo -e "${GREEN}✅ Prometheus data source configured${NC}"
else
    echo -e "${RED}❌ Prometheus data source not found${NC}"
fi

echo ""
echo "5️⃣  Testing Sample Queries"
echo "================================"

# Test Neo4j metrics query
echo -n "Testing Neo4j node count query... "
neo4j_query=$(curl -s 'http://localhost:9090/api/v1/query?query=neo4j_database_node_count')
if echo "$neo4j_query" | grep -q "\"status\":\"success\""; then
    node_count=$(echo "$neo4j_query" | grep -o '"value":\[[^]]*\]' | grep -o '[0-9]\+' | tail -1)
    echo -e "${GREEN}✅ Success${NC} (Node count: $node_count)"
else
    echo -e "${RED}❌ Failed${NC}"
fi

# Test Weaviate metrics query
echo -n "Testing Weaviate object count query... "
weaviate_query=$(curl -s 'http://localhost:9090/api/v1/query?query=weaviate_object_count_total')
if echo "$weaviate_query" | grep -q "\"status\":\"success\""; then
    object_count=$(echo "$weaviate_query" | grep -o '"value":\[[^]]*\]' | grep -o '[0-9]\+' | tail -1)
    echo -e "${GREEN}✅ Success${NC} (Object count: ${object_count:-0})"
else
    echo -e "${RED}❌ Failed${NC}"
fi

echo ""
echo "6️⃣  Checking Dashboard"
echo "================================"
echo -n "Checking for UNESA KG dashboard... "
dashboards=$(curl -s -u admin:admin "http://localhost:3000/api/search?query=UNESA")
if echo "$dashboards" | grep -q "unesa-kg-monitoring"; then
    echo -e "${GREEN}✅ Dashboard found${NC}"
    dashboard_url="http://localhost:3000/d/unesa-kg-monitoring/unesa-knowledge-graph-neo4j-weaviate-monitoring"
    echo "    URL: $dashboard_url"
else
    echo -e "${YELLOW}⚠️  Dashboard not found (may need manual import)${NC}"
fi

echo ""
echo "7️⃣  Summary"
echo "================================"
echo "Service URLs:"
echo "  • Neo4j Browser:   http://localhost:7474"
echo "  • Weaviate API:    http://localhost:8080"
echo "  • Prometheus:      http://localhost:9090"
echo "  • Grafana:         http://localhost:3000 (admin/admin)"
echo ""
echo "Metrics Endpoints:"
echo "  • Neo4j:           http://localhost:2004/metrics"
echo "  • Weaviate:        http://localhost:2112/metrics"
echo ""
echo "Prometheus Targets:"
echo "  http://localhost:9090/targets"
echo ""
echo "Grafana Dashboard:"
echo "  http://localhost:3000/d/unesa-kg-monitoring/"
echo ""
echo "=================================================="
echo "✅ Verification complete!"
