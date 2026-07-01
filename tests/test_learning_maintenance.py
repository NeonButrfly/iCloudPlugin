from __future__ import annotations

import json
from pathlib import Path

from apps.classifier import learning_maintenance


class FakeSettings:
    vault_root = Path("/vault")
    output_root = Path("/output")
    lightgbm_model_path = Path("/output/_artifacts/lightgbm-classifier.joblib")
    lightgbm_report_path = Path("/output/_artifacts/lightgbm-training-report.json")
    manual_note_feedback_path = Path("/output/_artifacts/manual-note-feedback.jsonl")
    manual_note_sync_state_path = Path("/output/manual-note-sync-state.json")
    vault_folder_label_map_path = Path("/config/vault-folder-labels.json")
    ollama_url = "http://ollama:11434"
    classify_model = "qwen2.5:3b"
    vision_model = "qwen2.5vl:3b"
    codex_arbiter_enabled = False


def test_run_learning_maintenance_updates_feedback_shadow_lightgbm_and_readiness(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(learning_maintenance, "load_classifier_runtime_settings", lambda: FakeSettings())
    monkeypatch.setattr(learning_maintenance, "load_categories", lambda: ["medical", "text-message"])
    monkeypatch.setattr(
        learning_maintenance,
        "sync_manual_note_feedback",
        lambda *args, **kwargs: calls.append("manual") or {"exported": 2},
    )
    monkeypatch.setattr(
        learning_maintenance,
        "process_shadow_queue_command",
        lambda **kwargs: calls.append("shadow") or {"processed": 3, "retrain": {"retrained": False}},
    )
    monkeypatch.setattr(
        learning_maintenance,
        "ensure_lightgbm_model",
        lambda: calls.append("ensure-lightgbm") or {"ok": True, "created": False},
    )
    monkeypatch.setattr(
        learning_maintenance,
        "load_hybrid_gating_config",
        lambda: {"auto_retrain_min_rows": 11, "auto_retrain_min_new_rows": 5},
    )

    def fake_retrain(**kwargs):
        calls.append(f"retrain:{kwargs['min_rows']}:{kwargs['min_new_rows_since_last_train']}")
        return {"retrained": True, "training_rows": 42}

    monkeypatch.setattr(learning_maintenance, "maybe_retrain_from_shadow_data", fake_retrain)
    monkeypatch.setattr(
        learning_maintenance,
        "write_readiness_report",
        lambda: calls.append("readiness") or {"ok": True, "real_ingestion_allowed": True},
    )

    result = learning_maintenance.run_learning_maintenance()

    assert result["ok"] is True
    assert result["manual_feedback"] == {"exported": 2}
    assert result["shadow_qwen"]["processed"] == 3
    assert result["lightgbm"]["training_rows"] == 42
    assert result["readiness"]["real_ingestion_allowed"] is True
    assert result["settings"]["qwen_model"] == "qwen2.5:3b"
    assert result["settings"]["codex_arbiter_enabled"] is False
    assert calls == ["manual", "shadow", "ensure-lightgbm", "retrain:11:5", "readiness"]


def test_run_learning_maintenance_can_force_index_lightgbm_training(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(learning_maintenance, "load_classifier_runtime_settings", lambda: FakeSettings())
    monkeypatch.setattr(learning_maintenance, "load_categories", lambda: ["medical"])
    monkeypatch.setattr(
        learning_maintenance,
        "ensure_lightgbm_model",
        lambda: calls.append("ensure-lightgbm") or {"ok": True, "created": False},
    )

    def fake_train_from_index(**kwargs):
        calls.append(kwargs["database_url"])
        assert kwargs["model_path"] == FakeSettings.lightgbm_model_path
        assert kwargs["report_path"] == FakeSettings.lightgbm_report_path
        assert kwargs["seed"] == 13
        return {"training_rows": 80}

    monkeypatch.setattr(learning_maintenance, "train_lightgbm_from_index", fake_train_from_index)
    monkeypatch.setattr(learning_maintenance, "write_readiness_report", lambda: {"ok": True})

    result = learning_maintenance.run_learning_maintenance(
        process_shadow=False,
        sync_manual_feedback=False,
        train_from_index=True,
        index_database_url="postgresql://example/index",
        seed=13,
    )

    assert result["lightgbm"]["training_source"] == "index"
    assert result["lightgbm"]["report"]["training_rows"] == 80
    assert calls == ["ensure-lightgbm", "postgresql://example/index"]


def test_learning_maintenance_main_writes_summary_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        learning_maintenance,
        "run_learning_maintenance",
        lambda **kwargs: {"ok": True, "kwargs": kwargs},
    )
    summary_path = tmp_path / "summary.json"

    exit_code = learning_maintenance.main(
        [
            "--no-shadow",
            "--no-manual-feedback",
            "--no-retrain",
            "--no-readiness",
            "--summary-json",
            str(summary_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["kwargs"]["process_shadow"] is False
    assert summary["kwargs"]["sync_manual_feedback"] is False
    assert summary["kwargs"]["retrain_lightgbm"] is False
    assert summary["kwargs"]["write_readiness"] is False
    assert '"ok": true' in capsys.readouterr().out
