"""
Live Integration Test for Blender AI MCP
========================================
Executes real end-to-end integration with headless Blender 5.3, the actual bridge script,
and real HTTP socket communication over localhost.

Tests:
1. Live socket connection and version handshake.
2. Scene hierarchy inspection on real bpy scene.
3. Creation of 3D primitive mesh (Cube).
4. Transformation of primitive (translation to [10, 12, 4]).
5. Export of geometry to STL format on disk.
6. Object deletion and orphan datablock purging.
7. Verification that scene object was removed.
"""

import os
import sys
import time
import shutil
import tempfile
import subprocess
import pytest
import requests

from blender_mcp.blender_client import BlenderClient

# Locate Blender executable
DEFAULT_BLENDER_PATH = r"C:\Program Files\Blender Foundation\Blender 5.3\blender.exe"
BLENDER_PATH = os.environ.get("BLENDER_EXE", shutil.which("blender") or DEFAULT_BLENDER_PATH)
BLENDER_AVAILABLE = os.path.isfile(BLENDER_PATH)

TEST_BRIDGE_PORT = 9899
TEST_BRIDGE_URL = f"http://127.0.0.1:{TEST_BRIDGE_PORT}"


@pytest.fixture(scope="module")
def live_blender_bridge():
    """Starts headless Blender with actual bridge script on an isolated test port."""
    if not BLENDER_AVAILABLE:
        pytest.skip(f"Blender executable not found at: {BLENDER_PATH}")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bridge_script = os.path.join(repo_root, "blender_mcp", "blender_bridge.py")

    driver_code = f"""
import sys, os, time
os.environ['BLENDER_BRIDGE_PORT'] = '{TEST_BRIDGE_PORT}'
os.environ['BLENDER_BRIDGE_HOST'] = '127.0.0.1'

with open(r'{bridge_script}', 'r', encoding='utf-8') as f:
    exec(f.read(), globals())

while globals().get('SERVER_RUNNING', True):
    process_queue()
    time.sleep(0.01)
"""
    driver_file = os.path.join(tempfile.gettempdir(), f"blender_test_driver_{TEST_BRIDGE_PORT}.py")
    with open(driver_file, "w", encoding="utf-8") as f:
        f.write(driver_code)

    proc = subprocess.Popen(
        [BLENDER_PATH, "-b", "--factory-startup", "--python", driver_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    client = BlenderClient(bridge_url=TEST_BRIDGE_URL)

    # Wait for server ready via /status
    ready = False
    for _ in range(20):
        time.sleep(0.3)
        st = client.get_status()
        if st.get("status") == "connected":
            ready = True
            break

    if not ready:
        proc.kill()
        out, err = proc.communicate()
        try:
            os.remove(driver_file)
        except OSError:
            pass
        pytest.fail(f"Failed to connect to live Blender bridge within 6s.\nSTDOUT:\n{out}\nSTDERR:\n{err}")

    yield client

    # Teardown
    try:
        client.execute_python("global SERVER_RUNNING; SERVER_RUNNING=False", timeout=2.0)
    except Exception:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=3.0)
    except subprocess.TimeoutExpired:
        proc.kill()

    try:
        if os.path.isfile(driver_file):
            os.remove(driver_file)
    except OSError:
        pass


@pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender executable not installed in environment")
def test_live_bridge_connection_status(live_blender_bridge):
    """Test 1: Live socket connection handshake and Blender version."""
    status = live_blender_bridge.get_status()
    assert status.get("status") == "connected"
    assert status.get("blender_version") == "5.3.0"
    assert "active_object" in status
    assert status.get("executed_on_thread") == "MainThread"
    assert isinstance(status.get("executed_on_thread_id"), int)


@pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender executable not installed in environment")
def test_live_scene_inspection(live_blender_bridge):
    """Test 2: Inspect live Blender scene hierarchy and verify main-thread execution."""
    scene = live_blender_bridge.inspect_scene()
    assert "objects" in scene
    assert "total_objects" in scene or "object_count" in scene or len(scene.get("objects", [])) >= 1
    assert isinstance(scene["objects"], list)
    assert scene.get("executed_on_thread") == "MainThread"
    assert isinstance(scene.get("executed_on_thread_id"), int)


@pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender executable not installed in environment")
def test_live_lifecycle_create_transform_export_delete(live_blender_bridge, tmp_path):
    """
    Test 3: Complete lifecycle on live Blender instance:
    Create primitive -> Transform -> Export STL -> Delete -> Verify removal.
    """
    client = live_blender_bridge
    obj_name = "LiveTestCube"

    # Verify execution runs strictly on MainThread
    res_thread = client.execute_python("import threading; result = threading.current_thread().name")
    assert res_thread.get("success") is True
    assert res_thread.get("executed_on_thread") == "MainThread"
    assert res_thread.get("result") == "MainThread"

    # 1. Create primitive
    res_create = client.create_primitive("cube", name=obj_name, location=(2.0, 3.0, 1.0), size=2.5)
    assert res_create.get("success") is True or "result" in res_create
    assert res_create.get("executed_on_thread") == "MainThread"

    # Verify object appears in scene
    found = client.query_objects(name_filter=obj_name)
    assert len(found) >= 1
    assert any(o["name"] == obj_name for o in found)

    # 2. Transform object
    res_trans = client.transform_object(obj_name, location=[10.0, 12.0, 4.0])
    assert res_trans.get("success") is True

    # 3. Export to STL
    export_path = str(tmp_path / "live_cube_export.stl")
    res_export = client.export_model(export_path, format_type="stl", selected_only=False)
    assert res_export.get("success") is True
    assert os.path.isfile(export_path), f"STL file was not created: {export_path}"
    file_size = os.path.getsize(export_path)
    assert file_size > 84, f"Exported STL is truncated or empty ({file_size} bytes)"

    # 4. Delete object and purge datablock
    res_del = client.delete_objects([obj_name])
    assert res_del.get("success") is True

    # 5. Verify object is completely gone from scene
    after_del = client.query_objects(name_filter=obj_name)
    assert len(after_del) == 0, f"Object {obj_name} was not deleted from scene"


@pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender executable not installed in environment")
def test_live_allow_python_exec_disabled(tmp_path):
    """
    Test 4: Verify BLENDER_ALLOW_PYTHON_EXEC=false blocks execution with HTTP 403 Forbidden
    while allowing read-only status inspection.
    """
    port = 9897
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bridge_script = os.path.join(repo_root, "blender_mcp", "blender_bridge.py")

    driver_code = f"""
import sys, os, time
os.environ['BLENDER_BRIDGE_PORT'] = '{port}'
os.environ['BLENDER_BRIDGE_HOST'] = '127.0.0.1'
os.environ['BLENDER_ALLOW_PYTHON_EXEC'] = 'false'

with open(r'{bridge_script}', 'r', encoding='utf-8') as f:
    exec(f.read(), globals())

while globals().get('SERVER_RUNNING', True):
    process_queue()
    time.sleep(0.01)
"""
    driver_file = os.path.join(tempfile.gettempdir(), f"blender_test_driver_{port}.py")
    with open(driver_file, "w", encoding="utf-8") as f:
        f.write(driver_code)

    proc = subprocess.Popen(
        [BLENDER_PATH, "-b", "--factory-startup", "--python", driver_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    client = BlenderClient(bridge_url=f"http://127.0.0.1:{port}")

    try:
        # Wait for bridge ready
        ready = False
        for _ in range(20):
            time.sleep(0.3)
            st = client.get_status()
            if st.get("status") == "connected":
                ready = True
                break
        assert ready, "Bridge failed to start in exec-disabled mode"

        # Verify status still works
        st = client.get_status()
        assert st.get("status") == "connected"
        assert st.get("executed_on_thread") == "MainThread"

        # Verify execute_python is blocked with 403 Forbidden
        res = client.execute_python("print('should be blocked')")
        assert res.get("success") is False
        assert res.get("http_code") == 403
        assert "disabled" in res.get("error", "").lower()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.remove(driver_file)
        except OSError:
            pass


@pytest.mark.skipif(not BLENDER_AVAILABLE, reason="Blender executable not installed in environment")
def test_live_bridge_auth_token_enforcement(tmp_path):
    """
    Test 5: Verify BLENDER_BRIDGE_AUTH_TOKEN rejects unauthorized requests (401)
    and accepts authorized requests (200).
    """
    port = 9896
    token = "secret_integration_token_xyz"
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bridge_script = os.path.join(repo_root, "blender_mcp", "blender_bridge.py")

    driver_code = f"""
import sys, os, time
os.environ['BLENDER_BRIDGE_PORT'] = '{port}'
os.environ['BLENDER_BRIDGE_HOST'] = '127.0.0.1'
os.environ['BLENDER_BRIDGE_AUTH_TOKEN'] = '{token}'

with open(r'{bridge_script}', 'r', encoding='utf-8') as f:
    exec(f.read(), globals())

while globals().get('SERVER_RUNNING', True):
    process_queue()
    time.sleep(0.01)
"""
    driver_file = os.path.join(tempfile.gettempdir(), f"blender_test_driver_{port}.py")
    with open(driver_file, "w", encoding="utf-8") as f:
        f.write(driver_code)

    proc = subprocess.Popen(
        [BLENDER_PATH, "-b", "--factory-startup", "--python", driver_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    client_unauth = BlenderClient(bridge_url=f"http://127.0.0.1:{port}", auth_token=None)
    client_wrong = BlenderClient(bridge_url=f"http://127.0.0.1:{port}", auth_token="wrong_token")
    client_auth = BlenderClient(bridge_url=f"http://127.0.0.1:{port}", auth_token=token)

    try:
        # Wait for bridge ready via authorized client
        ready = False
        for _ in range(20):
            time.sleep(0.3)
            st = client_auth.get_status()
            if st.get("status") == "connected":
                ready = True
                break
        assert ready, "Bridge failed to start with auth token"

        # 1. Unauthenticated request -> 401
        res_unauth = client_unauth.get_status()
        assert res_unauth.get("status") == "error"
        assert res_unauth.get("http_code") == 401

        # 2. Wrong token request -> 401
        res_wrong = client_wrong.get_status()
        assert res_wrong.get("status") == "error"
        assert res_wrong.get("http_code") == 401

        # 3. Authorized request -> 200
        res_ok = client_auth.get_status()
        assert res_ok.get("status") == "connected"
        assert res_ok.get("executed_on_thread") == "MainThread"

        # 4. Authorized execute -> 200
        res_exec = client_auth.execute_python("result = 42 * 2")
        assert res_exec.get("success") is True
        assert res_exec.get("result") == "84"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            os.remove(driver_file)
        except OSError:
            pass
