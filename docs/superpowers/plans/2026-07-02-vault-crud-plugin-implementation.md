# Vault CRUD Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add origin-first reversible CRUD and restore support for `google1`, `google2`, `icloud`, and structured `document_vault` writes, while hiding `_`-prefixed directories from normal plugin discovery and importing legacy quarantine/dedupe state into `_CHANGES_BACKUP`.

**Architecture:** Build one backend file-operations service in the origin app that owns namespace resolution, `_`-directory policy, `_CHANGES_BACKUP` change sets, delete-as-move, restore, and structured Obsidian note creation. Then expose thin wrappers through the local MCP bridge, Cloudflare remote MCP Worker, plugin metadata, and ChatGPT submission descriptors.

**Tech Stack:** FastAPI, SQLAlchemy, Python services/tests, existing Obsidian note writer in `apps/classifier/classify_to_obsidian.py`, FastMCP, Cloudflare Worker TypeScript, Vitest, GitHub issue tracking.

---

### Task 1: Build Namespace Resolution And Hidden-Directory Policy

**Files:**
- Create: `src/icloud_index_service/services/file_mutation_service.py`
- Modify: `src/icloud_index_service/services/file_access_service.py`
- Modify: `src/icloud_index_service/services/search_service.py`
- Modify: `tests/test_search_api.py`
- Create: `tests/test_file_mutation_service.py`

- [ ] **Step 1: Write the failing namespace and hidden-directory tests**

```python
from pathlib import Path

from icloud_index_service.services.file_mutation_service import (
    FileNamespace,
    FileMutationPolicyError,
    resolve_namespace_root,
    resolve_live_path,
    is_hidden_internal_path,
)


def test_resolve_namespace_root_maps_document_vault_to_runtime_mount(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    vault_root = tmp_path / "cloud-vault" / "document-vault"
    mirror_root.mkdir(parents=True)
    vault_root.mkdir(parents=True)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    assert resolve_namespace_root(FileNamespace.DOCUMENT_VAULT) == vault_root.resolve()


def test_hidden_internal_path_blocks_normal_reads(tmp_path: Path):
    namespace_root = tmp_path / "google1"
    hidden_file = namespace_root / "_CHANGES_BACKUP" / "change-set-1" / "meta.json"
    hidden_file.parent.mkdir(parents=True)
    hidden_file.write_text("{}", encoding="utf-8")

    assert is_hidden_internal_path(hidden_file, namespace_root=namespace_root) is True


def test_resolve_live_path_rejects_underscore_paths_for_normal_access(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    google_root = mirror_root / "google1"
    google_root.mkdir(parents=True)
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    try:
        resolve_live_path(
            namespace=FileNamespace.GOOGLE1,
            relative_path="_CHANGES_BACKUP/secret.txt",
            allow_internal=False,
        )
    except FileMutationPolicyError as exc:
        assert "underscore-prefixed" in str(exc)
    else:
        raise AssertionError("Expected underscore-prefixed path to be rejected")
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_file_mutation_service.py -v`
Expected: FAIL with `ModuleNotFoundError` or missing symbols from `file_mutation_service.py`

- [ ] **Step 3: Add the minimal namespace and policy implementation**

```python
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path


class FileMutationPolicyError(RuntimeError):
    pass


class FileNamespace(str, Enum):
    GOOGLE1 = "google1"
    GOOGLE2 = "google2"
    ICLOUD = "icloud"
    DOCUMENT_VAULT = "document_vault"


def resolve_namespace_root(namespace: FileNamespace) -> Path:
    mirror_root = Path((os.getenv("ICLOUD_MIRROR_ROOT") or "").strip()).resolve()
    vault_root = Path((os.getenv("CLASSIFIER_VAULT_ROOT") or "").strip()).resolve()
    if namespace == FileNamespace.DOCUMENT_VAULT:
        return vault_root
    return mirror_root / namespace.value


def is_hidden_internal_path(path: Path, *, namespace_root: Path) -> bool:
    relative = path.resolve().relative_to(namespace_root.resolve())
    return any(part.startswith("_") for part in relative.parts)


def resolve_live_path(
    *,
    namespace: FileNamespace,
    relative_path: str,
    allow_internal: bool,
) -> Path:
    namespace_root = resolve_namespace_root(namespace)
    candidate = (namespace_root / relative_path).resolve()
    if namespace_root.resolve() not in (candidate, *candidate.parents):
        raise FileMutationPolicyError("Resolved path escapes namespace root.")
    if not allow_internal and is_hidden_internal_path(candidate, namespace_root=namespace_root):
        raise FileMutationPolicyError(
            "Normal access to underscore-prefixed internal directories is not allowed."
        )
    return candidate
```

