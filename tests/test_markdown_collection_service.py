from icloud_index_service.services.markdown_collection_service import (
    build_collection_header,
)


def test_build_collection_header_uses_collection_title():
    header = build_collection_header("Project Atlas")

    assert header == "# Project Atlas\n"
