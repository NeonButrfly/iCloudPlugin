# iCloud Index Plugin

This repository contains the early scaffold for a private iCloud Drive indexing stack and its companion Codex plugin.

## Current state

Task 1 wires up:

- a minimal FastAPI service with `/health`
- Python project metadata and pytest import path setup
- a starter Docker Compose stack shape for `service` and `postgres` that can boot from a fresh checkout using default values
- a repo-local plugin manifest, MCP config, and inline Task 1 MCP stub entrypoint

Later tasks add database wiring, Apple session bootstrap, crawling, extraction, and the MCP server implementation.

## Baseline runtime wiring

- `docker compose up --build` works without creating `.env`
- copy `.env.example` to `.env` only if you want to override the default ports or credentials
- the plugin's MCP entrypoint is an inline placeholder stub for Task 1, not the full Task 7 server

## Local test

```bash
python -m pytest tests/test_health_api.py -v
```