- [ ] **Step 4: Hide `_` paths from normal search and file reads**

```python
def _path_contains_hidden_internal_segment(path_value: str) -> bool:
    normalized_path = str(path_value or "").replace("\\", "/").strip("/")
    if not normalized_path:
        return False
    return any(part.startswith("_") for part in normalized_path.split("/"))


# in search_service.py file queries
.where(FileRecord.is_deleted.is_(False))
.where(~FileRecord.path.startswith("/_"))


# in file_access_service.py before returning file/note/source payloads
if _path_contains_hidden_internal_segment(file_record.path):
    return None
```

- [ ] **Step 5: Re-run focused tests**

Run: `pytest tests/test_file_mutation_service.py tests/test_search_api.py -v`
Expected: PASS with underscore-prefixed paths hidden from ordinary search/file access

- [ ] **Step 6: Commit**

```bash
git add src/icloud_index_service/services/file_mutation_service.py src/icloud_index_service/services/file_access_service.py src/icloud_index_service/services/search_service.py tests/test_file_mutation_service.py tests/test_search_api.py
git commit -m "feat: add vault namespace and hidden path policy"
```

### Task 2: Add Reversible Change Sets, Delete-As-Move, And Restore

**Files:**
- Modify: `src/icloud_index_service/services/file_mutation_service.py`
- Modify: `src/icloud_index_service/api/files.py`
- Modify: `tests/test_file_mutation_service.py`
- Create: `tests/test_files_api_mutation.py`

- [ ] **Step 1: Write the failing change-set and restore tests**

```python
from pathlib import Path

from icloud_index_service.services.file_mutation_service import (
    FileNamespace,
    delete_file_by_path,
    restore_change_set,
)


def test_delete_moves_live_file_into_changes_backup(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    result = delete_file_by_path(
        namespace=FileNamespace.GOOGLE1,
        relative_path="Cases/Appeal.txt",
        actor="pytest",
    )

    assert result["change_set_id"]
    assert not file_path.exists()
    assert Path(result["backup_path"]).exists()


def test_restore_change_set_returns_deleted_file_to_live_path(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    file_path = mirror_root / "google1" / "Cases" / "Appeal.txt"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    deleted = delete_file_by_path(
        namespace=FileNamespace.GOOGLE1,
        relative_path="Cases/Appeal.txt",
        actor="pytest",
    )
    restored = restore_change_set(change_set_id=deleted["change_set_id"], actor="pytest-restore")

    assert restored["status"] == "restored"
    assert file_path.exists()
    assert file_path.read_text(encoding="utf-8") == "appeal"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_file_mutation_service.py::test_delete_moves_live_file_into_changes_backup tests/test_file_mutation_service.py::test_restore_change_set_returns_deleted_file_to_live_path -v`
Expected: FAIL because delete/restore helpers do not exist yet

- [ ] **Step 3: Implement `_CHANGES_BACKUP` change-set helpers**

