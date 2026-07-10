from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from packages.runtime import load_classifier_runtime_settings

from .classify_to_obsidian import ensure_vault
from .hybrid_runtime import ensure_lightgbm_model, ensure_runtime_artifacts_bootstrapped, write_readiness_report
from .ollama_runtime import ensure_ollama_models_present


def _remove_path(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"files": 0, "dirs": 0}
    if path.is_file():
        path.unlink()
        return {"files": 1, "dirs": 0}

    files = 0
    dirs = 0
    for child in path.rglob("*"):
        if child.is_file():
            files += 1
        elif child.is_dir():
            dirs += 1
    shutil.rmtree(path)
    return {"files": files, "dirs": dirs + 1}


def reset_generated_classifier_outputs(
    *,
    vault_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    removed = {"files": 0, "dirs": 0}
    targets = [
        vault_root / "01 Classified",
        vault_root / "02 Needs Review",
        vault_root / "90 Attachments",
        vault_root / "_system" / "classifications",
        vault_root / "_system" / "extracted-markdown",
        vault_root / "Classification Index.md",
        output_root / "shadow-queue",
        output_root / "shadow-comparisons.jsonl",
        output_root / "readiness-report.json",
        output_root / "manifest.jsonl",
        output_root / "retrain",
    ]

    for target in targets:
        result = _remove_path(target)
        removed["files"] += result["files"]
        removed["dirs"] += result["dirs"]

    ensure_vault(vault_root)
    return {
        "ok": True,
        "vault_root": str(vault_root),
        "output_root": str(output_root),
        "removed": removed,
    }


def prepare_classifier_runtime(*, reset_generated_notes: bool = False) -> dict[str, Any]:
    settings = load_classifier_runtime_settings()
    result: dict[str, Any] = {
        "ok": True,
        "settings": {
            "vault_root": str(settings.vault_root),
            "output_root": str(settings.output_root),
            "classify_model": settings.classify_model,
            "vision_model": settings.vision_model,
            "ollama_url": settings.ollama_url,
        },
    }

    if reset_generated_notes:
        result["reset"] = reset_generated_classifier_outputs(
            vault_root=settings.vault_root,
            output_root=settings.output_root,
        )
    else:
        ensure_vault(settings.vault_root)
        result["reset"] = {"ok": True, "skipped": True}

    result["bootstrapped"] = ensure_runtime_artifacts_bootstrapped()
    result["lightgbm"] = ensure_lightgbm_model()
    result["readiness"] = write_readiness_report()

    try:
        result["qwen_runtime"] = ensure_ollama_models_present(
            settings.ollama_url,
            required_models=[settings.classify_model, settings.vision_model],
        )
    except Exception as exc:
        result["qwen_runtime"] = {
            "ok": False,
            "required_models_present": False,
            "error": str(exc),
            "required_models": [settings.classify_model, settings.vision_model],
        }
        result["ok"] = False

    if result.get("lightgbm", {}).get("ok") is False:
        result["ok"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reset generated classifier outputs and prepare local runtime artifacts for a fresh run."
    )
    parser.add_argument(
        "--reset-generated-notes",
        action="store_true",
        help="Remove generated classifier vault outputs and runtime state before rebuilding readiness artifacts.",
    )
    args = parser.parse_args(argv)

    result = prepare_classifier_runtime(reset_generated_notes=args.reset_generated_notes)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
