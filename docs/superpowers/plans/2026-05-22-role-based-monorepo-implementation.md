# Role-Based Monorepo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `iCloudPlugin` into the backbone monorepo for sync, indexing, classifier, API, and MCP roles while preserving separate-host deployment and cleaning up vault/note naming.

**Architecture:** Keep runtime behavior stable while introducing a role-based monorepo layout inside the existing repo. Move classifier code into `apps/classifier`, create app/package boundaries for role ownership, keep backward-compatible entrypoints during the transition, and switch new note output to cleaner human-readable filenames with collision-safe suffixes and metadata-backed hashes.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy, pytest, Docker Compose, filesystem-backed vault generation

---

### Task 1: Create the monorepo skeleton without breaking current imports

**Files:**
- Create: `C:\Code\iCloudPlugin\apps\cloudsync\__init__.py`
- Create: `C:\Code\iCloudPlugin\apps\cloudsync\worker.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\__init__.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\api_server.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\note_writer.py`
- Create: `C:\Code\iCloudPlugin\apps\api\__init__.py`
- Create: `C:\Code\iCloudPlugin\apps\api\main.py`
- Create: `C:\Code\iCloudPlugin\apps\mcp\__init__.py`
- Create: `C:\Code\iCloudPlugin\apps\mcp\server.py`
- Create: `C:\Code\iCloudPlugin\packages\contracts\__init__.py`
- Create: `C:\Code\iCloudPlugin\packages\storage\__init__.py`
- Create: `C:\Code\iCloudPlugin\packages\vault\__init__.py`
- Create: `C:\Code\iCloudPlugin\packages\classification\__init__.py`
- Create: `C:\Code\iCloudPlugin\packages\runtime\__init__.py`
- Modify: `C:\Code\iCloudPlugin\pyproject.toml`
- Test: `C:\Code\iCloudPlugin\tests\test_health_api.py`

- [ ] **Step 1: Write a failing structure smoke test**

```python
def test_role_based_monorepo_entrypoints_exist():
    repo_root = Path(__file__).resolve().parents[1]
    expected_paths = [
        repo_root / "apps" / "cloudsync" / "worker.py",
        repo_root / "apps" / "classifier" / "api_server.py",
        repo_root / "apps" / "api" / "main.py",
        repo_root / "apps" / "mcp" / "server.py",
        repo_root / "packages" / "vault" / "__init__.py",
    ]
    assert all(path.exists() for path in expected_paths)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health_api.py::test_role_based_monorepo_entrypoints_exist -q`

Expected: `FAIL` because the new `apps/` and `packages/` layout does not exist yet.

- [ ] **Step 3: Add the skeleton files and compatibility wrappers**

```python
# apps/cloudsync/worker.py
from icloud_index_service.worker import main

if __name__ == "__main__":
    main()
```

```python
# apps/api/main.py
from icloud_index_service.main import app
```

```python
# apps/mcp/server.py
from icloud_plugin_mcp.server import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Extend package discovery**

```toml
[tool.pytest.ini_options]
pythonpath = ["src", "."]
```

- [ ] **Step 5: Run the smoke test again**

Run: `python -m pytest tests/test_health_api.py::test_role_based_monorepo_entrypoints_exist -q`

Expected: `PASS`

### Task 2: Import the classifier into the backbone repo with role-local paths

**Files:**
- Create: `C:\Code\iCloudPlugin\apps\classifier\category_manager.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\hybrid_runtime.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\retrain_hybrid_model.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\taxonomy_router\predict_taxonomy.py`
- Create: `C:\Code\iCloudPlugin\apps\classifier\taxonomy_router\train_taxonomy_router.py`
- Create: `C:\Code\iCloudPlugin\config\categories.local.txt`
- Create: `C:\Code\iCloudPlugin\config\category-groups.json`
- Create: `C:\Code\iCloudPlugin\config\heuristic-rules.json`
- Create: `C:\Code\iCloudPlugin\config\hybrid-gating.json`
- Create: `C:\Code\iCloudPlugin\config\taxonomy-sources.json`
- Create: `C:\Code\iCloudPlugin\tests\test_classifier_role_imports.py`

- [ ] **Step 1: Write a failing import test**

```python
def test_classifier_role_can_import_api_server():
    module = import_module("apps.classifier.api_server")
    assert hasattr(module, "APP")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_classifier_role_imports.py -q`

Expected: `FAIL` because the classifier files are not in the monorepo yet.

- [ ] **Step 3: Copy the classifier runtime into `apps/classifier`**
- [ ] Preserve behavior first. Do not redesign internals in this step.
- [ ] Update imports so the role can resolve its local modules under `apps.classifier`.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest tests/test_classifier_role_imports.py -q`

Expected: `PASS`

### Task 3: Move shared vault and naming logic into role-neutral packages