```python
import json
from datetime import datetime, timezone
from shutil import move
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _changes_backup_root(namespace: FileNamespace) -> Path:
    return resolve_namespace_root(namespace) / "_CHANGES_BACKUP"


def _write_change_set(namespace: FileNamespace, payload: dict[str, object]) -> Path:
    change_set_id = str(payload["change_set_id"])
    change_root = _changes_backup_root(namespace) / change_set_id
    change_root.mkdir(parents=True, exist_ok=True)
    metadata_path = change_root / "change-set.json"
    metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return change_root


def delete_file_by_path(*, namespace: FileNamespace, relative_path: str, actor: str) -> dict[str, object]:
    live_path = resolve_live_path(namespace=namespace, relative_path=relative_path, allow_internal=False)
    change_set_id = uuid4().hex
    change_root = _changes_backup_root(namespace) / change_set_id
    payload_root = change_root / "payload"
    payload_root.mkdir(parents=True, exist_ok=True)
    backup_path = payload_root / live_path.name
    move(str(live_path), str(backup_path))
    payload = {
        "change_set_id": change_set_id,
        "namespace": namespace.value,
        "actor": actor,
        "operation": "delete",
        "original_relative_path": relative_path,
        "backup_path": str(backup_path),
        "created_at": _now_iso(),
        "status": "deleted",
    }
    _write_change_set(namespace, payload)
    return payload


def restore_change_set(*, change_set_id: str, actor: str) -> dict[str, object]:
    for namespace in FileNamespace:
        metadata_path = _changes_backup_root(namespace) / change_set_id / "change-set.json"
        if not metadata_path.exists():
            continue
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        live_path = resolve_live_path(
            namespace=namespace,
            relative_path=str(payload["original_relative_path"]),
            allow_internal=False,
        )
        live_path.parent.mkdir(parents=True, exist_ok=True)
        move(str(payload["backup_path"]), str(live_path))
        payload["status"] = "restored"
        payload["restored_at"] = _now_iso()
        payload["restored_by"] = actor
        metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload
    raise FileMutationPolicyError(f"Unknown change set: {change_set_id}")
```

- [ ] **Step 4: Add the origin routes for delete and restore**

```python
@router.post("/ops/delete", dependencies=[Depends(require_plugin_api_token)])
def delete_file_route(payload: DeleteFileRequest) -> dict[str, object]:
    return delete_file_by_path(
        namespace=payload.namespace,
        relative_path=payload.relative_path,
        actor="plugin-api",
    )


@router.post("/ops/restore", dependencies=[Depends(require_plugin_api_token)])
def restore_change_set_route(payload: RestoreChangeSetRequest) -> dict[str, object]:
    return restore_change_set(
        change_set_id=payload.change_set_id,
        actor="plugin-api",
    )
```

- [ ] **Step 5: Run the mutation tests and focused API tests**

Run: `pytest tests/test_file_mutation_service.py tests/test_files_api_mutation.py -v`
Expected: PASS with delete implemented as move into `_CHANGES_BACKUP` and restore returning files to live paths

- [ ] **Step 6: Commit**

```bash
git add src/icloud_index_service/services/file_mutation_service.py src/icloud_index_service/api/files.py tests/test_file_mutation_service.py tests/test_files_api_mutation.py
git commit -m "feat: add reversible vault delete and restore routes"
```

### Task 3: Add Structured `document_vault` Note Creation And Auto Feedback Sync

**Files:**
- Modify: `src/icloud_index_service/services/file_mutation_service.py`
- Modify: `apps/classifier/note_writer.py`
- Modify: `src/icloud_index_service/services/vault_reconciliation.py`
- Create: `tests/test_document_vault_mutation.py`
- Modify: `tests/test_vault_naming.py`

- [ ] **Step 1: Write the failing structured note tests**

```python
from pathlib import Path

from icloud_index_service.services.file_mutation_service import create_document_vault_note


def test_create_document_vault_note_uses_categorizer_contract(monkeypatch, tmp_path: Path):
    vault_root = tmp_path / "document-vault"
    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    result = create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path=str(source_path),
    )

    note_text = Path(result["note_path"]).read_text(encoding="utf-8")
    assert 'type: classified-document' in note_text
    assert 'canonical_source_path:' in note_text
    assert 'source_link:' in note_text
    assert '## Original File' in note_text


def test_create_document_vault_note_prefers_vault_local_attachment_link(monkeypatch, tmp_path: Path):
    vault_root = tmp_path / "document-vault"
    source_root = tmp_path / "mirrors"
    source_path = source_root / "google1" / "Appeal.docx"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("appeal", encoding="utf-8")
    monkeypatch.setenv("CLASSIFIER_VAULT_ROOT", str(vault_root))

    result = create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path=str(source_path),
        attach_originals=True,
    )

    note_text = Path(result["note_path"]).read_text(encoding="utf-8")
    assert "[[90 Attachments/" in note_text
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_document_vault_mutation.py tests/test_vault_naming.py -v`
Expected: FAIL because structured `document_vault` creation helper does not exist yet

