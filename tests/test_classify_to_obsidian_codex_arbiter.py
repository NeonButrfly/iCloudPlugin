from pathlib import Path


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
        "candidate_categories_used": ["financial", "technical", "needs-review", "unknown"],
    }


def test_apply_codex_arbiter_if_enabled_skips_runner_when_disabled(monkeypatch):
    from apps.classifier import classify_to_obsidian

    def fail_runner(**kwargs):
        raise AssertionError("runner should not be called when arbiter is disabled")

    monkeypatch.setattr(classify_to_obsidian, "run_codex_final_arbiter", fail_runner)

    classification, live_source, meta = classify_to_obsidian.apply_codex_arbiter_if_enabled(
        enabled=False,
        source_path=Path("/source/google1/Docs/Budget.txt"),
        markdown="Budget details",
        local_classification=_local_classification(),
        heuristic_classification={"primary_label": "financial"},
        hybrid_live_source="inline-llm",
    )

    assert classification["primary_label"] == "financial"
    assert live_source == "inline-llm"
    assert meta["status"] == "disabled"


def test_apply_codex_arbiter_if_enabled_uses_runner_result(monkeypatch):
    from apps.classifier import classify_to_obsidian

    def fake_runner(**kwargs):
        return (
            {
                **_local_classification(),
                "primary_label": "technical",
                "secondary_labels": ["work"],
                "confidence": 0.99,
            },
            {"status": "applied", "applied": True},
        )

    monkeypatch.setattr(classify_to_obsidian, "run_codex_final_arbiter", fake_runner)

    classification, live_source, meta = classify_to_obsidian.apply_codex_arbiter_if_enabled(
        enabled=True,
        source_path=Path("/source/google1/Docs/Budget.txt"),
        markdown="Budget details and deployment notes",
        local_classification=_local_classification(),
        heuristic_classification={"primary_label": "financial"},
        hybrid_live_source="inline-llm",
    )

    assert classification["primary_label"] == "technical"
    assert classification["secondary_labels"] == ["work"]
    assert live_source == "codex-final-arbiter"
    assert meta["status"] == "applied"
