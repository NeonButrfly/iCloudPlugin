import tempfile
from pathlib import Path

from packages.vault.naming import (
    build_attachment_filename,
    build_extracted_markdown_filename,
    build_note_filename,
)
from apps.classifier.classify_to_obsidian import ensure_vault, write_index, write_obsidian_note


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


def test_write_obsidian_note_prefers_canonical_filename_over_staged_upload_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        source_path = root / "input" / "api" / (
            "326d39e1bebd4d9aaac79a91206320ec-"
            "Aetna Life Insurance Company - APPEAL 1 FFS.docx"
        )
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"appeal-doc")
        ensure_vault(vault)

        note_path = write_obsidian_note(
            vault=vault,
            source_path=source_path,
            file_hash="abcdef1234567890",
            markdown="Appeal preview",
            classification={
                "primary_label": "appeal",
                "secondary_labels": [],
                "confidence": 0.95,
                "summary": "Appeal summary.",
                "reason": "Insurance appeal document.",
                "sensitive_flags": [],
                "recommended_action": "review",
                "file_date_guess": "2026-05-24",
                "language": "English",
            },
            attach_originals=True,
            canonical_source_path="/srv/cloud-vault/mirrors/google1/Aetna Life Insurance Company - APPEAL 1 FFS.docx",
            canonical_source_hash="abcdef1234567890",
            last_seen_filename="Aetna Life Insurance Company - APPEAL 1 FFS.docx",
        )

        attachment = vault / "90 Attachments" / "medical" / "appeals" / "Aetna Life Insurance Company - APPEAL 1 FFS.docx"
        extracted = vault / "_system" / "extracted-markdown" / "medical" / "appeals" / (
            "Aetna Life Insurance Company - APPEAL 1 FFS.extracted.md"
        )
        note_text = note_path.read_text(encoding="utf-8")

        assert note_path.parent.relative_to(vault).as_posix() == "01 Classified/medical/appeals"
        assert note_path.name == "Aetna Life Insurance Company - APPEAL 1 FFS - medical - appeals.md"
        assert "326d39e1bebd4d9aaac79a91206320ec" not in note_path.name
        assert "326d39e1bebd4d9aaac79a91206320ec" not in note_text
        assert 'attachment_mode: "canonical-source-link"' in note_text
        assert "entity_summary:" in note_text
        assert "retrieval_terms:" in note_text
        assert r"\\192.168.50.86\cloud-vault\mirrors\google1\Aetna Life Insurance Company - APPEAL 1 FFS.docx" in note_text
        assert not attachment.exists()
        assert extracted.exists()


def test_write_obsidian_note_recovers_malformed_payload_from_hybrid_hint():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        source_path = root / "google2" / "claims.csv"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text("claim_id,amount\n123,10\n", encoding="utf-8")
        ensure_vault(vault)

        note_path = write_obsidian_note(
            vault=vault,
            source_path=source_path,
            file_hash="abcdef1234567890",
            markdown="Aetna claim rows",
            classification={
                "candidate_categories_used": ["medical", "insurance", "needs-review"],
                "summary": "Claims export from insurer.",
                "reason": "Structured model output omitted the required primary label field.",
                "confidence": "",
            },
            attach_originals=False,
        )

        note_text = note_path.read_text(encoding="utf-8")

        assert note_path.parent.relative_to(vault).as_posix() == "02 Needs Review"
        assert note_path.name == "claims - needs-review.md"
        assert 'primary_label: "needs-review"' in note_text
        assert 'recommended_action: "review"' in note_text
        assert 'confidence: 0.55' in note_text
        assert "Structured model output omitted the required primary label field." in note_text


def test_write_obsidian_note_reuses_existing_note_for_same_canonical_source():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        source_path = root / "input" / "api" / "uuid-project kay memory.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"memory-pdf")
        ensure_vault(vault)

        classification = {
            "primary_label": "medical",
            "secondary_labels": [],
            "confidence": 0.42,
            "summary": "Needs review summary.",
            "reason": "Low confidence medical memory document.",
            "sensitive_flags": [],
            "recommended_action": "review",
            "file_date_guess": "2026-05-27",
            "language": "English",
        }
        kwargs = {
            "vault": vault,
            "source_path": source_path,
            "file_hash": "abcdef1234567890",
            "markdown": "Memory preview",
            "classification": classification,
            "attach_originals": False,
            "canonical_source_path": "/srv/cloud-vault/mirrors/icloud/project kay memory.pdf",
            "canonical_source_hash": "abcdef1234567890",
            "last_seen_filename": "project kay memory.pdf",
        }

        first_note_path = write_obsidian_note(**kwargs)
        second_note_path = write_obsidian_note(**kwargs)

        matching_notes = sorted((vault / "02 Needs Review").glob("project kay memory - medical*.md"))
        matching_extracted = sorted(
            (vault / "_system" / "extracted-markdown" / "medical").glob("project kay memory.extracted*.md")
        )

        assert first_note_path == second_note_path
        assert first_note_path.name == "project kay memory - medical.md"
        assert [path.name for path in matching_notes] == ["project kay memory - medical.md"]
        assert [path.name for path in matching_extracted] == ["project kay memory.extracted.md"]


