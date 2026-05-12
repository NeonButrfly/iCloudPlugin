# iCloud Index Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a current Codex/OpenAI-style local plugin backed by an on-prem Dockerized Linux service that reads iCloud Drive through Apple's private web surface, indexes metadata plus extracted text into Postgres, and returns relevant read-only search results and excerpts.

**Architecture:** The repo will contain two deliverables that ship together: a Python-based `icloud-index-service` stack for auth, crawl, extraction, and search, plus a thin repo-local Codex plugin that exposes tools through MCP and calls the service over a private authenticated API. The implementation is split so the fragile Apple session logic stays on the server while the plugin remains stateless and easy to install.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, psycopg, Postgres 16, Docker Compose, pytest, httpx, pydantic, pypdf, python-docx, openpyxl, markdown-it-py, MCP server config via repo-local plugin manifest.

---

## Planned File Structure

### Repository files

- Create: `C:\Code\iCloudPlugin\pyproject.toml`
- Create: `C:\Code\iCloudPlugin\docker-compose.yml`
- Create: `C:\Code\iCloudPlugin\.env.example`
- Create: `C:\Code\iCloudPlugin\README.md`
- Create: `C:\Code\iCloudPlugin\.agents\plugins\marketplace.json`

### Service package

- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\__init__.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\config.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\db.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\main.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\health.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\search.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\files.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\refresh.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\auth.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\base.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\file.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\extracted_content.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\sync_run.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\auth_session.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\job.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\schemas\search.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\schemas\file.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\schemas\refresh.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\auth_session_manager.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\icloud_web_client.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\crawler.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\extractor.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\search_service.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\job_runner.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\markdown_collection_service.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\categorization_service.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\text_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\pdf_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\docx_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\xlsx_parser.py`

### Migrations

- Create: `C:\Code\iCloudPlugin\alembic.ini`
- Create: `C:\Code\iCloudPlugin\migrations\env.py`
- Create: `C:\Code\iCloudPlugin\migrations\versions\0001_initial_schema.py`
- Create: `C:\Code\iCloudPlugin\migrations\versions\0002_search_indexes.py`

### Worker entrypoint

- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\worker.py`

### Plugin package

- Create: `C:\Code\iCloudPlugin\plugins\icloud-drive\.codex-plugin\plugin.json`
- Create: `C:\Code\iCloudPlugin\plugins\icloud-drive\.mcp.json`
- Create: `C:\Code\iCloudPlugin\plugins\icloud-drive\README.md`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\__init__.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\server.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\service_client.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\tool_schemas.py`

### Tests

- Create: `C:\Code\iCloudPlugin\tests\conftest.py`
- Create: `C:\Code\iCloudPlugin\tests\test_config.py`
- Create: `C:\Code\iCloudPlugin\tests\test_health_api.py`
- Create: `C:\Code\iCloudPlugin\tests\test_models.py`
- Create: `C:\Code\iCloudPlugin\tests\test_search_api.py`
- Create: `C:\Code\iCloudPlugin\tests\test_auth_session_manager.py`
- Create: `C:\Code\iCloudPlugin\tests\test_crawler.py`
- Create: `C:\Code\iCloudPlugin\tests\test_extractor.py`
- Create: `C:\Code\iCloudPlugin\tests\test_plugin_client.py`
- Create: `C:\Code\iCloudPlugin\tests\test_degraded_mode.py`
- Create: `C:\Code\iCloudPlugin\tests\test_markdown_collection_service.py`
- Create: `C:\Code\iCloudPlugin\tests\test_categorization_service.py`

## Task 1: Bootstrap the repo, runtime, and plugin scaffold

**Files:**
- Create: `C:\Code\iCloudPlugin\pyproject.toml`
- Create: `C:\Code\iCloudPlugin\docker-compose.yml`
- Create: `C:\Code\iCloudPlugin\.env.example`
- Create: `C:\Code\iCloudPlugin\README.md`
- Create: `C:\Code\iCloudPlugin\.agents\plugins\marketplace.json`
- Create: `C:\Code\iCloudPlugin\plugins\icloud-drive\.codex-plugin\plugin.json`
- Create: `C:\Code\iCloudPlugin\plugins\icloud-drive\.mcp.json`
- Test: `C:\Code\iCloudPlugin\tests\test_health_api.py`

- [ ] **Step 1: Write the failing health test**

```python
from fastapi.testclient import TestClient

