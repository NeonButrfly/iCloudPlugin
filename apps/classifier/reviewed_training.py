from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .external_taxonomy import load_external_taxonomy_aliases, load_external_taxonomy_prune_rules, match_external_taxonomy_candidates
from .label_map import canonicalize_label
from packages.runtime import load_classifier_runtime_settings

SETTINGS = load_classifier_runtime_settings()
DEFAULT_MANIFEST_PATH = Path(
    r"C:\Users\Keifm\AppData\Local\Temp\lightgbm-training-set\lightgbm-training-set.combined.manifest.json"
)
EXAMPLES_PATH = SETTINGS.examples_path
REPORT_PATH = SETTINGS.reviewed_examples_report_path

DEFAULT_TARGET_LABELS: dict[str, int] = {
    "appeal": 25,
    "benefits": 15,
    "claim": 10,
    "invoice": 12,
    "receipt": 12,
    "medical-receipt": 10,
    "reimbursement-packet": 8,
    "contract": 8,
    "product-photo": 8,
}


def _split_csv_labels(value: Any) -> list[str]:
    return [
        item.strip()
        for item in str(value or "").split(",")
        if item and item.strip()
    ]


def _load_manifest_rows(manifest_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    return [row for row in rows if isinstance(row, dict)]


def _row_to_example(row: dict[str, Any]) -> dict[str, Any]:
    secondary_labels = _split_csv_labels(row.get("secondary_labels"))
    summary_parts = [
        str(row.get("reason") or "").strip(),
        str(row.get("evidence_excerpt") or "").strip(),
        str(row.get("evidence_terms") or "").strip(),
    ]
    summary = " ".join(part for part in summary_parts if part).strip()
    return {
        "kind": "reviewed_manifest",
        "filename": str(row.get("file_name") or row.get("source_path") or "unknown"),
        "source_filename": str(row.get("source_path") or row.get("file_name") or "unknown"),
        "source_path": str(row.get("source_full_path") or row.get("source_path") or ""),
        "correct_label": str(row.get("final_label") or "unknown"),
        "primary_label": str(row.get("final_label") or "unknown"),
        "secondary_labels": secondary_labels,
        "summary": summary,
        "note": str(row.get("queue_notes") or row.get("reason") or "").strip(),
        "old_label": str(row.get("queue_label") or row.get("heuristic_label") or ""),
        "review_status": str(row.get("review_status") or ""),
        "confidence": row.get("confidence"),
    }


def import_reviewed_examples_from_manifest(
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    examples_path: Path = EXAMPLES_PATH,
    report_path: Path = REPORT_PATH,
    target_labels: dict[str, int] | None = None,
) -> dict[str, Any]:
    rows = _load_manifest_rows(manifest_path)
    targets = dict(DEFAULT_TARGET_LABELS)
    if target_labels:
        targets.update(target_labels)

    selected: list[dict[str, Any]] = []
    selected_by_label: Counter[str] = Counter()

    for label, limit in targets.items():
        candidates = [
            row for row in rows
            if str(row.get("final_label") or "") == label
        ]
        candidates.sort(
            key=lambda row: (
                str(row.get("review_status") or "") != "confirmed",
                str(row.get("queue_label") or "") == str(row.get("final_label") or ""),
                -float(row.get("confidence") or 0.0),
                str(row.get("file_name") or ""),
            )
        )
        for row in candidates[:limit]:
            selected.append(_row_to_example(row))
            selected_by_label[label] += 1

    seen_filenames: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in selected:
        key = f"{row['filename']}::{row['correct_label']}"
        if key in seen_filenames:
            continue
        seen_filenames.add(key)
        deduped.append(row)

    deduped_label_counts = Counter(str(row.get("correct_label") or "unknown") for row in deduped)

    examples_path.parent.mkdir(parents=True, exist_ok=True)
    examples_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in deduped),
        encoding="utf-8",
    )

    report = {
        "ok": True,
        "manifest_path": str(manifest_path),
        "examples_path": str(examples_path),
        "imported_rows": len(deduped),
        "label_counts": dict(sorted(deduped_label_counts.items())),
        "target_labels": targets,
        "noisy_alias_summary": build_noisy_alias_summary(rows),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def build_noisy_alias_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    aliases = load_external_taxonomy_aliases()
    prune_rules = load_external_taxonomy_prune_rules()
    noisy_hits: Counter[tuple[str, tuple[str, ...]]] = Counter()
    helpful_hits: Counter[tuple[str, tuple[str, ...]]] = Counter()
    per_label_truths: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        truth = str(row.get("final_label") or "unknown")
        truth_canonical = canonicalize_label(truth)
        text = " ".join(
            part for part in [
                str(row.get("file_name") or ""),
                str(row.get("evidence_excerpt") or ""),
                str(row.get("reason") or ""),
                str(row.get("evidence_terms") or ""),
                str(row.get("source_meta") or ""),
            ]
            if part
        )
        matches = match_external_taxonomy_candidates(
            text,
            aliases=aliases,
            prune_rules=prune_rules,
            limit=8,
        )
        for match in matches:
            label = str(match["label"])
            evidence = tuple(str(item) for item in match.get("evidence", []))
            key = (label, evidence)
            if canonicalize_label(label) == truth_canonical or label == truth:
                helpful_hits[key] += 1
            else:
                noisy_hits[key] += 1
                per_label_truths[label][truth_canonical] += 1

    return {
        "top_noisy_aliases": [
            {
                "label": label,
                "evidence": list(evidence),
                "count": count,
            }
            for (label, evidence), count in noisy_hits.most_common(20)
        ],
        "top_helpful_aliases": [
            {
                "label": label,
                "evidence": list(evidence),
                "count": count,
            }
            for (label, evidence), count in helpful_hits.most_common(20)
        ],
        "per_label_mismatch_targets": {
            label: dict(counter.most_common(8))
            for label, counter in sorted(per_label_truths.items(), key=lambda item: -sum(item[1].values()))[:12]
        },
    }


def main() -> None:
    report = import_reviewed_examples_from_manifest()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
