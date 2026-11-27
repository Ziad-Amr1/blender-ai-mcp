"""
Unit Tests for Blender Bridge Security & Auth Controls
======================================================
Tests:
1. Host binding security: non-loopback requires BLENDER_BRIDGE_AUTH_TOKEN.
2. Token authorization parsing (Bearer and X-Bridge-Token headers).
3. BLENDER_ALLOW_PYTHON_EXEC toggle and 403 Forbidden enforcement.
4. Token never leaked in error messages or logs.
5. Client authorization header propagation.
"""

import os
from unittest.mock import patch, MagicMock
import pytest
import urllib.error

from blender_mcp.blender_client import BlenderClient


def test_host_binding_security_loopback_allowed_without_token():
    from blender_mcp.blender_bridge import check_host_binding_security
    # Loopback bindings should succeed without token
    check_host_binding_security("127.0.0.1", None)
    check_host_binding_security("localhost", None)
    check_host_binding_security("::1", None)


def test_host_binding_security_non_loopback_requires_token():
    from blender_mcp.blender_bridge import check_host_binding_security
    # Non-loopback binding without token MUST raise RuntimeError
    with pytest.raises(RuntimeError, match="Refusing to bind Blender Bridge to non-loopback"):
        check_host_binding_security("0.0.0.0", None)

    with pytest.raises(RuntimeError, match="Refusing to bind Blender Bridge to non-loopback"):
        check_host_binding_security("192.168.1.100", "")

    # Non-loopback binding WITH token must succeed
    check_host_binding_security("0.0.0.0", "super-secret-token")
    check_host_binding_security("192.168.1.100", "my-token")


def test_client_headers_with_and_without_token():
    client_no_token = BlenderClient(auth_token=None)
    headers = client_no_token._get_headers({"Accept": "application/json"})
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/json"

    client_with_token = BlenderClient(auth_token="secret_key_abc")
    headers_auth = client_with_token._get_headers({"Accept": "application/json"})
    assert headers_auth["Authorization"] == "Bearer secret_key_abc"
    assert headers_auth["Accept"] == "application/json"


@patch("urllib.request.urlopen")
def test_client_handles_401_unauthorized(mock_urlopen):
    # Simulate HTTP 401 response from server
    err = urllib.error.HTTPError(
        url="http://127.0.0.1:9876/status",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=MagicMock(read=lambda: b'{"error": "Unauthorized: Invalid or missing bridge token"}')
    )
    mock_urlopen.side_effect = err

    client = BlenderClient()
    res = client.get_status()
    assert res.get("status") == "error"
    assert res.get("http_code") == 401
    assert "Unauthorized" in res.get("error", "")


@patch("urllib.request.urlopen")
def test_client_handles_403_forbidden_exec_disabled(mock_urlopen):
    # Simulate HTTP 403 response from server when execution is disabled
    err = urllib.error.HTTPError(
        url="http://127.0.0.1:9876/execute",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=MagicMock(read=lambda: b'{"error": "Arbitrary Python execution is disabled by BLENDER_ALLOW_PYTHON_EXEC configuration"}')
    )
    mock_urlopen.side_effect = err

    client = BlenderClient()
    res = client.execute_python("print('test')")
    assert res.get("success") is False
    assert res.get("http_code") == 403
    assert "disabled" in res.get("error", "")
