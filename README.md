# iCloud Index Plugin

This repository contains the early scaffold for a private iCloud Drive indexing stack and its companion Codex plugin.

## Current state

Task 1 wires up:

- a minimal FastAPI service with `/health`
- Python project metadata and pytest import path setup
- a starter Docker Compose stack shape for `service` and `postgres`
- a repo-local plugin manifest, MCP config, and marketplace entry

Later tasks add database wiring, Apple session bootstrap, crawling, extraction, and the MCP server implementation.

## Local test

```bash
python -m pytest tests/test_health_api.py -v
```
