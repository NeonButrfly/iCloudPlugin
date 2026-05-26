from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from packages.runtime import load_classifier_runtime_settings

SETTINGS = load_classifier_runtime_settings()
TAXONOMY_SOURCES_PATH = SETTINGS.taxonomy_sources_path
EXTERNAL_TAXONOMY_ALIASES_PATH = SETTINGS.external_taxonomy_aliases_path
EXTERNAL_TAXONOMY_PRUNE_PATH = SETTINGS.external_taxonomy_prune_path

FetchText = Callable[[str], str]

EXACT_LABEL_MAPPINGS: dict[str, tuple[str, ...]] = {
    "advertisement": ("marketing",),
    "budget": ("financial",),
    "email": ("letter", "work"),
    "file folder": ("work",),
    "form": ("form",),
    "invoice": ("invoice", "financial"),
    "memo": ("report", "work"),
    "news article": ("report",),
    "presentation": ("presentation",),
    "questionnaire": ("form",),
    "resume": ("identity-document", "work"),
    "scientific publication": ("report", "school"),
    "scientific report": ("report", "school"),
    "specification": ("technical", "manual"),
}

LOCAL_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "invoice": ("invoice", "billing statement", "balance due", "amount due"),
    "receipt": ("receipt", "subtotal", "line total", "proof of purchase"),
    "financial": ("budget", "bank", "banking", "finance", "financial", "payment", "accounting", "transaction"),
    "tax": ("tax", "1099", "w-2", "w2", "1040", "withholding"),
    "insurance": ("insurance", "benefits", "claim", "claims", "premium", "coverage", "appeal", "deductible"),
    "explanation-of-benefits": ("explanation of benefits", "eob"),
    "denial-letter": ("denial", "denied claim", "adverse benefit determination"),
    "appeal-template": ("appeal template", "appeal form", "complaint and appeal form"),
    "claim-form": ("claim form", "member complaint", "submit a claim"),
    "billing-statement": ("billing statement", "balance due", "account summary"),
    "bank-statement": ("bank statement", "account ending", "ending balance"),
    "tax-form": ("tax form", "1099", "w-2", "w2", "1040"),
    "check": ("check", "check number", "routing number"),
    "medical": ("medical", "health", "healthcare", "clinic", "doctor", "patient", "hospital", "ambulance", "syringe"),
    "medical-receipt": ("medical receipt", "visit receipt", "copay", "co-pay"),
    "medical-estimate": ("estimate", "procedures and services cost", "treatment plan"),
    "pharmacy": ("pharmacy",),
    "prescription": ("prescription", "rx"),
    "otc-medication": ("over the counter", "over-the-counter", "otc"),
    "sunscreen": ("sunscreen",),
    "spf-product": ("spf", "sun care"),
    "cosmetic-spf": ("cosmetics", "skincare", "moisturizer", "personal care"),
    "legal": ("legal", "law", "laws", "regulation", "regulations", "contract", "agreement", "compliance", "patent"),
    "form": ("application", "questionnaire", "business forms", "medical forms"),
    "manual": ("manual", "guide", "instructions", "specification"),
    "report": ("report", "publication", "article", "memo"),
    "presentation": ("presentation", "slides", "deck"),
    "identity-document": ("passport", "driver license", "driver's license", "id card", "identity"),
    "eligibility-notice": ("eligibility notice", "eligibility results notice", "eligibility"),
    "payment-history": ("payment history", "payment methods", "transactions", "paid to"),
    "return-summary": ("return summary", "rma id", "ups store", "no box no label"),
    "consumer-report": ("consumer report", "checkr", "lexisnexis", "disclosure report"),
    "utility-bill": ("utility bill", "electric bill", "meter number", "service address"),
    "hotel-folio": ("hotel folio", "folio no", "room no", "arrival", "departure"),
    "school": ("education", "student", "school", "scientific"),
    "work": ("office", "office supplies", "office building"),
    "technical": ("technical", "software", "computer", "code", "specification"),
    "marketing": ("advertisement", "advertising", "shopping", "brand", "catalog"),
    "reference-image": ("architecture", "landscape", "industrial", "building", "facility"),
    "product-photo": ("product", "packaging", "cosmetics", "bottle", "box"),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_phrase(value: str) -> str:
    text = value.strip().lower().replace("&", " and ")
    text = text.replace("-", " ")
    text = text.replace("/", " ")
    text = text.replace(">", " ")
    text = re.sub(r"[^a-z0-9_ -]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_label_token(value: str) -> str:
    return re.sub(r"\s+", "-", _normalize_phrase(value)).strip("-")


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = f" {_normalize_phrase(text)} "
    normalized_phrase = _normalize_phrase(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in normalized_text


def _fetch_url_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def load_external_taxonomy_prune_rules(path: Path | None = None) -> dict[str, Any]:
    prune_path = path or EXTERNAL_TAXONOMY_PRUNE_PATH
    if not prune_path.exists():
        return {"blocked_aliases_by_label": {}, "blocked_aliases_global": []}
    try:
        payload = json.loads(prune_path.read_text(encoding="utf-8"))
    except Exception:
        return {"blocked_aliases_by_label": {}, "blocked_aliases_global": []}
    if not isinstance(payload, dict):
        return {"blocked_aliases_by_label": {}, "blocked_aliases_global": []}
    blocked_by_label = payload.get("blocked_aliases_by_label", {})
    blocked_global = payload.get("blocked_aliases_global", [])
    return {
        "blocked_aliases_by_label": {
            _clean_label_token(str(label)): [
                _normalize_phrase(str(alias))
                for alias in values
                if _normalize_phrase(str(alias))
            ]
            for label, values in blocked_by_label.items()
            if isinstance(values, list)
        },
        "blocked_aliases_global": [
            _normalize_phrase(str(alias))
            for alias in blocked_global
            if _normalize_phrase(str(alias))
        ],
    }


def _alias_allowed(label: str, alias: str, prune_rules: dict[str, Any] | None) -> bool:
    if not alias:
        return False
    normalized_alias = _normalize_phrase(alias)
    if not normalized_alias:
        return False
    rules = prune_rules or {}
    blocked_global = {
        _normalize_phrase(str(item))
        for item in rules.get("blocked_aliases_global", []) or []
    }
    blocked_by_label = {
        _clean_label_token(str(key)): {
            _normalize_phrase(str(item))
            for item in value
        }
        for key, value in (rules.get("blocked_aliases_by_label", {}) or {}).items()
        if isinstance(value, list)
    }
    normalized_label = _clean_label_token(label)
    if normalized_alias in blocked_global:
        return False
    if normalized_alias in blocked_by_label.get(normalized_label, set()):
        return False
    return True


def load_taxonomy_sources(path: Path | None = None) -> list[dict[str, Any]]:
    sources_path = path or TAXONOMY_SOURCES_PATH
    if not sources_path.exists():
        return []
    try:
        payload = json.loads(sources_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict) and item.get("enabled", True)]


def _parse_csv_last_column(text: str) -> list[str]:
    rows = csv.reader(io.StringIO(text))
    labels: list[str] = []
    for row in rows:
        if not row:
            continue
        label = _normalize_phrase(row[-1])
        if label:
            labels.append(label)
    return labels


def _parse_google_product_taxonomy(text: str) -> list[str]:
    labels: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [_normalize_phrase(part) for part in line.split(">") if _normalize_phrase(part)]
        if not parts:
            continue
        labels.append(" > ".join(parts))
        labels.extend(parts[-2:])
    return labels


def _parse_iab_tsv(text: str) -> list[str]:
    lines = text.splitlines()
    header_index = next((index for index, line in enumerate(lines) if "Unique ID" in line and "\t" in line), None)
    if header_index is None:
        return []
    rows = csv.DictReader(io.StringIO("\n".join(lines[header_index:])), delimiter="\t")
    labels: list[str] = []
    for row in rows:
        name = _normalize_phrase(str(row.get("Name", "") or ""))
        tiers = [
            _normalize_phrase(str(row.get(column, "") or ""))
            for column in ("Tier 1", "Tier 2", "Tier 3", "Tier 4")
        ]
        tiers = [tier for tier in tiers if tier]
        if name:
            labels.append(name)
        if tiers:
            labels.append(" > ".join(tiers))
            labels.extend(tiers[-2:])
    return labels


def _parse_static(source: dict[str, Any]) -> list[str]:
    labels = source.get("labels", [])
    if not isinstance(labels, list):
        return []
    return [_normalize_phrase(str(label)) for label in labels if _normalize_phrase(str(label))]


def parse_source_labels(source: dict[str, Any], fetch_text: FetchText | None = None) -> list[str]:
    parser = str(source.get("parser", "static") or "static").strip().lower()
    if parser == "static":
        labels = _parse_static(source)
    else:
        url = str(source.get("url", "") or "").strip()
        if not url:
            return []
        raw_text = (fetch_text or _fetch_url_text)(url)
        if parser == "csv_last_column":
            labels = _parse_csv_last_column(raw_text)
        elif parser == "google_product_taxonomy":
            labels = _parse_google_product_taxonomy(raw_text)
        elif parser == "iab_tsv":
            labels = _parse_iab_tsv(raw_text)
        else:
            labels = []
    return list(dict.fromkeys(label for label in labels if label))


def _map_exact_label(label: str) -> list[str]:
    normalized = _normalize_phrase(label)
    return list(EXACT_LABEL_MAPPINGS.get(normalized, ()))


def map_external_label_to_local_categories(label: str, kind: str = "") -> list[str]:
    normalized = _normalize_phrase(label)
    mapped: list[str] = []
    seen: set[str] = set()

    for local_label in _map_exact_label(normalized):
        if local_label not in seen:
            mapped.append(local_label)
            seen.add(local_label)

    for local_label, keywords in LOCAL_CATEGORY_KEYWORDS.items():
        if any(_contains_phrase(normalized, keyword) for keyword in keywords):
            if local_label not in seen:
                mapped.append(local_label)
                seen.add(local_label)

    if kind == "document" and "manual" not in seen and _contains_phrase(normalized, "specification"):
        mapped.append("manual")
    if kind == "vision" and "product-photo" not in seen and any(_contains_phrase(normalized, term) for term in ("cosmetics", "toothbrush", "bottle", "box")):
        mapped.append("product-photo")

    return mapped


def _alias_variants(label: str) -> list[str]:
    normalized = _normalize_phrase(label)
    if not normalized:
        return []
    parts = [part.strip() for part in normalized.split(">") if part.strip()]
    variants: list[str] = []
    if parts:
        variants.append(parts[-1])
        if len(parts) > 1:
            variants.append(" > ".join(parts[-2:]))
    else:
        variants.append(normalized)
    return list(dict.fromkeys(variant for variant in variants if variant))


def build_external_taxonomy_aliases(
    sources: list[dict[str, Any]],
    fetch_text: FetchText | None = None,
    max_aliases_per_label: int = 120,
    prune_rules: dict[str, Any] | None = None,
) -> dict[str, Any]:
    label_aliases: dict[str, set[str]] = defaultdict(set)
    source_examples: dict[str, list[dict[str, str]]] = defaultdict(list)
    source_summaries: list[dict[str, Any]] = []

    for source in sources:
        parsed_labels = parse_source_labels(source, fetch_text=fetch_text)
        mapped_count = 0
        for parsed_label in parsed_labels:
            mapped_labels = map_external_label_to_local_categories(parsed_label, kind=str(source.get("kind", "") or ""))
            if not mapped_labels:
                continue
            mapped_count += 1
            variants = _alias_variants(parsed_label)
            for local_label in mapped_labels:
                for variant in variants:
                    if _alias_allowed(local_label, variant, prune_rules) and len(label_aliases[local_label]) < max_aliases_per_label:
                        label_aliases[local_label].add(variant)
                if len(source_examples[local_label]) < 6:
                    source_examples[local_label].append(
                        {
                            "source": str(source.get("name", "unknown")),
                            "label": parsed_label,
                        }
                    )
        source_summaries.append(
            {
                "name": str(source.get("name", "unknown")),
                "kind": str(source.get("kind", "unknown")),
                "parsed_label_count": len(parsed_labels),
                "mapped_label_count": mapped_count,
            }
        )

    return {
        "generated_at": _utc_now(),
        "source_count": len(source_summaries),
        "sources": source_summaries,
        "label_aliases": {
            label: sorted(values)
            for label, values in sorted(label_aliases.items())
        },
        "source_examples": dict(source_examples),
    }


def refresh_external_taxonomy_aliases(
    *,
    sources_path: Path | None = None,
    aliases_path: Path | None = None,
    fetch_text: FetchText | None = None,
) -> dict[str, Any]:
    sources = load_taxonomy_sources(sources_path)
    payload = build_external_taxonomy_aliases(
        sources,
        fetch_text=fetch_text,
        prune_rules=load_external_taxonomy_prune_rules(),
    )
    output_path = aliases_path or EXTERNAL_TAXONOMY_ALIASES_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload["ok"] = True
    payload["mapped_alias_count"] = sum(len(values) for values in payload["label_aliases"].values())
    payload["aliases_path"] = str(output_path)
    return payload


def load_external_taxonomy_aliases(path: Path | None = None) -> dict[str, list[str]]:
    aliases_path = path or EXTERNAL_TAXONOMY_ALIASES_PATH
    if not aliases_path.exists():
        return {}
    return _load_external_taxonomy_aliases_cached(str(aliases_path), aliases_path.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _load_external_taxonomy_aliases_cached(path_str: str, _mtime_ns: int) -> dict[str, list[str]]:
    aliases_path = Path(path_str)
    try:
        payload = json.loads(aliases_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    aliases = payload.get("label_aliases", {})
    if not isinstance(aliases, dict):
        return {}
    return {
        _clean_label_token(str(label)): [
            _normalize_phrase(str(alias))
            for alias in values
            if _normalize_phrase(str(alias))
        ]
        for label, values in aliases.items()
        if isinstance(values, list)
    }


def match_external_taxonomy_candidates(
    text: str,
    aliases: dict[str, list[str]] | None = None,
    prune_rules: dict[str, Any] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    alias_map = aliases or load_external_taxonomy_aliases()
    if not alias_map:
        return []
    active_prune_rules = prune_rules or load_external_taxonomy_prune_rules()

    normalized_text = _normalize_phrase(text)
    matches: list[dict[str, Any]] = []
    for label, label_aliases in alias_map.items():
        score = 0
        evidence: list[str] = []
        for alias in label_aliases:
            if not _alias_allowed(label, alias, active_prune_rules) or len(alias) < 3:
                continue
            if _contains_phrase(normalized_text, alias):
                score += 2 + min(len(alias.split()), 3)
                evidence.append(alias)
        if score > 0:
            matches.append(
                {
                    "label": label,
                    "score": score,
                    "evidence": evidence[:4],
                }
            )

    matches.sort(key=lambda item: (-int(item["score"]), item["label"]))
    return matches[:limit]


def build_external_taxonomy_hint_text(
    text: str,
    aliases: dict[str, list[str]] | None = None,
    limit: int = 6,
) -> str:
    matches = match_external_taxonomy_candidates(text, aliases=aliases, limit=limit)
    if not matches:
        return ""

    tokens: list[str] = []
    for match in matches:
        tokens.append(str(match["label"]))
        tokens.extend(str(alias) for alias in match.get("evidence", []))
    return " ".join(dict.fromkeys(token for token in tokens if token)).strip()
