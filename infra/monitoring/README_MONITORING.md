# 📊 Monitoring Neo4j & Weaviate dengan Prometheus + Grafana

## 🎯 Arsitektur Monitoring

```
┌─────────────────────────────────────────────────────────────┐
│                 UNESA Knowledge Graph System                 │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌────────────┐         ┌─────────────┐                     │
│  │  Neo4j     │:2004    │  Weaviate   │:2112                │
│  │  (Graph)   ├─────┐   │  (Vector)   ├─────┐              │
│  └────────────┘     │   └─────────────┘     │              │
│                     │                        │              │
│                     │   ┌─────────────┐     │              │
│                     └──►│ Prometheus  │◄────┘              │
│                         │   :9090     │                     │
│                         └──────┬──────┘                     │
│                                │                             │
│                         ┌──────▼──────┐                     │
│                         │   Grafana   │                     │
│                         │    :3000    │                     │
│                         └─────────────┘                     │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Start All Services

```bash
cd "/c/Users/rizky/OneDrive/Dokumen/GitHub/Tugas_Akhir"

# Start semua services
docker-compose up -d

# Check status
docker-compose ps
```

### 2. Verify Prometheus Targets

```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Or visit browser
# http://localhost:9090/targets
```

Expected targets:

- ✅ `neo4j` → http://neo4j:2004/metrics
- ✅ `weaviate` → http://weaviate:2112/metrics
- ✅ `node` → http://node_exporter:9100/metrics
- ✅ `prometheus` → http://localhost:9090/metrics

### 3. Access Grafana Dashboard

```
URL: http://localhost:3000
Username: admin
Password: admin

Dashboard: "UNESA Knowledge Graph - Neo4j & Weaviate Monitoring"
```

## 📊 Metrics Overview

### Neo4j Metrics (Port 2004)

#### Database Metrics

```promql
# Total nodes in datascience database
neo4j_database_node_count{database="datascience"}

# Total relationships
neo4j_database_relationship_count{database="datascience"}

# Database size (bytes)
neo4j_database_store_size_total{database="datascience"}
```

#### Transaction Metrics

```promql
# Active read transactions
neo4j_transaction_active_read{database="datascience"}

# Active write transactions
neo4j_transaction_active_write{database="datascience"}

# Transaction rate
rate(neo4j_transaction_committed_total{database="datascience"}[5m])
```

#### Query Performance

```promql
# Query execution time (p95)
histogram_quantile(0.95, rate(neo4j_cypher_query_execution_latency_millis_bucket[5m]))

# Slow queries (>1s)
increase(neo4j_cypher_query_execution_slow_total[5m])
```

#### Memory Usage

```promql
# Heap memory used
neo4j_vm_heap_used

# Page cache hits ratio
rate(neo4j_page_cache_hits_total[5m]) /
(rate(neo4j_page_cache_hits_total[5m]) + rate(neo4j_page_cache_faults_total[5m]))
```

### Weaviate Metrics (Port 2112)

#### Object Metrics

```promql
# Total objects across all classes
weaviate_object_count_total

# Objects per class
weaviate_object_count_total{class_name="AcademicDocument"}
```

#### Query Performance

```promql
# Request latency p95
histogram_quantile(0.95, rate(weaviate_requests_total_duration_ms_bucket[5m]))

# Request latency p99
histogram_quantile(0.99, rate(weaviate_requests_total_duration_ms_bucket[5m]))

# Average latency
rate(weaviate_requests_total_duration_ms_sum[5m]) /
rate(weaviate_requests_total_duration_ms_count[5m])
```

#### Request Rate

```promql
# GraphQL requests per second
rate(weaviate_requests_total{api="graphql"}[5m])

# REST API requests per second
rate(weaviate_requests_total{api="rest"}[5m])

# Total RPS
sum(rate(weaviate_requests_total[5m]))
```

#### Vector Operations

```promql
# Vector search operations
rate(weaviate_vector_index_operations_total{operation="search"}[5m])

# Vector insertions
rate(weaviate_vector_index_operations_total{operation="insert"}[5m])

# Vector search duration
rate(weaviate_vector_index_operations_duration_ms_sum[5m]) /
rate(weaviate_vector_index_operations_duration_ms_count[5m])
```

#### Batch Operations

```promql
# Batch import rate
rate(weaviate_batch_requests_total[5m])

