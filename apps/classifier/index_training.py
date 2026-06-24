from __future__ import annotations

import argparse
import json
import os
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

from packages.runtime import load_classifier_runtime_settings
from .external_taxonomy import match_external_taxonomy_candidates
from .label_map import canonicalize_label, canonicalize_labels

SETTINGS = load_classifier_runtime_settings()
LIVE_INDEX_DEFAULTS = {
    "host": "192.168.50.232",
    "port": 5432,
    "user": "icloud",
    "password": "change-me",
    "database": "icloud_index",
}

DEFAULT_SAMPLE_SPLIT = {
    "provider_balanced": 100,
    "sensitive_keyword": 75,
    "low_confidence": 50,
    "ambiguous": 40,
    "file_type_coverage": 35,
}

PROVIDER_SAMPLE_SPLIT = {
    "icloud": 34,
    "google1": 33,
    "google2": 33,
}

SENSITIVE_TOPIC_SPLIT = {
    "medical": 10,
    "legal": 10,
    "financial": 10,
    "insurance": 10,
    "tax": 10,
    "bank": 9,
    "appeal": 8,
    "benefits": 8,
}

FILE_TYPE_SAMPLE_SPLIT = {
    "pdf": 8,
    "docx": 7,
    "spreadsheet": 7,
    "html_text": 7,
    "images": 6,
}

IMPORTANT_DOC_LABELS = {"invoice", "receipt", "medical-receipt", "statement"}

DOC_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "txt",
    "md",
    "markdown",
    "csv",
    "html",
    "htm",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
}

IMAGE_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "heic",
    "webp",
    "gif",
    "bmp",
    "tif",
    "tiff",
    "jxr",
}

ARCHIVE_EXTENSIONS = {
    "7z",
    "bz2",
    "cab",
    "dmg",
    "gz",
    "iso",
    "rar",
    "tar",
    "tgz",
    "xz",
    "zip",
}

ARCHIVE_MIME_PREFIXES = (
    "application/gzip",
    "application/vnd.rar",
    "application/x-7z-compressed",
    "application/x-bzip2",
    "application/x-compressed",
    "application/x-compress",
    "application/x-tar",
    "application/x-xz",
    "application/zip",
)

SPREADSHEET_EXTENSIONS = {"csv", "xls", "xlsx"}
HTML_TEXT_EXTENSIONS = {"html", "htm", "txt", "md", "markdown"}
SENSITIVE_KEYWORDS = {
    "medical": ("medical", "clinic", "hospital", "prescription", "pharmacy", "doctor", "patient", "health"),
    "legal": ("legal", "contract", "agreement", "policy", "clause", "terms", "court", "law", "notice"),
    "financial": ("financial", "bank", "statement", "account", "transaction", "balance", "payment", "invoice"),
    "insurance": ("insurance", "coverage", "deductible", "premium", "claim", "member", "policy"),
    "tax": ("tax", "irs", "1099", "w-2", "w2", "1040", "return", "withholding"),
    "bank": ("bank", "checking", "savings", "routing", "deposit", "withdrawal", "balance", "statement"),
    "appeal": ("appeal", "appealed", "appealing", "appeal letter", "appeal packet"),
    "benefits": ("benefits", "benefit", "coverage", "enrollment", "eob", "explanation of benefits"),
}

