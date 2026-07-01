from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .category_manager import load_categories
from .classify_to_obsidian import process_shadow_queue_command
from .hybrid_runtime import (
    ensure_lightgbm_model,
    load_hybrid_gating_config,
    maybe_retrain_from_shadow_data,
    write_readiness_report,
)
from .index_training import train_lightgbm_from_index
from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback
from packages.runtime import load_classifier_runtime_settings


def run_learning_maintenance(
    *,
    process_shadow: bool = True,
    sync_manual_feedback: bool = True,
    retrain_lightgbm: bool = True,
    write_readiness: bool = True,
    train_from_index: bool = False,
    index_database_url: str | None = None,
    min_rows: int | None = None,
    min_new_rows: int | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    settings = load_classifier_runtime_settings()
    categories = load_categories()
    result: dict[str, Any] = {
        "ok": True,
        "manual_feedback": {"skipped": True},
        "shadow_qwen": {"skipped": True},
        "lightgbm": {"skipped": True},
        "readiness": {"skipped": True},
        "settings": {
            "vault_root": str(settings.vault_root),
            "output_root": str(settings.output_root),
            "model_path": str(settings.lightgbm_model_path),
            "report_path": str(settings.lightgbm_report_path),
            "qwen_model": settings.classify_model,
            "qwen_vision_model": settings.vision_model,
            "codex_arbiter_enabled": settings.codex_arbiter_enabled,
        },
    }

    if sync_manual_feedback:
        result["manual_feedback"] = sync_manual_note_feedback(
            settings.vault_root,
            feedback_path=settings.manual_note_feedback_path,
            state_path=settings.manual_note_sync_state_path,
            known_labels=categories,
            folder_label_map_path=settings.vault_folder_label_map_path,
        )

    if process_shadow:
        result["shadow_qwen"] = process_shadow_queue_command(
            categories=categories,
            ollama_url=settings.ollama_url,
            model=settings.classify_model,
            vision_model=settings.vision_model,
            max_chars=50000,
        )

    if retrain_lightgbm:
        created = ensure_lightgbm_model()
        if created.get("ok") and created.get("created"):
            result["lightgbm"] = created
        elif train_from_index:
            result["lightgbm"] = {
                "retrained": True,
                "training_source": "index",
                "report": train_lightgbm_from_index(
                    database_url=index_database_url,
                    model_path=settings.lightgbm_model_path,
                    report_path=settings.lightgbm_report_path,
                    seed=seed,
                ),
            }
        else:
            gating = load_hybrid_gating_config()
            result["lightgbm"] = maybe_retrain_from_shadow_data(
                min_rows=min_rows
                if min_rows is not None
                else max(int(gating.get("auto_retrain_min_rows", 25) or 25), 1),
                min_new_rows_since_last_train=min_new_rows
                if min_new_rows is not None
                else max(int(gating.get("auto_retrain_min_new_rows", 10) or 0), 0),
            )

    if write_readiness:
        result["readiness"] = write_readiness_report()

    lightgbm_result = result.get("lightgbm") or {}
    result["ok"] = not bool(lightgbm_result.get("ok") is False)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one bounded classifier learning-maintenance pass."
    )
    parser.add_argument("--no-shadow", action="store_true", help="Skip Qwen shadow queue processing.")
    parser.add_argument("--no-manual-feedback", action="store_true", help="Skip Obsidian manual feedback sync.")
    parser.add_argument("--no-retrain", action="store_true", help="Skip LightGBM retrain checks.")
    parser.add_argument("--no-readiness", action="store_true", help="Skip readiness report refresh.")
    parser.add_argument(
        "--train-from-index",
        action="store_true",
        help="Force LightGBM retraining from the live index instead of approved feedback rows.",
    )
    parser.add_argument("--database-url", default=None, help="Optional Postgres URL for --train-from-index.")
    parser.add_argument("--min-rows", type=int, default=None, help="Minimum approved rows for feedback retrain.")
    parser.add_argument("--min-new-rows", type=int, default=None, help="Minimum new approved rows for feedback retrain.")
    parser.add_argument("--seed", type=int, default=7, help="Sampling seed for --train-from-index.")
    parser.add_argument("--summary-json", default=None, help="Optional path to write the JSON summary.")
    args = parser.parse_args(argv)

    result = run_learning_maintenance(
        process_shadow=not args.no_shadow,
        sync_manual_feedback=not args.no_manual_feedback,
        retrain_lightgbm=not args.no_retrain,
        write_readiness=not args.no_readiness,
        train_from_index=args.train_from_index,
        index_database_url=args.database_url,
        min_rows=args.min_rows,
        min_new_rows=args.min_new_rows,
        seed=args.seed,
    )
    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
