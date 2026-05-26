from __future__ import annotations

import json

from apps.classifier import category_manager, hybrid_runtime
from apps.classifier.external_taxonomy import (
    build_external_taxonomy_hint_text,
    match_external_taxonomy_candidates,
    refresh_external_taxonomy_aliases,
)


def test_refresh_external_taxonomy_aliases_maps_public_sources(tmp_path):
    sources_path = tmp_path / "taxonomy-sources.json"
    aliases_path = tmp_path / "external-taxonomy-aliases.json"
    sources_path.write_text(
        json.dumps(
            [
                {
                    "name": "openimages_boxable",
                    "enabled": True,
                    "kind": "vision",
                    "parser": "csv_last_column",
                    "url": "https://example.test/openimages.csv",
                },
                {
                    "name": "google_product_taxonomy",
                    "enabled": True,
                    "kind": "product",
                    "parser": "google_product_taxonomy",
                    "url": "https://example.test/google.txt",
                },
                {
                    "name": "iab_content_taxonomy_v3_1",
                    "enabled": True,
                    "kind": "content",
                    "parser": "iab_tsv",
                    "url": "https://example.test/iab.tsv",
                },
                {
                    "name": "rvl_cdip_static",
                    "enabled": True,
                    "kind": "document",
                    "parser": "static",
                    "labels": ["invoice", "scientific report", "form", "presentation", "budget"],
                },
            ]
        ),
        encoding="utf-8",
    )

    fake_payloads = {
        "https://example.test/openimages.csv": "/m/012n7d,Ambulance\n/m/012ysf,Syringe\n/m/014trl,Cosmetics\n",
        "https://example.test/google.txt": "\n".join(
            [
                "# version",
                "Health & Beauty > Personal Care > Cosmetics",
                "Office Supplies > Filing & Organization > Forms",
                "Business & Industrial > Medical > Medical Forms",
            ]
        ),
        "https://example.test/iab.tsv": "\n".join(
            [
                "Unique ID\tParent\tName\tTier 1\tTier 2",
                "1\t\tLaw\tLaw\t",
                "2\t\tMedical Health\tMedical Health\t",
                "3\t\tEducation\tEducation\t",
            ]
        ),
    }

    report = refresh_external_taxonomy_aliases(
        sources_path=sources_path,
        aliases_path=aliases_path,
        fetch_text=fake_payloads.__getitem__,
    )

    payload = json.loads(aliases_path.read_text(encoding="utf-8"))
    aliases = payload["label_aliases"]

    assert report["ok"] is True
    assert report["source_count"] == 4
    assert "medical" in aliases
    assert "legal" in aliases
    assert "invoice" in aliases
    assert any(alias == "scientific report" for alias in aliases["report"])
    assert any(alias == "presentation" for alias in aliases["presentation"])
    assert any(alias == "budget" for alias in aliases["financial"])
    assert any(alias == "ambulance" for alias in aliases["medical"])
    assert any(alias == "medical forms" for alias in aliases["form"])


def test_match_external_taxonomy_candidates_scores_local_labels():
    aliases = {
        "invoice": ["invoice", "billing statement"],
        "legal": ["law", "laws and regulations"],
        "medical": ["medical health", "syringe"],
    }

    matches = match_external_taxonomy_candidates(
        "Billing statement with total due and related laws and regulations.",
        aliases=aliases,
        limit=3,
    )

    assert any(match["label"] == "invoice" and "billing statement" in match["evidence"] for match in matches)
    assert any(match["label"] == "legal" for match in matches)


def test_build_external_taxonomy_hint_text_summarizes_matches():
    hint_text = build_external_taxonomy_hint_text(
        "A medical health invoice with a syringe charge and balance due.",
        aliases={
            "medical": ["medical health", "syringe"],
            "invoice": ["invoice"],
        },
        limit=4,
    )

    assert "medical" in hint_text
    assert "invoice" in hint_text
    assert "syringe" in hint_text


def test_select_candidate_categories_uses_external_taxonomy_matches(monkeypatch):
    monkeypatch.setattr(
        category_manager,
        "match_external_taxonomy_candidates",
        lambda text, limit=10: [
            {"label": "invoice", "score": 6, "evidence": ["billing statement"]},
            {"label": "legal", "score": 4, "evidence": ["laws and regulations"]},
        ],
    )

    labels = category_manager.select_candidate_categories(
        ["invoice", "legal", "unknown", "needs-review"],
        "notice.txt",
        "txt",
        "billing statement and laws and regulations",
    )

    assert "invoice" in labels[:2]
    assert "legal" in labels[:3]


def test_build_feature_text_includes_external_taxonomy_hints(monkeypatch):
    monkeypatch.setattr(
        hybrid_runtime,
        "build_external_taxonomy_hint_text",
        lambda text, aliases=None, limit=6: "medical syringe invoice",
    )

    feature_text = hybrid_runtime.build_feature_text(
        {
            "filename": "claim.pdf",
            "extension": "pdf",
            "parser": "pdf",
            "heuristic_primary": "medical",
            "taxonomy_candidates": ["medical", "invoice"],
            "text_preview": "patient invoice claim total due",
        }
    )

    assert "external-taxonomy medical syringe invoice" in feature_text
