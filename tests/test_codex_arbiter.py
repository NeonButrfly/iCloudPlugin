from pathlib import Path
from types import SimpleNamespace

import pytest


def _local_classification() -> dict:
    return {
        "primary_label": "financial",
        "secondary_labels": [],
        "confidence": 0.66,
        "summary": "Local classifier summary.",
        "reason": "Local classifier reason.",
        "sensitive_flags": ["financial"],
        "recommended_action": "review",
        "file_date_guess": "unknown",
        "language": "English",
    }


def test_run_codex_final_arbiter_returns_normalized_result_for_valid_json(monkeypatch):
    from apps.classifier.codex_arbiter import run_codex_final_arbiter

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stdout=(
                '{"primary_label":"technical","secondary_labels":["work"],'
                '"confidence":0.97,"summary":"Codex summary.","reason":"Codex reason.",'
                '"sensitive_flags":["none"],"recommended_action":"keep",'
                '"file_date_guess":"2026-05-31","language":"English"}'
            ),
            stderr="",
        )

    monkeypatch.setattr("apps.classifier.codex_arbiter.subprocess.run", fake_run)

    classification, meta = run_codex_final_arbiter(
        source_path=Path("/source/google1/Docs/Budget.txt"),
        markdown="Budget details and technical deployment notes",
        local_classification=_local_classification(),
        candidate_categories=["technical", "work", "financial", "needs-review", "unknown"],
        command=["codex", "exec"],
        timeout_seconds=30,
    )

    assert classification["primary_label"] == "technical"
    assert classification["secondary_labels"] == ["work"]
    assert classification["confidence"] == 0.97
    assert classification["summary"] == "Codex summary."
    assert meta["status"] == "applied"
    assert meta["applied"] is True


def test_run_codex_final_arbiter_falls_back_on_invalid_json(monkeypatch):
    from apps.classifier.codex_arbiter import run_codex_final_arbiter

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr("apps.classifier.codex_arbiter.subprocess.run", fake_run)

    local = _local_classification()
    classification, meta = run_codex_final_arbiter(
        source_path=Path("/source/google1/Docs/Budget.txt"),
        markdown="Budget details",
        local_classification=local,
        candidate_categories=["technical", "financial", "needs-review", "unknown"],
        command=["codex", "exec"],
        timeout_seconds=30,
    )

    assert classification == local
    assert meta["status"] == "invalid-json"
    assert meta["applied"] is False


def test_run_codex_final_arbiter_falls_back_on_timeout(monkeypatch):
    from apps.classifier.codex_arbiter import run_codex_final_arbiter

    def fake_run(cmd, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("apps.classifier.codex_arbiter.subprocess.run", fake_run)

    local = _local_classification()
    classification, meta = run_codex_final_arbiter(
        source_path=Path("/source/google1/Docs/Budget.txt"),
        markdown="Budget details",
        local_classification=local,
        candidate_categories=["technical", "financial", "needs-review", "unknown"],
        command=["codex", "exec"],
        timeout_seconds=30,
    )

    assert classification == local
    assert meta["status"] == "timeout"
    assert meta["applied"] is False
