"""
Tests for Blender MCP Tools and Annotations
===========================================
Verifies that all 14 MCP tools are registered with proper ToolAnnotations metadata.
"""

import asyncio
from unittest.mock import patch
import pytest

from blender_mcp.mcp_server import mcp, blender_get_connection_status


def test_all_14_blender_tools_registered_with_annotations():
    tools = asyncio.run(mcp.list_tools())
    assert len(tools) == 14

    tool_dict = {t.name: t for t in tools}
    expected_tools = [
        "blender_get_connection_status",
        "blender_inspect_scene",
        "blender_execute_python",
        "blender_query_objects",
        "blender_select_objects",
        "blender_create_primitive",
        "blender_transform_object",
        "blender_apply_modifier",
        "blender_setup_camera_light",
        "blender_create_material",
        "blender_delete_objects",
        "blender_render_viewport",
        "blender_import_model",
        "blender_export_model",
    ]

    for name in expected_tools:
        assert name in tool_dict, f"Missing tool: {name}"
        tool = tool_dict[name]
        assert tool.annotations is not None, f"Tool {name} missing ToolAnnotations"

    # Verify classification
    assert tool_dict["blender_get_connection_status"].annotations.readOnlyHint is True
    assert tool_dict["blender_inspect_scene"].annotations.readOnlyHint is True
    assert tool_dict["blender_query_objects"].annotations.readOnlyHint is True
    assert tool_dict["blender_execute_python"].annotations.destructiveHint is True
    assert tool_dict["blender_execute_python"].annotations.openWorldHint is True
    assert tool_dict["blender_delete_objects"].annotations.destructiveHint is True
    assert tool_dict["blender_render_viewport"].annotations.destructiveHint is True
    assert tool_dict["blender_export_model"].annotations.destructiveHint is True


def test_tool_get_connection_status_disconnected():
    res = asyncio.run(blender_get_connection_status())
    assert "status" in res
