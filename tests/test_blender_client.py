"""
Tests for BlenderClient
=======================
Verifies client request building and error handling with mock HTTP bridge responses.
"""

from unittest.mock import patch, MagicMock
import json
import pytest

from blender_mcp.blender_client import BlenderClient


def test_client_status_disconnected():
    client = BlenderClient(bridge_url="http://127.0.0.1:9999")
    status = client.get_status()
    assert status["status"] == "disconnected"
    assert "error" in status


@patch("urllib.request.urlopen")
def test_client_status_connected(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"status": "connected", "active_document": "Scene.blend"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = BlenderClient()
    res = client.get_status()
    assert res["status"] == "connected"
    assert res["active_document"] == "Scene.blend"


@patch("urllib.request.urlopen")
def test_client_execute_python_success(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"success": True, "result": "Cube"}).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = BlenderClient()
    res = client.execute_python("print('hello')")
    assert res["success"] is True
    assert res["result"] == "Cube"


@patch("urllib.request.urlopen")
def test_client_inspect_scene(mock_urlopen):
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "objects": [{"name": "Cube", "type": "MESH"}],
        "total_objects": 1
    }).encode("utf-8")
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    client = BlenderClient()
    res = client.inspect_scene()
    assert res["total_objects"] == 1
    assert res["objects"][0]["name"] == "Cube"


@patch.object(BlenderClient, "inspect_scene")
def test_client_query_objects(mock_inspect):
    mock_inspect.return_value = {
        "objects": [
            {"name": "Camera", "type": "CAMERA"},
            {"name": "Light", "type": "LIGHT"},
            {"name": "Cube", "type": "MESH"}
        ]
    }
    client = BlenderClient()
    res = client.query_objects(object_type="MESH")
    assert len(res) == 1
    assert res[0]["name"] == "Cube"

    res_cam = client.query_objects(name_filter="cam")
    assert len(res_cam) == 1
    assert res_cam[0]["name"] == "Camera"
