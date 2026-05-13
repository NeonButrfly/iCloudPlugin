from icloud_index_service.services.categorization_service import build_category_prompt


def test_build_category_prompt_mentions_path_and_excerpt():
    prompt = build_category_prompt(
        path="/Finance/Budget.md",
        excerpt="Quarterly spend",
    )

    assert "/Finance/Budget.md" in prompt
    assert "Quarterly spend" in prompt