LABEL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("explanation-of-benefits", ("explanation of benefits", "eob", "benefit details", "member responsibility")),
    ("denial-letter", ("denial", "denied claim", "not covered", "adverse benefit determination", "coverage denial")),
    ("appeal-template", ("appeal template", "appeal form", "complaint and appeal form", "instructions for using")),
    ("claim-form", ("claim form", "member complaint", "submit a claim", "claim number", "claim submission")),
    ("billing-statement", ("billing statement", "balance due", "account summary", "statement date", "due date")),
    ("bank-statement", ("bank statement", "ending balance", "account ending", "checking account", "savings account")),
    ("tax-form", ("tax form", "1099", "w-2", "w2", "1040", "withholding statement")),
    ("check", ("check number", "routing number", "pay to the order of", "check no", "payable to")),
    ("medical-estimate", ("estimate", "procedures & services cost", "procedures and services cost", "treatment plan estimate", "surgical quote")),
    ("eligibility-notice", ("eligibility results notice", "eligibility notice", "eligibility verification", "coverage eligibility")),
    ("payment-history", ("payment history", "payment methods", "transactions", "paid to", "payment appeared on")),
    ("return-summary", ("return summary card", "rma id", "the ups store", "no box no label", "send by return ship method")),
    ("consumer-report", ("consumer report", "checkr", "lexisnexis", "disclosure report", "consumer disclosure")),
    ("utility-bill", ("service address", "meter number", "bill number", "electric", "utility")),
    ("hotel-folio", ("folio no", "room no", "arrival", "departure", "hotel")),
    ("receipt", ("receipt", "receipts", "cash receipt", "proof of purchase")),
    ("invoice", ("invoice", "billing", "bill ", "bill_", "billed", "charge", "charges")),
    ("reimbursement-packet", ("reimbursement", "reimburse", "packet", "submission packet", "expense packet")),
    ("medical-receipt", ("medical receipt", "copay", "co-pay", "visit receipt", "clinic receipt")),
    ("fsa", ("fsa",)),
    ("hsa", ("hsa",)),
    ("pharmacy", ("pharmacy", "rx ", "rx-", "pharmac")),
    ("prescription", ("prescription", "rx", "dosage", "medication")),
    ("otc-medication", ("otc", "over the counter", "over-the-counter", "medication")),
    ("sunscreen", ("sunscreen",)),
    ("spf-product", ("spf", "broad spectrum", "sun care")),
    ("cosmetic-spf", ("cosmetic", "skincare", "face sunscreen", "daily moisturizer")),
    ("medical", ("medical", "clinic", "doctor", "patient", "hospital", "health", "procedure")),
    ("legal", ("legal", "contract", "agreement", "policy", "clause", "law", "court", "notice")),
    ("insurance", ("insurance", "coverage", "deductible", "premium", "claims", "claim number")),
    ("tax", ("tax", "irs", "1099", "w-2", "w2", "1040", "return", "withholding")),
    ("financial", ("financial", "bank", "statement", "account", "transaction", "payment", "deposit", "balance")),
    ("identity-document", ("passport", "license", "driver license", "driver's license", "identity", "id card", "social security")),
    ("school", ("school", "assignment", "homework", "teacher", "student", "class")),
    ("work", ("project", "meeting", "agenda", "work", "team", "status", "report", "client", "notes")),
    ("technical", ("technical", "docker", "git", "ssh", "api", "stack trace", "error", "log", "build", "config")),
    ("marketing", ("marketing", "promo", "campaign", "brand", "flyer", "advert", "ad ")),
    ("personal", ("personal", "family", "vacation", "home", "recipe", "birthday", "trip")),
    ("statement", ("statement", "monthly statement")),
    ("letter", ("dear ", "sincerely", "regards", "letter")),
    ("form", ("form", "application", "questionnaire", "fill out")),
    ("contract", ("contract", "agreement", "terms", "nda", "clause")),
    ("policy", ("policy", "privacy policy", "policy document")),
    ("manual", ("manual", "instructions", "how to", "user guide")),
    ("report", ("report", "summary", "analysis", "findings", "memo")),
    ("spreadsheet", ("spreadsheet", "sheet", "csv", "excel", "table")),
    ("presentation", ("presentation", "slides", "deck", "powerpoint", "ppt")),
    ("source-code", ("source code", "function", "class ", "import ", "def ", "const ", "let ", "var ", "module", "package")),
    ("markdown-note", ("markdown", "# ", "## ", "### ", "obsidian", "note")),
    ("appeal", ("appeal", "appealed", "appealing", "appeal letter", "appeal packet")),
    ("benefits", ("benefits", "benefit", "coverage", "enrollment", "eob", "explanation of benefits")),
    ("claim", ("claim", "claims", "claim number", "claim form")),
    ("screenshot", ("screenshot", "screen shot", "terminal", "console", "error", "dialog")),
    ("ui-screenshot", ("ui", "user interface", "screen", "window", "button", "menu")),
    ("product-photo", ("product", "package", "packaging", "bottle", "box", "label")),
    ("reference-image", ("concept", "reference", "architecture", "environment", "industrial", "sci-fi", "waystation", "facility")),
    ("image-only", ("photo", "picture", "image", "jpeg", "jpg", "png")),
    ("unknown", ()),
    ("needs-review", ()),
]


@dataclass(frozen=True)
class ScoredLabel:
    label: str
    score: int
    evidence: tuple[str, ...]


def _word_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _normalize_text(*values: Any) -> str:
    return " ".join(
        str(value).strip().lower()
        for value in values
        if value is not None and str(value).strip()
    )


def resolve_index_database_url() -> str:
    explicit = os.getenv("INDEX_DATABASE_URL", "").strip()
    if explicit:
        return explicit

    host = os.getenv("INDEX_POSTGRES_HOST", os.getenv("POSTGRES_HOST", LIVE_INDEX_DEFAULTS["host"]))
    port_text = os.getenv("INDEX_POSTGRES_PORT", os.getenv("POSTGRES_PORT", str(LIVE_INDEX_DEFAULTS["port"])))
    user = os.getenv("INDEX_POSTGRES_USER", os.getenv("POSTGRES_USER", LIVE_INDEX_DEFAULTS["user"]))
    password = os.getenv("INDEX_POSTGRES_PASSWORD", os.getenv("POSTGRES_PASSWORD", LIVE_INDEX_DEFAULTS["password"]))
    database = os.getenv("INDEX_POSTGRES_DB", os.getenv("POSTGRES_DB", LIVE_INDEX_DEFAULTS["database"]))

    try:
        port = int(port_text)
    except ValueError:
        port = LIVE_INDEX_DEFAULTS["port"]

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def fetch_index_corpus(database_url: str | None = None, content_chars: int = 1200) -> list[dict[str, Any]]:
    db_url = database_url or resolve_index_database_url()
    sql = """
        select
            f.id,
            f.external_id,
            f.name,
            f.path,
            f.mime_type,
            coalesce(f.extension, '') as extension,
            coalesce(substr(ec.content_text, 1, %(content_chars)s), '') as content_text
        from files f
        left join extracted_contents ec on ec.file_id = f.id
        where not f.is_deleted
        order by f.id asc
    """

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        rows = conn.execute(sql, {"content_chars": content_chars}).fetchall()
    return [dict(row) for row in rows]


