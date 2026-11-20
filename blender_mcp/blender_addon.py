bl_info = {
    "name": "Blender AI MCP Bridge",
    "author": "Ziad Amr / Antigravity AI",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N-Panel) > AI Bridge",
    "description": "Connects Blender to external AI clients and MCP servers for live bidirectional control.",
    "category": "Development",
}

import bpy
import threading
import queue
import io
import sys
import os
import json
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# Addon Properties
class AIBridgeProperties(bpy.types.PropertyGroup):
    host: bpy.props.StringProperty(
        name="Host",
        default="127.0.0.1",
        description="Bridge server listen address"
    )
    port: bpy.props.IntProperty(
        name="Port",
        default=9876,
        min=1024,
        max=65535,
        description="Bridge server listen port"
    )
    is_running: bpy.props.BoolProperty(
        name="Is Running",
        default=False
    )
    request_count: bpy.props.IntProperty(
        name="Requests Processed",
        default=0
    )


TASK_QUEUE = queue.Queue()
SERVER_INSTANCE = None
SERVER_THREAD = None


def process_queue_addon():
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

        try:
            bpy.context.scene.ai_bridge_props.request_count += 1
        except Exception:
            pass

    props = getattr(bpy.context.scene, "ai_bridge_props", None)
    if props and props.is_running:
        return 0.05
    return None


class AddonBridgeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/ping", "/status"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
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
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/execute":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(body)
                code = data.get("code", "")
                timeout = float(data.get("timeout", 60.0))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
                return

            event = threading.Event()
            result_container = {}
            TASK_QUEUE.put({"code": code, "result_container": result_container, "event": event})
            finished = event.wait(timeout=timeout)

            if not finished:
                self.send_response(504)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Timeout after {timeout}s"}).encode("utf-8"))
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(result_container).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


class WM_OT_StartAIBridge(bpy.types.Operator):
    bl_idname = "wm.start_ai_bridge"
    bl_label = "Start AI Bridge"
    bl_description = "Starts the HTTP live bridge server for AI / MCP connectivity"

    def execute(self, context):
        global SERVER_INSTANCE, SERVER_THREAD
        props = context.scene.ai_bridge_props
        if props.is_running:
            self.report({'INFO'}, "AI Bridge is already running.")
            return {'FINISHED'}

        try:
            SERVER_INSTANCE = HTTPServer((props.host, props.port), AddonBridgeHandler)
            SERVER_THREAD = threading.Thread(target=SERVER_INSTANCE.serve_forever, daemon=True)
            SERVER_THREAD.start()

            props.is_running = True
            if not bpy.app.timers.is_registered(process_queue_addon):
                bpy.app.timers.register(process_queue_addon, persistent=True)

            self.report({'INFO'}, f"AI Bridge started on http://{props.host}:{props.port}")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to start server: {e}")
        return {'FINISHED'}


class WM_OT_StopAIBridge(bpy.types.Operator):
    bl_idname = "wm.stop_ai_bridge"
    bl_label = "Stop AI Bridge"
    bl_description = "Stops the AI live bridge server"

    def execute(self, context):
        global SERVER_INSTANCE
        props = context.scene.ai_bridge_props
        if not props.is_running:
            self.report({'INFO'}, "AI Bridge is not running.")
            return {'FINISHED'}

        if SERVER_INSTANCE:
            try:
                SERVER_INSTANCE.shutdown()
                SERVER_INSTANCE.server_close()
            except Exception as e:
                print(f"[Bridge] Error closing server: {e}")
            SERVER_INSTANCE = None

        props.is_running = False
        self.report({'INFO'}, "AI Bridge stopped.")
        return {'FINISHED'}


class VIEW3D_PT_AIBridgePanel(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'AI Bridge'
    bl_label = 'AI MCP Bridge'

    def draw(self, context):
        layout = self.layout
        props = context.scene.ai_bridge_props

        box = layout.box()
        if props.is_running:
            box.label(text=f"Status: RUNNING", icon='CHECKMARK')
            box.label(text=f"Endpoint: http://{props.host}:{props.port}")
            box.label(text=f"Requests: {props.request_count}")
            layout.operator("wm.stop_ai_bridge", text="Stop Bridge Server", icon='CANCEL')
        else:
            box.label(text="Status: STOPPED", icon='X')
            box.prop(props, "host")
            box.prop(props, "port")
            layout.operator("wm.start_ai_bridge", text="Start Bridge Server", icon='PLAY')


classes = (
    AIBridgeProperties,
    WM_OT_StartAIBridge,
    WM_OT_StopAIBridge,
    VIEW3D_PT_AIBridgePanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ai_bridge_props = bpy.props.PointerProperty(type=AIBridgeProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ai_bridge_props

if __name__ == "__main__":
    register()
