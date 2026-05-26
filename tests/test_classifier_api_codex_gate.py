from types import SimpleNamespace

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
