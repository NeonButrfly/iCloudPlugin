import tempfile
from pathlib import Path

from packages.vault.naming import (
    build_attachment_filename,
    build_extracted_markdown_filename,
    build_note_filename,
)
from apps.classifier.classify_to_obsidian import ensure_vault, write_obsidian_note


def test_default_note_name_omits_visible_hash():
    note_name = build_note_filename(title="Budget Draft", primary_label="financial")

    assert note_name == "Budget Draft - financial.md"


def test_duplicate_note_names_use_collision_suffix():
    existing = {"Budget Draft - financial.md"}

    note_name = build_note_filename(
        title="Budget Draft",
        primary_label="financial",
        existing_names=existing,
    )

    assert note_name == "Budget Draft - financial (2).md"


def test_extracted_markdown_name_stays_human_readable():
    extracted_name = build_extracted_markdown_filename(title="Budget Draft")

    assert extracted_name == "Budget Draft.extracted.md"


def test_attachment_name_stays_human_readable():
    attachment_name = build_attachment_filename(source_name="Budget Draft.pdf")

    assert attachment_name == "Budget Draft.pdf"


def test_write_obsidian_note_uses_clean_visible_note_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        source_path = root / "Inbox" / "Budget Draft.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"budget-pdf")
        ensure_vault(vault)

        note_path = write_obsidian_note(
            vault=vault,
            source_path=source_path,
            file_hash="abcdef1234567890",
            markdown="Budget preview",
            classification={
                "primary_label": "financial",
                "secondary_labels": [],
                "confidence": 0.95,
                "summary": "Budget summary.",
                "reason": "Financial budget document.",
                "sensitive_flags": [],
                "recommended_action": "retain",
                "file_date_guess": "2026-05-22",
                "language": "English",
            },
            attach_originals=False,
        )

    assert note_path.name == "Budget Draft - financial.md"
