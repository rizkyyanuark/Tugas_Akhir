# Neo4j Monitoring Setup

## Overview

This configuration sets up monitoring for Neo4j database using Prometheus, Grafana, and other monitoring tools.

## Services

### Neo4j Database

- **Image**: neo4j:5.24-community
- **Ports**:
  - 7474 (Neo4j Browser)
  - 7687 (Bolt protocol)
- **Credentials**: neo4j/rizkyyk123
- **Default Database**: datascience
- **Plugins**: Graph Data Science (GDS), APOC

### Monitoring Stack

- **Prometheus**: Metrics collection
- **Grafana**: Visualization dashboard
- **Node Exporter**: System metrics
- **cAdvisor**: Container metrics

## Quick Start

1. **Start the services:**

   ```bash
   docker-compose up -d
   ```

2. **Access Neo4j Browser:**

   - URL: http://localhost:7474
   - Username: neo4j
   - Password: rizkyyk123

3. **Access Grafana:**

   - URL: http://localhost:3000
   - Username: admin
   - Password: admin

4. **Access Prometheus:**
   - URL: http://localhost:9090

## Neo4j Configuration

### Environment Variables

- `NEO4J_AUTH`: neo4j/rizkyyk123
- `NEO4J_PLUGINS`: ["graph-data-science"]
- `NEO4J_dbms_default_database`: datascience

### Volumes

- `neo4j_data`: Database files
- `neo4j_logs`: Log files
- `neo4j_plugins`: Plugin files
- `neo4j_import`: Import directory

## Monitoring Metrics

Neo4j exposes metrics on port 7474 at the `/metrics` endpoint. Key metrics include:

- Database connections
- Query performance
- Memory usage
- Transaction statistics
- GDS algorithm metrics

## Health Check

The Neo4j service includes a health check that:

- Runs every 30 seconds
- Times out after 10 seconds
- Retries 5 times before marking unhealthy
- Uses cypher-shell to verify connectivity

## Troubleshooting

### Common Issues

1. **Connection Refused**: Ensure Neo4j is fully started (check logs)
2. **Authentication Failed**: Verify credentials in environment variables
3. **Plugin Errors**: Check if GDS plugin is properly loaded
4. **Memory Issues**: Adjust container memory limits if needed

### Logs

```bash
# View Neo4j logs
docker-compose logs neo4j

# Follow real-time logs
docker-compose logs -f neo4j
```

### Cypher Shell Access

```bash
# Connect to Neo4j from container
docker-compose exec neo4j cypher-shell -u neo4j -p rizkyyk123
```