- [ ] **Step 3: Reuse the existing categorizer note writer**

```python
from apps.classifier.classify_to_obsidian import ensure_vault, write_obsidian_note
from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback


def create_document_vault_note(
    *,
    relative_folder: str,
    visible_title: str,
    summary: str,
    canonical_source_path: str,
    attach_originals: bool = True,
) -> dict[str, object]:
    vault_root = resolve_namespace_root(FileNamespace.DOCUMENT_VAULT)
    ensure_vault(vault_root)
    source_path = Path(canonical_source_path).resolve()
    note_path = write_obsidian_note(
        vault=vault_root,
        source_path=source_path,
        file_hash="manual-document-vault-note",
        markdown=None,
        classification={
            "primary_label": Path(relative_folder).parts[-1] if relative_folder else "unknown",
            "secondary_labels": [],
            "confidence": 1.0,
            "summary": summary,
            "reason": "Structured ChatGPT document_vault note creation.",
            "sensitive_flags": [],
            "recommended_action": "retain",
            "file_date_guess": "unknown",
            "language": "unknown",
        },
        attach_originals=attach_originals,
        canonical_source_path=str(source_path),
        last_seen_filename=visible_title,
        source_parser="manual-document-vault",
        heuristic_primary_hint="manual-document-vault",
        hybrid_live_source="chatgpt-plugin",
    )
    sync_manual_note_feedback(vault_root, known_labels=[], folder_label_map_path=None, limit=25)
    return {"note_path": str(note_path)}
```

- [ ] **Step 4: Run the structured-note tests**

Run: `pytest tests/test_document_vault_mutation.py tests/test_vault_naming.py::test_write_obsidian_note_uses_clean_visible_note_name -v`
Expected: PASS with categorizer-compatible frontmatter and vault-local attachment links when attachments are enabled

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/file_mutation_service.py apps/classifier/note_writer.py src/icloud_index_service/services/vault_reconciliation.py tests/test_document_vault_mutation.py tests/test_vault_naming.py
git commit -m "feat: add structured document vault note creation"
```

### Task 4: Expose CRUD, Restore, And `document_vault` Tools Through MCP And Remote MCP

**Files:**
- Modify: `src/icloud_plugin_mcp/service_client.py`
- Modify: `src/icloud_plugin_mcp/server.py`
- Modify: `src/icloud_plugin_mcp/tool_schemas.py`
- Modify: `cloudflare/remote-mcp/src/index.ts`
- Modify: `cloudflare/remote-mcp/chatgpt-app-submission.json`
- Modify: `cloudflare/remote-mcp/scripts/chatgpt-app-submission-content.mjs`
- Modify: `tests/test_plugin_client.py`
- Modify: `tests/test_plugin_server_tools.py`
- Modify: `tests/test_chatgpt_app_submission.py`
- Modify: `cloudflare/remote-mcp/tests/mcp-e2e.test.ts`

- [ ] **Step 1: Write the failing MCP client and tool metadata tests**

```python
def test_create_document_vault_note_posts_to_origin_endpoint():
    client = PluginServiceClient("http://service.test", api_token="token")
    transport = RecordingTransport(json_payload={"note_path": "/vault/Appeal.md"})
    client._client = httpx.Client(transport=transport, base_url="http://service.test")

    payload = client.create_document_vault_note(
        relative_folder="01 Classified/appeal",
        visible_title="Appeal",
        summary="Appeal summary.",
        canonical_source_path="/mnt/cloud-vault/mirrors/google1/Appeal.docx",
    )

    captured_request = transport.requests[-1]
    assert str(captured_request.url) == "http://service.test/files/ops/document-vault/note"
    assert payload["note_path"] == "/vault/Appeal.md"


def test_delete_file_posts_to_delete_endpoint():
    client = PluginServiceClient("http://service.test", api_token="token")
    transport = RecordingTransport(json_payload={"status": "deleted", "change_set_id": "abc123"})
    client._client = httpx.Client(transport=transport, base_url="http://service.test")

    payload = client.delete_file(namespace="google1", relative_path="Cases/Appeal.txt")

    captured_request = transport.requests[-1]
    assert str(captured_request.url) == "http://service.test/files/ops/delete"
    assert payload["change_set_id"] == "abc123"


