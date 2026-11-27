"""
Blender Live Agent Bridge Server
================================
Run this script inside Blender's Text Editor (or install the companion add-on)
to allow external AI agents and MCP servers to inspect and edit your active Blender scene.

Features:
- Strict thread-safe command execution: ZERO bpy/bmesh access on HTTP threads.
  All bpy, bmesh, context, and data operations dispatch to Blender's main thread.
- Captures executed_on_thread and executed_on_thread_id in responses.
- Security controls:
  * BLENDER_ALLOW_PYTHON_EXEC: disable arbitrary execution (returns 403 Forbidden).
  * Mandatory BLENDER_BRIDGE_AUTH_TOKEN when binding to non-loopback network interfaces.
  * Bearer and X-Bridge-Token authentication validation (never logged).
- Captures stdout, stderr, exception tracebacks, and return values.
- JSON REST API for status, scene inspection, arbitrary Python execution, and viewport rendering.
"""

import sys
import io
import os
import json
import queue
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional
try:
    import bpy
    import bmesh
except ImportError:
    bpy = None
    bmesh = None

DEFAULT_PORT = 9876
DEFAULT_HOST = "127.0.0.1"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", DEFAULT_PORT))
HOST = os.environ.get("BLENDER_BRIDGE_HOST", DEFAULT_HOST)
ALLOW_PYTHON_EXEC = os.environ.get("BLENDER_ALLOW_PYTHON_EXEC", "true").strip().lower() in ("true", "1", "yes")
AUTH_TOKEN = os.environ.get("BLENDER_BRIDGE_AUTH_TOKEN", "").strip() or None


def check_host_binding_security(host: str, token: Optional[str]) -> None:
    """Verify that binding to an external/non-loopback network interface requires authentication."""
    is_loopback = host in LOOPBACK_HOSTS
    if not is_loopback and not token:
        raise RuntimeError(
            f"Refusing to bind Blender Bridge to non-loopback interface '{host}' "
            "without BLENDER_BRIDGE_AUTH_TOKEN set. Configure a secure token to proceed."
        )


check_host_binding_security(HOST, AUTH_TOKEN)

# Manage singleton server instance to avoid address-in-use errors upon reload
if "BRIDGE_SERVER" in globals() and globals()["BRIDGE_SERVER"]:
    try:
        globals()["BRIDGE_SERVER"].shutdown()
        globals()["BRIDGE_SERVER"].server_close()
        print("[Blender Bridge] Closed existing server instance.")
    except Exception as e:
        print(f"[Blender Bridge] Warning closing previous instance: {e}")

TASK_QUEUE = queue.Queue()
SERVER_RUNNING = True


def process_queue():
    """
    Runs strictly on Blender's main thread via bpy.app.timers or main loop.
    Executes queued tasks and records main-thread identity proof.
    """
    while not TASK_QUEUE.empty():
        try:
            task = TASK_QUEUE.get_nowait()
        except queue.Empty:
            break

        func = task.get("func")
        code = task.get("code")
        result_container = task.get("result_container", {})
        done_event = task.get("event")

        current_thread = threading.current_thread()
        result_container["executed_on_thread"] = current_thread.name
        result_container["executed_on_thread_id"] = current_thread.ident

        if callable(func):
            try:
                res = func()
                result_container["result"] = res
                result_container["success"] = True
            except Exception:
                result_container["error"] = traceback.format_exc()
                result_container["success"] = False
            finally:
                if done_event:
                    done_event.set()
            continue

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr

        exec_globals = {
            "bpy": bpy,
            "bmesh": bmesh,
            "context": bpy.context,
            "data": bpy.data,
            "ops": bpy.ops,
            "result": None,
        }

        success = False
        error_msg = None
        result_val = None

        try:
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            exec(code, exec_globals)
            result_val = exec_globals.get("result")
            success = True
        except Exception:
            error_msg = traceback.format_exc()
            success = False
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        result_container["success"] = success
        result_container["stdout"] = stdout_buf.getvalue()
        result_container["stderr"] = stderr_buf.getvalue()
        result_container["error"] = error_msg
        result_container["result"] = str(result_val) if result_val is not None else None
        if done_event:
            done_event.set()

    return 0.05 if SERVER_RUNNING else None