**Files:**
- Create: `C:\Code\iCloudPlugin\packages\vault\naming.py`
- Create: `C:\Code\iCloudPlugin\packages\vault\frontmatter.py`
- Create: `C:\Code\iCloudPlugin\packages\storage\hashing.py`
- Create: `C:\Code\iCloudPlugin\tests\test_vault_naming.py`
- Modify: `C:\Code\iCloudPlugin\apps\classifier\note_writer.py`
- Modify: `C:\Code\iCloudPlugin\src\icloud_index_service\services\vault_reconciliation.py`

- [ ] **Step 1: Write failing naming tests**

```python
def test_default_note_name_omits_visible_hash():
    note_name = build_note_filename(title="Budget Draft", primary_label="financial")
    assert note_name == "Budget Draft - financial.md"

def test_duplicate_note_names_use_collision_suffix():
    existing = {"Budget Draft - financial.md"}
    note_name = build_note_filename(
        title="Budget Draft",
        primary_label="financial",
        existing_names=existing,
    )
    assert note_name == "Budget Draft - financial (2).md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_vault_naming.py -q`

Expected: `FAIL` because the shared naming module does not exist yet.

- [ ] **Step 3: Implement shared naming and frontmatter helpers**

```python
def build_note_filename(title: str, primary_label: str, existing_names: set[str] | None = None) -> str:
    base = f"{clean_visible_title(title)} - {primary_label}.md"
    if not existing_names or base not in existing_names:
        return base
    counter = 2
    while True:
        candidate = f"{clean_visible_title(title)} - {primary_label} ({counter}).md"
        if candidate not in existing_names:
            return candidate
        counter += 1
```

- [ ] **Step 4: Update the classifier note writer to use the shared helpers**
- [ ] Keep hashes in frontmatter, not in the visible default note name.
- [ ] Keep extracted markdown and compatibility attachment naming human-readable.

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_vault_naming.py tests/test_vault_reconciliation.py -q`

Expected: `PASS`

### Task 4: Rename the vault concept to `document-vault` in operator-facing surfaces

**Files:**
- Modify: `C:\Code\iCloudPlugin\README.md`
- Modify: `C:\Code\iCloudPlugin\docs\operations.md`
- Modify: `C:\Code\iCloudPlugin\docker-compose.yml`
- Create: `C:\Code\iCloudPlugin\deploy\roles\cloudsync\README.md`
- Create: `C:\Code\iCloudPlugin\deploy\roles\classifier\README.md`
- Create: `C:\Code\iCloudPlugin\deploy\roles\combined\README.md`
- Test: `C:\Code\iCloudPlugin\tests\test_health_api.py`

- [ ] **Step 1: Write a failing config/documentation expectation test**

```python
def test_compose_defaults_classifier_vault_root_to_document_vault():
    config = load_compose_json()
    worker_env = config["services"]["classification-worker"]["environment"]
    assert worker_env["CLASSIFIER_VAULT_ROOT"] == "/srv/cloud-vault/document-vault"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health_api.py::test_compose_defaults_classifier_vault_root_to_document_vault -q`

Expected: `FAIL` because the current default still points at `local-doc-classifier-vault`.

- [ ] **Step 3: Update operator-facing naming**
- [ ] Change default deploy examples and docs to `document-vault`.
- [ ] Preserve runtime overrides so existing hosts can migrate safely.

- [ ] **Step 4: Add role deployment docs**
- [ ] Document:
  - required mounts
  - required environment variables
  - which host can run which role

- [ ] **Step 5: Run focused tests**

Run: `python -m pytest tests/test_health_api.py -q`

Expected: `PASS`

### Task 5: Validate the merged repo while preserving separate-host deployability

**Files:**
- Create: `C:\Code\iCloudPlugin\tests\test_role_deploy_layout.py`
- Modify as needed: `C:\Code\iCloudPlugin\docker-compose.yml`
- Modify as needed: `C:\Code\iCloudPlugin\pyproject.toml`

- [ ] **Step 1: Write a failing deploy-layout test**

```python
def test_role_docs_exist_for_cloudsync_classifier_and_combined():
    repo_root = Path(__file__).resolve().parents[1]
    expected = [
        repo_root / "deploy" / "roles" / "cloudsync" / "README.md",
        repo_root / "deploy" / "roles" / "classifier" / "README.md",
        repo_root / "deploy" / "roles" / "combined" / "README.md",
    ]
    assert all(path.exists() for path in expected)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_role_deploy_layout.py -q`

Expected: `FAIL`

- [ ] **Step 3: Implement role deployment documentation and any missing config glue**

- [ ] **Step 4: Run the integration-focused suite**

Run: `python -m pytest tests/test_health_api.py tests/test_classification_submission.py tests/test_vault_reconciliation.py tests/test_classifier_role_imports.py tests/test_vault_naming.py tests/test_role_deploy_layout.py -q`

Expected: `PASS`

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`

Expected: `PASS`