def fetch_index_training_corpus(
    database_url: str | None = None,
    *,
    content_chars: int = 4000,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    db_url = database_url or resolve_index_database_url()
    limit_sql = ""
    params: dict[str, Any] = {"content_chars": content_chars}
    if limit is not None:
        params["row_limit"] = max(int(limit), 0)
        limit_sql = "\n        limit %(row_limit)s"
    sql = f"""
        select
            f.id,
            f.external_id,
            f.name,
            f.path,
            f.mime_type,
            coalesce(f.extension, '') as extension,
            coalesce(substr(ec.content_text, 1, %(content_chars)s), '') as content_text,
            cs.submission_status,
            cs.classifier_note_path,
            cs.classifier_manifest_record,
            cs.primary_label as state_primary_label,
            cs.summary as state_summary,
            cs.confidence as state_confidence,
            cs.reasoning as state_reasoning,
            cs.entity_summary,
            cs.topic_summary,
            cs.retrieval_terms_json,
            cs.retrieval_text,
            cs.response_payload_json,
            cs.last_error
        from files f
        left join extracted_contents ec on ec.file_id = f.id
        left join classification_states cs on cs.file_id = f.id
        where not f.is_deleted
        order by f.id asc{limit_sql}
    """

    with psycopg.connect(db_url, row_factory=dict_row) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def _provider_from_path(path: str) -> str:
    segments = [segment for segment in str(path).split("/") if segment]
    if not segments:
        return "unknown"
    return segments[0].lower()


def _extension_from_record(record: dict[str, Any]) -> str:
    ext = str(record.get("extension") or "").strip().lower().lstrip(".")
    if ext:
        return ext
    name = str(record.get("name") or "")
    suffix = Path(name).suffix.lower().lstrip(".")
    return suffix


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _json_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
        raw_items = parsed if isinstance(parsed, list) else []
    else:
        raw_items = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _is_doc_like(extension: str, mime_type: str) -> bool:
    return extension in DOC_EXTENSIONS or mime_type.startswith("application/") or mime_type.startswith("text/")


def _is_image_like(extension: str, mime_type: str) -> bool:
    return extension in IMAGE_EXTENSIONS or mime_type.startswith("image/")


def _is_archive_like(extension: str, mime_type: str) -> bool:
    mime = mime_type.lower()
    return extension in ARCHIVE_EXTENSIONS or any(mime.startswith(prefix) for prefix in ARCHIVE_MIME_PREFIXES)


def _file_type_group(extension: str, mime_type: str) -> str:
    if extension in {"pdf"}:
        return "pdf"
    if extension in {"doc", "docx"}:
        return "docx"
    if extension in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if extension in HTML_TEXT_EXTENSIONS or mime_type.startswith("text/"):
        return "html_text"
    if _is_image_like(extension, mime_type):
        return "images"
    return "other"


def _score_label(label: str, text: str, extension: str, mime_type: str) -> ScoredLabel:
    if label in {"unknown", "needs-review"}:
        return ScoredLabel(label=label, score=0, evidence=())

    score = 0
    evidence: list[str] = []
    lower_text = text.lower()

    for rule_label, keywords in LABEL_RULES:
        if rule_label != label:
            continue
        for keyword in keywords:
            if keyword and keyword in lower_text:
                score += 2 if len(keyword) > 4 else 1
                evidence.append(keyword)
        break

    if label == "spreadsheet" and extension in SPREADSHEET_EXTENSIONS:
        score += 4
        evidence.append(f"extension:{extension}")
    elif label == "markdown-note" and extension in {"md", "markdown"}:
        score += 4
        evidence.append(f"extension:{extension}")
    elif label == "presentation" and extension in {"ppt", "pptx"}:
        score += 4
        evidence.append(f"extension:{extension}")
    elif label == "source-code" and extension in {"ts", "tsx", "js", "jsx", "py", "go", "java", "c", "cc", "cpp", "cs", "rs", "sh"}:
        score += 4
        evidence.append(f"extension:{extension}")
    elif label == "screenshot" and _is_image_like(extension, mime_type):
        if any(term in lower_text for term in ("screenshot", "screen shot", "terminal", "console", "error")):
            score += 4
            evidence.append(f"image:{extension}")
    elif label == "product-photo" and _is_image_like(extension, mime_type):
        if any(term in lower_text for term in ("product", "packaging", "bottle", "box", "label")):
            score += 4
            evidence.append(f"image:{extension}")
    elif label == "reference-image" and _is_image_like(extension, mime_type):
        if any(term in lower_text for term in ("concept", "reference", "architecture", "environment", "facility", "industrial", "sci-fi")):
            score += 4
            evidence.append(f"image:{extension}")
    elif label == "image-only" and _is_image_like(extension, mime_type):
        score += 2
        evidence.append(f"image:{extension}")

    if mime_type.startswith("text/") and label in {"technical", "markdown-note", "work", "report", "letter", "manual"}:
        score += 1
        evidence.append(f"mime:{mime_type}")
    if mime_type.startswith("application/pdf") and label in {"report", "manual", "contract", "policy", "legal", "medical", "insurance", "financial"}:
        score += 1
        evidence.append("mime:pdf")

    return ScoredLabel(label=label, score=score, evidence=tuple(dict.fromkeys(evidence)))


def _rank_labels(text: str, extension: str, mime_type: str) -> list[ScoredLabel]:
    lower_text = _normalize_text(text)
    scored = [_score_label(label, lower_text, extension, mime_type) for label, _keywords in LABEL_RULES]
    scored.sort(key=lambda item: (item.score, len(item.evidence), item.label), reverse=True)
    return scored


def _boost_ranked_labels_with_external_matches(
    ranked: list[ScoredLabel],
    external_matches: list[dict[str, Any]],
) -> list[ScoredLabel]:
    if not external_matches:
        return ranked

    by_label = {item.label: item for item in ranked}
    for match in external_matches:
        label = str(match.get("label", "") or "")
        if not label:
            continue
        base = by_label.get(label, ScoredLabel(label=label, score=0, evidence=()))
        extra_score = max(2, int(match.get("score", 0) or 0))
        evidence = tuple(dict.fromkeys([*base.evidence, *[str(item) for item in match.get("evidence", [])]]))
        by_label[label] = ScoredLabel(label=label, score=base.score + extra_score, evidence=evidence)

    boosted = list(by_label.values())
    boosted.sort(key=lambda item: (item.score, len(item.evidence), item.label), reverse=True)
    return boosted


def _heuristic_label_from_provider(record: dict[str, Any]) -> str:
    provider = _provider_from_path(str(record.get("path") or ""))
    extension = _extension_from_record(record)
    mime_type = str(record.get("mime_type") or "")
    if _is_image_like(extension, mime_type):
        return "photo" if provider == "icloud" else "reference-image"
    if extension in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if extension in HTML_TEXT_EXTENSIONS:
        return "markdown-note" if extension in {"md", "markdown"} else "work" if provider != "icloud" else "personal"
    if provider == "icloud":
        return "personal"
    if provider.startswith("google"):
        return "work"
    return "unknown"


def _teacher_label_from_record(record: dict[str, Any]) -> dict[str, Any]:
    name = str(record.get("name") or "")
    path = str(record.get("path") or "")
    content = str(record.get("content_text") or "")
    extension = _extension_from_record(record)
    mime_type = str(record.get("mime_type") or "")
    provider = _provider_from_path(path)

    text_surface = _normalize_text(name, path)
    text_full = _normalize_text(name, path, content[:8000])

    surface_ranked = _rank_labels(text_surface, extension, mime_type)
    full_ranked = _rank_labels(text_full, extension, mime_type)
    full_ranked = _boost_ranked_labels_with_external_matches(
        full_ranked,
        match_external_taxonomy_candidates(text_full, limit=6),
    )

    surface_primary = next((item for item in surface_ranked if item.score > 0), surface_ranked[0])
    full_primary = next((item for item in full_ranked if item.score > 0), full_ranked[0])

    top = full_primary
    runner_up = next((item for item in full_ranked if item.label != top.label), ScoredLabel(label="unknown", score=0, evidence=()))
    ambiguity_score = max(0, runner_up.score - top.score + len(runner_up.evidence))
    confidence = 0.0
    if top.score > 0 or runner_up.score > 0:
        confidence = round(top.score / max(top.score + runner_up.score, 1), 4)

    if top.score == 0:
        if _is_image_like(extension, mime_type):
            top = ScoredLabel(label="image-only", score=1, evidence=("filetype",))
            confidence = 0.25
        elif extension in SPREADSHEET_EXTENSIONS:
            top = ScoredLabel(label="spreadsheet", score=1, evidence=("filetype",))
            confidence = 0.35
        elif provider == "icloud":
            top = ScoredLabel(label="personal", score=1, evidence=("provider",))
            confidence = 0.25
        elif provider.startswith("google"):
            top = ScoredLabel(label="work", score=1, evidence=("provider",))
            confidence = 0.25
        else:
            top = ScoredLabel(label="unknown", score=0, evidence=())
            confidence = 0.0

    if confidence < 0.30:
        label = "unknown"
    elif confidence < 0.45 and top.label not in {"unknown", "needs-review"}:
        label = "needs-review"
    else:
        label = top.label

    return {
        "teacher_label": label,
        "teacher_confidence": confidence,
        "teacher_primary": top.label,
        "teacher_secondary": runner_up.label,
        "teacher_ranked_labels": [item.label for item in full_ranked[:5]],
        "teacher_evidence": list(top.evidence),
        "surface_primary": surface_primary.label,
        "surface_confidence": round(surface_primary.score / max(surface_primary.score + 1, 1), 4) if surface_primary.score > 0 else 0.0,
        "ambiguity_score": ambiguity_score,
        "topic_matches": [
            topic for topic, keywords in SENSITIVE_KEYWORDS.items()
            if any(keyword in text_full for keyword in keywords)
        ],
        "file_type_group": _file_type_group(extension, mime_type),
    }


def _sensitive_topics_for_record(record: dict[str, Any]) -> list[str]:
    text = _normalize_text(record.get("name"), record.get("path"), record.get("content_text", ""))
    return [
        topic for topic, keywords in SENSITIVE_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]


def _annotate_record(record: dict[str, Any]) -> dict[str, Any]:
    name = str(record.get("name") or "")
    path = str(record.get("path") or "")
    content = str(record.get("content_text") or "")
    mime_type = str(record.get("mime_type") or "")
    extension = _extension_from_record(record)
    provider = _provider_from_path(path)
    teacher = _teacher_label_from_record(record)
    surface_label = _heuristic_label_from_provider(record)
    topics = _sensitive_topics_for_record(record)
    file_type_group = teacher["file_type_group"]
    doc_like = _is_doc_like(extension, mime_type)
    image_like = _is_image_like(extension, mime_type)
    archive_like = _is_archive_like(extension, mime_type)
    query_text = _normalize_text(name, path, content[:4000])
    content_tokens = _word_tokens(query_text)
    sensitive_topic = topics[0] if topics else ""
    sensitive_hit = bool(topics)

    if not surface_label or surface_label == "unknown":
        surface_label = "needs-review" if teacher["teacher_confidence"] < 0.35 else teacher["teacher_primary"]

    return {
        "file_id": int(record["id"]),
        "external_id": str(record.get("external_id") or ""),
        "filename": Path(name).name or "unknown",
        "extension": extension,
        "mime_type": mime_type,
        "path": path,
        "provider": provider,
        "content_text": content,
        "query_text": query_text,
        "doc_like": doc_like,
        "image_like": image_like,
        "archive_like": archive_like,
        "sample_eligible": not archive_like,
        "file_type_group": file_type_group,
        "sensitive_topics": topics,
        "sensitive_hit": sensitive_hit,
        "sensitive_topic": sensitive_topic,
        "naive_label": surface_label,
        "teacher_label": teacher["teacher_label"],
        "teacher_primary": teacher["teacher_primary"],
        "teacher_secondary": teacher["teacher_secondary"],
        "teacher_confidence": teacher["teacher_confidence"],
        "teacher_ranked_labels": teacher["teacher_ranked_labels"],
        "teacher_evidence": teacher["teacher_evidence"],
        "surface_primary": teacher["surface_primary"],
        "surface_confidence": teacher["surface_confidence"],
        "ambiguity_score": teacher["ambiguity_score"],
        "disagreement": surface_label != teacher["teacher_label"],
    }


def _priority_sort_key(row: dict[str, Any]) -> tuple[int, int, float, int]:
    important = 0 if row["teacher_primary"] in IMPORTANT_DOC_LABELS else 1
    doc_bonus = 0 if row["doc_like"] else 1
    return (important, doc_bonus, -float(row["teacher_confidence"]), row["file_id"])


def _sort_by_provider_balance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[record["provider"]].append(record)
    out: list[dict[str, Any]] = []
    providers = sorted(grouped)
    while True:
        progressed = False
        for provider in providers:
            if grouped[provider]:
                out.append(grouped[provider].pop(0))
                progressed = True
        if not progressed:
            break
    return out


def _distribute_counts(total: int, keys: Iterable[str]) -> dict[str, int]:
    ordered_keys = list(keys)
    if not ordered_keys:
        return {}
    base = total // len(ordered_keys)
    remainder = total % len(ordered_keys)
    counts = {key: base for key in ordered_keys}
    for key in ordered_keys[:remainder]:
        counts[key] += 1
    return counts


def _scale_weighted_counts(total: int, weights: dict[str, int]) -> dict[str, int]:
    if total <= 0 or not weights:
        return {key: 0 for key in weights}

    weight_total = sum(max(value, 0) for value in weights.values())
    if weight_total <= 0:
        return {key: 0 for key in weights}

    raw_counts = {key: total * value / weight_total for key, value in weights.items()}
    counts = {key: int(value) for key, value in raw_counts.items()}
    remainder = total - sum(counts.values())
    if remainder > 0:
        for key, _fraction in sorted(
            ((key, raw_counts[key] - counts[key]) for key in weights),
            key=lambda item: (-item[1], item[0]),
        )[:remainder]:
            counts[key] += 1
    return counts


def build_stratified_training_rows(
    records: list[dict[str, Any]],
    *,
    sample_split: dict[str, int] | None = None,
    target_sample_size: int | None = None,
    seed: int = 7,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    split = dict(DEFAULT_SAMPLE_SPLIT)
    if sample_split:
        split.update(sample_split)

    annotated = [_annotate_record(record) for record in records]
    eligible = [row for row in annotated if row["sample_eligible"]]
    excluded_archives = [row for row in annotated if row["archive_like"]]
    selected_ids: set[int] = set()
    selected_rows: list[dict[str, Any]] = []
    bucket_counts: Counter[str] = Counter()

    rng = random.Random(seed)

    def add_rows(bucket_name: str, pool: list[dict[str, Any]], quota: int) -> None:
        if quota <= 0 or not pool:
            return
        shuffled = pool[:]
        rng.shuffle(shuffled)
        added = 0
        for row in shuffled:
            if row["file_id"] in selected_ids:
                continue
            selected_ids.add(row["file_id"])
            bucket_counts[bucket_name] += 1
            row_copy = dict(row)
            row_copy["sample_bucket"] = bucket_name
            row_copy["sample_rank"] = len(selected_rows) + 1
            row_copy["heuristic_primary"] = canonicalize_label(row_copy["naive_label"])
            row_copy["accepted_primary"] = canonicalize_label(row_copy["teacher_label"])
            row_copy["used_inline_llm"] = bucket_name in {"low_confidence", "ambiguous"} or row_copy["teacher_confidence"] < 0.45
            row_copy["disagreement"] = row_copy["heuristic_primary"] != row_copy["accepted_primary"]
            row_copy["taxonomy_candidates"] = canonicalize_labels(row_copy["teacher_ranked_labels"])
            row_copy["text_preview"] = row_copy["query_text"][:4000]
            row_copy["parser"] = row_copy["file_type_group"]
            selected_rows.append(row_copy)
            added += 1
            if added >= quota:
                break

    provider_quota = _distribute_counts(split["provider_balanced"], PROVIDER_SAMPLE_SPLIT.keys())
    for provider, quota in provider_quota.items():
        pool = [row for row in eligible if row["provider"] == provider and row["doc_like"]]
        if not pool:
            pool = [row for row in eligible if row["provider"] == provider]
        pool.sort(key=_priority_sort_key)
        pool = _sort_by_provider_balance(pool)
        add_rows(f"provider:{provider}", pool, quota)

    sensitive_quota = _scale_weighted_counts(split["sensitive_keyword"], SENSITIVE_TOPIC_SPLIT)
    for topic, quota in sensitive_quota.items():
        pool = [
            row for row in eligible
            if topic in row["sensitive_topics"] and row["file_id"] not in selected_ids
        ]
        pool.sort(key=lambda row: (-row["teacher_confidence"], row["file_id"]))
        add_rows(f"sensitive:{topic}", pool, quota)

    low_confidence_pool = [
        row for row in eligible
        if row["file_id"] not in selected_ids and (row["teacher_confidence"] < 0.45 or row["teacher_label"] in {"unknown", "needs-review"})
    ]
    low_confidence_pool.sort(key=lambda row: (_priority_sort_key(row), row["teacher_confidence"], row["file_id"]))
    add_rows("low_confidence", low_confidence_pool, split["low_confidence"])

    ambiguous_pool = [
        row for row in eligible
        if row["file_id"] not in selected_ids and (row["disagreement"] or row["ambiguity_score"] > 0 or row["teacher_confidence"] < 0.75)
    ]
    ambiguous_pool.sort(key=lambda row: (_priority_sort_key(row), -row["ambiguity_score"], row["teacher_confidence"], row["file_id"]))
    add_rows("ambiguous", ambiguous_pool, split["ambiguous"])

    file_type_groups = {
        "pdf": [row for row in eligible if row["file_id"] not in selected_ids and row["file_type_group"] == "pdf"],
        "docx": [row for row in eligible if row["file_id"] not in selected_ids and row["file_type_group"] == "docx"],
        "spreadsheet": [row for row in eligible if row["file_id"] not in selected_ids and row["file_type_group"] == "spreadsheet"],
        "html_text": [row for row in eligible if row["file_id"] not in selected_ids and row["file_type_group"] == "html_text"],
        "images": [row for row in eligible if row["file_id"] not in selected_ids and row["file_type_group"] == "images"],
    }
    file_type_quota = _scale_weighted_counts(split["file_type_coverage"], FILE_TYPE_SAMPLE_SPLIT)
    for group, quota in file_type_quota.items():
        pool = file_type_groups.get(group, [])
        pool.sort(key=_priority_sort_key)
        add_rows(f"file_type:{group}", pool, quota)

    requested_total = target_sample_size if target_sample_size is not None else sum(split.values())
    if len(selected_rows) < requested_total:
        fallback_pool = [row for row in eligible if row["file_id"] not in selected_ids]
        fallback_pool.sort(
            key=lambda row: (
                row["provider"],
                0 if row["teacher_primary"] in IMPORTANT_DOC_LABELS else 1,
                0 if row["doc_like"] else 1,
                -row["teacher_confidence"],
                row["file_id"],
            )
        )
        add_rows("fallback", fallback_pool, requested_total - len(selected_rows))

    selected_rows = selected_rows[:requested_total]

    label_counts = Counter(row["accepted_primary"] for row in selected_rows)
    file_type_counts = Counter(row["file_type_group"] for row in selected_rows)
    provider_counts = Counter(row["provider"] for row in selected_rows)

    report = {
        "ok": True,
        "source": "live-index",
        "requested_sample_size": requested_total,
        "selected_sample_size": len(selected_rows),
        "requested_split": split,
        "realized_bucket_counts": dict(bucket_counts),
        "provider_counts": dict(provider_counts),
        "label_counts": dict(label_counts),
        "file_type_counts": dict(file_type_counts),
        "excluded_archive_rows": len(excluded_archives),
        "excluded_archive_extensions": dict(Counter(row["extension"] for row in excluded_archives)),
        "total_index_rows_seen": len(records),
        "annotated_rows": len(annotated),
        "eligible_rows": len(eligible),
        "provider_pool_sizes": {
            provider: sum(1 for row in eligible if row["provider"] == provider and row["doc_like"])
            for provider in PROVIDER_SAMPLE_SPLIT
        },
        "sensitive_topic_pool_sizes": {
            topic: sum(1 for row in eligible if topic in row["sensitive_topics"])
            for topic in SENSITIVE_TOPIC_SPLIT
        },
    }
    return selected_rows, report


def build_taxonomy_training_dataset(
    records: list[dict[str, Any]],
    *,
    text_preview_chars: int = 4000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    provider_counts: Counter[str] = Counter()
    submission_status_counts: Counter[str] = Counter()
    current_label_counts: Counter[str] = Counter()
    teacher_label_counts: Counter[str] = Counter()
    training_target_counts: Counter[str] = Counter()
    file_type_counts: Counter[str] = Counter()
    topic_counts: Counter[str] = Counter()
    review_reason_counts: Counter[str] = Counter()
    top_candidate_counts: Counter[str] = Counter()

    with_state = 0
    review_recommended = 0
    teacher_disagreement = 0

    for record in records:
        annotated = _annotate_record(record)
        response_payload = _json_object(record.get("response_payload_json"))
        manifest_record = _json_object(record.get("classifier_manifest_record"))
        retrieval_terms = _json_string_list(record.get("retrieval_terms_json"))
        secondary_labels = canonicalize_labels(
            response_payload.get("secondary_labels")
            if isinstance(response_payload.get("secondary_labels"), list)
            else []
        )
        current_primary_raw = str(
            record.get("state_primary_label")
            or response_payload.get("primary_label")
            or manifest_record.get("primary_label")
            or ""
        ).strip()
        current_primary = canonicalize_label(current_primary_raw) if current_primary_raw else ""
        current_confidence = record.get("state_confidence")
        try:
            current_confidence_value = float(current_confidence) if current_confidence is not None else 0.0
        except (TypeError, ValueError):
            current_confidence_value = 0.0
        taxonomy_matches = match_external_taxonomy_candidates(annotated["query_text"], limit=8)
        taxonomy_candidates = canonicalize_labels([str(item.get("label") or "") for item in taxonomy_matches])
        training_target = current_primary if current_primary and current_primary not in {"unknown", "needs-review"} else canonicalize_label(annotated["teacher_label"])
        review_reasons: list[str] = []
        if not current_primary:
            review_reasons.append("missing-classifier-label")
        elif current_primary in {"unknown", "needs-review"}:
            review_reasons.append("classifier-review-label")
        if current_confidence_value and current_confidence_value < 0.70:
            review_reasons.append("classifier-low-confidence")
        if annotated["teacher_confidence"] < 0.45:
            review_reasons.append("teacher-low-confidence")
        if current_primary and current_primary not in {"unknown", "needs-review"}:
            teacher_primary = canonicalize_label(annotated["teacher_primary"])
            if current_primary != teacher_primary:
                review_reasons.append("teacher-current-disagreement")

        needs_review = bool(review_reasons)
        if needs_review:
            review_recommended += 1
        if "teacher-current-disagreement" in review_reasons:
            teacher_disagreement += 1

        row = {
            "file_id": annotated["file_id"],
            "external_id": annotated["external_id"],
            "filename": annotated["filename"],
            "path": annotated["path"],
            "provider": annotated["provider"],
            "extension": annotated["extension"],
            "mime_type": annotated["mime_type"],
            "file_type_group": annotated["file_type_group"],
            "submission_status": str(record.get("submission_status") or ""),
            "classifier_note_path": str(record.get("classifier_note_path") or ""),
            "classifier_primary_label": current_primary,
            "classifier_primary_label_raw": current_primary_raw,
            "classifier_secondary_labels": secondary_labels,
            "classifier_confidence": round(current_confidence_value, 4) if current_confidence is not None else None,
            "classifier_summary": str(record.get("state_summary") or response_payload.get("summary") or ""),
            "classifier_reasoning": str(record.get("state_reasoning") or response_payload.get("reasoning") or ""),
            "entity_summary": str(record.get("entity_summary") or response_payload.get("entity_summary") or ""),
            "topic_summary": str(record.get("topic_summary") or response_payload.get("topic_summary") or ""),
            "retrieval_terms": retrieval_terms,
            "retrieval_text": str(record.get("retrieval_text") or response_payload.get("retrieval_text") or ""),
            "last_error": str(record.get("last_error") or ""),
            "naive_label": canonicalize_label(annotated["naive_label"]),
            "teacher_label": canonicalize_label(annotated["teacher_label"]),
            "teacher_primary": canonicalize_label(annotated["teacher_primary"]),
            "teacher_secondary": canonicalize_label(annotated["teacher_secondary"]),
            "teacher_confidence": annotated["teacher_confidence"],
            "teacher_ranked_labels": canonicalize_labels(annotated["teacher_ranked_labels"]),
            "teacher_evidence": list(annotated["teacher_evidence"]),
            "surface_primary": canonicalize_label(annotated["surface_primary"]),
            "surface_confidence": annotated["surface_confidence"],
            "ambiguity_score": annotated["ambiguity_score"],
            "sensitive_topics": list(annotated["sensitive_topics"]),
            "taxonomy_candidates": taxonomy_candidates,
            "training_target_label": training_target,
            "review_recommended": needs_review,
            "review_reasons": review_reasons,
            "text_preview": annotated["query_text"][:text_preview_chars],
        }
        rows.append(row)

        provider_counts[row["provider"]] += 1
        submission_status_counts[row["submission_status"] or "unsubmitted"] += 1
        current_label_counts[row["classifier_primary_label"] or "unclassified"] += 1
        teacher_label_counts[row["teacher_label"]] += 1
        training_target_counts[row["training_target_label"]] += 1
        file_type_counts[row["file_type_group"]] += 1
        if row["submission_status"]:
            with_state += 1
        for topic in row["sensitive_topics"]:
            topic_counts[topic] += 1
        for reason in review_reasons:
            review_reason_counts[reason] += 1
        for label in row["taxonomy_candidates"][:3]:
            top_candidate_counts[label] += 1

    report = {
        "ok": True,
        "kind": "taxonomy-training-dataset-v1",
        "total_rows": len(rows),
        "rows_with_classification_state": with_state,
        "review_recommended_rows": review_recommended,
        "teacher_current_disagreement_rows": teacher_disagreement,
        "provider_counts": dict(sorted(provider_counts.items())),
        "submission_status_counts": dict(sorted(submission_status_counts.items())),
        "classifier_label_counts": dict(sorted(current_label_counts.items())),
        "teacher_label_counts": dict(sorted(teacher_label_counts.items())),
        "training_target_counts": dict(sorted(training_target_counts.items())),
        "file_type_counts": dict(sorted(file_type_counts.items())),
        "sensitive_topic_counts": dict(sorted(topic_counts.items())),
        "review_reason_counts": dict(sorted(review_reason_counts.items())),
        "top_taxonomy_candidates": dict(top_candidate_counts.most_common(20)),
    }
    return rows, report


def export_taxonomy_training_dataset(
    *,
    database_url: str | None = None,
    output_path: Path,
    report_path: Path,
    content_chars: int = 4000,
    limit: int | None = None,
) -> dict[str, Any]:
    records = fetch_index_training_corpus(
        database_url=database_url,
        content_chars=content_chars,
        limit=limit,
    )
    rows, report = build_taxonomy_training_dataset(records, text_preview_chars=content_chars)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    full_report = dict(report)
    full_report.update(
        {
            "database_url_source": "explicit" if database_url else "environment",
            "output_path": str(output_path),
            "report_path": str(report_path),
            "content_chars": content_chars,
            "limit": limit,
        }
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(full_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return full_report


def train_lightgbm_from_index(
    *,
    database_url: str | None = None,
    model_path: Path,
    report_path: Path,
    sample_split: dict[str, int] | None = None,
    seed: int = 7,
) -> dict[str, Any]:
    from apps.classifier.hybrid_runtime import train_lightgbm_model

    requested_split = dict(DEFAULT_SAMPLE_SPLIT)
    if sample_split:
        requested_split.update(sample_split)
    records = fetch_index_corpus(database_url=database_url)
    training_rows, sample_report = build_stratified_training_rows(
        records,
        sample_split=requested_split,
        target_sample_size=sum(requested_split.values()),
        seed=seed,
    )
    model_report = train_lightgbm_model(
        training_rows=training_rows,
        model_path=model_path,
        report_path=report_path,
    )
    model_report.update(
        {
            "sample_source": sample_report["source"],
            "requested_sample_size": sample_report["requested_sample_size"],
            "selected_sample_size": sample_report["selected_sample_size"],
            "requested_split": sample_report["requested_split"],
            "realized_bucket_counts": sample_report["realized_bucket_counts"],
            "provider_counts": sample_report["provider_counts"],
            "label_counts": sample_report["label_counts"],
            "file_type_counts": sample_report["file_type_counts"],
            "excluded_archive_rows": sample_report["excluded_archive_rows"],
            "excluded_archive_extensions": sample_report["excluded_archive_extensions"],
            "total_index_rows_seen": sample_report["total_index_rows_seen"],
            "annotated_rows": sample_report["annotated_rows"],
            "eligible_rows": sample_report["eligible_rows"],
            "provider_pool_sizes": sample_report["provider_pool_sizes"],
            "sensitive_topic_pool_sizes": sample_report["sensitive_topic_pool_sizes"],
        }
    )
    report_path.write_text(json.dumps(model_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return model_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export classifier taxonomy/training datasets or train LightGBM from the index.")
    parser.add_argument(
        "--mode",
        choices=("export-taxonomy-dataset", "train-lightgbm"),
        default="export-taxonomy-dataset",
        help="Operation to run.",
    )
    parser.add_argument("--database-url", default=None, help="Optional explicit Postgres URL for the live index.")
    parser.add_argument("--content-chars", type=int, default=4000, help="Maximum extracted content chars to include per row.")
    parser.add_argument("--limit", type=int, default=None, help="Optional maximum row count to export.")
    parser.add_argument("--seed", type=int, default=7, help="Sampling seed for LightGBM training mode.")
    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output path override. Defaults to the runtime taxonomy dataset or LightGBM model path.",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Optional report path override. Defaults to the runtime taxonomy dataset report or LightGBM report path.",
    )
    args = parser.parse_args(argv)

    if args.mode == "train-lightgbm":
        model_path = Path(args.output_path) if args.output_path else SETTINGS.lightgbm_model_path
        report_path = Path(args.report_path) if args.report_path else SETTINGS.lightgbm_report_path
        result = train_lightgbm_from_index(
            database_url=args.database_url,
            model_path=model_path,
            report_path=report_path,
            seed=args.seed,
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    output_path = Path(args.output_path) if args.output_path else SETTINGS.taxonomy_training_dataset_path
    report_path = Path(args.report_path) if args.report_path else SETTINGS.taxonomy_training_dataset_report_path
    result = export_taxonomy_training_dataset(
        database_url=args.database_url,
        output_path=output_path,
        report_path=report_path,
        content_chars=args.content_chars,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
