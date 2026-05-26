from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from packages.runtime import load_classifier_runtime_settings

from .index_training import (
    _annotate_record,
    _extension_from_record,
    _is_doc_like,
    _is_image_like,
    resolve_index_database_url,
)
from .label_map import canonicalize_label

SETTINGS = load_classifier_runtime_settings()
EXAMPLES_PATH = SETTINGS.examples_path
REPORT_PATH = SETTINGS.example_mining_report_path

PRIMARY_PUBLIC_DATASET = "rvl_cdip_static"
IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "heic")


@dataclass(frozen=True)
class LabelMiningSpec:
    quota: int
    query_terms: tuple[str, ...]
    required_terms: tuple[str, ...] = ()
    path_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    extensions: tuple[str, ...] = ()
    min_confidence: float = 0.0
    min_content_chars: int = 60
    teacher_alignment: str = "exact"
    require_path_term: bool = False


LABEL_SPECS: dict[str, LabelMiningSpec] = {
    "appeal": LabelMiningSpec(
        quota=20,
        query_terms=("appeal", "internal appeal", "appeal of denied claim", "member complaint and appeal"),
        required_terms=("appeal",),
        path_terms=("appeal",),
        exclude_terms=("professor", "semester", "problem of evil", "phil a201"),
        min_confidence=0.48,
    ),
    "appeal-template": LabelMiningSpec(
        quota=15,
        query_terms=("appeal template", "appeal form", "member complaint and appeal form", "instructions for using"),
        required_terms=("appeal template", "appeal form", "complaint and appeal form"),
        path_terms=("appeal",),
        min_confidence=0.45,
    ),
    "benefits": LabelMiningSpec(
        quota=10,
        query_terms=("copay assistance", "benefits", "coverage", "member services", "welcome letter"),
        required_terms=("copay assistance", "benefits", "coverage"),
        path_terms=("vyepti", "appeal"),
        exclude_terms=("benefits generalist", "return to work", "professor", "semester"),
        min_confidence=0.35,
    ),
    "explanation-of-benefits": LabelMiningSpec(
        quota=25,
        query_terms=("explanation of benefits", "eob", "member responsibility", "claim remarks"),
        required_terms=("explanation of benefits", "eob"),
        min_confidence=0.4,
        teacher_alignment="canonical",
    ),
    "denial-letter": LabelMiningSpec(
        quota=15,
        query_terms=("denial", "coverage denial", "not covered", "adverse benefit determination"),
        required_terms=("denial", "not covered", "adverse benefit determination"),
        path_terms=("appeal",),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "claim": LabelMiningSpec(
        quota=20,
        query_terms=("claim id", "claim number", "provider billed", "plan paid", "you may owe"),
        required_terms=("claim id", "claim number", "provider billed", "plan paid"),
        exclude_terms=("professor", "semester", "problem of evil", "phil a201"),
        min_confidence=0.4,
        teacher_alignment="canonical",
    ),
    "claim-form": LabelMiningSpec(
        quota=15,
        query_terms=("claim form", "member complaint", "reimbursement request form", "submit a claim"),
        required_terms=("claim form", "member complaint", "submit a claim"),
        path_terms=("appeal", "vyepti"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "invoice": LabelMiningSpec(
        quota=20,
        query_terms=("invoice", "amount due", "charges", "vendor invoice", "bill number"),
        required_terms=("invoice", "amount due", "vendor invoice", "charges", "bill number"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "receipt": LabelMiningSpec(
        quota=25,
        query_terms=("payment receipt", "thank you for shopping", "sale - approved", "proof of purchase", "transaction details"),
        required_terms=("payment receipt", "thank you for shopping", "sale - approved", "proof of purchase", "transaction details"),
        path_terms=("receipts",),
        exclude_terms=("confirmation receipt number", "complaint form confirmation receipt"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "medical-receipt": LabelMiningSpec(
        quota=20,
        query_terms=("payment receipt", "paid to", "patient name", "total paid", "visit receipt"),
        required_terms=("payment receipt", "paid to", "total paid", "visit receipt"),
        path_terms=("receipts", "vyepti", "billing & payments"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "reimbursement-packet": LabelMiningSpec(
        quota=15,
        query_terms=("reimbursement packet", "reimbursement request", "reimbursement", "expense packet"),
        required_terms=("reimbursement packet", "reimbursement request", "reimbursement"),
        path_terms=("receipts", "vyepti"),
        min_confidence=0.3,
        teacher_alignment="canonical",
    ),
    "billing-statement": LabelMiningSpec(
        quota=20,
        query_terms=("billing statement", "balance due", "statement date", "account summary", "due date"),
        required_terms=("billing statement", "balance due", "statement date", "account summary"),
        min_confidence=0.4,
        teacher_alignment="canonical",
    ),
    "bank-statement": LabelMiningSpec(
        quota=15,
        query_terms=("bank statement", "ending balance", "account ending", "checking account", "savings account"),
        required_terms=("bank statement", "ending balance", "account ending", "checking account", "savings account"),
        path_terms=("credit",),
        min_confidence=0.35,
        require_path_term=True,
        teacher_alignment="canonical",
    ),
    "tax": LabelMiningSpec(
        quota=15,
        query_terms=("tax return", "property tax", "tax year", "irs", "withholding"),
        required_terms=("tax", "irs", "property tax", "withholding"),
        path_terms=("tax", "2025taxes", "taxes2025"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "tax-form": LabelMiningSpec(
        quota=20,
        query_terms=("1099", "w-2", "w2", "1040", "1098", "tax form"),
        required_terms=("1099", "w-2", "w2", "1040", "1098", "tax form"),
        path_terms=("tax", "2025taxes", "taxes2025"),
        min_confidence=0.3,
        teacher_alignment="canonical",
    ),
    "check": LabelMiningSpec(
        quota=15,
        query_terms=("check number", "routing number", "pay to the order of", "check no", "deposit"),
        required_terms=("check number", "routing number", "pay to the order of", "check no"),
        path_terms=("checks",),
        extensions=("pdf", "jpg", "jpeg", "png"),
        min_confidence=0.25,
        require_path_term=True,
        teacher_alignment="canonical",
    ),
    "contract": LabelMiningSpec(
        quota=15,
        query_terms=("retainer agreement", "agreement", "contract", "terms and conditions", "signed"),
        required_terms=("agreement", "contract", "retainer"),
        path_terms=("legal",),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "policy": LabelMiningSpec(
        quota=15,
        query_terms=("policy", "coverage policy", "privacy policy", "policy number"),
        required_terms=("policy", "coverage policy", "privacy policy"),
        min_confidence=0.35,
        teacher_alignment="canonical",
    ),
    "identity-document": LabelMiningSpec(
        quota=20,
        query_terms=("driver license", "passport", "legal name", "id card", "social security", "consumer disclosure"),
        required_terms=("driver license", "passport", "id card", "legal name", "consumer disclosure"),
        path_terms=("name change", "credit", "legal"),
        extensions=("pdf", "jpg", "jpeg", "png"),
        min_confidence=0.25,
        require_path_term=True,
        teacher_alignment="canonical",
    ),
    "medical-estimate": LabelMiningSpec(
        quota=15,
        query_terms=("procedures & services cost", "estimate", "treatment plan", "surgical quote"),
        required_terms=("procedures & services cost", "estimate", "treatment plan", "surgical quote"),
        path_terms=("surgery",),
        min_confidence=0.3,
        teacher_alignment="canonical",
    ),
    "eligibility-notice": LabelMiningSpec(
        quota=15,
        query_terms=("eligibility results notice", "eligibility notice", "eligibility verification", "coverage eligibility"),
        required_terms=("eligibility results notice", "eligibility notice", "eligibility verification"),
        min_confidence=0.3,
        teacher_alignment="canonical",
    ),
    "payment-history": LabelMiningSpec(
        quota=15,
        query_terms=("payment methods", "payment history", "transactions", "billing country", "paid to"),
        required_terms=("payment methods", "payment history", "transactions", "billing country"),
        path_terms=("uber data",),
        min_confidence=0.25,
        teacher_alignment="canonical",
    ),
    "spreadsheet": LabelMiningSpec(
        quota=20,
        query_terms=("spreadsheet", "xlsx", "csv", "account name", "service date"),
        extensions=("csv", "xls", "xlsx"),
        min_content_chars=30,
        teacher_alignment="exact",
    ),
    "manual": LabelMiningSpec(
        quota=15,
        query_terms=("manual", "user guide", "instructions", "owner's manual"),
        required_terms=("manual", "user guide", "instructions", "owner's manual"),
        path_terms=("manuals",),
        min_confidence=0.3,
        require_path_term=True,
    ),
    "legal": LabelMiningSpec(
        quota=25,
        query_terms=("legal", "agreement", "complaint", "court", "law", "name change"),
        required_terms=("legal", "agreement", "complaint", "court", "law", "name change"),
        path_terms=("legal", "name change", "lawsuit"),
        min_confidence=0.25,
        teacher_alignment="canonical",
    ),
    "medical": LabelMiningSpec(
        quota=25,
        query_terms=("patient", "provider", "clinic", "medical", "hospital", "procedure"),
        required_terms=("patient", "provider", "clinic", "medical", "hospital", "procedure"),
        path_terms=("vyepti", "surgery", "psych", "med fam verfify"),
        min_confidence=0.25,
        teacher_alignment="canonical",
    ),
    "technical": LabelMiningSpec(
        quota=20,
        query_terms=("docker", "git", "api", "error", "stack trace", "config", "build"),
        required_terms=("docker", "git", "api", "error", "config", "build"),
        path_terms=("documents", "downloads", "training"),
        min_confidence=0.25,
    ),
    "letter": LabelMiningSpec(
        quota=15,
        query_terms=("dear ", "sincerely", "regards", "to whom", "letter"),
        required_terms=("dear ", "sincerely", "regards", "to whom"),
        min_confidence=0.2,
    ),
    "presentation": LabelMiningSpec(
        quota=10,
        query_terms=("presentation", "slides", "deck", "powerpoint"),
        required_terms=("presentation", "slides", "deck", "powerpoint"),
        extensions=("ppt", "pptx"),
        min_content_chars=20,
    ),
    "source-code": LabelMiningSpec(
        quota=10,
        query_terms=("import ", "def ", "class ", "const ", "function", "module"),
        required_terms=("import ", "def ", "class ", "const ", "function", "module"),
        extensions=("py", "ts", "tsx", "js", "jsx", "json", "md"),
        min_content_chars=30,
    ),
    "school": LabelMiningSpec(
        quota=15,
        query_terms=("professor", "semester", "student", "course", "assignment", "phil "),
        required_terms=("professor", "semester", "student", "course", "assignment", "phil "),
        exclude_terms=("claim id", "provider billed", "plan paid"),
        min_confidence=0.2,
    ),
    "financial": LabelMiningSpec(
        quota=20,
        query_terms=("account", "transaction", "payment", "balance", "statement", "credit card"),
        required_terms=("account", "transaction", "payment", "balance", "statement", "credit card"),
        path_terms=("uber data", "credit"),
        min_confidence=0.2,
        teacher_alignment="canonical",
    ),
    "ui-screenshot": LabelMiningSpec(
        quota=15,
        query_terms=("status tracker", "recent transactions", "search amazon", "inbox", "menu", "provided by bank of america"),
        required_terms=("status tracker", "recent transactions", "search amazon", "provided by bank of america"),
        path_terms=("screenshots",),
        extensions=IMAGE_EXTENSIONS,
        min_content_chars=20,
        require_path_term=True,
    ),
    "return-summary": LabelMiningSpec(
        quota=20,
        query_terms=("return summary card", "the ups store", "no box no label", "rma id", "send by return ship method"),
        required_terms=("return summary card", "the ups store", "no box no label", "rma id"),
        path_terms=("screenshots", "amazon"),
        extensions=IMAGE_EXTENSIONS,
        min_content_chars=20,
        teacher_alignment="canonical",
    ),
    "product-photo": LabelMiningSpec(
        quota=0,
        query_terms=("product", "packaging", "bottle", "box", "label"),
        required_terms=("product", "packaging", "bottle", "box", "label"),
        extensions=IMAGE_EXTENSIONS,
        min_content_chars=20,
        teacher_alignment="canonical",
    ),
    "consumer-report": LabelMiningSpec(
        quota=15,
        query_terms=("consumer report", "checkr", "lexisnexis", "disclosure report", "request form"),
        required_terms=("consumer report", "checkr", "lexisnexis", "disclosure report"),
        path_terms=("credit",),
        min_confidence=0.2,
        require_path_term=True,
        teacher_alignment="canonical",
    ),
    "utility-bill": LabelMiningSpec(
        quota=10,
        query_terms=("service address", "meter number", "bill number", "chugach", "electric"),
        required_terms=("service address", "meter number", "bill number", "chugach"),
        min_confidence=0.2,
        teacher_alignment="canonical",
    ),
    "hotel-folio": LabelMiningSpec(
        quota=10,
        query_terms=("folio no", "room no", "arrival", "departure", "hotel"),
        required_terms=("folio no", "room no"),
        min_confidence=0.2,
        teacher_alignment="canonical",
    ),
    "insurance": LabelMiningSpec(
        quota=20,
        query_terms=("insurance", "coverage", "deductible", "member", "policy"),
        required_terms=("insurance", "coverage", "deductible", "member", "policy"),
        min_confidence=0.25,
        teacher_alignment="canonical",
    ),
    "form": LabelMiningSpec(
        quota=20,
        query_terms=("form", "application", "request form", "fill out", "questionnaire"),
        required_terms=("form", "request form", "application", "questionnaire"),
        min_confidence=0.2,
    ),
    "report": LabelMiningSpec(
        quota=25,
        query_terms=("report", "summary", "findings", "analysis", "memo"),
        required_terms=("report", "summary", "findings", "analysis", "memo"),
        min_confidence=0.2,
    ),
    "statement": LabelMiningSpec(
        quota=20,
        query_terms=("statement", "monthly statement", "account summary", "statement date"),
        required_terms=("statement", "monthly statement", "account summary", "statement date"),
        min_confidence=0.2,
        teacher_alignment="canonical",
    ),
    "work": LabelMiningSpec(
        quota=20,
        query_terms=("meeting", "agenda", "team", "status", "project", "client"),
        required_terms=("meeting", "agenda", "team", "status", "project", "client"),
        min_confidence=0.2,
    ),
}

EXAMPLE_TARGET_QUOTAS: dict[str, int] = {label: spec.quota for label, spec in LABEL_SPECS.items()}
GENERIC_REJECT_TERMS = ("queue=", "(doctitle)", "meta-2025", "facebook", "backupcodes")


def _normalize_text(*parts: Any) -> str:
    return " ".join(str(part or "").strip().lower() for part in parts if str(part or "").strip())


def _match_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term and term in text]


def _extract_matched_terms(label: str, record: dict[str, Any], annotation: dict[str, Any]) -> dict[str, list[str]]:
    spec = LABEL_SPECS[label]
    path = str(record.get("path") or "").lower()
    content = str(record.get("content_text") or "")
    text = _normalize_text(record.get("name"), record.get("path"), content[:4000])
    return {
        "required": _match_terms(text, spec.required_terms or spec.query_terms),
        "query": _match_terms(text, spec.query_terms),
        "path": _match_terms(path, spec.path_terms),
        "teacher": [str(item) for item in annotation.get("teacher_evidence", []) if item],
    }


def _teacher_matches_spec(label: str, annotation: dict[str, Any]) -> bool:
    spec = LABEL_SPECS[label]
    teacher_primary = str(annotation.get("teacher_primary") or "")
    ranked = [str(item) for item in annotation.get("teacher_ranked_labels", []) if item]

    if spec.teacher_alignment == "none":
        return True
    if spec.teacher_alignment == "exact":
        return teacher_primary == label or label in ranked

    target = canonicalize_label(label)
    if canonicalize_label(teacher_primary) == target:
        return True
    return any(canonicalize_label(item) == target for item in ranked)


def is_sane_example_candidate(label: str, record: dict[str, Any], annotation: dict[str, Any]) -> tuple[bool, str]:
    spec = LABEL_SPECS[label]
    path = str(record.get("path") or "")
    name = str(record.get("name") or "")
    content = str(record.get("content_text") or "")
    extension = _extension_from_record(record)
    mime_type = str(record.get("mime_type") or "")
    text = _normalize_text(name, path, content[:4000])
    path_text = path.lower()

    if not path or not name:
        return False, "missing-source-path"
    if any(term in text for term in GENERIC_REJECT_TERMS):
        return False, "generic-placeholder-signal"
    if any(term in text for term in spec.exclude_terms):
        return False, "excluded-term"
    if spec.extensions and extension not in spec.extensions:
        return False, "wrong-extension"
    if len(content.strip()) < spec.min_content_chars:
        return False, "too-little-content"
    if spec.min_confidence and float(annotation.get("teacher_confidence", 0.0) or 0.0) < spec.min_confidence:
        return False, "confidence-too-low"

    required_hits = _match_terms(text, spec.required_terms or spec.query_terms)
    if not required_hits:
        return False, "required-terms-missing"
    path_hits = _match_terms(path_text, spec.path_terms)
    if spec.require_path_term and spec.path_terms and not path_hits:
        return False, "path-hint-missing"
    if not _teacher_matches_spec(label, annotation):
        return False, "teacher-mismatch"

    if label in {"ui-screenshot", "return-summary"} and not _is_image_like(extension, mime_type):
        return False, "not-image-like"
    if label in {"manual", "legal", "medical"} and not (_is_doc_like(extension, mime_type) or extension in {"pdf", "doc", "docx"}):
        return False, "not-document-like"
    return True, "ok"


def _record_to_example(record: dict[str, Any], annotation: dict[str, Any], label: str) -> dict[str, Any]:
    matched = _extract_matched_terms(label, record, annotation)
    ranked = [item for item in annotation.get("teacher_ranked_labels", []) if item and item != label][:5]
    summary = str(record.get("content_text") or "")[:1600].strip()
    note = f"source-backed {label} example from live index"
    return {
        "kind": "live_index_sanity_checked",
        "filename": str(record.get("name") or "unknown"),
        "source_filename": str(record.get("name") or "unknown"),
        "source_path": str(record.get("path") or ""),
        "correct_label": label,
        "primary_label": label,
        "secondary_labels": ranked,
        "summary": summary,
        "note": note,
        "old_label": str(annotation.get("naive_label") or ""),
        "review_status": "codex_sanity_checked",
        "confidence": annotation.get("teacher_confidence"),
        "teacher_primary": annotation.get("teacher_primary"),
        "teacher_evidence": annotation.get("teacher_evidence", []),
        "teacher_ranked_labels": annotation.get("teacher_ranked_labels", []),
        "matched_terms": matched,
        "source_extension": _extension_from_record(record),
        "source_mime_type": str(record.get("mime_type") or ""),
        "provider": annotation.get("provider"),
    }


def _existing_review_rows(examples_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not examples_path.exists():
        return rows
    for line in examples_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict) and item.get("kind") == "reviewed_manifest":
            rows.append(item)
    return rows


def mine_example_corpus(
    *,
    database_url: str | None = None,
    examples_path: Path = EXAMPLES_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    db_url = database_url or resolve_index_database_url()
    selected_by_label: dict[str, list[dict[str, Any]]] = {label: [] for label in EXAMPLE_TARGET_QUOTAS}
    taxonomy_counts: Counter[str] = Counter()
    taxonomy_paths: dict[str, list[str]] = defaultdict(list)
    rejected_reasons: Counter[str] = Counter()
    existing_rows = _existing_review_rows(examples_path)
    selected_paths = {str(row.get("source_path") or "").strip() for row in existing_rows if str(row.get("source_path") or "").strip()}

    for label, spec in LABEL_SPECS.items():
        candidates = _fetch_candidate_records_for_label(db_url, label, limit=max(spec.quota * 25, 80))
        taxonomy_counts[label] = len(candidates)
        for record in candidates:
            source_path = str(record.get("path") or "").strip()
            if not source_path or source_path in selected_paths:
                continue
            if len(selected_by_label[label]) >= spec.quota:
                break
            annotation = _annotate_record(record)
            ok, reason = is_sane_example_candidate(label, record, annotation)
            if not ok:
                rejected_reasons[reason] += 1
                continue
            selected_by_label[label].append(_record_to_example(record, annotation, label))
            selected_paths.add(source_path)
            if len(taxonomy_paths[label]) < 5:
                taxonomy_paths[label].append(source_path)

    mined_rows = [row for label in LABEL_SPECS for row in selected_by_label[label]]
    merged_rows = existing_rows + mined_rows

    examples_path.parent.mkdir(parents=True, exist_ok=True)
    examples_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in merged_rows),
        encoding="utf-8",
    )

    sanity_samples: dict[str, list[dict[str, Any]]] = {}
    for label in ("receipt", "claim", "ui-screenshot", "return-summary", "consumer-report", "utility-bill", "hotel-folio"):
        sanity_samples[label] = [
            {
                "source_path": row.get("source_path"),
                "teacher_primary": row.get("teacher_primary"),
                "confidence": row.get("confidence"),
                "matched_terms": row.get("matched_terms"),
                "summary_preview": str(row.get("summary") or "")[:200],
            }
            for row in selected_by_label.get(label, [])[:3]
        ]

    report = {
        "ok": True,
        "primary_public_dataset": PRIMARY_PUBLIC_DATASET,
        "database_url_used": db_url,
        "existing_rows_preserved": len(existing_rows),
        "mined_rows_added": len(mined_rows),
        "total_rows_written": len(merged_rows),
        "selected_label_counts": {label: len(rows) for label, rows in selected_by_label.items()},
        "rejected_reasons": dict(rejected_reasons),
        "taxonomy_expansion": {
            "primary_public_dataset": PRIMARY_PUBLIC_DATASET,
            "expanded_labels": sorted(LABEL_SPECS),
            "live_index_label_counts": dict(taxonomy_counts),
            "sample_paths": dict(taxonomy_paths),
        },
        "sanity_samples": sanity_samples,
        "examples_path": str(examples_path),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def _fetch_candidate_records_for_label(database_url: str, label: str, limit: int) -> list[dict[str, Any]]:
    spec = LABEL_SPECS[label]
    patterns = [f"%{term.lower()}%" for term in dict.fromkeys([*spec.query_terms, *spec.required_terms, *spec.path_terms]) if term]
    sql = """
        select
            f.id,
            f.external_id,
            f.name,
            f.path,
            f.mime_type,
            coalesce(f.extension, '') as extension,
            coalesce(substr(ec.content_text, 1, 1800), '') as content_text
        from files f
        left join extracted_contents ec on ec.file_id = f.id
        where not f.is_deleted
          and (
            (%(has_patterns)s and (
                lower(f.name) like any(%(patterns)s)
                or lower(f.path) like any(%(patterns)s)
                or lower(coalesce(ec.content_text, '')) like any(%(patterns)s)
            ))
            or (%(has_extensions)s and lower(coalesce(f.extension, '')) = any(%(extensions)s))
          )
        order by f.id asc
        limit %(limit)s
    """
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        rows = conn.execute(
            sql,
            {
                "has_patterns": bool(patterns),
                "patterns": patterns or ["%__no_pattern__%"],
                "has_extensions": bool(spec.extensions),
                "extensions": list(spec.extensions),
                "limit": limit,
            },
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    report = mine_example_corpus()
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