# Average objects per batch
rate(weaviate_batch_objects_total[5m]) /
rate(weaviate_batch_requests_total[5m])
```

## 🔧 Custom Alerts

### Create Alert Rules (`monitoring/prometheus/alerts.yml`)

```yaml
groups:
  - name: neo4j_alerts
    interval: 30s
    rules:
      # High query latency
      - alert: Neo4jHighQueryLatency
        expr: histogram_quantile(0.95, rate(neo4j_cypher_query_execution_latency_millis_bucket[5m])) > 1000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Neo4j query latency is high"
          description: "P95 query latency is {{ $value }}ms (threshold: 1000ms)"

      # Database size growth
      - alert: Neo4jDatabaseSizeGrowth
        expr: rate(neo4j_database_store_size_total{database="datascience"}[1h]) > 1000000000
        for: 1h
        labels:
          severity: info
        annotations:
          summary: "Neo4j database growing rapidly"
          description: "Database size increased by {{ $value }} bytes in the last hour"

      # Page cache efficiency
      - alert: Neo4jLowPageCacheHitRatio
        expr: |
          rate(neo4j_page_cache_hits_total[5m]) / 
          (rate(neo4j_page_cache_hits_total[5m]) + rate(neo4j_page_cache_faults_total[5m])) < 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Neo4j page cache hit ratio is low"
          description: "Page cache hit ratio is {{ $value }} (threshold: 0.8)"

  - name: weaviate_alerts
    interval: 30s
    rules:
      # High request latency
      - alert: WeaviateHighLatency
        expr: histogram_quantile(0.99, rate(weaviate_requests_total_duration_ms_bucket[5m])) > 500
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Weaviate request latency is high"
          description: "P99 latency is {{ $value }}ms (threshold: 500ms)"

      # High error rate
      - alert: WeaviateHighErrorRate
        expr: rate(weaviate_requests_total{status="error"}[5m]) / rate(weaviate_requests_total[5m]) > 0.05
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Weaviate error rate is high"
          description: "Error rate is {{ $value }} (threshold: 5%)"

      # Vector index issues
      - alert: WeaviateVectorIndexSlow
        expr: |
          rate(weaviate_vector_index_operations_duration_ms_sum{operation="search"}[5m]) / 
          rate(weaviate_vector_index_operations_duration_ms_count{operation="search"}[5m]) > 200
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Weaviate vector search is slow"
          description: "Average vector search duration is {{ $value }}ms (threshold: 200ms)"
```

### Enable Alerts in Prometheus

Update `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

# Load alert rules
rule_files:
  - "alerts.yml"

# Alert manager configuration (optional)
alerting:
  alertmanagers:
    - static_configs:
        - targets:
          # - alertmanager:9093

scrape_configs:
  # ... existing scrape configs ...
```

## 📈 Grafana Dashboard Panels

### Panel 1: Neo4j Database Size

```json
{
  "targets": [
    {
      "expr": "neo4j_database_store_size_total{database=\"datascience\"}"
    }
  ],
  "title": "Neo4j Database Size"
}
```

### Panel 2: Neo4j Transaction Rate

```json
{
  "targets": [
    {
      "expr": "rate(neo4j_transaction_active_read{database=\"datascience\"}[5m])",
      "legendFormat": "Read Transactions"
    },
    {
      "expr": "rate(neo4j_transaction_active_write{database=\"datascience\"}[5m])",
      "legendFormat": "Write Transactions"
    }
  ],
  "title": "Neo4j Active Transactions"
}
```

### Panel 3: Weaviate Query Latency

```json
{
  "targets": [
    {
      "expr": "histogram_quantile(0.95, rate(weaviate_requests_total_duration_ms_bucket[5m]))",
      "legendFormat": "p95"
    },
    {
      "expr": "histogram_quantile(0.99, rate(weaviate_requests_total_duration_ms_bucket[5m]))",
      "legendFormat": "p99"
    }
  ],
  "title": "Weaviate Query Latency"
}
```

### Panel 4: Combined Request Rate

```json
{
  "targets": [
    {
      "expr": "sum(rate(neo4j_transaction_committed_total[5m]))",
      "legendFormat": "Neo4j Transactions/s"
    },
    {
      "expr": "sum(rate(weaviate_requests_total[5m]))",
      "legendFormat": "Weaviate Requests/s"
    }
  ],
  "title": "System Request Rate"
}
```

## 🧪 Testing Metrics

### Test Neo4j Metrics

```bash
# Check if Neo4j metrics endpoint is accessible
curl http://localhost:2004/metrics

