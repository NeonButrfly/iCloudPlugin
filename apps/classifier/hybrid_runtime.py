import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import LabelEncoder

from packages.runtime import load_classifier_runtime_settings
from .external_taxonomy import build_external_taxonomy_hint_text
from .label_map import canonicalize_label, canonicalize_labels

SETTINGS = load_classifier_runtime_settings()
CONFIG_DIR = SETTINGS.config_root
OUTPUT_ROOT = SETTINGS.output_root

HYBRID_GATING_PATH = SETTINGS.hybrid_gating_path
HEURISTIC_RULES_PATH = SETTINGS.heuristic_rules_path
LIGHTGBM_MODEL_PATH = SETTINGS.lightgbm_model_path
LIGHTGBM_REPORT_PATH = SETTINGS.lightgbm_report_path
SHADOW_QUEUE_DIR = SETTINGS.shadow_queue_dir
SHADOW_COMPARISONS_PATH = SETTINGS.shadow_comparisons_path
READINESS_REPORT_PATH = SETTINGS.readiness_report_path
RETRAIN_DIR = SETTINGS.retrain_dir
MANIFEST_PATH = SETTINGS.manifest_path
CORRECTIONS_PATH = SETTINGS.corrections_path
EXAMPLES_PATH = SETTINGS.examples_path
MANUAL_NOTE_FEEDBACK_PATH = SETTINGS.manual_note_feedback_path

DEFAULT_HYBRID_GATING = {
    "mode": "hybrid",
    "heuristic_fast_confidence": 0.92,
    "lightgbm_fast_confidence": 0.80,
    "aligned_soft_confidence": 0.60,
    "needs_llm_threshold": 0.45,
    "disagreement_risk_threshold": 0.35,
    "teacher_confidence_threshold": 0.85,
    "shadow_mode": "all",
    "shadow_sample_rate": 1.0,
    "auto_retrain_enabled": True,
    "auto_threshold_update_enabled": True,
    "shadow_batch_size": 25,
    "auto_retrain_min_rows": 25,
    "auto_retrain_min_new_rows": 10,
    "auto_inline_disagreement_threshold": 3,
    "readiness_min_teacher_samples": 10,
    "readiness_min_unique_teacher_files": 10,
    "readiness_min_teacher_extensions": 6,
    "readiness_min_teacher_labels": 5,
    "readiness_min_teacher_agreement_rate": 0.80,
    "readiness_min_teacher_approval_rate": 0.70,
    "readiness_max_queue_depth": 25,
    "allow_real_ingestion": False,
}

