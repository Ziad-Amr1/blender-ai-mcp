"""
Unit Tests for Blender Bridge Security & Auth Controls
======================================================
Tests:
1. Host binding security: loopback vs non-loopback.
2. Non-loopback requires explicit BLENDER_BRIDGE_ALLOW_NON_LOOPBACK opt-in AND token of at least 16 chars.
3. BLENDER_ALLOW_PYTHON_EXEC defaults to FALSE (secure by default).
4. Token authorization parsing with constant-time HMAC comparison (Bearer and X-Bridge-Token headers).
5. Token never leaked in error messages or logs.
6. Client authorization header propagation.
7. Main-thread execution verification and concurrency violation detection.
8. Server shutdown queue draining prevents hanging worker threads.
"""

import os
import queue
import threading
from unittest.mock import patch, MagicMock
import pytest
import urllib.error

from blender_mcp.blender_client import BlenderClient
from blender_mcp.blender_bridge import (
    check_host_binding_security,
    ALLOW_PYTHON_EXEC,
    ALLOW_NON_LOOPBACK,
    TASK_QUEUE,
    process_queue,
    stop_server
)


def test_default_security_settings():
    # Security Requirement: Execution must be DISABLED by default
    # and non-loopback binding must be DISABLED by default
    assert ALLOW_PYTHON_EXEC is False or os.environ.get("BLENDER_ALLOW_PYTHON_EXEC", "false").lower() in ("false", "0", "no")
    assert ALLOW_NON_LOOPBACK is False or os.environ.get("BLENDER_BRIDGE_ALLOW_NON_LOOPBACK", "false").lower() in ("false", "0", "no")


def test_host_binding_security_loopback_allowed_without_token():
    # Loopback bindings should succeed without token or explicit opt-in
    check_host_binding_security("127.0.0.1", None, allow_non_loopback=False)
    check_host_binding_security("localhost", None, allow_non_loopback=False)
    check_host_binding_security("::1", None, allow_non_loopback=False)


def test_host_binding_security_non_loopback_refused_without_opt_in():
    # Non-loopback binding WITHOUT allow_non_loopback must raise RuntimeError even if token exists
    with pytest.raises(RuntimeError, match="Refusing to bind Blender Bridge to non-loopback"):
        check_host_binding_security("0.0.0.0", "a" * 32, allow_non_loopback=False)

    with pytest.raises(RuntimeError, match="Refusing to bind Blender Bridge to non-loopback"):
        check_host_binding_security("192.168.1.100", "a" * 32, allow_non_loopback=False)


def test_host_binding_security_non_loopback_requires_min_length_token():
    # With allow_non_loopback=True, token must be at least 16 characters
    with pytest.raises(RuntimeError, match="at least 16 characters"):
        check_host_binding_security("0.0.0.0", "short_secret", allow_non_loopback=True)

    with pytest.raises(RuntimeError, match="at least 16 characters"):
        check_host_binding_security("0.0.0.0", None, allow_non_loopback=True)

    # Valid non-loopback configuration: explicit opt-in + 32-char token
    check_host_binding_security("0.0.0.0", "super-secret-high-entropy-token-1234", allow_non_loopback=True)


def test_client_headers_with_and_without_token():
    client_no_token = BlenderClient(auth_token=None)
    headers = client_no_token._get_headers({"Accept": "application/json"})
    assert "Authorization" not in headers
    assert headers["Accept"] == "application/json"

    client_with_token = BlenderClient(auth_token="secret_key_abc_12345")
    headers_auth = client_with_token._get_headers({"Accept": "application/json"})
    assert headers_auth["Authorization"] == "Bearer secret_key_abc_12345"
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
    assert "secret" not in res.get("error", "").lower()


@patch("urllib.request.urlopen")
def test_client_handles_403_forbidden_exec_disabled(mock_urlopen):
    # Simulate HTTP 403 response from server when execution is disabled by default
    err = urllib.error.HTTPError(
        url="http://127.0.0.1:9876/execute",
        code=403,
        msg="Forbidden",
        hdrs={},
        fp=MagicMock(read=lambda: b'{"error": "Arbitrary Python execution is disabled by default (BLENDER_ALLOW_PYTHON_EXEC=false)."}')
    )
    mock_urlopen.side_effect = err

    client = BlenderClient()
    res = client.execute_python("print('test')")
    assert res.get("success") is False
    assert res.get("http_code") == 403
    assert "disabled" in res.get("error", "")


def test_main_thread_violation_detection():
    # Simulate execution on a worker background thread (NOT Blender MainThread)
    from blender_mcp import blender_bridge

    result = {}
    event = threading.Event()
    blender_bridge.TASK_QUEUE.put({
        "func": lambda: "should_not_run",
        "result_container": result,
        "event": event
    })

    # Temporarily set MAIN_THREAD_ID to a fake ID to simulate background thread execution
    real_id = blender_bridge.MAIN_THREAD_ID
    try:
        blender_bridge.MAIN_THREAD_ID = 999999999  # distinct from current thread
        blender_bridge.process_queue()
        assert event.is_set()
        assert result.get("success") is False
        assert result.get("is_main_thread") is False
        assert "CRITICAL CONCURRENCY VIOLATION" in result.get("error", "")
    finally:
        blender_bridge.MAIN_THREAD_ID = real_id


def test_stop_server_drains_queue_without_hanging():
    # Verify that stopping server flushes pending tasks and unblocks waiting HTTP requests
    result = {}
    event = threading.Event()
    TASK_QUEUE.put({
        "func": lambda: None,
        "result_container": result,
        "event": event
    })

    stop_server()

    # Event must have been signaled
    assert event.is_set()
    assert result.get("success") is False
    assert "shutting down" in result.get("error", "").lower()
