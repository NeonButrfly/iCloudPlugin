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
    }

    for tool_name in expected_read_only:
        tool = tools_by_name[tool_name]
        assert tool.outputSchema is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.openWorldHint is False
        assert tool.annotations.destructiveHint is False

    refresh_tool = tools_by_name["refresh_icloud_index"]
    assert refresh_tool.outputSchema is not None
    assert refresh_tool.annotations is not None
    assert refresh_tool.annotations.readOnlyHint is False
    assert refresh_tool.annotations.openWorldHint is False
    assert refresh_tool.annotations.destructiveHint is False