from icloud_index_service.main import app


def test_health_endpoint_reports_ok():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'icloud_index_service'`

- [ ] **Step 3: Write minimal project scaffold**

```toml
[project]
name = "icloud-index-plugin"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "sqlalchemy>=2.0.36",
  "psycopg[binary]>=3.2.3",
  "alembic>=1.14.0",
  "httpx>=0.28.0",
  "pydantic>=2.10.0",
  "python-docx>=1.1.2",
  "openpyxl>=3.1.5",
  "pypdf>=5.1.0",
  "pytest>=8.3.3"
]

[tool.pytest.ini_options]
pythonpath = ["src"]
```
```

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```
```

```json
{
  "name": "icloud-drive",
  "version": "0.1.0",
  "description": "Search and retrieve iCloud Drive content through a private on-prem index service.",
  "author": {
    "name": "Keifm",
    "email": "keifm@local.invalid",
    "url": "https://github.com/NeonButrfly/iCloudPlugin"
  },
  "repository": "https://github.com/NeonButrfly/iCloudPlugin",
  "license": "MIT",
  "mcpServers": "./.mcp.json",
  "interface": {
    "displayName": "iCloud Drive",
    "shortDescription": "Search your indexed iCloud Drive",
    "longDescription": "Query a private on-prem iCloud indexing service for relevant files and excerpts.",
    "developerName": "Keifm",
    "category": "Productivity",
    "capabilities": ["Interactive"]
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_health_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml docker-compose.yml .env.example README.md .agents/plugins/marketplace.json plugins/icloud-drive src/icloud_index_service tests/test_health_api.py
git commit -m "chore: scaffold service and plugin layout"
```

## Task 2: Add configuration, Docker Compose, and Postgres connectivity

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\config.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\db.py`
- Modify: `C:\Code\iCloudPlugin\docker-compose.yml`
- Modify: `C:\Code\iCloudPlugin\.env.example`
- Test: `C:\Code\iCloudPlugin\tests\conftest.py`

- [ ] **Step 1: Write the failing config test**

```python
from icloud_index_service.config import Settings


def test_settings_build_database_url():
    settings = Settings(
        postgres_user="icloud",
        postgres_password="secret",
        postgres_host="db",
        postgres_port=5432,
        postgres_db="icloud_index"
    )

    assert settings.database_url == "postgresql+psycopg://icloud:secret@db:5432/icloud_index"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError` or missing `Settings`

- [ ] **Step 3: Write minimal config and Compose setup**

```python
from pydantic import BaseModel, computed_field


class Settings(BaseModel):
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int
    postgres_db: str

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
```
```

```yaml
services:
  postgres:
    image: postgres:16
    env_file: .env
    ports:
      - "5432:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data

  service:
    build: .
    env_file: .env
    command: uvicorn icloud_index_service.main:app --host 0.0.0.0 --port 8080
    depends_on:
      - postgres
    ports:
      - "8080:8080"

volumes:
  postgres-data:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/config.py src/icloud_index_service/db.py docker-compose.yml .env.example tests/test_config.py
git commit -m "feat: add service configuration and postgres wiring"
```

## Task 3: Add schema models and migrations

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\base.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\file.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\extracted_content.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\sync_run.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\auth_session.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\models\job.py`
- Create: `C:\Code\iCloudPlugin\alembic.ini`
- Create: `C:\Code\iCloudPlugin\migrations\env.py`
- Create: `C:\Code\iCloudPlugin\migrations\versions\0001_initial_schema.py`
- Test: `C:\Code\iCloudPlugin\tests\test_models.py`

- [ ] **Step 1: Write the failing model test**

```python
from icloud_index_service.models.file import FileRecord


