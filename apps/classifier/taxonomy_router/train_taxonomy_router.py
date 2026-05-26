#!/usr/bin/env python3
import json
import re
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from apps.classifier.external_taxonomy import load_external_taxonomy_aliases, refresh_external_taxonomy_aliases
from packages.runtime import load_classifier_runtime_settings

SETTINGS = load_classifier_runtime_settings()
CONFIG_DIR = SETTINGS.config_root
FULL_CATEGORIES = CONFIG_DIR / "categories.full.txt"
LOCAL_CATEGORIES = SETTINGS.local_categories_path
GROUPS_FILE = SETTINGS.category_groups_path
CORRECTIONS_FILE = SETTINGS.corrections_path
EXAMPLES_FILE = SETTINGS.examples_path
MODEL_PATH = SETTINGS.taxonomy_router_model_path
REPORT_PATH = SETTINGS.taxonomy_router_report_path
EXTERNAL_TAXONOMY_ALIASES_PATH = SETTINGS.external_taxonomy_aliases_path

def clean_label(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._/ -]", " ", value)
    value = re.sub(r"\s+", "-", value)
    return value.strip("-")

def load_lines(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label = clean_label(line)
        if label:
            out.append(label)
    return list(dict.fromkeys(out))

def load_groups():
    if GROUPS_FILE.exists():
        try:
            return json.loads(GROUPS_FILE.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
    return {}

def load_corrections():
    if not CORRECTIONS_FILE.exists():
        return []
    rows = []
    for line in CORRECTIONS_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            pass
    return rows


def load_examples():
    if not EXAMPLES_FILE.exists():
        return []
    rows = []
    for line in EXAMPLES_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        except Exception:
            pass
    return rows

def label_words(label: str) -> str:
    return label.replace("-", " ").replace("/", " ").replace("_", " ")

def examples_for_label(label: str):
    words = label_words(label)
    examples = [
        label,
        words,
        f"classification category {words}",
        f"file label {words}",
    ]

    if any(k in label for k in ["receipt", "invoice", "reimbursement", "financial", "tax", "claim", "fsa", "hsa"]):
        examples += [
            f"receipt invoice vendor total payment order reimbursement claim {words}",
            f"financial fsa hsa benefits claim receipt sunscreen spf medical expense {words}",
        ]

    if any(k in label for k in ["legal", "contract", "policy", "law", "regulation"]):
        examples += [
            f"legal contract policy regulation agreement terms clause {words}",
        ]

    if any(k in label for k in ["medical", "pharmacy", "prescription", "health"]):
        examples += [
            f"medical healthcare pharmacy prescription insurance patient clinic medication {words}",
        ]

    if any(k in label for k in ["reference", "concept", "environment", "game", "architecture", "industrial", "sci-fi", "snow", "facility", "waystation", "post-apocalyptic"]):
        examples += [
            f"image reference concept art environment game architecture industrial sci fi snow facility waystation {words}",
            f"visual reference frozen industrial exterior machinery facility not document not receipt {words}",
        ]

    if any(k in label for k in ["screenshot", "ui", "terminal", "source-code", "diagram"]):
        examples += [
            f"screenshot user interface terminal error code console technical diagram {words}",
        ]

    if any(k in label for k in ["product", "photo", "shopping"]):
        examples += [
            f"product photo retail item packaging object shopping catalog {words}",
        ]

    return examples

def main():
    categories = load_lines(FULL_CATEGORIES) or load_lines(LOCAL_CATEGORIES)
    groups = load_groups()
    corrections = load_corrections()
    examples = load_examples()
    if not EXTERNAL_TAXONOMY_ALIASES_PATH.exists():
        refresh_external_taxonomy_aliases()
    external_aliases = load_external_taxonomy_aliases()

    if not categories:
        raise SystemExit("No categories found. Run taxonomy sync first.")

    texts = []
    labels = []

    for label in categories:
        for text in examples_for_label(label):
            texts.append(text)
            labels.append(label)

    for group_name, group_labels in groups.items():
        for label in group_labels:
            label = clean_label(str(label))
            if not label:
                continue
            texts.append(f"{group_name} {label_words(label)}")
            labels.append(label)

    for c in corrections:
        correct = clean_label(str(c.get("correct_label", "")))
        if not correct:
            continue
        filename = str(c.get("filename", ""))
        note = str(c.get("note", ""))
        summary = str(c.get("summary", ""))
        secondary = " ".join(map(str, c.get("secondary_labels", [])))
        old_label = str(c.get("old_label", ""))
        sample = f"{filename} {note} {summary} secondary {secondary} old {old_label}"
        texts.append(sample)
        labels.append(correct)

    example_rows = 0
    for example in examples:
        correct = clean_label(str(example.get("correct_label") or example.get("primary_label") or ""))
        if not correct:
            continue
        filename = str(example.get("filename", ""))
        source_path = str(example.get("source_path", ""))
        note = str(example.get("note", ""))
        summary = str(example.get("summary", ""))
        secondary = " ".join(map(str, example.get("secondary_labels", [])))
        old_label = str(example.get("old_label", ""))
        teacher_primary = str(example.get("teacher_primary", ""))
        teacher_evidence = " ".join(map(str, example.get("teacher_evidence", [])))
        matched_terms = json.dumps(example.get("matched_terms", {}), ensure_ascii=False)
        sample = (
            f"{filename} {source_path} {note} {summary} secondary {secondary} "
            f"old {old_label} teacher {teacher_primary} evidence {teacher_evidence} "
            f"matched {matched_terms}"
        )
        texts.append(sample)
        labels.append(correct)
        example_rows += 1

    external_rows = 0
    for label, aliases in external_aliases.items():
        if label not in categories:
            continue
        for alias in aliases[:40]:
            texts.append(f"external taxonomy alias {alias}")
            labels.append(label)
            external_rows += 1

    vectorizer = TfidfVectorizer(
        lowercase=True,
        analyzer="word",
        ngram_range=(1, 2),
        max_features=60000,
        min_df=1,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )

    matrix = vectorizer.fit_transform(texts)

    model = {
        "kind": "tfidf_label_index",
        "vectorizer": vectorizer,
        "matrix": matrix,
        "labels": labels,
    }

    joblib.dump(model, MODEL_PATH, compress=3)

    report = {
        "ok": True,
        "kind": "tfidf_label_index",
        "category_count": len(set(labels)),
        "training_rows": len(texts),
        "features": len(vectorizer.vocabulary_),
        "corrections_used": len(corrections),
        "examples_used": example_rows,
        "external_alias_rows": external_rows,
        "external_alias_labels": len(external_aliases),
        "model_path": str(MODEL_PATH),
    }

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
