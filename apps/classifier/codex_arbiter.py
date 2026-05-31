from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from shutil import which
from typing import Any, Sequence


DEFAULT_MARKDOWN_CHARS = 12000
REPO_ROOT = Path(__file__).resolve().parents[2]


def _coerce_command(command: Sequence[str] | str) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command, posix=False)
    return [str(part) for part in command]


def _extract_json_object(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _tail_text(value: str, max_chars: int = 4000) -> str:
    return str(value or "")[-max_chars:]


def build_codex_arbiter_readiness(
    *,
    enabled: bool,
    command: Sequence[str] | str,
    timeout_seconds: int,
) -> dict[str, Any]:
    cmd = _coerce_command(command)
    binary = cmd[0] if cmd else ""
    cli_path = which(binary) if binary else None
    auth_file = Path.home() / ".codex" / "auth.json"
    auth_mode = "missing"
    if os.getenv("OPENAI_API_KEY", "").strip():
        auth_mode = "api-key-env"
    elif auth_file.exists():
        auth_mode = "codex-auth-file"
    return {
        "enabled": bool(enabled),
        "command": " ".join(cmd).strip(),
        "timeout_seconds": max(int(timeout_seconds), 1),
        "cli_available": cli_path is not None,
        "cli_path": cli_path,
        "auth_mode": auth_mode,
        "auth_present": auth_mode != "missing",
    }


def _build_codex_arbiter_prompt(
    *,
    source_path: Path,
    markdown: str,
    local_classification: dict[str, Any],
    candidate_categories: list[str],
) -> str:
    allowed_categories = [str(item).strip() for item in candidate_categories if str(item).strip()]
    return (
        "You are the final classification arbiter for a document-routing system.\n"
        "Return exactly one JSON object and no extra prose.\n"
        "Only choose primary_label and secondary_labels from the allowed categories.\n"
        "If uncertain, prefer needs-review or unknown over guessing.\n\n"
        f"Source path: {source_path}\n"
        f"Allowed categories: {json.dumps(allowed_categories, ensure_ascii=False)}\n"
        f"Local classification: {json.dumps(local_classification, ensure_ascii=False)}\n\n"
        "Document text excerpt:\n"
        f"{markdown[:DEFAULT_MARKDOWN_CHARS]}\n\n"
        "Required JSON schema:\n"
        '{'
        '"primary_label":"one allowed category",'
        '"secondary_labels":["zero or more allowed categories"],'
        '"confidence":0.0,'
        '"summary":"brief summary",'
        '"reason":"brief reason",'
        '"sensitive_flags":["zero or more flags"],'
        '"recommended_action":"keep|review|retain|archive|unknown",'
        '"file_date_guess":"date or unknown",'
        '"language":"language name or unknown"'
        '}'
    )


def run_codex_final_arbiter(
    *,
    source_path: Path,
    markdown: str,
    local_classification: dict[str, Any],
    candidate_categories: list[str],
    command: Sequence[str] | str,
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    from .classify_to_obsidian import normalize_vault_classification

    prompt = _build_codex_arbiter_prompt(
        source_path=source_path,
        markdown=markdown,
        local_classification=local_classification,
        candidate_categories=candidate_categories,
    )
    cmd = _coerce_command(command)
    if not cmd:
        return local_classification, {"status": "unavailable", "applied": False, "reason": "empty-command"}

    started_at = time.perf_counter()
    try:
        proc = subprocess.run(
            [*cmd, prompt],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=max(int(timeout_seconds), 1),
            check=False,
        )
    except (TimeoutError, subprocess.TimeoutExpired):
        return local_classification, {"status": "timeout", "applied": False, "duration_ms": round((time.perf_counter() - started_at) * 1000, 3)}
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return local_classification, {
            "status": "unavailable",
            "applied": False,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
            "error": str(exc),
        }

    duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
    if int(proc.returncode) != 0:
        return local_classification, {
            "status": "nonzero-exit",
            "applied": False,
            "duration_ms": duration_ms,
            "stderr_tail": _tail_text(proc.stderr),
        }

    parsed = _extract_json_object(proc.stdout)
    if parsed is None:
        return local_classification, {
            "status": "invalid-json",
            "applied": False,
            "duration_ms": duration_ms,
            "stdout_tail": _tail_text(proc.stdout),
            "stderr_tail": _tail_text(proc.stderr),
        }

    normalized = normalize_vault_classification(
        parsed,
        candidate_categories=candidate_categories,
        fallback_primary=str(local_classification.get("primary_label", "") or ""),
        fallback_confidence=float(local_classification.get("confidence", 0.0) or 0.0),
        fallback_secondary=[str(item) for item in (local_classification.get("secondary_labels", []) or [])],
    )
    normalized["candidate_categories_used"] = [
        str(item).strip()
        for item in candidate_categories
        if str(item).strip()
    ]
    return normalized, {
        "status": "applied",
        "applied": True,
        "duration_ms": duration_ms,
        "command": cmd,
    }