def test_file_record_defaults_to_active():
    record = FileRecord(
        external_id="file-123",
        name="notes.md",
        path="/Work/notes.md",
        mime_type="text/markdown"
    )

    assert record.is_deleted is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ImportError` or missing model

- [ ] **Step 3: Write minimal SQLAlchemy models and migration**

```python
from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FileRecord(Base):
    __tablename__ = "files"

    external_id: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(String(255))
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
```
```

```python
def upgrade() -> None:
    op.create_table(
        "files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=255), nullable=False, unique=True),
        sa.Column("name", sa.String(length=512), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false())
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/models alembic.ini migrations tests/test_models.py
git commit -m "feat: add database schema and initial migration"
```

## Task 4: Add auth session management and browser-assisted bootstrap endpoints

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\auth_session_manager.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\auth.py`
- Modify: `C:\Code\iCloudPlugin\src\icloud_index_service\main.py`
- Test: `C:\Code\iCloudPlugin\tests\test_auth_session_manager.py`

- [ ] **Step 1: Write the failing auth session test**

```python
from icloud_index_service.services.auth_session_manager import redact_cookie_value


def test_redact_cookie_value_masks_interior_characters():
    assert redact_cookie_value("abcdef123456") == "ab********56"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_session_manager.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal auth session manager**

```python
def redact_cookie_value(raw: str) -> str:
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"
```
```

```python
from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status() -> dict[str, str]:
    return {"status": "needs-bootstrap"}
```

```python
from fastapi import FastAPI

from icloud_index_service.api.auth import router as auth_router

