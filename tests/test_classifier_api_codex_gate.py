from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import apps.classifier.api_server as api_server


def test_classifier_api_does_not_pass_codex_arbiter_flag_by_default(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_server, "CODEX_ARBITER_ENABLED", False)
    monkeypatch.setattr(api_server, "INPUT_ROOT", tmp_path / "input")
    monkeypatch.setattr(api_server, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(api_server, "VAULT_ROOT", tmp_path / "vault")
    monkeypatch.setattr(api_server, "MANIFEST_PATH", tmp_path / "output" / "manifest.jsonl")
    monkeypatch.setattr(api_server.subprocess, "run", fake_run)

    with TestClient(api_server.APP) as client:
        response = client.post(
            "/classify/upload",
            files={"file": ("sample.txt", b"sample text", "text/plain")},
            data={"attach_originals": "false", "ingestion_mode": "adhoc"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "--enable-codex-arbiter" not in captured["cmd"]


def test_classifier_api_passes_codex_arbiter_flag_only_when_enabled(monkeypatch, tmp_path):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_server, "CODEX_ARBITER_ENABLED", True)
    monkeypatch.setattr(api_server, "INPUT_ROOT", tmp_path / "input")
    monkeypatch.setattr(api_server, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(api_server, "VAULT_ROOT", tmp_path / "vault")
    monkeypatch.setattr(api_server, "MANIFEST_PATH", tmp_path / "output" / "manifest.jsonl")
    monkeypatch.setattr(api_server.subprocess, "run", fake_run)

    with TestClient(api_server.APP) as client:
        response = client.post(
            "/classify/upload",
            files={"file": ("sample.txt", b"sample text", "text/plain")},
            data={"attach_originals": "false", "ingestion_mode": "adhoc"},
        )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "--enable-codex-arbiter" in captured["cmd"]


def test_classifier_api_source_ingestion_reads_from_source_root_without_staging(
    monkeypatch,
    tmp_path,
):
    captured = {}
    source_root = tmp_path / "source"
    source_file = source_root / "google1" / "Docs" / "Appeal.pdf"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"pdf-bytes")

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(api_server, "SOURCE_ROOT", source_root)
    monkeypatch.setattr(api_server, "INPUT_ROOT", tmp_path / "input")
    monkeypatch.setattr(api_server, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(api_server, "VAULT_ROOT", tmp_path / "vault")
    monkeypatch.setattr(api_server, "MANIFEST_PATH", tmp_path / "output" / "manifest.jsonl")
    monkeypatch.setattr(api_server, "maybe_start_shadow_worker", lambda: None)
    monkeypatch.setattr(api_server.subprocess, "run", fake_run)
    monkeypatch.setattr(api_server, "load_json", lambda *_args, **_kwargs: {"real_ingestion_allowed": True})

    with TestClient(api_server.APP) as client:
        response = client.post(
            "/classify/source",
            data={
                "source_relative_path": "google1/Docs/Appeal.pdf",
                "attach_originals": "false",
                "ingestion_mode": "real-folder",
                "canonical_source_path": "/srv/cloud-vault/mirrors/google1/Docs/Appeal.pdf",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["source_path"] == str(source_file)
    assert payload["staged_path"] is None
    assert captured["cmd"][2] == str(source_file)
    assert not (tmp_path / "input").exists()


def test_classifier_api_source_ingestion_rejects_path_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(api_server, "SOURCE_ROOT", tmp_path / "source")
    monkeypatch.setattr(api_server, "maybe_start_shadow_worker", lambda: None)
    monkeypatch.setattr(api_server, "load_json", lambda *_args, **_kwargs: {"real_ingestion_allowed": True})

    with TestClient(api_server.APP) as client:
        response = client.post(
            "/classify/source",
            data={
                "source_relative_path": "../secret.txt",
                "attach_originals": "false",
                "ingestion_mode": "real-folder",
            },
        )

    assert response.status_code == 400
    assert "Path outside allowed root" in response.text or "relative path" in response.text


@pytest.mark.parametrize("returncode", [0, 1])
def test_classifier_api_upload_cleans_staged_file_after_processing(monkeypatch, tmp_path, returncode):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=returncode, stdout="", stderr="")

    monkeypatch.setattr(api_server, "INPUT_ROOT", tmp_path / "input")
    monkeypatch.setattr(api_server, "OUTPUT_ROOT", tmp_path / "output")
    monkeypatch.setattr(api_server, "VAULT_ROOT", tmp_path / "vault")
    monkeypatch.setattr(api_server, "MANIFEST_PATH", tmp_path / "output" / "manifest.jsonl")
    monkeypatch.setattr(api_server, "maybe_start_shadow_worker", lambda: None)
    monkeypatch.setattr(api_server.subprocess, "run", fake_run)

    with TestClient(api_server.APP) as client:
        response = client.post(
            "/classify/upload",
            files={"file": ("sample.txt", b"sample text", "text/plain")},
            data={"attach_originals": "false", "ingestion_mode": "adhoc"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["staged_file_exists_after_response"] is False
    assert not api_server.Path(payload["staged_path"]).exists()