def test_write_obsidian_note_collapses_existing_duplicate_note_for_same_canonical_source():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        source_path = root / "icloud" / "project kay memory.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"memory-pdf")
        ensure_vault(vault)

        note_dir = vault / "02 Needs Review"
        note_dir.mkdir(parents=True, exist_ok=True)
        extracted_dir = vault / "_system" / "extracted-markdown" / "medical"
        extracted_dir.mkdir(parents=True, exist_ok=True)

        canonical_source_path = "/srv/cloud-vault/mirrors/icloud/project kay memory.pdf"
        canonical_source_hash = "abcdef1234567890"
        frontmatter = (
            "---\n"
            'type: "classified-document"\n'
            'primary_label: "medical"\n'
            f'canonical_source_path: "{canonical_source_path}"\n'
            f'canonical_source_hash: "{canonical_source_hash}"\n'
            'last_seen_filename: "project kay memory.pdf"\n'
            'attachment_mode: "none"\n'
            'compatibility_attachment_path: ""\n'
            'source_link: ""\n'
            'extracted_markdown: "[[_system/extracted-markdown/medical/project kay memory.extracted.md]]"\n'
            "---\n\n# project kay memory.pdf\n"
        )
        duplicate_frontmatter = frontmatter.replace(
            "project kay memory.extracted.md",
            "project kay memory.extracted (2).md",
        )
        (note_dir / "project kay memory - medical.md").write_text(frontmatter, encoding="utf-8")
        (note_dir / "project kay memory - medical (2).md").write_text(duplicate_frontmatter, encoding="utf-8")
        (extracted_dir / "project kay memory.extracted.md").write_text("original", encoding="utf-8")
        (extracted_dir / "project kay memory.extracted (2).md").write_text("duplicate", encoding="utf-8")

        note_path = write_obsidian_note(
            vault=vault,
            source_path=source_path,
            file_hash=canonical_source_hash,
            markdown="Updated memory preview",
            classification={
                "primary_label": "medical",
                "secondary_labels": [],
                "confidence": 0.42,
                "summary": "Needs review summary.",
                "reason": "Low confidence medical memory document.",
                "sensitive_flags": [],
                "recommended_action": "review",
                "file_date_guess": "2026-05-27",
                "language": "English",
            },
            attach_originals=False,
            canonical_source_path=canonical_source_path,
            canonical_source_hash=canonical_source_hash,
            last_seen_filename="project kay memory.pdf",
        )

        matching_notes = sorted((vault / "02 Needs Review").glob("project kay memory - medical*.md"))
        matching_extracted = sorted(
            (vault / "_system" / "extracted-markdown" / "medical").glob("project kay memory.extracted*.md")
        )

        assert note_path.name == "project kay memory - medical.md"
        assert [path.name for path in matching_notes] == ["project kay memory - medical.md"]
        assert [path.name for path in matching_extracted] == ["project kay memory.extracted.md"]


def test_write_index_surfaces_discovery_topics_and_entities():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        vault = root / "vault"
        ensure_vault(vault)

        note_path = vault / "01 Classified" / "financial" / "Budget Draft - financial.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text("# Budget Draft\n", encoding="utf-8")

        write_index(
            vault,
            [note_path],
            [
                {
                    "entity_summary": "organizations: Aetna; identifiers: claim id: EDPDK70ZX00",
                    "retrieval_topics": ["medical", "insurance", "appeal"],
                }
            ],
        )

        index_text = (vault / "Classification Index.md").read_text(encoding="utf-8")

        assert "## Discovery topics" in index_text
        assert "`medical` (1)" in index_text
        assert "organizations: Aetna (1)" in index_text
        assert "[[01 Classified/financial/Budget Draft - financial.md]]" in index_text