# Sample output should include:
# neo4j_database_node_count{database="datascience"} 1000
# neo4j_database_relationship_count{database="datascience"} 5000
```

### Test Weaviate Metrics

```bash
# Check Weaviate metrics endpoint
curl http://localhost:2112/metrics

# Sample output should include:
# weaviate_object_count_total{class_name="AcademicDocument"} 500
# weaviate_requests_total_duration_ms_bucket{le="100"} 1000
```

### Query Prometheus Directly

```bash
# Neo4j node count
curl 'http://localhost:9090/api/v1/query?query=neo4j_database_node_count'

# Weaviate object count
curl 'http://localhost:9090/api/v1/query?query=weaviate_object_count_total'

# Combined query
curl 'http://localhost:9090/api/v1/query?query=sum(weaviate_object_count_total)+sum(neo4j_database_node_count)'
```

## 🔍 Debugging

### Check Service Health

```bash
# Neo4j health
curl http://localhost:7474/

# Weaviate health
curl http://localhost:8080/v1/meta

# Prometheus health
curl http://localhost:9090/-/healthy

# Grafana health
curl http://localhost:3000/api/health
```

### View Prometheus Targets

```bash
# Check which targets are UP/DOWN
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
```

### Grafana Data Source Test

```bash
# Test Prometheus data source
curl -X POST \
  -H "Content-Type: application/json" \
  -d '{"type":"prometheus","url":"http://prometheus:9090","access":"proxy"}' \
  http://admin:admin@localhost:3000/api/datasources
```

## 📝 Port Summary

| Service              | Port     | Endpoint                      | Purpose               |
| -------------------- | -------- | ----------------------------- | --------------------- |
| Neo4j Browser        | 7474     | http://localhost:7474         | Graph UI              |
| Neo4j Bolt           | 7687     | bolt://localhost:7687         | Graph queries         |
| **Neo4j Metrics**    | **2004** | http://localhost:2004/metrics | **Prometheus scrape** |
| Weaviate API         | 8080     | http://localhost:8080         | Vector DB API         |
| Weaviate gRPC        | 50051    | grpc://localhost:50051        | High-perf queries     |
| **Weaviate Metrics** | **2112** | http://localhost:2112/metrics | **Prometheus scrape** |
| Prometheus           | 9090     | http://localhost:9090         | Metrics storage       |
| Grafana              | 3000     | http://localhost:3000         | Visualization         |
| Node Exporter        | 9100     | http://localhost:9100         | System metrics        |

## 🎯 Use Cases

### 1. Monitor Research Data Growth

```promql
# Track Penelitian nodes over time
neo4j_database_node_count{database="datascience",label="Penelitian"}

# Track academic documents in Weaviate
weaviate_object_count_total{class_name="AcademicDocument"}
```

### 2. Query Performance Analysis

```promql
# Compare Neo4j vs Weaviate query latency
histogram_quantile(0.95, rate(neo4j_cypher_query_execution_latency_millis_bucket[5m]))
vs
histogram_quantile(0.95, rate(weaviate_requests_total_duration_ms_bucket[5m]))
```

### 3. System Load Monitoring

```promql
# Total operations per second
sum(rate(neo4j_transaction_committed_total[5m])) +
sum(rate(weaviate_requests_total[5m]))
```

## 🔗 Resources

- [Neo4j Metrics Documentation](https://neo4j.com/docs/operations-manual/current/monitoring/metrics/)
- [Weaviate Monitoring Guide](https://weaviate.io/developers/weaviate/configuration/monitoring)
- [Prometheus Query Examples](https://prometheus.io/docs/prometheus/latest/querying/examples/)
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/best-practices/)

---

**Created for**: UNESA Knowledge Graph Project  
**Author**: Rizky Yanuarko  
**Date**: October 9, 2025
