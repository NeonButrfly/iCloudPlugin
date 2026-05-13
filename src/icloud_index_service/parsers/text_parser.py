from __future__ import annotations


def extract_text_from_plaintext_bytes(payload: bytes) -> str:
    return payload.decode("utf-8", errors="ignore")
