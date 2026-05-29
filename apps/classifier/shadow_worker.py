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
    categories = load_categories()
    shadow_result = process_shadow_queue_command(
        categories=categories,
        ollama_url=settings.ollama_url,
        model=os.getenv("CLASSIFY_MODEL", "qwen2.5:3b"),
        vision_model=os.getenv("VISION_MODEL", "qwen2.5vl:3b"),
        max_chars=int(os.getenv("CLASSIFIER_MAX_CHARS", "50000")),
    )
    manual_note_result = sync_manual_note_feedback(
        settings.vault_root,
        feedback_path=settings.manual_note_feedback_path,
        state_path=settings.manual_note_sync_state_path,
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
