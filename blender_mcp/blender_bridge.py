"""
Blender Live Agent Bridge Server
================================
Run this script inside Blender's Text Editor (or install the companion add-on)
to allow external AI agents and MCP servers to inspect and edit your active Blender scene.

Features:
- Strict thread-safe command execution: ZERO bpy/bmesh access on HTTP threads.
  All bpy, bmesh, context, and data operations dispatch to Blender's main thread.
- Proof of main-thread execution: captures Blender's initialization thread identity
  and verifies every queued operation executes on the main thread (is_main_thread = True).
- Security controls:
  * BLENDER_ALLOW_PYTHON_EXEC: defaults to FALSE. Explicit opt-in required to enable execution.
  * Blocks execution requests before parsing, queueing, or evaluation with HTTP 403.
  * Constant-time token comparison (hmac.compare_digest) to prevent timing attacks.
  * Refuses unsafe non-loopback network exposure without explicit BLENDER_BRIDGE_ALLOW_NON_LOOPBACK
    opt-in and an authentication token of at least 16 characters.
  * Remote access warning: setting an auth token over plain HTTP does not protect against network
    sniffing, tampering, or token replay; remote connections require an encrypted transport
    such as a TLS reverse proxy (Nginx, Caddy), SSH tunnel, or VPN.
- Captures stdout, stderr, exception tracebacks, and return values.
- Clean queue draining and event signaling on shutdown to prevent worker thread hangs.
- JSON REST API for status, scene inspection, arbitrary Python execution, and viewport rendering.
"""

import sys
import io
import os
import json
import queue
import threading
import traceback
import hmac
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

try:
    import bpy
    import bmesh
except ImportError:
    bpy = None
    bmesh = None

# Capture initialization thread identity (the Blender main thread when running inside Blender)
MAIN_THREAD_ID = threading.get_ident()
MAIN_THREAD_NAME = threading.current_thread().name

DEFAULT_PORT = 9876
DEFAULT_HOST = "127.0.0.1"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", DEFAULT_PORT))
HOST = os.environ.get("BLENDER_BRIDGE_HOST", DEFAULT_HOST)
# Security default: arbitrary Python execution is DISABLED by default (requires explicit opt-in)
ALLOW_PYTHON_EXEC = os.environ.get("BLENDER_ALLOW_PYTHON_EXEC", "false").strip().lower() in ("true", "1", "yes")
ALLOW_NON_LOOPBACK = os.environ.get("BLENDER_BRIDGE_ALLOW_NON_LOOPBACK", "false").strip().lower() in ("true", "1", "yes")
AUTH_TOKEN = os.environ.get("BLENDER_BRIDGE_AUTH_TOKEN", "").strip() or None


def check_host_binding_security(host: str, token: Optional[str], allow_non_loopback: bool) -> None:
    """
    Verify that binding to an external/non-loopback network interface requires explicit
    administrative opt-in and a secure authentication token.
    Plain HTTP over untrusted networks is insecure; production exposure must use a TLS reverse
    proxy (Nginx/Caddy) or SSH/VPN tunnel.
    """
    is_loopback = host in LOOPBACK_HOSTS
    if not is_loopback:
        if not allow_non_loopback:
            raise RuntimeError(
                f"Refusing to bind Blender Bridge to non-loopback interface '{host}'. "
                "Plain HTTP on non-loopback interfaces exposes arbitrary scene control and is prohibited "
                "without explicit opt-in. Set BLENDER_BRIDGE_ALLOW_NON_LOOPBACK=true and "
                "BLENDER_BRIDGE_AUTH_TOKEN=<secret>, and deploy behind a TLS reverse proxy (e.g. Nginx, Caddy) "
                "or secure SSH/VPN tunnel."
            )
        if not token or len(token) < 16:
            raise RuntimeError(
                f"Refusing to bind Blender Bridge to non-loopback interface '{host}' "
                "with an insecure or missing token. BLENDER_BRIDGE_AUTH_TOKEN must be at least "
                "16 characters when non-loopback binding is enabled."
            )


check_host_binding_security(HOST, AUTH_TOKEN, ALLOW_NON_LOOPBACK)

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
    Executes queued tasks and verifies main-thread identity proof against initialization thread.
    """
    current_thread = threading.current_thread()
    current_id = current_thread.ident
    current_name = current_thread.name
    is_main = (current_id == MAIN_THREAD_ID)

    while not TASK_QUEUE.empty():
        try:
            task = TASK_QUEUE.get_nowait()
        except queue.Empty:
            break

        func = task.get("func")
        code = task.get("code")
        result_container = task.get("result_container", {})
        done_event = task.get("event")

        result_container["main_thread_id"] = MAIN_THREAD_ID
        result_container["main_thread_name"] = MAIN_THREAD_NAME
        result_container["executed_on_thread"] = current_name
        result_container["executed_on_thread_id"] = current_id
        result_container["is_main_thread"] = is_main

        if not is_main:
            result_container["success"] = False
            result_container["error"] = (
                f"CRITICAL CONCURRENCY VIOLATION: Task executed on thread '{current_name}' (ID {current_id}) "
                f"instead of captured Blender main thread '{MAIN_THREAD_NAME}' (ID {MAIN_THREAD_ID})."
            )
            if done_event:
                done_event.set()
            continue

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
            "context": getattr(bpy, "context", None),
            "data": getattr(bpy, "data", None),
            "ops": getattr(bpy, "ops", None),
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
            if hmac.compare_digest(token, AUTH_TOKEN):
                return True
        x_token = self.headers.get("X-Bridge-Token", "").strip()
        if x_token and hmac.compare_digest(x_token, AUTH_TOKEN):
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
            payload["main_thread_id"] = result_container.get("main_thread_id")
            payload["is_main_thread"] = result_container.get("is_main_thread")

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
            payload["main_thread_id"] = result_container.get("main_thread_id")
            payload["is_main_thread"] = result_container.get("is_main_thread")

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
            # Security: verify execution is enabled BEFORE reading payload or queueing
            if not ALLOW_PYTHON_EXEC:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": (
                        "Arbitrary Python execution is disabled by default (BLENDER_ALLOW_PYTHON_EXEC=false). "
                        "Explicit opt-in (BLENDER_ALLOW_PYTHON_EXEC=true) is required to run automation scripts."
                    )
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
        # Silence routine HTTP request logs to keep terminal clean and avoid leaking headers/tokens
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

    # Drain any remaining tasks in TASK_QUEUE and signal their events to avoid blocking HTTP workers
    while not TASK_QUEUE.empty():
        try:
            task = TASK_QUEUE.get_nowait()
            result_container = task.get("result_container", {})
            result_container["success"] = False
            result_container["error"] = "Blender Bridge server is shutting down"
            done_event = task.get("event")
            if done_event:
                done_event.set()
        except queue.Empty:
            break

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
    print(f" [Blender AI Bridge] MainThread ID: {MAIN_THREAD_ID} | Exec Allowed: {ALLOW_PYTHON_EXEC}")
    print("=" * 65)
