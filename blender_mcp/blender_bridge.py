"""
Blender Live Agent Bridge Server
================================
Run this script inside Blender's Text Editor (or install the companion add-on)
to allow external AI agents and MCP servers to inspect and edit your active Blender scene.

Features:
- Thread-safe command execution via bpy.app.timers on Blender's main thread
- Safe execution context with access to bpy, bmesh, context, data, and ops
- Captures stdout, stderr, exception tracebacks, and return values
- JSON REST API for status, scene inspection, arbitrary Python execution, and viewport rendering
"""

import sys
import io
import os
import json
import queue
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
import bpy
import bmesh

DEFAULT_PORT = 9876
DEFAULT_HOST = "127.0.0.1"

PORT = int(os.environ.get("BLENDER_BRIDGE_PORT", DEFAULT_PORT))
HOST = os.environ.get("BLENDER_BRIDGE_HOST", DEFAULT_HOST)

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
    """Runs on Blender's main thread via bpy.app.timers to safely execute bpy/bmesh operations."""
    while not TASK_QUEUE.empty():
        try:
            task = TASK_QUEUE.get_nowait()
        except queue.Empty:
            break

        code = task.get("code", "")
        result_container = task.get("result_container")
        done_event = task.get("event")

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
        done_event.set()

    return 0.05 if SERVER_RUNNING else None


class BridgeHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path in ("/ping", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()

            active_obj = bpy.context.active_object.name if bpy.context.active_object else None
            payload = {
                "status": "connected",
                "blender_version": bpy.app.version_string,
                "filepath": bpy.data.filepath or "Untitled.blend",
                "mode": bpy.context.mode if hasattr(bpy.context, "mode") else "UNKNOWN",
                "active_object": active_obj,
                "selected_objects": [o.name for o in bpy.context.selected_objects],
                "total_objects": len(bpy.data.objects),
                "total_materials": len(bpy.data.materials),
                "total_meshes": len(bpy.data.meshes),
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        elif self.path == "/inspect":
            event = threading.Event()
            result_container = {}
            inspect_code = """
import json
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
result = {
    "active_object": bpy.context.active_object.name if bpy.context.active_object else None,
    "selected_objects": [o.name for o in bpy.context.selected_objects],
    "objects": objs,
    "total_objects": len(objs),
    "blender_version": bpy.app.version_string,
    "filepath": bpy.data.filepath or "Untitled.blend",
    "mode": bpy.context.mode if hasattr(bpy.context, "mode") else "UNKNOWN"
}
"""
            TASK_QUEUE.put({
                "code": inspect_code,
                "result_container": result_container,
                "event": event,
            })
            finished = event.wait(timeout=15.0)
            if not finished or not result_container.get("success"):
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._send_cors_headers()
                self.end_headers()
                err = result_container.get("error") or "Scene inspection timed out"
                self.wfile.write(json.dumps({"error": err}).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._send_cors_headers()
            self.end_headers()
            res_str = result_container.get("result", "{}")
            # Parse back if stringified dict
            try:
                parsed = eval(res_str) if isinstance(res_str, str) else res_str
                self.wfile.write(json.dumps(parsed).encode("utf-8"))
            except Exception:
                self.wfile.write(res_str.encode("utf-8"))

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()

    def do_POST(self):
        if self.path == "/execute":
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


# Start server in daemon thread
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# Register timer in Blender main thread
if not bpy.app.timers.is_registered(process_queue):
    bpy.app.timers.register(process_queue, persistent=True)

print("=" * 65)
print(f" [Blender AI Bridge] READY! Connected to Blender {bpy.app.version_string}")
print(f" [Blender AI Bridge] Listening on http://{HOST}:{PORT}")
print("=" * 65)