def test_restore_change_set_posts_to_restore_endpoint():
    client = PluginServiceClient("http://service.test", api_token="token")
    transport = RecordingTransport(json_payload={"status": "restored", "change_set_id": "abc123"})
    client._client = httpx.Client(transport=transport, base_url="http://service.test")

    payload = client.restore_change_set(change_set_id="abc123")

    captured_request = transport.requests[-1]
    assert str(captured_request.url) == "http://service.test/files/ops/restore"
    assert payload["status"] == "restored"
```

```python
def test_plugin_server_tools_expose_mutating_annotations_for_crud_and_restore():
    expected_mutating = {
        "create_icloud_file",
        "update_icloud_file",
        "move_icloud_file",
        "delete_icloud_file",
        "restore_icloud_change_set",
        "create_document_vault_note",
    }

    registered = {tool.name: tool for tool in build_test_tool_registry()}
    assert expected_mutating.issubset(set(registered))
    for tool_name in expected_mutating:
        assert registered[tool_name].annotations == WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS
```

- [ ] **Step 2: Run the focused MCP/plugin tests to verify they fail**

Run: `pytest tests/test_plugin_client.py tests/test_plugin_server_tools.py tests/test_chatgpt_app_submission.py -v`
Expected: FAIL because CRUD and restore methods/tools do not exist yet

- [ ] **Step 3: Add the MCP client methods and local tool registrations**

```python
def create_document_vault_note(self, *, relative_folder: str, visible_title: str, summary: str, canonical_source_path: str) -> dict[str, Any]:
    return self._request("POST", "/files/ops/document-vault/note", json_body={
        "relative_folder": relative_folder,
        "visible_title": visible_title,
        "summary": summary,
        "canonical_source_path": canonical_source_path,
    })


def delete_file(self, *, namespace: str, relative_path: str) -> dict[str, Any]:
    return self._request("POST", "/files/ops/delete", json_body={
        "namespace": namespace,
        "relative_path": relative_path,
    })


def restore_change_set(self, *, change_set_id: str) -> dict[str, Any]:
    return self._request("POST", "/files/ops/restore", json_body={"change_set_id": change_set_id})
```

```python
@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def create_document_vault_note(...): ...


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def delete_icloud_file(...): ...


