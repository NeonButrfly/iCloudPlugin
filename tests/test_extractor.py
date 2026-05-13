from icloud_index_service.services.extractor import summarize_text


def test_summarize_text_truncates_to_requested_length():
    source = "alpha beta gamma delta epsilon"

    assert summarize_text(source, 12) == "alpha beta g"
