from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

MAX_ENTITY_VALUES = 5
MAX_RETRIEVAL_TERMS = 24
MAX_SOURCE_TEXT_CHARS = 20000

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{1,63}")
DATE_RE = re.compile(
    r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{4})\b",
    re.IGNORECASE,
)
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]*)?(?:\(?\d{3}\)?[-.\s]*)\d{3}[-.\s]*\d{4}\b")
LABELED_VALUE_RE = re.compile(
    r"(?im)\b("
    r"patient(?:\s+name)?|member(?:\s+name)?|subscriber(?:\s+name)?|"
    r"provider|doctor|physician|clinic|hospital|insurer|insurance company|vendor|merchant|"
    r"bank(?:/issuer name)?|issuer|hotel|airline|employer|employee|customer|company|organization"
    r")\s*[:#-]\s*([^\n|]{2,100})"
)
IDENTIFIER_RE = re.compile(
    r"(?im)\b("
    r"claim(?:\s+id|\s+#)?|member\s+id|policy(?:\s+number)?|account(?:\s+number)?|"
    r"invoice(?:\s+number)?|order(?:\s+number)?|case(?:\s+number)?|reference(?:\s+number)?|"
    r"tracking(?:\s+number)?|confirmation(?:\s+number)?|authorization(?:\s+number)?|"
    r"rx(?:\s+number)?|appeal(?:\s+id)?|check(?:\s+number|\s+no)?|folio(?:\s+no)?"
    r")\s*[:#-]?\s*([A-Z0-9][A-Z0-9._/-]{2,40})"
)

STOP_WORDS = {
    "and",
    "for",
    "from",
    "that",
    "this",
    "with",
    "your",
    "have",
    "will",
    "file",
    "document",
    "folder",
    "shared",
    "untitled",
    "draft",
    "copy",
    "final",
    "updated",
    "notes",
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "medical": ("patient", "provider", "clinic", "hospital", "diagnosis", "prescription", "vyepti"),
    "insurance": ("insurance", "claim", "coverage", "benefits", "eob", "deductible", "copay"),
    "legal": ("agreement", "contract", "terms", "notice", "policy", "appeal", "dispute"),
    "tax": ("tax", "1099", "w-2", "w2", "irs", "refund", "withholding"),
    "financial": ("invoice", "receipt", "statement", "payment", "budget", "balance", "bank", "venmo"),
    "travel": ("hotel", "flight", "airline", "reservation", "itinerary", "uber"),
    "identity": ("driver license", "passport", "ssn", "social security", "id card", "name change"),
    "education": ("school", "course", "student", "philosophy", "essay", "assignment"),
    "technical": ("incident", "server", "network", "log", "source code", "configuration", "manual"),
    "shopping": ("order", "return", "purchase", "shipping", "merchant", "lowe", "amazon"),
    "screenshot": ("screenshot", "screen shot", "ui", "dialog", "error", "window"),
    "photo": ("photo", "image", "jpeg", "camera", "portrait", "family"),
}


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


def _normalize_label_tokens(classification: Mapping[str, Any] | None) -> list[str]:
    if not classification:
        return []
    labels = [
        str(classification.get("primary_label") or "").strip(),
        *[str(item).strip() for item in (classification.get("secondary_labels") or [])],
        *[str(item).strip() for item in (classification.get("retrieval_topics") or [])],
    ]
    return [label for label in _unique_preserve(labels) if label]


def _path_terms(source_path: Path) -> list[str]:
    raw_parts = [
        source_path.stem,
        *[part for part in source_path.parts if part not in {source_path.anchor, "/", "\\"}],
    ]
    terms: list[str] = []
    for part in raw_parts:
        for token in re.split(r"[^A-Za-z0-9]+", str(part or "")):
            lowered = token.strip().lower()
            if len(lowered) < 3 or lowered in STOP_WORDS:
                continue
            terms.append(lowered)
    return _unique_preserve(terms)


