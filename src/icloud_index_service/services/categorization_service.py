from __future__ import annotations


def build_category_prompt(*, path: str, excerpt: str) -> str:
    return (
        "Classify this file into a stable knowledge category.\n"
        f"Path: {path}\n"
        f"Excerpt: {excerpt}\n"
        "Return a suggested category, confidence, and brief reasoning."
    )