@mcp.tool(annotations=WRITE_ONLY_INTERNAL_TOOL_ANNOTATIONS, structured_output=True)
def restore_icloud_change_set(...): ...
```

- [ ] **Step 4: Mirror the new tools in the Cloudflare Worker and submission metadata**

```ts
server.registerTool(
  "create_document_vault_note",
  {
    description: "Create a structured Obsidian note in document_vault using the categorizer-compatible note contract.",
    inputSchema: {
      relative_folder: z.string().min(1),
      visible_title: z.string().min(1),
      summary: z.string().min(1),
      canonical_source_path: z.string().min(1),
    },
    outputSchema: genericJsonObjectSchema,
    annotations: internalWriteAnnotations,
  },
  async ({ relative_folder, visible_title, summary, canonical_source_path }) => {
    const payload = await fetchOriginJson(env, "/files/ops/document-vault/note", {
      method: "POST",
      body: JSON.stringify({ relative_folder, visible_title, summary, canonical_source_path }),
      headers: { "content-type": "application/json" },
    });
    return jsonToolResult(payload);
  },
);
```

- [ ] **Step 5: Run local MCP/plugin and remote MCP tests**

Run: `pytest tests/test_plugin_client.py tests/test_plugin_server_tools.py tests/test_chatgpt_app_submission.py -v`
Run: `npm --prefix cloudflare/remote-mcp test -- --runInBand`
Expected: PASS with new CRUD/restore/document_vault tool descriptors, annotations, and submission metadata

- [ ] **Step 6: Commit**

```bash
git add src/icloud_plugin_mcp/service_client.py src/icloud_plugin_mcp/server.py src/icloud_plugin_mcp/tool_schemas.py cloudflare/remote-mcp/src/index.ts cloudflare/remote-mcp/chatgpt-app-submission.json cloudflare/remote-mcp/scripts/chatgpt-app-submission-content.mjs tests/test_plugin_client.py tests/test_plugin_server_tools.py tests/test_chatgpt_app_submission.py cloudflare/remote-mcp/tests/mcp-e2e.test.ts
git commit -m "feat: expose vault CRUD and document vault tools"
```

### Task 5: Import Legacy Quarantine State And Finalize Docs/Verification

**Files:**
- Modify: `src/icloud_index_service/services/file_mutation_service.py`
- Create: `scripts/import_duplicate_quarantine_to_changes_backup.py`
- Modify: `tests/test_file_mutation_service.py`
- Modify: `docs/operations.md`
- Modify: `docs/chat-handoff.md`
- Modify: `src/icloud_index_service/services/product_readiness.py`

- [ ] **Step 1: Write the failing legacy import tests**

```python
def test_import_duplicate_quarantine_creates_legacy_change_sets(monkeypatch, tmp_path: Path):
    mirror_root = tmp_path / "cloud-vault" / "mirrors"
    quarantine_file = mirror_root / "google1" / "_DUPLICATE_QUARANTINE" / "dup.txt"
    quarantine_file.parent.mkdir(parents=True, exist_ok=True)
    quarantine_file.write_text("duplicate", encoding="utf-8")
    monkeypatch.setenv("ICLOUD_MIRROR_ROOT", str(mirror_root))

    result = import_duplicate_quarantine_to_changes_backup(actor="pytest")

    assert result["imported_files"] == 1
    assert result["change_sets_created"] >= 1
    assert not quarantine_file.exists()
```

- [ ] **Step 2: Run the focused import tests to verify they fail**

Run: `pytest tests/test_file_mutation_service.py::test_import_duplicate_quarantine_creates_legacy_change_sets -v`
Expected: FAIL because import helper does not exist yet

- [ ] **Step 3: Implement the quarantine import helper and operator script**

```python
def import_duplicate_quarantine_to_changes_backup(*, actor: str) -> dict[str, object]:
    imported_files = 0
    change_sets_created = 0
    for namespace in (FileNamespace.GOOGLE1, FileNamespace.GOOGLE2, FileNamespace.ICLOUD):
        namespace_root = resolve_namespace_root(namespace)
        quarantine_root = namespace_root / "_DUPLICATE_QUARANTINE"
        if not quarantine_root.exists():
            continue
        for source_path in quarantine_root.rglob("*"):
            if not source_path.is_file():
                continue
            relative_name = source_path.name
            payload = delete_file_by_path(
                namespace=namespace,
                relative_path=str(source_path.relative_to(namespace_root)).replace("\\", "/"),
                actor=actor,
            )
            payload["legacy_import"] = "_DUPLICATE_QUARANTINE"
            imported_files += 1
            change_sets_created += 1
    return {"imported_files": imported_files, "change_sets_created": change_sets_created}
```

```python
from icloud_index_service.services.file_mutation_service import import_duplicate_quarantine_to_changes_backup


if __name__ == "__main__":
    result = import_duplicate_quarantine_to_changes_backup(actor="operator-script")
    print(result)
```

- [ ] **Step 4: Update readiness/docs and run full verification**

Run: `pytest tests/test_file_mutation_service.py tests/test_document_vault_mutation.py tests/test_plugin_client.py tests/test_plugin_server_tools.py tests/test_chatgpt_app_submission.py tests/test_search_api.py tests/test_vault_naming.py -v`
Run: `npm --prefix cloudflare/remote-mcp test -- --runInBand`
Run: `git diff --check`
Expected: PASS with no whitespace errors and all CRUD, restore, document_vault, underscore-policy, and import tests green

- [ ] **Step 5: Commit**

```bash
git add src/icloud_index_service/services/file_mutation_service.py scripts/import_duplicate_quarantine_to_changes_backup.py tests/test_file_mutation_service.py docs/operations.md docs/chat-handoff.md src/icloud_index_service/services/product_readiness.py
git commit -m "feat: import duplicate quarantine into changes backup"
```
