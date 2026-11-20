"""
Blender AI Model Context Protocol (MCP) Server
==============================================
Enables AI assistants (Google Antigravity, OpenCode, Claude Desktop, Cursor)
to interact directly with Blender through standard MCP protocol.
"""

import os
import sys
import logging
from typing import Any, Dict, List, Optional
from mcp.server.fastmcp import FastMCP

from blender_client import BlenderClient, DEFAULT_BRIDGE_URL

# Configure logging to stderr so stdout is reserved for JSON-RPC stdio
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Blender.MCP] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("Blender.MCP.Server")

bridge_url = os.environ.get("BLENDER_BRIDGE_URL", DEFAULT_BRIDGE_URL)
client = BlenderClient(bridge_url=bridge_url)

mcp = FastMCP(
    name="Blender 3D",
    instructions=(
        "Blender 3D MCP server connects AI clients to Blender 3D. "
        "Use blender_get_connection_status to verify the live bridge. "
        "Use blender_inspect_scene and blender_query_objects to inspect the active scene hierarchy. "
        "Use blender_execute_python to run arbitrary bpy/bmesh automation scripts. "
        "Use blender_create_primitive, blender_select_objects, blender_delete_objects, "
        "and blender_render_viewport to construct geometry and preview render results."
    )
)


@mcp.tool(name="blender_get_connection_status")
async def blender_get_connection_status() -> Dict[str, Any]:
    """Check if the Blender live bridge is active and view active document status, active object, and object counts."""
    res = client.get_status()
    if res.get("status") == "connected":
        return res
    if "error" in res:
        return {
            "status": "disconnected",
            "message": (
                "Cannot connect to Blender Live Bridge. To connect, open Blender, load 'blender_bridge.py' "
                "in Blender's Text Editor and click 'Run Script' (Alt+P), or start the server via the AI Bridge Add-on panel."
            ),
            "details": res.get("error")
        }
    return res


@mcp.tool(name="blender_inspect_scene")
async def blender_inspect_scene() -> Dict[str, Any]:
    """Retrieve full hierarchy of objects in the active scene with transforms, types, modifier lists, and polycounts."""
    return client.inspect_scene()


@mcp.tool(name="blender_execute_python")
async def blender_execute_python(code: str, timeout_seconds: float = 60.0) -> Dict[str, Any]:
    """
    Execute arbitrary Python code inside Blender's main thread via bpy.app.timers.
    Globals available: bpy, bmesh, context, data, ops, and 'result'.
    Set 'result = your_data' to return a structured value.
    """
    return client.execute_python(code=code, timeout=timeout_seconds)


@mcp.tool(name="blender_query_objects")
async def blender_query_objects(name_filter: str = "", object_type: str = "") -> List[Dict[str, Any]]:
    """Filter objects in the active scene by name substring and/or type (MESH, CAMERA, LIGHT, CURVE, EMPTY)."""
    return client.query_objects(name_filter=name_filter, object_type=object_type)


@mcp.tool(name="blender_select_objects")
async def blender_select_objects(names: List[str], clear_existing: bool = True) -> Dict[str, Any]:
    """Select specific objects by name in Blender and set the first matched object as active."""
    return client.select_objects(names=names, clear_existing=clear_existing)


@mcp.tool(name="blender_create_primitive")
async def blender_create_primitive(
    primitive_type: str,
    name: str = "",
    location: Optional[List[float]] = None,
    rotation: Optional[List[float]] = None,
    scale: Optional[List[float]] = None
) -> Dict[str, Any]:
    """Create a 3D primitive mesh. Types supported: 'cube', 'sphere', 'cylinder', 'plane', 'cone', 'torus', 'monkey'."""
    return client.create_primitive(
        primitive_type=primitive_type,
        name=name,
        location=location,
        rotation=rotation,
        scale=scale
    )


@mcp.tool(name="blender_delete_objects")
async def blender_delete_objects(names: List[str]) -> Dict[str, Any]:
    """Delete objects by name from Blender and unlink them from all scene collections."""
    return client.delete_objects(names=names)


@mcp.tool(name="blender_get_materials")
async def blender_get_materials() -> Dict[str, Any]:
    """List all materials in the current Blender file with their node status and user counts."""
    code = """
import bpy
mats = []
for m in bpy.data.materials:
    mats.append({
        "name": m.name,
        "users": m.users,
        "use_nodes": m.use_nodes,
        "is_grease_pencil": m.is_grease_pencil if hasattr(m, 'is_grease_pencil') else False
    })
result = {"materials": mats, "count": len(mats)}
"""
    res = client.execute_python(code)
    if res.get("success") and res.get("result"):
        try:
            return eval(res["result"])
        except Exception:
            pass
    return res


@mcp.tool(name="blender_render_viewport")
async def blender_render_viewport(
    output_path: str,
    camera_name: str = "",
    resolution_x: int = 1920,
    resolution_y: int = 1080
) -> Dict[str, Any]:
    """Render the active scene to an image file (PNG/JPEG). Specify camera_name or leave empty to use scene default camera."""
    return client.render_viewport(
        output_path=output_path,
        camera_name=camera_name,
        resolution_x=resolution_x,
        resolution_y=resolution_y
    )


@mcp.tool(name="blender_export_model")
async def blender_export_model(
    filepath: str,
    format: str = "obj",
    selected_only: bool = False
) -> Dict[str, Any]:
    """Export the active scene or selected objects to OBJ, PLY, STL, or GLTF."""
    fmt = format.lower()
    code = f"""
import bpy, os
out_p = os.path.abspath({repr(filepath)})
os.makedirs(os.path.dirname(out_p), exist_ok=True)
sel = {selected_only}

if "{fmt}" == "obj":
    if hasattr(bpy.ops.wm, "obj_export"):
        bpy.ops.wm.obj_export(filepath=out_p, export_selected_objects=sel)
    else:
        bpy.ops.export_scene.obj(filepath=out_p, use_selection=sel)
elif "{fmt}" == "ply":
    if hasattr(bpy.ops.wm, "ply_export"):
        bpy.ops.wm.ply_export(filepath=out_p, export_selected_objects=sel)
    else:
        bpy.ops.export_mesh.ply(filepath=out_p, use_selection=sel)
elif "{fmt}" == "stl":
    if hasattr(bpy.ops.wm, "stl_export"):
        bpy.ops.wm.stl_export(filepath=out_p, export_selected_objects=sel)
    else:
        bpy.ops.export_mesh.stl(filepath=out_p, use_selection=sel)
elif "{fmt}" in ("gltf", "glb"):
    bpy.ops.export_scene.gltf(filepath=out_p, use_selection=sel)
else:
    raise ValueError(f"Unsupported format: {fmt}")

result = {{"exported_file": out_p, "file_exists": os.path.exists(out_p), "format": "{fmt}"}}
"""
    return client.execute_python(code)


if __name__ == "__main__":
    mcp.run()
