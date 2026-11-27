"""
Blender Client Library
======================
Python client interface to communicate with a running Blender Live Bridge.
Provides general-purpose automation for scene inspection, object modeling,
materials, lighting, modifiers, rendering, and file exchange.
"""

import os
import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple, Union

DEFAULT_BRIDGE_URL = "http://127.0.0.1:9876"


class BlenderClient:
    def __init__(self, bridge_url: str = DEFAULT_BRIDGE_URL, timeout: float = 45.0):
        self.bridge_url = bridge_url.rstrip("/")
        self.timeout = timeout

    def get_status(self) -> Dict[str, Any]:
        """Check if the bridge server is responding and retrieve scene summary."""
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
        """Retrieve full hierarchy of objects in the scene with transforms, modifiers, and types."""
        try:
            req = urllib.request.Request(f"{self.bridge_url}/inspect", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            # Fallback to direct script execution
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

    def select_objects(self, names: List[str], active_name: Optional[str] = None, deselect_others: bool = True) -> Dict[str, Any]:
        """Select specified objects in the viewport and optionally set active object."""
        code = f"""
import bpy
if {deselect_others}:
    bpy.ops.object.select_all(action='DESELECT')
target_names = {json.dumps(names)}
selected = []
for name in target_names:
    obj = bpy.data.objects.get(name)
    if obj:
        obj.select_set(True)
        selected.append(name)
active_name = {json.dumps(active_name)}
if active_name and active_name in bpy.data.objects:
    bpy.context.view_layer.objects.active = bpy.data.objects[active_name]
result = {{
    "selected": selected,
    "active": bpy.context.active_object.name if bpy.context.active_object else None
}}
"""
        return self.execute_python(code)

    def create_primitive(
        self,
        primitive_type: str,
        name: Optional[str] = None,
        location: Tuple[float, float, float] = (0.0, 0.0, 0.0),
        size: float = 2.0,
        radius: float = 1.0,
        depth: float = 2.0
    ) -> Dict[str, Any]:
        """Create parametric primitive mesh (cube, cylinder, uv_sphere, ico_sphere, cone, plane)."""
        ptype = primitive_type.lower().strip()
        code = f"""
import bpy
ptype = {json.dumps(ptype)}
loc = {list(location)}
size = {float(size)}
radius = {float(radius)}
depth = {float(depth)}

if ptype in ('cube', 'box'):
    bpy.ops.mesh.primitive_cube_add(size=size, location=loc)
elif ptype in ('cylinder', 'tube'):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=loc)
elif ptype in ('sphere', 'uv_sphere'):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=loc)
elif ptype in ('icosphere', 'ico_sphere'):
    bpy.ops.mesh.primitive_ico_sphere_add(radius=radius, location=loc)
elif ptype in ('cone'):
    bpy.ops.mesh.primitive_cone_add(radius1=radius, depth=depth, location=loc)
elif ptype in ('plane', 'quad'):
    bpy.ops.mesh.primitive_plane_add(size=size, location=loc)
else:
    raise ValueError(f"Unsupported primitive type: {{ptype}}")

obj = bpy.context.active_object
custom_name = {json.dumps(name)}
if custom_name and obj:
    obj.name = custom_name
result = {{"created": obj.name, "type": obj.type, "location": list(obj.location)}}
"""
        return self.execute_python(code)

    def transform_object(
        self,
        name: str,
        location: Optional[List[float]] = None,
        rotation_euler: Optional[List[float]] = None,
        scale: Optional[List[float]] = None,
        relative: bool = False
    ) -> Dict[str, Any]:
        """Apply translation, rotation, or scale to an object in world space or relative offset."""
        target_name = json.dumps(name)
        code = f"""
import bpy, math
obj = bpy.data.objects.get({target_name})
if not obj:
    raise ValueError("Object " + {target_name!r} + " not found")

loc = {repr(location)}
rot = {repr(rotation_euler)}
sc = {repr(scale)}
rel = {repr(bool(relative))}

if loc is not None:
    if rel:
        obj.location.x += loc[0]; obj.location.y += loc[1]; obj.location.z += loc[2]
    else:
        obj.location = loc
if rot is not None:
    if rel:
        obj.rotation_euler.x += rot[0]; obj.rotation_euler.y += rot[1]; obj.rotation_euler.z += rot[2]
    else:
        obj.rotation_euler = rot
if sc is not None:
    if rel:
        obj.scale.x *= sc[0]; obj.scale.y *= sc[1]; obj.scale.z *= sc[2]
    else:
        obj.scale = sc

result = {{
    "object": obj.name,
    "location": [round(v, 4) for v in obj.location],
    "rotation_euler": [round(v, 4) for v in obj.rotation_euler],
    "scale": [round(v, 4) for v in obj.scale]
}}
"""
        return self.execute_python(code)

    def apply_modifier(
        self,
        name: str,
        modifier_type: str,
        modifier_name: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        apply: bool = False
    ) -> Dict[str, Any]:
        """Add or configure a modifier (SUBSURF, BEVEL, BOOLEAN, MIRROR, SOLIDIFY) and optionally apply it."""
        code = f"""
import bpy
obj = bpy.data.objects.get({json.dumps(name)})
if not obj:
    raise ValueError("Object not found")

m_type = {json.dumps(modifier_type.upper())}
m_name = {repr(modifier_name)} or m_type.capitalize()
mod = obj.modifiers.get(m_name) or obj.modifiers.new(name=m_name, type=m_type)

props = {json.dumps(properties or {})}
for k, v in props.items():
    if hasattr(mod, k):
        setattr(mod, k, v)

if {repr(bool(apply))}:
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)
    result = {{"applied": True, "object": obj.name, "modifier": m_name}}
else:
    result = {{"applied": False, "object": obj.name, "modifier": mod.name, "type": mod.type}}
"""
        return self.execute_python(code)

    def setup_camera_light(
        self,
        camera_loc: Optional[List[float]] = None,
        camera_target: Optional[List[float]] = None,
        focal_length: float = 50.0,
        light_type: str = "SUN",
        light_energy: float = 5.0,
        light_color: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    ) -> Dict[str, Any]:
        """Configure scene camera and principal lighting."""
        code = f"""
import bpy, math
from mathutils import Vector

cam = bpy.context.scene.camera
if not cam:
    cam_data = bpy.data.cameras.new("AI_Camera")
    cam = bpy.data.objects.new("AI_Camera", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam

cam_loc_val = {repr(camera_loc)}
if cam_loc_val is not None:
    cam.location = cam_loc_val
if hasattr(cam.data, 'lens'):
    cam.data.lens = {float(focal_length)}

target = {repr(camera_target)}
if target:
    direction = Vector(target) - cam.location
    rot_quat = direction.to_track_quat('-Z', 'Y')
    cam.rotation_euler = rot_quat.to_euler()

# Setup Light
light_type = {json.dumps(light_type.upper())}
light_obj = bpy.data.objects.get("AI_Light")
if not light_obj:
    light_data = bpy.data.lights.new("AI_Light", type=light_type)
    light_obj = bpy.data.objects.new("AI_Light", light_data)
    bpy.context.scene.collection.objects.link(light_obj)
    light_obj.location = (cam.location.x + 2, cam.location.y - 2, cam.location.z + 5)

light_obj.data.type = light_type
light_obj.data.energy = {float(light_energy)}
light_obj.data.color = {list(light_color)}

result = {{
    "camera": {{"name": cam.name, "location": list(cam.location), "focal_length": cam.data.lens}},
    "light": {{"name": light_obj.name, "type": light_obj.data.type, "energy": light_obj.data.energy}}
}}
"""
        return self.execute_python(code)

    def create_material(
        self,
        name: str,
        base_color: Tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0),
        metallic: float = 0.0,
        roughness: float = 0.5,
        transmission: float = 0.0,
        emission: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)
    ) -> Dict[str, Any]:
        """Create or configure a PBR Principled BSDF material."""
        code = f"""
import bpy
mat = bpy.data.materials.get({json.dumps(name)}) or bpy.data.materials.new(name={json.dumps(name)})
mat.use_nodes = True
nodes = mat.node_tree.nodes
bsdf = nodes.get("Principled BSDF") or nodes.new(type="ShaderNodeBsdfPrincipled")

if "Base Color" in bsdf.inputs:
    bsdf.inputs["Base Color"].default_value = {list(base_color)}
if "Metallic" in bsdf.inputs:
    bsdf.inputs["Metallic"].default_value = {float(metallic)}
if "Roughness" in bsdf.inputs:
    bsdf.inputs["Roughness"].default_value = {float(roughness)}
if "Transmission Weight" in bsdf.inputs:
    bsdf.inputs["Transmission Weight"].default_value = {float(transmission)}
elif "Transmission" in bsdf.inputs:
    bsdf.inputs["Transmission"].default_value = {float(transmission)}
if "Emission Color" in bsdf.inputs:
    bsdf.inputs["Emission Color"].default_value = {list(emission)}

result = {{"material": mat.name, "metallic": {float(metallic)}, "roughness": {float(roughness)}}}
"""
        return self.execute_python(code)

    def delete_objects(self, names: List[str]) -> Dict[str, Any]:
        """Remove specified objects and purge orphan mesh datablocks."""
        code = f"""
import bpy
names = {json.dumps(names)}
deleted = []
for name in names:
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)
        deleted.append(name)
for mesh in list(bpy.data.meshes):
    if mesh.users == 0:
        bpy.data.meshes.remove(mesh)
result = {{"deleted": deleted, "count": len(deleted)}}
"""
        return self.execute_python(code)

    def render_viewport(self, output_path: str, resolution: Tuple[int, int] = (1920, 1080), render_engine: str = "BLENDER_EEVEE_NEXT") -> Dict[str, Any]:
        """Render high-resolution frame to image file."""
        code = f"""
import bpy, os
scene = bpy.context.scene
scene.render.resolution_x = {int(resolution[0])}
scene.render.resolution_y = {int(resolution[1])}
scene.render.resolution_percentage = 100
scene.render.filepath = {json.dumps(output_path)}
scene.render.image_settings.file_format = 'PNG'

# Engine fallback
try:
    scene.render.engine = {json.dumps(render_engine)}
except Exception:
    scene.render.engine = 'CYCLES'

bpy.ops.render.render(write_still=True)
result = {{
    "output_file": os.path.abspath(scene.render.filepath),
    "exists": os.path.isfile(scene.render.filepath),
    "resolution": [{int(resolution[0])}, {int(resolution[1])}]
}}
"""
        return self.execute_python(code)

    def import_model(self, filepath: str) -> Dict[str, Any]:
        """Import standard 3D asset (STL, OBJ, FBX, GLTF, PLY) into scene."""
        code = f"""
import bpy, os
fp = {json.dumps(filepath)}
ext = os.path.splitext(fp)[1].lower()
before = set(bpy.data.objects.keys())

if ext in ('.stl',):
    bpy.ops.wm.stl_import(filepath=fp) if hasattr(bpy.ops.wm, 'stl_import') else bpy.ops.import_mesh.stl(filepath=fp)
elif ext in ('.obj',):
    bpy.ops.wm.obj_import(filepath=fp) if hasattr(bpy.ops.wm, 'obj_import') else bpy.ops.import_scene.obj(filepath=fp)
elif ext in ('.fbx',):
    bpy.ops.import_scene.fbx(filepath=fp)
elif ext in ('.gltf', '.glb'):
    bpy.ops.import_scene.gltf(filepath=fp)
elif ext in ('.ply',):
    bpy.ops.wm.ply_import(filepath=fp) if hasattr(bpy.ops.wm, 'ply_import') else bpy.ops.import_mesh.ply(filepath=fp)
else:
    raise ValueError(f"Unsupported format: {{ext}}")

after = set(bpy.data.objects.keys())
imported = list(after - before)
result = {{"imported_objects": imported, "count": len(imported), "filepath": fp}}
"""
        return self.execute_python(code)

    def export_model(self, filepath: str, format_type: str = "stl", selected_only: bool = False) -> Dict[str, Any]:
        """Export scene or selection to STL, OBJ, FBX, or GLTF."""
        code = f"""
import bpy, os
fp = {json.dumps(filepath)}
fmt = {json.dumps(format_type.lower())}
sel = {repr(bool(selected_only))}
os.makedirs(os.path.dirname(os.path.abspath(fp)), exist_ok=True)

if fmt == 'stl':
    if hasattr(bpy.ops.wm, 'stl_export'):
        bpy.ops.wm.stl_export(filepath=fp, export_selected_objects=sel)
    else:
        bpy.ops.export_mesh.stl(filepath=fp, use_selection=sel)
elif fmt == 'obj':
    if hasattr(bpy.ops.wm, 'obj_export'):
        bpy.ops.wm.obj_export(filepath=fp, export_selected_objects=sel)
    else:
        bpy.ops.export_scene.obj(filepath=fp, use_selection=sel)
elif fmt == 'fbx':
    bpy.ops.export_scene.fbx(filepath=fp, use_selection=sel)
elif fmt in ('gltf', 'glb'):
    bpy.ops.export_scene.gltf(filepath=fp, use_selection=sel)
else:
    raise ValueError(f"Unsupported format: {{fmt}}")

result = {{"exported_file": os.path.abspath(fp), "size_bytes": os.path.getsize(fp) if os.path.isfile(fp) else 0}}
"""
        return self.execute_python(code)
