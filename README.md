# Yunesa

Yunesa is an academic knowledge base for UNESA lecturer and publication data. The application combines structured academic ETL, knowledge graph enrichment, graph retrieval, vector retrieval, and a web/API interface for the final user-facing system.

## Architecture

The runtime stack is split by responsibility:

- `web`: Vue frontend.
- `api`: FastAPI application and knowledge retrieval endpoints.
- `worker`: backend asynchronous jobs.
- `postgres`: application and Airflow metadata persistence.
- `redis`: backend queue/cache dependency.
- `graph`: Neo4j academic knowledge graph.
- `milvus`, `etcd`, `minio`: vector storage runtime and object storage dependencies.
- `etl-worker`: immutable ETL execution image.
- `airflow-webserver`, `airflow-scheduler`: ETL orchestration for lecturer and paper pipelines.
- `tunnel`: Cloudflare Tunnel entrypoint for production HTTP access.

Production HTTP traffic should enter through Cloudflare Tunnel. The production compose file does not need public host ports for the frontend, API, or Airflow.

## Branch Workflow

- `dev` is the integration branch for active development.
- `master` is the release branch for code that is ready for production.
- GitHub Actions production deployment is triggered by pushes to `master` or manual dispatch.
- The EC2 deploy step always resets the server worktree to `origin/master` before rebuilding services.

A normal release path is:

```bash
git checkout dev
# develop and verify changes
git checkout master
git merge dev
git push origin master
```

## Local Development

Create local secrets first:

```bash
cp .env.example .env
```

Start the core application:

```bash
docker compose -f docker-compose.yml up -d --build
```

Start local ETL and Airflow as well:

```bash
docker compose -f docker-compose.yml --profile etl up -d --build
```

Local access points:

- Web: `http://localhost:5173`
- API: `http://localhost:5050`
- API docs: `http://localhost:5050/doc`
- Airflow: `http://localhost:8080`

## Production Deployment

Production deployment is defined by:

- `.github/workflows/deploy.yml`
- `docker-compose.prod.yml`
- `scripts/setup-server.sh`

The GitHub workflow generates `.env` and Cloudflare Tunnel runtime files from GitHub Secrets on EC2, then builds and starts:

```bash
docker compose -f docker-compose.prod.yml --profile etl up -d --build --remove-orphans
```

Production access points:

- Web: `https://app.tugasakhir.space`
- API: `https://api.tugasakhir.space`
- Airflow: `https://airflow.tugasakhir.space`

Keep these deployment files out of Git:

- `.env`
- `cloudflared/config.yaml`
- `cloudflared/credentials.json`
- SSH private keys and cloud credentials

## ETL Runtime

Airflow runs ETL tasks through `DockerOperator` using the `etl-worker` image. This keeps task execution reproducible and makes code changes take effect only after the ETL image is rebuilt and redeployed.

Development compose defaults are suitable for sample runs. Production compose defaults use incremental ETL behavior and Airflow scheduling for regular refreshes.

## Production Operations

Minimum production checks before a release:

1. Validate compose configuration.
2. Run ETL dispatch tests.
3. Confirm GitHub Secrets match `.env.example`.
4. Confirm Cloudflare Tunnel ingress points to `web-prod`, `api-prod`, and `airflow-webserver-prod`.
5. Confirm AWS Security Group does not expose direct frontend/API/Airflow ports when Tunnel is the official entrypoint.

Recommended infrastructure controls:

- EBS snapshot or backup policy before large deployment changes.
- CloudWatch alarms for EC2 health and resource pressure.
- Encrypted EBS volumes for persistent production storage.
- IAM roles or GitHub OIDC where possible instead of long-lived AWS keys.
