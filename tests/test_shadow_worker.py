from __future__ import annotations

from pathlib import Path

from apps.classifier import shadow_worker


def test_run_shadow_worker_once_includes_manual_note_sync(monkeypatch, tmp_path: Path):
    call_order: list[str] = []

    class FakeSettings:
        ollama_url = "http://ollama:11434"
        vault_root = tmp_path / "vault"
        manual_note_feedback_path = tmp_path / "manual-note-feedback.jsonl"
        manual_note_sync_state_path = tmp_path / "manual-note-sync-state.json"
        vault_folder_label_map_path = tmp_path / "vault-folder-labels.json"

    monkeypatch.setattr(shadow_worker, "load_classifier_runtime_settings", lambda: FakeSettings())
    monkeypatch.setattr(shadow_worker, "load_categories", lambda: ["medical"])
    monkeypatch.setattr(
        shadow_worker,
        "process_shadow_queue_command",
        lambda **kwargs: call_order.append("shadow") or {"processed": 2},
    )
    monkeypatch.setattr(
        shadow_worker,
        "sync_manual_note_feedback",
        lambda vault_root, *, feedback_path, state_path, known_labels, folder_label_map_path: call_order.append("manual") or {
            "scanned": 3,
            "exported": 1,
            "unchanged": 2,
        },
    )

    result = shadow_worker.run_shadow_worker_once()

    assert result["processed"] == 2
    assert result["manual_note_sync"] == {
        "scanned": 3,
        "exported": 1,
        "unchanged": 2,
    }
    assert call_order == ["manual", "shadow"]
