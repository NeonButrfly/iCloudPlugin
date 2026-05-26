from __future__ import annotations

from typing import Iterable


CANONICAL_LABEL_MAP: dict[str, str] = {
    "appeal": "insurance",
    "benefits": "insurance",
    "claim": "insurance",
    "insurance": "insurance",
    "explanation-of-benefits": "insurance",
    "denial-letter": "insurance",
    "appeal-template": "insurance",
    "claim-form": "insurance",
    "eligibility-notice": "insurance",
    "medical-receipt": "financial",
    "reimbursement-packet": "financial",
    "fsa": "financial",
    "hsa": "financial",
    "receipt": "financial",
    "invoice": "financial",
    "statement": "financial",
    "bank": "financial",
    "financial": "financial",
    "billing-statement": "financial",
    "bank-statement": "financial",
    "check": "financial",
    "payment-history": "financial",
    "return-summary": "financial",
    "utility-bill": "financial",
    "hotel-folio": "financial",
    "pharmacy": "medical",
    "prescription": "medical",
    "otc-medication": "medical",
    "sunscreen": "medical",
    "spf-product": "medical",
    "cosmetic-spf": "medical",
    "medical": "medical",
    "medical-estimate": "medical",
    "tax-form": "tax",
    "contract": "legal",
    "policy": "legal",
    "legal": "legal",
    "photo": "image-only",
    "product-photo": "image-only",
    "consumer-report": "identity-document",
    "ui-screenshot": "screenshot",
}


def canonicalize_label(label: str | None) -> str:
    normalized = str(label or "").strip().lower()
    if not normalized:
        return "unknown"
    return CANONICAL_LABEL_MAP.get(normalized, normalized)


def canonicalize_labels(labels: Iterable[str] | None) -> list[str]:
    if not labels:
        return []
    out: list[str] = []
    for label in labels:
        canonical = canonicalize_label(label)
        if canonical and canonical not in out:
            out.append(canonical)
    return out
