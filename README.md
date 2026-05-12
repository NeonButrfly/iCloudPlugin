# iCloud Index Plugin

This repository contains the early scaffold for a private iCloud Drive indexing stack and its companion Codex plugin.

## Current state

Task 1 and Task 2 currently wire up:

- a minimal FastAPI service with `/health`
- Python project metadata and pytest import path setup
- service configuration that builds a Postgres SQLAlchemy DSN from environment values
- cached database engine/session wiring plus a startup validation step that attempts a real database connection before `uvicorn` starts
- a Docker Compose stack for `service` and `postgres`, including a Postgres healthcheck so the API waits for database readiness before startup
- a repo-local plugin manifest, MCP config, and inline Task 1 MCP stub entrypoint

Later tasks add database wiring, Apple session bootstrap, crawling, extraction, and the MCP server implementation.

## Baseline runtime wiring

- `docker compose up --build` works without creating `.env`
- copy `.env.example` to `.env` only if you want to override the default ports or credentials
- use `POSTGRES_PUBLISHED_PORT` to change the host-facing database port without changing the service's internal Postgres connection on `5432`
- the service container validates DB connectivity with `SELECT 1` before serving HTTP
- the plugin's MCP entrypoint is an inline placeholder stub for Task 1, not the full Task 7 server

## Local test

```bash
python -m pytest tests/test_health_api.py tests/test_config.py -v
```
