from __future__ import annotations

import json
import os
import sys
import time

from .category_manager import load_categories
from .classify_to_obsidian import process_shadow_queue_command
from icloud_index_service.services.vault_reconciliation import sync_manual_note_feedback
from packages.runtime import load_classifier_runtime_settings


def run_shadow_worker_once() -> dict:
    settings = load_classifier_runtime_settings()
    if not settings.background_classification_enabled:
        return {
            "ok": True,
            "classifier_mode": settings.classifier_mode,
            "background_classification_enabled": False,
            "queued_jobs_auto_running": False,
            "shadow_queue_processed": False,
            "manual_note_sync": {"scanned": 0, "created": 0, "unchanged": 0, "event_ids": []},
            "message": "Shadow worker is dormant because classifier mode is not background.",
        }
    categories = load_categories()
    manual_note_result = sync_manual_note_feedback(
        settings.vault_root,
        feedback_path=settings.manual_note_feedback_path,
        state_path=settings.manual_note_sync_state_path,
        known_labels=categories,
        folder_label_map_path=settings.vault_folder_label_map_path,
    )
    shadow_result = process_shadow_queue_command(
        categories=categories,
        ollama_url=settings.ollama_url,
        model=os.getenv("CLASSIFY_MODEL", "qwen2.5:7b"),
        vision_model=os.getenv("VISION_MODEL", "qwen2.5vl:7b"),
        max_chars=int(os.getenv("CLASSIFIER_MAX_CHARS", "50000")),
    )
    return {
        **shadow_result,
        "manual_note_sync": manual_note_result,
    }


def run_shadow_worker_loop() -> int:
    settings = load_classifier_runtime_settings()
    interval_seconds = max(int(settings.shadow_worker_interval_seconds or 15), 1)

    while True:
        try:
            result = run_shadow_worker_once()
            print(json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                file=sys.stderr,
                flush=True,
            )
        time.sleep(interval_seconds)


def main() -> int:
    return run_shadow_worker_loop()


if __name__ == "__main__":
    raise SystemExit(main())