DEFAULT_HEURISTIC_RULES = {
    "document_fast_path": {
        "legal_agreement_min_score": 6,
        "technical_incident_min_score": 6,
        "technical_report_min_score": 4,
    },
    "spreadsheet_fast_path": {
        "enabled": True,
    },
    "force_inline_llm_for": [],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc_timestamp(raw_value: Any) -> datetime | None:
    if not isinstance(raw_value, str):
        return None
    text = raw_value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _copy_if_missing(target_path: Path, filename: str) -> bool:
    if target_path.exists():
        return False
    source_path = SETTINGS.resolve_existing_config_path(filename, include_artifact=False)
    if source_path is None or source_path == target_path or not source_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return True


def ensure_runtime_artifacts_bootstrapped() -> Dict[str, Any]:
    bootstrapped = []
    for filename, target_path in [
        ("hybrid-gating.json", HYBRID_GATING_PATH),
        ("heuristic-rules.json", HEURISTIC_RULES_PATH),
        ("lightgbm-classifier.joblib", LIGHTGBM_MODEL_PATH),
        ("lightgbm-training-report.json", LIGHTGBM_REPORT_PATH),
        ("taxonomy-router.joblib", SETTINGS.taxonomy_router_model_path),
        ("taxonomy-router-report.json", SETTINGS.taxonomy_router_report_path),
    ]:
        if _copy_if_missing(target_path, filename):
            bootstrapped.append(filename)
    return {
        "ok": True,
        "bootstrapped": bootstrapped,
    }


def load_hybrid_gating_config(path: Optional[Path] = None) -> Dict[str, Any]:
    merged = dict(DEFAULT_HYBRID_GATING)
    active_path = path or HYBRID_GATING_PATH
    source_path = active_path
    if not source_path.exists():
        source_path = SETTINGS.resolve_existing_config_path("hybrid-gating.json", include_artifact=False) or active_path
    merged.update(load_json(source_path, default={}) or {})
    return merged


def load_heuristic_rules(path: Optional[Path] = None) -> Dict[str, Any]:
    merged = json.loads(json.dumps(DEFAULT_HEURISTIC_RULES))
    active_path = path or HEURISTIC_RULES_PATH
    source_path = active_path
    if not source_path.exists():
        source_path = SETTINGS.resolve_existing_config_path("heuristic-rules.json", include_artifact=False) or active_path
    loaded = load_json(source_path, default={}) or {}
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def choose_live_decision(
    heuristic_result: Optional[Dict[str, Any]],
    lightgbm_result: Optional[Dict[str, Any]],
    gating_config: Dict[str, Any],
    candidate_categories: Optional[list[str]] = None,
) -> Dict[str, Any]:
    heuristic_result = heuristic_result or {}
    lightgbm_result = lightgbm_result or {}
    candidate_categories = candidate_categories or []

    heuristic_primary = str(heuristic_result.get("primary_label", "unknown") or "unknown")
    heuristic_confidence = float(heuristic_result.get("confidence", 0.0) or 0.0)
    model_primary = str(lightgbm_result.get("top_label", heuristic_primary) or heuristic_primary)
    model_confidence = float(lightgbm_result.get("top_probability", 0.0) or 0.0)
    needs_llm_probability = float(lightgbm_result.get("needs_llm_probability", 1.0) or 0.0)
    disagreement_risk = float(lightgbm_result.get("disagreement_risk", 1.0) or 0.0)

    canonical_heuristic_primary = canonicalize_label(heuristic_primary)
    canonical_model_primary = canonicalize_label(model_primary)

    aligned = canonical_heuristic_primary == canonical_model_primary
    heuristic_ready = heuristic_confidence >= float(gating_config["heuristic_fast_confidence"])
    model_ready = model_confidence >= float(gating_config["lightgbm_fast_confidence"])
    aligned_soft_ready = aligned and model_confidence >= float(gating_config.get("aligned_soft_confidence", 0.60))
    low_llm_need = needs_llm_probability < float(gating_config["needs_llm_threshold"])
    low_disagreement = disagreement_risk < float(gating_config["disagreement_risk_threshold"])
    strong_alignment = aligned and heuristic_ready and model_ready and low_disagreement
    soft_alignment = aligned and heuristic_ready and aligned_soft_ready and low_llm_need and low_disagreement

    if strong_alignment or soft_alignment:
        return {
            "use_inline_llm": False,
            "live_source": "heuristic-fast-path",
            "selected_primary_hint": canonical_heuristic_primary,
            "decision_reason": "fast-path-aligned",
            "candidate_count": len(candidate_categories),
            "heuristic_confidence": heuristic_confidence,
            "lightgbm_confidence": model_confidence,
            "needs_llm_probability": needs_llm_probability,
            "disagreement_risk": disagreement_risk,
        }

    return {
        "use_inline_llm": True,
        "live_source": "inline-llm",
        "selected_primary_hint": canonical_model_primary,
        "decision_reason": "model-required",
        "candidate_count": len(candidate_categories),
        "heuristic_confidence": heuristic_confidence,
        "lightgbm_confidence": model_confidence,
        "needs_llm_probability": needs_llm_probability,
        "disagreement_risk": disagreement_risk,
    }


def build_shadow_record(
    filename: str,
    extension: str,
    parser: Optional[str],
    heuristic_result: Optional[Dict[str, Any]],
    lightgbm_result: Optional[Dict[str, Any]],
    live_result: Optional[Dict[str, Any]],
    llm_result: Optional[Dict[str, Any]],
    taxonomy_candidates: list[str],
    text_preview: str,
    live_source: str = "",
    entity_summary: str = "",
    topic_summary: str = "",
    retrieval_terms: Optional[list[str]] = None,
    retrieval_text: str = "",
    ocr_engine: str = "",
    ocr_quality: str = "",
    ocr_char_count: int = 0,
    extraction_quality: str = "",
) -> Dict[str, Any]:
    heuristic_result = heuristic_result or {}
    lightgbm_result = lightgbm_result or {}
    live_result = live_result or {}
    llm_result = llm_result or {}

    heuristic_primary = str(heuristic_result.get("primary_label", "unknown") or "unknown")
    lightgbm_primary = str(lightgbm_result.get("top_label", "unknown") or "unknown")
    live_primary = str(live_result.get("primary_label", "unknown") or "unknown")
    shadow_primary = str(llm_result.get("primary_label", "unknown") or "unknown")
    teacher_review = evaluate_teacher_result(
        llm_result=llm_result,
        taxonomy_candidates=taxonomy_candidates,
        live_result=live_result,
        gating_config=load_hybrid_gating_config(),
    )

    return {
        "recorded_at": utc_now(),
        "filename": filename,
        "extension": extension,
        "parser": parser,
        "heuristic_primary": heuristic_primary,
        "heuristic_confidence": heuristic_result.get("confidence"),
        "lightgbm_primary": lightgbm_primary,
        "lightgbm_confidence": lightgbm_result.get("top_probability"),
        "needs_llm_probability": lightgbm_result.get("needs_llm_probability"),
        "disagreement_risk": lightgbm_result.get("disagreement_risk"),
        "live_primary": live_primary,
        "live_source": live_source,
        "shadow_primary": shadow_primary,
        "shadow_confidence": llm_result.get("confidence"),
        "taxonomy_candidates": taxonomy_candidates,
        "disagreement": live_primary != shadow_primary,
        "teacher_review_status": teacher_review["review_status"],
        "teacher_reason": teacher_review["reason"],
        "teacher_approved_for_training": teacher_review["teacher_approved_for_training"],
        "teacher_supports_live_result": teacher_review["teacher_supports_live_result"],
        "teacher_suggests_correction": teacher_review["teacher_suggests_correction"],
        "entity_summary": entity_summary,
        "topic_summary": topic_summary,
        "retrieval_terms": retrieval_terms or [],
        "retrieval_text": retrieval_text[:4000],
        "ocr_engine": ocr_engine,
        "ocr_quality": ocr_quality,
        "ocr_char_count": int(ocr_char_count or 0),
        "extraction_quality": extraction_quality,
        "text_preview": text_preview[:4000],
    }


def evaluate_teacher_result(
    llm_result: Optional[Dict[str, Any]],
    taxonomy_candidates: list[str],
    live_result: Optional[Dict[str, Any]],
    gating_config: Dict[str, Any],
) -> Dict[str, Any]:
    llm_result = llm_result or {}
    live_result = live_result or {}
    taxonomy_candidates = taxonomy_candidates or []

    teacher_primary = str(llm_result.get("primary_label", "unknown") or "unknown")
    live_primary = str(live_result.get("primary_label", "unknown") or "unknown")
    teacher_confidence = safe_float(llm_result.get("confidence"), 0.0)
    confidence_ok = teacher_confidence >= safe_float(gating_config.get("teacher_confidence_threshold"), 0.85)
    in_candidate_set = not taxonomy_candidates or teacher_primary in taxonomy_candidates
    supports_live = teacher_primary == live_primary
    suggests_correction = teacher_primary != live_primary and teacher_primary != "unknown"

    if not confidence_ok:
        return {
            "review_status": "teacher-low-confidence",
            "reason": "teacher-confidence-below-threshold",
            "teacher_approved_for_training": False,
            "teacher_supports_live_result": supports_live,
            "teacher_suggests_correction": False,
        }

    if not in_candidate_set:
        return {
            "review_status": "teacher-outside-candidates",
            "reason": "teacher-label-outside-taxonomy-candidates",
            "teacher_approved_for_training": False,
            "teacher_supports_live_result": False,
            "teacher_suggests_correction": False,
        }

    return {
        "review_status": "teacher-approved",
        "reason": "teacher-approved-for-training",
        "teacher_approved_for_training": True,
        "teacher_supports_live_result": supports_live,
        "teacher_suggests_correction": suggests_correction,
    }


def build_feature_text(payload: Dict[str, Any]) -> str:
    filename = str(payload.get("filename", ""))
    extension = str(payload.get("extension", ""))
    parser = str(payload.get("parser", ""))
    heuristic_primary = canonicalize_label(payload.get("heuristic_primary", ""))
    taxonomy_candidates = " ".join(canonicalize_labels(payload.get("taxonomy_candidates", []) or []))
    entity_summary = str(payload.get("entity_summary", ""))
    topic_summary = str(payload.get("topic_summary", ""))
    retrieval_text = str(payload.get("retrieval_text", ""))
    retrieval_terms = " ".join(
        str(item)
        for item in (payload.get("retrieval_terms", []) or [])
        if str(item).strip()
    )
    ocr_engine = str(payload.get("ocr_engine", ""))
    ocr_quality = str(payload.get("ocr_quality", ""))
    ocr_char_count = payload.get("ocr_char_count", "")
    extraction_quality = str(payload.get("extraction_quality", ""))
    text_preview = str(payload.get("text_preview", ""))[:12000]
    external_hint_text = build_external_taxonomy_hint_text(
        f"{filename}\n{topic_summary}\n{entity_summary}\n{retrieval_text}\n{text_preview}",
        limit=6,
    )
    return " ".join(
        [
            filename,
            extension,
            parser,
            f"heuristic {heuristic_primary}",
            f"taxonomy {taxonomy_candidates}",
            f"topics {topic_summary}" if topic_summary else "",
            f"entities {entity_summary}" if entity_summary else "",
            f"retrieval-terms {retrieval_terms}" if retrieval_terms else "",
            f"retrieval-text {retrieval_text}" if retrieval_text else "",
            f"ocr-engine {ocr_engine}" if ocr_engine else "",
            f"ocr-quality {ocr_quality}" if ocr_quality else "",
            f"ocr-chars {ocr_char_count}" if str(ocr_char_count).strip() else "",
            f"extraction-quality {extraction_quality}" if extraction_quality else "",
            f"external-taxonomy {external_hint_text}" if external_hint_text else "",
            text_preview,
        ]
    ).strip()


def _train_binary_model(matrix, values):
    unique = sorted(set(int(v) for v in values))
    if len(unique) <= 1:
        return {"kind": "constant", "value": float(unique[0] if unique else 0)}

    import lightgbm as lgb

    model = lgb.LGBMClassifier(
        objective="binary",
        n_estimators=40,
        num_leaves=15,
        min_data_in_leaf=1,
        random_state=7,
        verbose=-1,
    )
    model.fit(matrix, np.array(values, dtype=np.int32))
    return {"kind": "lightgbm", "model": model}


def _predict_binary_model(model_artifact, matrix) -> float:
    if model_artifact.get("kind") == "constant":
        return float(model_artifact.get("value", 0.0))
    model = model_artifact["model"]
    probabilities = model.predict_proba(matrix)[0]
    return float(probabilities[1] if len(probabilities) > 1 else probabilities[0])


def train_lightgbm_model(
    training_rows: list[Dict[str, Any]],
    model_path: Path,
    report_path: Path,
) -> Dict[str, Any]:
    rows = [row for row in training_rows if row.get("accepted_primary")]
    if not rows:
        raise ValueError("No training rows with accepted_primary available.")

    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        normalized["heuristic_primary"] = canonicalize_label(normalized.get("heuristic_primary"))
        normalized["accepted_primary"] = canonicalize_label(normalized.get("accepted_primary"))
        normalized["taxonomy_candidates"] = canonicalize_labels(normalized.get("taxonomy_candidates", []))
        normalized_rows.append(normalized)

    texts = [build_feature_text(row) for row in normalized_rows]
    labels = [str(row["accepted_primary"]) for row in normalized_rows]
    needs_llm_targets = [1 if row.get("used_inline_llm") else 0 for row in normalized_rows]
    disagreement_targets = [1 if row.get("disagreement") else 0 for row in normalized_rows]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        analyzer="word",
        ngram_range=(1, 2),
        max_features=12000,
        min_df=1,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )
    matrix = vectorizer.fit_transform(texts)

    label_encoder = LabelEncoder()
    y = label_encoder.fit_transform(labels)

    import lightgbm as lgb

    label_model = lgb.LGBMClassifier(
        objective="multiclass",
        n_estimators=60,
        num_leaves=15,
        min_data_in_leaf=1,
        random_state=7,
        verbose=-1,
    )
    label_model.fit(matrix, y)

    model_artifact = {
        "kind": "hybrid-lightgbm-v1",
        "vectorizer": vectorizer,
        "label_encoder": label_encoder,
        "label_model": label_model,
        "needs_llm_model": _train_binary_model(matrix, needs_llm_targets),
        "disagreement_model": _train_binary_model(matrix, disagreement_targets),
        "trained_at": utc_now(),
        "training_rows": len(normalized_rows),
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model_artifact, model_path, compress=3)

    report = {
        "ok": True,
        "kind": model_artifact["kind"],
        "trained_at": model_artifact["trained_at"],
        "training_rows": len(normalized_rows),
        "class_count": len(label_encoder.classes_),
        "features": len(vectorizer.vocabulary_),
        "model_path": str(model_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def predict_lightgbm_result(payload: Dict[str, Any], model_path: Path) -> Dict[str, Any]:
    model_artifact = joblib.load(model_path)
    matrix = model_artifact["vectorizer"].transform([build_feature_text(payload)])
    probabilities = model_artifact["label_model"].predict_proba(matrix)[0]
    classes = model_artifact["label_encoder"].classes_
    order = np.argsort(probabilities)[::-1]
    top_labels = [str(classes[idx]) for idx in order[:5]]
    top_label = top_labels[0] if top_labels else "unknown"
    top_probability = float(probabilities[order[0]]) if len(order) else 0.0

    return {
        "top_label": top_label,
        "top_probability": top_probability,
        "top_labels": top_labels,
        "label_probabilities": {
            str(classes[idx]): float(probabilities[idx])
            for idx in order[: min(10, len(order))]
        },
        "needs_llm_probability": _predict_binary_model(model_artifact["needs_llm_model"], matrix),
        "disagreement_risk": _predict_binary_model(model_artifact["disagreement_model"], matrix),
    }


def enqueue_shadow_job(payload: Dict[str, Any], queue_dir: Path = SHADOW_QUEUE_DIR) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    job_path = queue_dir / f"{utc_now().replace(':', '-')}-{uuid.uuid4().hex}.json"
    save_json(job_path, payload)
    return job_path


def append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def read_jsonl(path: Path, limit: Optional[int] = None) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[Dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit is not None:
        lines = lines[-limit:]
    for line in lines:
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _manual_feedback_row_is_effective(item: Dict[str, Any]) -> bool:
    review_status = str(item.get("review_status", "") or "").strip().lower()
    correct_label = str(item.get("correct_label") or item.get("primary_label") or item.get("label") or "").strip()
    old_label = str(item.get("old_label", "") or "").strip()
    if review_status == "manual-note-move" and correct_label and old_label and correct_label == old_label:
        secondary_labels = {
            str(value).strip().lower()
            for value in (item.get("secondary_labels", []) or [])
            if str(value).strip()
        }
        old_secondary_labels = {
            str(value).strip().lower()
            for value in (item.get("old_secondary_labels", []) or [])
            if str(value).strip()
        }
        if secondary_labels == old_secondary_labels:
            return False
    return True


def build_bootstrap_feedback_rows(
    *,
    corrections_path: Path = CORRECTIONS_PATH,
    examples_path: Path = EXAMPLES_PATH,
    manual_note_feedback_path: Path = MANUAL_NOTE_FEEDBACK_PATH,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []
    for source_name, path in [
        ("correction", corrections_path),
        ("reviewed-example", examples_path),
        ("manual-obsidian-note", manual_note_feedback_path),
    ]:
        for item in read_jsonl(path, limit=1000):
            if source_name == "manual-obsidian-note" and not _manual_feedback_row_is_effective(item):
                continue
            accepted_primary = str(
                item.get("correct_label") or item.get("primary_label") or item.get("label") or ""
            ).strip()
            if not accepted_primary:
                continue
            filename = str(
                item.get("filename")
                or item.get("source_filename")
                or Path(str(item.get("source_path") or "example")).name
                or "example"
            ).strip()
            extension = (
                Path(filename).suffix.lower()
                or Path(str(item.get("source_path") or filename)).suffix.lower()
            )
            text_preview = " ".join(
                filter(
                    None,
                    [
                        str(item.get("source_path", "")),
                        str(item.get("summary", "")),
                        str(item.get("note", "")),
                        str(item.get("old_label", "")),
                        str(item.get("teacher_primary", "")),
                        " ".join(map(str, item.get("teacher_evidence", []) or [])),
                        " ".join(map(str, item.get("secondary_labels", []) or [])),
                        " ".join(map(str, item.get("retrieval_terms", []) or [])),
                    ],
                )
            )
            rows.append(
                {
                    "recorded_at": str(item.get("recorded_at") or utc_now()),
                    "filename": filename,
                    "extension": extension,
                    "parser": str(item.get("parser", "")),
                    "heuristic_primary": str(
                        item.get("heuristic_primary")
                        or item.get("old_label")
                        or accepted_primary
                        or "unknown"
                    ),
                    "live_primary": accepted_primary,
                    "shadow_primary": accepted_primary,
                    "taxonomy_candidates": item.get("secondary_labels", []) or [],
                    "teacher_review_status": str(item.get("review_status") or "teacher-approved-bootstrap"),
                    "teacher_reason": "reviewed-corpus-bootstrap",
                    "teacher_approved_for_training": True,
                    "teacher_supports_live_result": True,
                    "teacher_suggests_correction": bool(str(item.get("old_label") or "").strip()),
                    "entity_summary": str(item.get("entity_summary", "")),
                    "topic_summary": str(item.get("topic_summary", "")),
                    "retrieval_terms": item.get("retrieval_terms", []) or [],
                    "retrieval_text": str(item.get("retrieval_text", "")),
                    "ocr_engine": str(item.get("ocr_engine", "")),
                    "ocr_quality": str(item.get("ocr_quality", "")),
                    "ocr_char_count": int(item.get("ocr_char_count", 0) or 0),
                    "extraction_quality": str(item.get("extraction_quality", "")),
                    "text_preview": text_preview[:4000],
                    "shadow_confidence": safe_float(item.get("confidence"), 1.0),
                    "feedback_source": source_name,
                }
            )
    return rows


def build_feedback_rows(
    *,
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
    corrections_path: Path = CORRECTIONS_PATH,
    examples_path: Path = EXAMPLES_PATH,
    manual_note_feedback_path: Path = MANUAL_NOTE_FEEDBACK_PATH,
) -> list[Dict[str, Any]]:
    rows = []
    for item in read_jsonl(comparisons_path, limit=2000):
        if isinstance(item, dict):
            enriched = dict(item)
            enriched.setdefault("feedback_source", "shadow-qwen")
            rows.append(enriched)
    rows.extend(
        build_bootstrap_feedback_rows(
            corrections_path=corrections_path,
            examples_path=examples_path,
            manual_note_feedback_path=manual_note_feedback_path,
        )
    )
    return rows


def process_shadow_queue_once(
    queue_dir: Path = SHADOW_QUEUE_DIR,
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
    shadow_classifier=None,
    max_jobs: int | None = None,
) -> int:
    if shadow_classifier is None:
        return 0

    processed = 0
    for job_path in sorted(queue_dir.glob("*.json")):
        if max_jobs is not None and processed >= max_jobs:
            break
        job = load_json(job_path, default={}) or {}
        try:
            llm_result = shadow_classifier(job)
            comparison = build_shadow_record(
                filename=str(job.get("filename", "")),
                extension=str(job.get("extension", "")),
                parser=job.get("parser"),
                heuristic_result=job.get("heuristic_result"),
                lightgbm_result=job.get("lightgbm_result"),
                live_result=job.get("live_result"),
                llm_result=llm_result,
                taxonomy_candidates=job.get("taxonomy_candidates", []) or [],
                text_preview=str(job.get("text_preview", "")),
                live_source=str(job.get("live_source", "")),
                entity_summary=str(job.get("entity_summary", "")),
                topic_summary=str(job.get("topic_summary", "")),
                retrieval_terms=job.get("retrieval_terms", []) or [],
                retrieval_text=str(job.get("retrieval_text", "")),
                ocr_engine=str(job.get("ocr_engine", "")),
                ocr_quality=str(job.get("ocr_quality", "")),
                ocr_char_count=int(job.get("ocr_char_count", 0) or 0),
                extraction_quality=str(job.get("extraction_quality", "")),
            )
        except Exception as exc:
            heuristic_result = job.get("heuristic_result") or {}
            lightgbm_result = job.get("lightgbm_result") or {}
            live_result = job.get("live_result") or {}
            comparison = {
                "recorded_at": utc_now(),
                "filename": str(job.get("filename", "")),
                "extension": str(job.get("extension", "")),
                "parser": job.get("parser"),
                "heuristic_primary": str(heuristic_result.get("primary_label", "unknown") or "unknown"),
                "heuristic_confidence": heuristic_result.get("confidence"),
                "lightgbm_primary": str(lightgbm_result.get("top_label", "unknown") or "unknown"),
                "lightgbm_confidence": lightgbm_result.get("top_probability"),
                "needs_llm_probability": lightgbm_result.get("needs_llm_probability"),
                "disagreement_risk": lightgbm_result.get("disagreement_risk"),
                "live_primary": str(live_result.get("primary_label", "unknown") or "unknown"),
                "live_source": str(job.get("live_source", "")),
                "shadow_primary": "unknown",
                "shadow_confidence": 0.0,
                "taxonomy_candidates": job.get("taxonomy_candidates", []) or [],
                "disagreement": False,
                "teacher_review_status": "shadow-error",
                "teacher_reason": str(exc),
                "teacher_approved_for_training": False,
                "teacher_supports_live_result": False,
                "teacher_suggests_correction": False,
                "entity_summary": str(job.get("entity_summary", "")),
                "topic_summary": str(job.get("topic_summary", "")),
                "retrieval_terms": job.get("retrieval_terms", []) or [],
                "retrieval_text": str(job.get("retrieval_text", ""))[:4000],
                "ocr_engine": str(job.get("ocr_engine", "")),
                "ocr_quality": str(job.get("ocr_quality", "")),
                "ocr_char_count": int(job.get("ocr_char_count", 0) or 0),
                "extraction_quality": str(job.get("extraction_quality", "")),
                "text_preview": str(job.get("text_preview", ""))[:4000],
                "feedback_source": "shadow-qwen",
                "shadow_error": str(exc),
            }
        append_jsonl(comparisons_path, comparison)
        try:
            job_path.unlink()
        except Exception:
            pass
        processed += 1
    return processed


def apply_disagreement_updates(
    comparisons: list[Dict[str, Any]],
    feedback_rows: list[Dict[str, Any]] | None = None,
    gating_path: Path = HYBRID_GATING_PATH,
    rules_path: Path = HEURISTIC_RULES_PATH,
) -> Dict[str, Any]:
    gating = load_hybrid_gating_config(gating_path)
    rules = load_heuristic_rules(rules_path)
    threshold = int(gating.get("auto_inline_disagreement_threshold", 3))

    counts: Dict[str, int] = {}
    for item in comparisons:
        if not item.get("disagreement"):
            continue
        key = f"{item.get('parser', 'unknown')}|{item.get('heuristic_primary', 'unknown')}"
        counts[key] = counts.get(key, 0) + 1

    for item in feedback_rows or []:
        if str(item.get("feedback_source", "")).strip() != "manual-obsidian-note":
            continue
        if not item.get("teacher_suggests_correction"):
            continue
        parser = str(item.get("parser", "") or "").strip()
        heuristic_primary = str(item.get("heuristic_primary", "") or "").strip()
        if not parser or parser.startswith("obsidian"):
            continue
        if not heuristic_primary:
            continue
        key = f"{parser}|{heuristic_primary}"
        counts[key] = counts.get(key, 0) + 1

    forced = set(rules.get("force_inline_llm_for", []) or [])
    updated = False

    for key, count in counts.items():
        if count >= threshold and key not in forced:
            forced.add(key)
            updated = True

    if updated:
        rules["force_inline_llm_for"] = sorted(forced)
        gating["heuristic_fast_confidence"] = max(
            0.75,
            round(float(gating["heuristic_fast_confidence"]) - 0.02, 4),
        )
        save_json(gating_path, gating)
        save_json(rules_path, rules)

    return {
        "updated": updated,
        "forced_rule_count": len(forced),
        "heuristic_fast_confidence": gating["heuristic_fast_confidence"],
    }


def maybe_retrain_from_shadow_data(
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
    corrections_path: Path = CORRECTIONS_PATH,
    examples_path: Path = EXAMPLES_PATH,
    manual_note_feedback_path: Path = MANUAL_NOTE_FEEDBACK_PATH,
    model_path: Path = LIGHTGBM_MODEL_PATH,
    report_path: Path = LIGHTGBM_REPORT_PATH,
    min_rows: int = 25,
    min_new_rows_since_last_train: int = 0,
) -> Dict[str, Any]:
    ensure_runtime_artifacts_bootstrapped()
    feedback_rows = build_feedback_rows(
        comparisons_path=comparisons_path,
        corrections_path=corrections_path,
        examples_path=examples_path,
        manual_note_feedback_path=manual_note_feedback_path,
    )
    approved = [row for row in feedback_rows if row.get("teacher_approved_for_training")]
    if len(approved) < min_rows:
        return {
            "retrained": False,
            "reason": "insufficient-approved-rows",
            "training_rows": len(approved),
            "teacher_approved_rows": len(approved),
        }

    previous_training_rows = 0
    previous_trained_at: datetime | None = None
    prior_report = load_json(report_path, default={}) or {}
    if isinstance(prior_report, dict):
        try:
            previous_training_rows = int(prior_report.get("training_rows", 0) or 0)
        except Exception:
            previous_training_rows = 0
        previous_trained_at = parse_utc_timestamp(prior_report.get("trained_at"))

    new_rows = max(len(approved) - previous_training_rows, 0)
    new_manual_teacher_rows = 0
    if previous_trained_at is not None:
        for row in approved:
            if str(row.get("feedback_source", "") or "").strip() != "manual-obsidian-note":
                continue
            row_recorded_at = parse_utc_timestamp(row.get("recorded_at"))
            if row_recorded_at is not None and row_recorded_at > previous_trained_at:
                new_manual_teacher_rows += 1
    should_bypass_new_row_threshold = new_manual_teacher_rows > 0

    if (
        previous_training_rows > 0
        and new_rows < min_new_rows_since_last_train
        and not should_bypass_new_row_threshold
    ):
        return {
            "retrained": False,
            "reason": "insufficient-new-approved-rows",
            "training_rows": len(approved),
            "teacher_approved_rows": len(approved),
            "new_teacher_rows": new_rows,
            "new_manual_teacher_rows": new_manual_teacher_rows,
            "previous_training_rows": previous_training_rows,
        }

    training_rows = []
    feedback_sources: Dict[str, int] = {}
    for row in approved:
        source_name = str(row.get("feedback_source", "shadow-qwen") or "shadow-qwen")
        feedback_sources[source_name] = feedback_sources.get(source_name, 0) + 1
        training_rows.append(
            {
                "filename": row.get("filename", ""),
                "extension": row.get("extension", ""),
                "parser": row.get("parser", ""),
                "text_preview": row.get("text_preview", ""),
                "heuristic_primary": row.get("heuristic_primary", "unknown"),
                "taxonomy_candidates": row.get("taxonomy_candidates", []),
                "entity_summary": row.get("entity_summary", ""),
                "topic_summary": row.get("topic_summary", ""),
                "retrieval_terms": row.get("retrieval_terms", []),
                "retrieval_text": row.get("retrieval_text", ""),
                "ocr_engine": row.get("ocr_engine", ""),
                "ocr_quality": row.get("ocr_quality", ""),
                "ocr_char_count": int(row.get("ocr_char_count", 0) or 0),
                "extraction_quality": row.get("extraction_quality", ""),
                "accepted_primary": row.get("shadow_primary") or row.get("live_primary") or row.get("heuristic_primary") or "unknown",
                "used_inline_llm": source_name == "shadow-qwen",
                "disagreement": bool(row.get("disagreement")),
            }
        )

    report = train_lightgbm_model(
        training_rows=training_rows,
        model_path=model_path,
        report_path=report_path,
    )
    return {
        "retrained": True,
        "training_rows": len(training_rows),
        "teacher_approved_rows": len(approved),
        "new_teacher_rows": new_rows,
        "new_manual_teacher_rows": new_manual_teacher_rows,
        "previous_training_rows": previous_training_rows,
        "feedback_sources": dict(sorted(feedback_sources.items())),
        "report": report,
    }


def run_autonomous_shadow_cycle(
    *,
    shadow_classifier,
    gating_config: Optional[Dict[str, Any]] = None,
    queue_dir: Path = SHADOW_QUEUE_DIR,
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
    model_path: Path = LIGHTGBM_MODEL_PATH,
    report_path: Path = LIGHTGBM_REPORT_PATH,
) -> Dict[str, Any]:
    gating = gating_config or load_hybrid_gating_config()
    batch_size = max(int(gating.get("shadow_batch_size", 25) or 25), 1)
    processed = process_shadow_queue_once(
        queue_dir=queue_dir,
        comparisons_path=comparisons_path,
        shadow_classifier=shadow_classifier,
        max_jobs=batch_size,
    )
    comparisons = read_jsonl(comparisons_path, limit=max(batch_size * 8, 200))
    feedback_rows = build_feedback_rows(comparisons_path=comparisons_path)

    if bool(gating.get("auto_threshold_update_enabled", True)):
        updates = apply_disagreement_updates(
            comparisons=comparisons,
            feedback_rows=feedback_rows,
        )
    else:
        updates = {
            "updated": False,
            "skipped": True,
            "reason": "auto-threshold-update-disabled",
        }

    if bool(gating.get("auto_retrain_enabled", True)):
        retrain = maybe_retrain_from_shadow_data(
            comparisons_path=comparisons_path,
            model_path=model_path,
            report_path=report_path,
            min_rows=max(int(gating.get("auto_retrain_min_rows", 25) or 25), 1),
            min_new_rows_since_last_train=max(
                int(gating.get("auto_retrain_min_new_rows", 10) or 0),
                0,
            ),
        )
    else:
        retrain = {
            "retrained": False,
            "skipped": True,
            "reason": "auto-retrain-disabled",
        }

    return {
        "ok": True,
        "processed": processed,
        "updates": updates,
        "retrain": retrain,
        "readiness": write_readiness_report(gating_config=gating),
    }


def build_training_rows_from_runtime(
    manifest_path: Path = MANIFEST_PATH,
    corrections_path: Path = CORRECTIONS_PATH,
    examples_path: Path = EXAMPLES_PATH,
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
) -> list[Dict[str, Any]]:
    rows: list[Dict[str, Any]] = []

    for item in read_jsonl(manifest_path, limit=500):
        classification = item.get("classification") or {}
        if not item.get("ok") or not classification.get("primary_label"):
            continue
        rows.append(
            {
                "filename": Path(str(item.get("source_path", ""))).name,
                "extension": Path(str(item.get("source_path", ""))).suffix.lower(),
                "parser": (item.get("timing") or {}).get("parser", ""),
                "text_preview": " ".join(
                    filter(
                        None,
                        [
                            str(classification.get("summary", "")),
                            str(classification.get("reason", "")),
                            str(classification.get("entity_summary", "")),
                            str(classification.get("topic_summary", "")),
                            str(classification.get("retrieval_text", "")),
                            " ".join(map(str, classification.get("secondary_labels", []) or [])),
                            " ".join(map(str, classification.get("retrieval_terms", []) or [])),
                        ],
                    )
                ),
                "heuristic_primary": ((item.get("hybrid") or {}).get("decision") or {}).get("selected_primary_hint", classification.get("primary_label", "unknown")),
                "taxonomy_candidates": (item.get("hybrid") or {}).get("taxonomy_candidates", []) or classification.get("candidate_categories_used", []),
                "entity_summary": str(classification.get("entity_summary", "")),
                "topic_summary": str(classification.get("topic_summary", "")),
                "retrieval_terms": classification.get("retrieval_terms", []) or [],
                "retrieval_text": str(classification.get("retrieval_text", "")),
                "ocr_engine": str(classification.get("ocr_engine", "") or (item.get("timing") or {}).get("ocr_engine", "")),
                "ocr_quality": str(classification.get("ocr_quality", "") or (item.get("timing") or {}).get("ocr_quality", "")),
                "ocr_char_count": int(classification.get("ocr_char_count", 0) or (item.get("timing") or {}).get("ocr_chars", 0) or 0),
                "extraction_quality": str(classification.get("extraction_quality", "") or (item.get("timing") or {}).get("extraction_quality", "")),
                "accepted_primary": classification.get("primary_label"),
                "used_inline_llm": ((item.get("hybrid") or {}).get("decision") or {}).get("live_source") == "inline-llm",
                "disagreement": False,
            }
        )

    for item in read_jsonl(corrections_path, limit=500) + read_jsonl(examples_path, limit=500):
        accepted = item.get("correct_label") or item.get("primary_label") or item.get("label")
        if not accepted:
            continue
        rows.append(
            {
                "filename": str(item.get("filename") or item.get("source_filename") or "example"),
                "extension": Path(str(item.get("filename") or item.get("source_filename") or "example")).suffix.lower(),
                "parser": str(item.get("parser", "")),
                "text_preview": " ".join(
                    filter(
                        None,
                        [
                            str(item.get("source_path", "")),
                            str(item.get("summary", "")),
                            str(item.get("note", "")),
                            str(item.get("old_label", "")),
                            str(item.get("teacher_primary", "")),
                            " ".join(map(str, item.get("teacher_evidence", []) or [])),
                            " ".join(map(str, item.get("retrieval_terms", []) or [])),
                            json.dumps(item.get("matched_terms", {}), ensure_ascii=False) if item.get("matched_terms") else "",
                        ],
                    )
                ),
                "heuristic_primary": str(item.get("old_label") or accepted),
                "taxonomy_candidates": item.get("secondary_labels", []) or [],
                "entity_summary": str(item.get("entity_summary", "")),
                "topic_summary": str(item.get("topic_summary", "")),
                "retrieval_terms": item.get("retrieval_terms", []) or [],
                "retrieval_text": str(item.get("retrieval_text", "")),
                "ocr_engine": str(item.get("ocr_engine", "")),
                "ocr_quality": str(item.get("ocr_quality", "")),
                "ocr_char_count": int(item.get("ocr_char_count", 0) or 0),
                "extraction_quality": str(item.get("extraction_quality", "")),
                "accepted_primary": str(accepted),
                "used_inline_llm": True,
                "disagreement": bool(item.get("old_label") and item.get("old_label") != accepted),
            }
        )

    for item in read_jsonl(comparisons_path, limit=1000):
        rows.append(
            {
                "filename": str(item.get("filename", "")),
                "extension": str(item.get("extension", "")),
                "parser": str(item.get("parser", "")),
                "text_preview": str(item.get("text_preview", "")),
                "heuristic_primary": str(item.get("heuristic_primary", "unknown")),
                "taxonomy_candidates": item.get("taxonomy_candidates", []) or [],
                "entity_summary": str(item.get("entity_summary", "")),
                "topic_summary": str(item.get("topic_summary", "")),
                "retrieval_terms": item.get("retrieval_terms", []) or [],
                "retrieval_text": str(item.get("retrieval_text", "")),
                "ocr_engine": str(item.get("ocr_engine", "")),
                "ocr_quality": str(item.get("ocr_quality", "")),
                "ocr_char_count": int(item.get("ocr_char_count", 0) or 0),
                "extraction_quality": str(item.get("extraction_quality", "")),
                "accepted_primary": str(item.get("shadow_primary") or item.get("live_primary") or item.get("heuristic_primary") or "unknown"),
                "used_inline_llm": True,
                "disagreement": bool(item.get("disagreement")),
            }
        )

    return rows


def ensure_lightgbm_model(
    model_path: Path = LIGHTGBM_MODEL_PATH,
    report_path: Path = LIGHTGBM_REPORT_PATH,
    min_rows: int = 3,
    training_source: str | None = None,
    index_database_url: str | None = None,
) -> Dict[str, Any]:
    ensure_runtime_artifacts_bootstrapped()
    if model_path.exists():
        return {"ok": True, "created": False, "model_path": str(model_path)}

    source_mode = (training_source or os.getenv("LIGHTGBM_TRAINING_SOURCE", "auto")).strip().lower()
    training_rows = build_training_rows_from_runtime()
    if source_mode in {"runtime", "auto"} and len(training_rows) >= min_rows:
        report = train_lightgbm_model(
            training_rows=training_rows,
            model_path=model_path,
            report_path=report_path,
        )
        return {"ok": True, "created": True, "report": report, "training_source": "runtime"}

    if source_mode in {"index", "auto"}:
        from .index_training import resolve_index_database_url, train_lightgbm_from_index

        report = train_lightgbm_from_index(
            database_url=index_database_url or os.getenv("INDEX_DATABASE_URL") or resolve_index_database_url(),
            model_path=model_path,
            report_path=report_path,
        )
        return {"ok": True, "created": True, "report": report, "training_source": "index"}

    return {
        "ok": False,
        "created": False,
        "reason": "insufficient-training-rows",
        "training_rows": len(training_rows),
        "training_source": source_mode or "runtime",
    }


def build_readiness_report(
    gating_config: Optional[Dict[str, Any]] = None,
    comparisons_path: Path = SHADOW_COMPARISONS_PATH,
    corrections_path: Path = CORRECTIONS_PATH,
    examples_path: Path = EXAMPLES_PATH,
    manual_note_feedback_path: Path = MANUAL_NOTE_FEEDBACK_PATH,
    queue_dir: Path = SHADOW_QUEUE_DIR,
    model_path: Path = LIGHTGBM_MODEL_PATH,
) -> Dict[str, Any]:
    gating = gating_config or load_hybrid_gating_config()
    ensure_runtime_artifacts_bootstrapped()
    feedback_rows = build_feedback_rows(
        comparisons_path=comparisons_path,
        corrections_path=corrections_path,
        examples_path=examples_path,
        manual_note_feedback_path=manual_note_feedback_path,
    )
    queue_depth = len(list(queue_dir.glob("*.json"))) if queue_dir.exists() else 0
    model_exists = model_path.exists()

    reviewed = [row for row in feedback_rows if row.get("teacher_review_status")]
    approved = [row for row in feedback_rows if row.get("teacher_approved_for_training")]
    agreements = [row for row in approved if row.get("teacher_supports_live_result")]
    feedback_sources: Dict[str, int] = {}
    for row in approved:
        source_name = str(row.get("feedback_source", "shadow-qwen") or "shadow-qwen")
        feedback_sources[source_name] = feedback_sources.get(source_name, 0) + 1
    approved_unique_files = sorted(
        {
            str(row.get("filename", "")).strip()
            for row in approved
            if str(row.get("filename", "")).strip()
        }
    )
    approved_extensions = sorted(
        {
            str(row.get("extension", "")).strip().lower()
            for row in approved
            if str(row.get("extension", "")).strip()
        }
    )
    approved_labels = sorted(
        {
            str(row.get("shadow_primary") or row.get("live_primary") or row.get("heuristic_primary") or "unknown").strip()
            for row in approved
            if str(row.get("shadow_primary") or row.get("live_primary") or row.get("heuristic_primary") or "").strip()
        }
    )
    approved_parsers = sorted(
        {
            str(row.get("parser", "")).strip()
            for row in approved
            if str(row.get("parser", "")).strip()
        }
    )
    approval_rate = (len(approved) / len(reviewed)) if reviewed else 0.0
    agreement_rate = (len(agreements) / len(approved)) if approved else 0.0

    min_samples = int(gating.get("readiness_min_teacher_samples", 10))
    min_unique_files = int(gating.get("readiness_min_unique_teacher_files", min_samples))
    min_extensions = int(gating.get("readiness_min_teacher_extensions", 4))
    min_labels = int(gating.get("readiness_min_teacher_labels", 4))
    min_agreement = safe_float(gating.get("readiness_min_teacher_agreement_rate"), 0.80)
    min_approval = safe_float(gating.get("readiness_min_teacher_approval_rate"), 0.70)
    max_queue_depth = int(gating.get("readiness_max_queue_depth", 25))
    allow_real_ingestion = bool(gating.get("allow_real_ingestion", False))

    thresholds_pass = (
        model_exists
        and len(approved) >= min_samples
        and len(approved_unique_files) >= min_unique_files
        and len(approved_extensions) >= min_extensions
        and len(approved_labels) >= min_labels
        and approval_rate >= min_approval
        and agreement_rate >= min_agreement
        and queue_depth <= max_queue_depth
    )

    warnings: list[str] = []
    if not model_exists:
        warnings.append("lightgbm-model-missing")
    if len(approved) < min_samples:
        warnings.append("insufficient-teacher-approved-samples")
    if len(approved_unique_files) < min_unique_files:
        warnings.append("insufficient-unique-teacher-files")
    if len(approved_extensions) < min_extensions:
        warnings.append("insufficient-teacher-extension-coverage")
    if len(approved_labels) < min_labels:
        warnings.append("insufficient-teacher-label-coverage")
    if approval_rate < min_approval:
        warnings.append("teacher-approval-rate-below-threshold")
    if agreement_rate < min_agreement:
        warnings.append("teacher-agreement-rate-below-threshold")
    if queue_depth > max_queue_depth:
        warnings.append("shadow-queue-backlog-too-deep")
    if thresholds_pass and not allow_real_ingestion:
        warnings.append("manual-real-ingestion-enable-still-required")

    return {
        "generated_at": utc_now(),
        "ok": True,
        "model_exists": model_exists,
        "comparison_rows": len(read_jsonl(comparisons_path, limit=500)),
        "teacher_reviewed_rows": len(reviewed),
        "teacher_approved_rows": len(approved),
        "teacher_live_agreement_rows": len(agreements),
        "teacher_approval_rate": round(approval_rate, 6),
        "teacher_agreement_rate": round(agreement_rate, 6),
        "teacher_unique_files": len(approved_unique_files),
        "teacher_extensions": approved_extensions,
        "teacher_labels": approved_labels,
        "teacher_parsers": approved_parsers,
        "feedback_sources": dict(sorted(feedback_sources.items())),
        "queue_depth": queue_depth,
        "thresholds": {
            "readiness_min_teacher_samples": min_samples,
            "readiness_min_unique_teacher_files": min_unique_files,
            "readiness_min_teacher_extensions": min_extensions,
            "readiness_min_teacher_labels": min_labels,
            "readiness_min_teacher_agreement_rate": min_agreement,
            "readiness_min_teacher_approval_rate": min_approval,
            "readiness_max_queue_depth": max_queue_depth,
        },
        "thresholds_pass": thresholds_pass,
        "allow_real_ingestion": allow_real_ingestion,
        "real_ingestion_allowed": thresholds_pass and allow_real_ingestion,
        "warnings": warnings,
    }


def write_readiness_report(
    gating_config: Optional[Dict[str, Any]] = None,
    readiness_path: Path = READINESS_REPORT_PATH,
) -> Dict[str, Any]:
    report = build_readiness_report(gating_config=gating_config)
    save_json(readiness_path, report)
    return report
