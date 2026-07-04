import anyio

from icloud_plugin_mcp.server import mcp


async def _list_tools():
    return await mcp.list_tools()


def test_plugin_server_tools_expose_annotations_and_output_schemas():
    tools = anyio.run(_list_tools)
    tools_by_name = {tool.name: tool for tool in tools}

    expected_read_only = {
        "search_icloud_files",
        "get_icloud_file",
        "get_icloud_file_excerpt",
        "get_icloud_note",
        "get_icloud_source_reference",
        "get_icloud_file_bundle",
        "search_icloud_notes_and_files",
        "get_icloud_system_status",
        "get_icloud_product_readiness",
        "get_icloud_change_set",
        "get_icloud_dedupe_job_status",
        "list_icloud_dedupe_groups",
        "get_icloud_dedupe_group",
    }

    for tool_name in expected_read_only:
        tool = tools_by_name[tool_name]
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is False

    for tool_name in {"refresh_icloud_index", "pause_icloud_index", "resume_icloud_index"}:
        tool = tools_by_name[tool_name]
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is False

    for tool_name in {
        "create_document_vault_note",
        "queue_cloud_vault_task",
        "continue_cloud_vault_task",
        "continue_cloud_vault_task_queue",
        "cancel_cloud_vault_task",
        "queue_create_document_vault_note_from_file_id_chatgpt_first",
        "queue_create_document_vault_notes_from_search",
        "queue_classifier_fallback_note_from_file_id",
        "queue_create_document_vault_note_from_external_data",
        "queue_import_server_file_to_cloud_vault",
        "queue_import_server_folder_to_cloud_vault",
        "queue_refresh_cloud_vault_index",
        "queue_reindex_document_vault_notes",
        "queue_sync_manual_feedback_events",
        "queue_dedupe_analysis",
        "queue_apply_icloud_dedupe_group",
        "queue_restore_icloud_change_set",
        "classify_file_and_create_document_vault_note_fallback",
        "batch_classify_files_and_create_document_vault_notes_fallback",
        "search_files_and_create_document_vault_notes_fallback",
        "delete_icloud_file",
        "restore_icloud_change_set",
        "sync_icloud_manual_feedback_events",
        "analyze_icloud_duplicates",
        "start_icloud_dedupe_job",
        "continue_icloud_dedupe_job",
        "apply_icloud_dedupe_group",
    }:
        tool = tools_by_name[tool_name]
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is False
