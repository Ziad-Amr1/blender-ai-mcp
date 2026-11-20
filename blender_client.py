"""
Blender Client Library
======================
Python client interface to communicate with a running Blender Live Bridge.
"""

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Union

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9876"


class BlenderClient:
    def __init__(self, bridge_url: str = DEFAULT_BRIDGE_URL, timeout: float = 35.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.timeout = timeout

    def get_status(self) -> Dict[str, Any]:
        """Check if the bridge server is responding and retrieve document status."""
        try:
            req = urllib.request.Request(f"{self.bridge_url}/status", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            return {
                "status": "disconnected",
                "error": f"Failed to connect to Blender bridge at {self.bridge_url}: {e.reason}"
            }
        except Exception as e:
            return {"status": "disconnected", "error": str(e)}

    def execute_python(self, code: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Execute Python code in Blender's main thread and return execution output."""
        try:
            to = timeout or self.timeout
            payload = json.dumps({"code": code, "timeout": to}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.bridge_url}/execute",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=to + 5.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", "ignore")
            try:
                return json.loads(err_body)
            except Exception:
                return {"success": False, "error": f"HTTP {e.code}: {err_body}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def inspect_scene(self) -> Dict[str, Any]:
        """Retrieve full hierarchy of objects in the scene with transforms and types."""
        try:
            req = urllib.request.Request(f"{self.bridge_url}/inspect", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # Fallback to direct execute_python if endpoint not present
            code = """
import bpy
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
    })
result = {
    "active_object": bpy.context.active_object.name if bpy.context.active_object else None,
    "selected_objects": [o.name for o in bpy.context.selected_objects],
    "objects": objs,
    "total_objects": len(objs)
}
"""
            res = self.execute_python(code)
            if res.get("success") and res.get("result"):
                try:
                    return eval(res["result"])
                except Exception:
                    pass
            return {"error": str(e), "fallback_result": res}

    def query_objects(self, name_filter: str = "", object_type: str = "") -> List[Dict[str, Any]]:
        """Filter objects in the active scene by name substring and/or type."""
        scene = self.inspect_scene()
        if "objects" not in scene:
            return []
        objs = scene["objects"]
        if name_filter:
            objs = [o for o in objs if name_filter.lower() in o["name"].lower()]
        if object_type:
            objs = [o for o in objs if o["type"].upper() == object_type.upper()]
        return objs

    def select_objects(self, names: List[str], clear_existing: bool = True) -> Dict[str, Any]:
        """Select specific objects by name in Blender."""
        code = f"""
import bpy
if {clear_existing}:
    bpy.ops.object.select_all(action='DESELECT')
matched = []
for name in {json.dumps(names)}:
    obj = bpy.data.objects.get(name)
    if obj:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        matched.append(name)
result = {{"selected": matched, "count": len(matched)}}
"""
        return self.execute_python(code)

    def create_primitive(
        self,
        primitive_type: str,
        name: str = "",
        location: Optional[List[float]] = None,
        rotation: Optional[List[float]] = None,
        scale: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """Create a 3D primitive mesh (cube, sphere, cylinder, plane, cone, monkey, etc.)."""
        loc = location or [0.0, 0.0, 0.0]
        rot = rotation or [0.0, 0.0, 0.0]
        sc = scale or [1.0, 1.0, 1.0]

        prim_map = {
            "cube": "bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot, scale=sc)",
            "sphere": "bpy.ops.mesh.primitive_uv_sphere_add(location=loc, rotation=rot, scale=sc)",
            "cylinder": "bpy.ops.mesh.primitive_cylinder_add(location=loc, rotation=rot, scale=sc)",
            "plane": "bpy.ops.mesh.primitive_plane_add(location=loc, rotation=rot, scale=sc)",
            "cone": "bpy.ops.mesh.primitive_cone_add(location=loc, rotation=rot, scale=sc)",
            "torus": "bpy.ops.mesh.primitive_torus_add(location=loc, rotation=rot)",
            "monkey": "bpy.ops.mesh.primitive_monkey_add(location=loc, rotation=rot, scale=sc)",
        }
        add_call = prim_map.get(primitive_type.lower())
        if not add_call:
            return {"success": False, "error": f"Unsupported primitive type: '{primitive_type}'. Choices: {list(prim_map.keys())}"}

        code = f"""
import bpy
loc = {loc}
rot = {rot}
sc = {sc}
{add_call}
obj = bpy.context.active_object
if {json.dumps(name)} and obj:
    obj.name = {json.dumps(name)}
result = {{"name": obj.name, "type": obj.type, "location": list(obj.location)}}
"""
        return self.execute_python(code)

    def delete_objects(self, names: List[str]) -> Dict[str, Any]:
        """Delete objects by name from Blender."""
        code = f"""
import bpy
deleted = []
for name in {json.dumps(names)}:
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)
        deleted.append(name)
result = {{"deleted": deleted, "count": len(deleted)}}
"""
        return self.execute_python(code)

    def render_viewport(
        self,
        output_path: str,
        camera_name: str = "",
        resolution_x: int = 1920,
        resolution_y: int = 1080
    ) -> Dict[str, Any]:
        """Render active scene or specified camera view to a PNG image file."""
        code = f"""
import bpy, os
scene = bpy.context.scene
if {json.dumps(camera_name)}:
    cam = bpy.data.objects.get({json.dumps(camera_name)})
    if cam and cam.type == 'CAMERA':
        scene.camera = cam

scene.render.resolution_x = {resolution_x}
scene.render.resolution_y = {resolution_y}
out_p = os.path.abspath({json.dumps(output_path)})
scene.render.filepath = out_p
bpy.ops.render.render(write_still=True)
result = {{"rendered_file": out_p, "file_exists": os.path.exists(out_p)}}
"""
        return self.execute_python(code)