def _extract_entity_groups(text: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "people": [],
        "organizations": [],
        "identifiers": [],
        "dates": [],
        "emails": [],
        "phones": [],
    }

    for label, value in LABELED_VALUE_RE.findall(text):
        cleaned = re.sub(r"\s+", " ", value.strip(" \t\r\n,.;"))
        if not cleaned:
            continue
        lowered_label = label.lower()
        if any(token in lowered_label for token in ("patient", "member", "subscriber", "employee", "customer")):
            groups["people"].append(cleaned)
        else:
            groups["organizations"].append(cleaned)

    for label, value in IDENTIFIER_RE.findall(text):
        groups["identifiers"].append(f"{label.strip()}: {value.strip()}")

    groups["dates"].extend(match.group(0) for match in DATE_RE.finditer(text))
    groups["emails"].extend(match.group(0) for match in EMAIL_RE.finditer(text))
    groups["phones"].extend(match.group(0) for match in PHONE_RE.finditer(text))

    return {
        key: _unique_preserve(values)[:MAX_ENTITY_VALUES]
        for key, values in groups.items()
        if values
    }


def _derive_topics(
    *,
    text_lower: str,
    path_terms: list[str],
    label_tokens: list[str],
) -> list[str]:
    topics: list[str] = []
    lookup_text = " ".join([text_lower, " ".join(path_terms), " ".join(label_tokens).lower()])
    for topic, keywords in TOPIC_KEYWORDS.items():
        if topic in {token.lower() for token in label_tokens}:
            topics.append(topic)
            continue
        if any(keyword in lookup_text for keyword in keywords):
            topics.append(topic)
    topics.extend(token.lower() for token in label_tokens if token)
    return _unique_preserve(topics)


def _entity_terms(entity_groups: dict[str, list[str]]) -> list[str]:
    terms: list[str] = []
    for values in entity_groups.values():
        for value in values:
            terms.append(value.lower())
            for token in re.split(r"[^A-Za-z0-9]+", value.lower()):
                if len(token) >= 3 and token not in STOP_WORDS:
                    terms.append(token)
    return _unique_preserve(terms)


def _text_terms(text: str) -> list[str]:
    counts: dict[str, int] = {}
    for token in TOKEN_RE.findall(text.lower()):
        normalized = token.strip("._/-")
        if len(normalized) < 3 or normalized in STOP_WORDS:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ranked[:MAX_RETRIEVAL_TERMS]]


def build_retrieval_metadata(
    *,
    source_path: str | Path,
    text: str,
    classification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(str(source_path))
    bounded_text = str(text or "")[:MAX_SOURCE_TEXT_CHARS]
    label_tokens = _normalize_label_tokens(classification)
    path_terms = _path_terms(path)
    text_lower = bounded_text.lower()
    entity_groups = _extract_entity_groups(bounded_text)
    topics = _derive_topics(
        text_lower=text_lower,
        path_terms=path_terms,
        label_tokens=label_tokens,
    )

    retrieval_terms = _unique_preserve(
        topics
        + label_tokens
        + path_terms
        + _entity_terms(entity_groups)
        + _text_terms(f"{path.name}\n{bounded_text}")
    )[:MAX_RETRIEVAL_TERMS]

    entity_sections = [
        f"{group}: {', '.join(values)}"
        for group, values in entity_groups.items()
        if values
    ]
    entity_summary = "; ".join(entity_sections)
    topic_summary = ", ".join(topics[:12])

    retrieval_text_parts = [
        path.name,
        path.as_posix(),
        " ".join(label_tokens),
        topic_summary,
        entity_summary,
        " ".join(retrieval_terms),
        bounded_text[:4000],
    ]
    retrieval_text = " ".join(part for part in retrieval_text_parts if part).strip()

    return {
        "entity_summary": entity_summary,
        "topic_summary": topic_summary,
        "retrieval_topics": topics[:12],
        "retrieval_terms": retrieval_terms,
        "retrieval_text": retrieval_text,
    }