class BridgeHandler(BaseHTTPRequestHandler):
    """
    HTTP handler running on worker threads.
    CRITICAL: ZERO bpy/bmesh operations are executed here.
    All scene operations are dispatched to TASK_QUEUE for MainThread execution.
    """

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Bridge-Token")

    def _is_authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        auth_hdr = self.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            token = auth_hdr[7:].strip()
            if token == AUTH_TOKEN:
                return True
        x_token = self.headers.get("X-Bridge-Token", "").strip()
        if x_token == AUTH_TOKEN:
            return True
        return False

    def _send_unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Unauthorized: Invalid or missing bridge token"}).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if not self._is_authorized():
            self._send_unauthorized()
            return

        if self.path in ("/", "/ping", "/status"):
            event = threading.Event()
            result_container = {}

            def get_status_data():
                view_layer = getattr(bpy.context, "view_layer", None)
                active_obj = None
                if view_layer and hasattr(view_layer, "objects") and getattr(view_layer.objects, "active", None):
                    active_obj = view_layer.objects.active.name
                elif getattr(bpy.context, "active_object", None):
                    active_obj = bpy.context.active_object.name

                selected_objs = []
                if hasattr(bpy.context, "selected_objects"):
                    selected_objs = [o.name for o in bpy.context.selected_objects]
                mode = getattr(bpy.context, "mode", "OBJECT")

                return {
                    "status": "connected",
                    "blender_version": bpy.app.version_string,
                    "filepath": bpy.data.filepath or "Untitled.blend",
                    "mode": mode,
                    "active_object": active_obj,
                    "selected_objects": selected_objs,
                    "total_objects": len(bpy.data.objects),
                    "total_materials": len(bpy.data.materials),
                    "total_meshes": len(bpy.data.meshes),
                }

            TASK_QUEUE.put({
                "func": get_status_data,
                "result_container": result_container,
                "event": event,
            })
            finished = event.wait(timeout=10.0)
            if not finished or not result_container.get("success"):
                self.send_response(504 if not finished else 500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                err = result_container.get("error") or "Status request timed out on Blender main thread"
                self.wfile.write(json.dumps({"error": err, "status": "disconnected"}).encode("utf-8"))
                return

            payload = result_container.get("result", {})
            payload["executed_on_thread"] = result_container.get("executed_on_thread")
            payload["executed_on_thread_id"] = result_container.get("executed_on_thread_id")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif self.path == "/inspect":
            event = threading.Event()
            result_container = {}

            def get_inspect_data():
                objs = []
                for o in bpy.data.objects:
                    objs.append({
                        "name": o.name,
                        "type": o.type,
                        "location": [round(v, 4) for v in o.location],
                        "scale": [round(v, 4) for v in o.scale],
                        "rotation_euler": [round(v, 4) for v in o.rotation_euler],
                        "visible": o.visible_get(),
                        "modifiers": [m.name + ' (' + m.type + ')' for m in o.modifiers],
                        "vertex_count": len(o.data.vertices) if o.type == 'MESH' and o.data else 0,
                        "polygon_count": len(o.data.polygons) if o.type == 'MESH' and o.data else 0,
                        "materials": [m.name for m in o.data.materials if m] if o.type == 'MESH' and o.data else []
                    })
                active_name = None
                if getattr(bpy.context, "active_object", None):
                    active_name = bpy.context.active_object.name
                elif getattr(bpy.context, "view_layer", None) and getattr(bpy.context.view_layer.objects, "active", None):
                    active_name = bpy.context.view_layer.objects.active.name

                selected_names = [o.name for o in getattr(bpy.context, "selected_objects", [])]

                return {
                    "active_object": active_name,
                    "selected_objects": selected_names,
                    "objects": objs,
                    "total_objects": len(objs),
                    "blender_version": bpy.app.version_string,
                    "filepath": bpy.data.filepath or "Untitled.blend",
                    "mode": getattr(bpy.context, "mode", "UNKNOWN")
                }

            TASK_QUEUE.put({
                "func": get_inspect_data,
                "result_container": result_container,
                "event": event,
            })
            finished = event.wait(timeout=15.0)
            if not finished or not result_container.get("success"):
                self.send_response(504 if not finished else 500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                err = result_container.get("error") or "Scene inspection timed out on Blender main thread"
                self.wfile.write(json.dumps({"error": err}).encode("utf-8"))
                return

            payload = result_container.get("result", {})
            payload["executed_on_thread"] = result_container.get("executed_on_thread")
            payload["executed_on_thread_id"] = result_container.get("executed_on_thread_id")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def do_POST(self):
        if not self._is_authorized():
            self._send_unauthorized()
            return

        if self.path == "/execute":
            if not ALLOW_PYTHON_EXEC:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "Arbitrary Python execution is disabled by BLENDER_ALLOW_PYTHON_EXEC configuration"
                }).encode("utf-8"))
                return

            content_length = int(self.headers.get("Content-Length", 0))
            post_data = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(post_data)
                code = data.get("code", "")
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Invalid JSON payload: {e}"}).encode("utf-8"))
                return

            event = threading.Event()
            result_container = {}
            TASK_QUEUE.put({
                "code": code,
                "result_container": result_container,
                "event": event,
            })

            timeout = float(data.get("timeout", 60.0))
            finished = event.wait(timeout=timeout)
            if not finished:
                self.send_response(504)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Execution timed out on Blender main thread after {timeout}s"}).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(result_container).encode("utf-8"))

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def log_message(self, format, *args):
        # Silence routine HTTP request logs to keep Blender terminal clean
        pass


def start_server():
    server = HTTPServer((HOST, PORT), BridgeHandler)
    globals()["BRIDGE_SERVER"] = server
    print(f"[Blender Bridge] Listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except Exception:
        pass


def stop_server():
    global SERVER_RUNNING
    SERVER_RUNNING = False
    if "BRIDGE_SERVER" in globals() and globals()["BRIDGE_SERVER"]:
        try:
            globals()["BRIDGE_SERVER"].shutdown()
            globals()["BRIDGE_SERVER"].server_close()
            print("[Blender Bridge] Server stopped.")
        except Exception as e:
            print(f"[Blender Bridge] Error stopping server: {e}")


if bpy is not None:
    # Start server in daemon thread
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Register timer in Blender main thread
    if hasattr(bpy, "app") and hasattr(bpy.app, "timers"):
        if not bpy.app.timers.is_registered(process_queue):
            bpy.app.timers.register(process_queue, persistent=True)

    print("=" * 65)
    print(f" [Blender AI Bridge] READY! Connected to Blender {bpy.app.version_string}")
    print(f" [Blender AI Bridge] Listening on http://{HOST}:{PORT}")
    print("=" * 65)