app = FastAPI()
app.include_router(auth_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth_session_manager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/auth_session_manager.py src/icloud_index_service/api/auth.py tests/test_auth_session_manager.py
git commit -m "feat: add auth session bootstrap primitives"
```

## Task 5: Add iCloud metadata crawl and refresh jobs

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\icloud_web_client.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\crawler.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\job_runner.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\refresh.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\worker.py`
- Modify: `C:\Code\iCloudPlugin\src\icloud_index_service\main.py`
- Modify: `C:\Code\iCloudPlugin\docker-compose.yml`
- Test: `C:\Code\iCloudPlugin\tests\test_crawler.py`

- [ ] **Step 1: Write the failing crawler test**

```python
from icloud_index_service.services.crawler import normalize_remote_item


def test_normalize_remote_item_maps_expected_fields():
    raw = {
        "id": "abc",
        "name": "Notes",
        "path": "/Work/Notes.md",
        "extension": "md",
        "size": 128
    }

    normalized = normalize_remote_item(raw)

    assert normalized["external_id"] == "abc"
    assert normalized["path"] == "/Work/Notes.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal crawler path**

```python
def normalize_remote_item(raw: dict) -> dict:
    return {
        "external_id": raw["id"],
        "name": raw["name"],
        "path": raw["path"],
        "extension": raw.get("extension"),
        "size_bytes": raw.get("size", 0)
    }
```
```

```python
from fastapi import APIRouter

router = APIRouter(prefix="/refresh", tags=["refresh"])


@router.post("")
def request_refresh() -> dict[str, str]:
    return {"status": "queued"}
```

```python
from fastapi import FastAPI

from icloud_index_service.api.refresh import router as refresh_router

app = FastAPI()
app.include_router(refresh_router)
```

```yaml
  worker:
    build: .
    env_file: .env
    command: python -m icloud_index_service.worker
    depends_on:
      - postgres
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_crawler.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/icloud_web_client.py src/icloud_index_service/services/crawler.py src/icloud_index_service/services/job_runner.py src/icloud_index_service/worker.py src/icloud_index_service/api/refresh.py src/icloud_index_service/main.py docker-compose.yml tests/test_crawler.py
git commit -m "feat: add metadata crawl and refresh job flow"
```

## Task 6: Add extraction pipeline and search API

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\text_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\pdf_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\docx_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\parsers\xlsx_parser.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\extractor.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\search_service.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\search.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\api\files.py`
- Modify: `C:\Code\iCloudPlugin\src\icloud_index_service\main.py`
- Test: `C:\Code\iCloudPlugin\tests\test_extractor.py`
- Test: `C:\Code\iCloudPlugin\tests\test_search_api.py`

- [ ] **Step 1: Write the failing extraction test**

```python
from icloud_index_service.services.extractor import summarize_text


def test_summarize_text_truncates_to_requested_length():
    source = "alpha beta gamma delta epsilon"
    assert summarize_text(source, 12) == "alpha beta g"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extractor.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal extraction and search implementation**

```python
def summarize_text(text: str, limit: int) -> str:
    return text[:limit]
```
```

```python
from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(query: str, limit: int = 10) -> dict:
    return {
        "query": query,
        "limit": limit,
        "results": []
    }
```

```python
from fastapi import FastAPI

from icloud_index_service.api.files import router as files_router
from icloud_index_service.api.search import router as search_router

app = FastAPI()
app.include_router(search_router)
app.include_router(files_router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_extractor.py tests/test_search_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/parsers src/icloud_index_service/services/extractor.py src/icloud_index_service/services/search_service.py src/icloud_index_service/api/search.py src/icloud_index_service/api/files.py src/icloud_index_service/main.py tests/test_extractor.py tests/test_search_api.py
git commit -m "feat: add extraction pipeline and search endpoints"
```

## Task 7: Add the thin MCP plugin client

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\service_client.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\tool_schemas.py`
- Create: `C:\Code\iCloudPlugin\src\icloud_plugin_mcp\server.py`
- Modify: `C:\Code\iCloudPlugin\plugins\icloud-drive\.mcp.json`
- Modify: `C:\Code\iCloudPlugin\plugins\icloud-drive\README.md`
- Test: `C:\Code\iCloudPlugin\tests\test_plugin_client.py`

- [ ] **Step 1: Write the failing plugin client test**

```python
from icloud_plugin_mcp.service_client import build_search_params


def test_build_search_params_omits_empty_path_scope():
    params = build_search_params(query="budget", limit=5, path_scope=None)
    assert params == {"query": "budget", "limit": 5}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_plugin_client.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal MCP client**

```python
def build_search_params(query: str, limit: int, path_scope: str | None) -> dict:
    params = {"query": query, "limit": limit}
    if path_scope:
        params["path_scope"] = path_scope
    return params
```
```

```json
{
  "mcpServers": {
    "icloud-drive": {
      "command": "python",
      "args": ["-m", "icloud_plugin_mcp.server"]
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_plugin_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_plugin_mcp plugins/icloud-drive/.mcp.json plugins/icloud-drive/README.md tests/test_plugin_client.py
git commit -m "feat: add MCP plugin proxy for iCloud search"
```

## Task 8: Add end-to-end docs, Compose validation, and safe degraded-mode behavior

**Files:**
- Modify: `C:\Code\iCloudPlugin\README.md`
- Create: `C:\Code\iCloudPlugin\docs\operations.md`
- Create: `C:\Code\iCloudPlugin\tests\test_degraded_mode.py`

- [ ] **Step 1: Write the failing degraded-mode test**

```python
from icloud_index_service.services.search_service import build_auth_needed_response


def test_build_auth_needed_response_preserves_cached_results_flag():
    payload = build_auth_needed_response(has_cached_results=True)
    assert payload["auth_status"] == "needs-bootstrap"
    assert payload["has_cached_results"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_degraded_mode.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal degraded-mode response and docs**

```python
def build_auth_needed_response(has_cached_results: bool) -> dict:
    return {
        "auth_status": "needs-bootstrap",
        "has_cached_results": has_cached_results
    }
```
```

```markdown
# Operations

## Start the stack

`docker compose up --build`

## Bootstrap Apple session

1. Open the auth bootstrap URL exposed by the service.
2. Complete the Apple web sign-in flow.
3. Confirm `/auth/status` reports a valid session.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_degraded_mode.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add README.md docs/operations.md src/icloud_index_service/services/search_service.py tests/test_degraded_mode.py
git commit -m "docs: add operations guide and degraded-mode contract"
```

## Task 9: Plan and add AI-assisted categorization upgrade hooks

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\categorization_service.py`
- Create: `C:\Code\iCloudPlugin\tests\test_categorization_service.py`
- Modify: `C:\Code\iCloudPlugin\README.md`

- [ ] **Step 1: Write the failing categorization policy test**

```python
from icloud_index_service.services.categorization_service import build_category_prompt


def test_build_category_prompt_mentions_path_and_excerpt():
    prompt = build_category_prompt(path="/Finance/Budget.md", excerpt="Quarterly spend")
    assert "/Finance/Budget.md" in prompt
    assert "Quarterly spend" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_categorization_service.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal categorization upgrade hook**

```python
def build_category_prompt(path: str, excerpt: str) -> str:
    return (
        "Classify this file into a stable knowledge category.\n"
        f"Path: {path}\n"
        f"Excerpt: {excerpt}\n"
    )
```

This task must stop at upgrade hooks, schema planning, and prompt contracts. Do not auto-move files in the initial rollout. Persist only suggested categories, confidence, and reasoning.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_categorization_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/categorization_service.py tests/test_categorization_service.py README.md
git commit -m "feat: add AI categorization planning hooks"
```

## Task 10: Plan and add markdown collection generation upgrade hooks

**Files:**
- Create: `C:\Code\iCloudPlugin\src\icloud_index_service\services\markdown_collection_service.py`
- Create: `C:\Code\iCloudPlugin\tests\test_markdown_collection_service.py`
- Modify: `C:\Code\iCloudPlugin\README.md`

- [ ] **Step 1: Write the failing markdown collection test**

```python
from icloud_index_service.services.markdown_collection_service import build_collection_header


def test_build_collection_header_uses_collection_title():
    header = build_collection_header("Project Atlas")
    assert header == "# Project Atlas\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_markdown_collection_service.py -v`
Expected: FAIL with missing function

- [ ] **Step 3: Write minimal markdown synthesis hook**

```python
def build_collection_header(title: str) -> str:
    return f"# {title}\n"
```

This task should define the upgrade path for generating markdown collections that aggregate:
- grouped file summaries
- canonical links back to indexed source files
- timestamps and category labels
- AI-authored overview sections with clear provenance

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_markdown_collection_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/markdown_collection_service.py tests/test_markdown_collection_service.py README.md
git commit -m "feat: add markdown collection generation hooks"
```

## Task 11: Final integration and validation

**Files:**
- Modify: `C:\Code\iCloudPlugin\README.md`
- Modify: `C:\Code\iCloudPlugin\docker-compose.yml`
- Test: `C:\Code\iCloudPlugin\tests\test_health_api.py`
- Test: `C:\Code\iCloudPlugin\tests\test_search_api.py`
- Test: `C:\Code\iCloudPlugin\tests\test_plugin_client.py`

- [ ] **Step 1: Run the focused unit suite**

Run: `python -m pytest tests/test_health_api.py tests/test_search_api.py tests/test_auth_session_manager.py tests/test_crawler.py tests/test_extractor.py tests/test_plugin_client.py -v`
Expected: PASS

- [ ] **Step 2: Run the upgrade-hook tests**

Run: `python -m pytest tests/test_categorization_service.py tests/test_markdown_collection_service.py -v`
Expected: PASS

- [ ] **Step 3: Run Compose validation**

Run: `docker compose config`
Expected: exits `0` and prints a resolved stack for `postgres`, `service`, and `worker`

- [ ] **Step 4: Run stack smoke test**

Run: `docker compose up --build -d`
Expected: containers start and `GET /health` returns `{"status":"ok"}`

- [ ] **Step 5: Commit**

```bash
git add README.md docker-compose.yml
git commit -m "test: validate iCloud index plugin end-to-end scaffold"
```

## Future Upgrade Notes

- AI categorization should begin as a suggestion system, not an autonomous mover.
- Markdown collections should preserve provenance by linking every generated section back to source file ids and paths.
- If later semantic retrieval is needed, add it as a reranking enhancement after the Postgres-first search path is stable.
- If remote access expands beyond one trusted user, introduce stronger service auth, per-user scoping, and secret rotation before opening the network boundary.
