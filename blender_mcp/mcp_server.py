"""
Blender AI Model Context Protocol (MCP) Server
==============================================
Standard MCP server connecting AI assistants (Google Antigravity, OpenCode,
Claude Desktop, Cursor) directly to live Blender sessions with ToolAnnotations
metadata and robust error handling.
"""

import os
import sys
import logging
from typing import Any, Dict, List, Optional, Tuple
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .blender_client import BlenderClient, DEFAULT_BRIDGE_URL

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
        "Blender 3D MCP server connects AI clients to live Blender 3D sessions. "
        "Use blender_get_connection_status to verify the live bridge. "
        "Use blender_inspect_scene and blender_query_objects to inspect the active scene hierarchy. "
        "Use blender_execute_python to run arbitrary bpy/bmesh automation scripts. "
        "Use blender_create_primitive, blender_transform_object, and blender_apply_modifier for 3D modeling. "
        "Use blender_setup_camera_light and blender_create_material for rendering prep. "
        "Use blender_render_viewport, blender_import_model, and blender_export_model for pipeline exchange."
    )
)


@mcp.tool(
    name="blender_get_connection_status",
    description="Check if Blender live bridge is active and view active document status, active object, and object counts.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
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
                "(or activate the Blender AI Bridge add-on) and run the bridge server on port 9876."
            ),
            "bridge_url": client.bridge_url,
            "details": res["error"]
        }
    return res


@mcp.tool(
    name="blender_inspect_scene",
    description="Retrieve full hierarchy of objects in the scene, including types, world transforms, modifiers, and polygon counts.",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_inspect_scene() -> Dict[str, Any]:
    """Retrieve full hierarchy of objects in the scene, including types, world transforms, modifiers, and polygon counts."""
    return client.inspect_scene()


@mcp.tool(
    name="blender_execute_python",
    description="Execute arbitrary Python code safely on Blender's main thread with full access to bpy and bmesh.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True
    )
)
async def blender_execute_python(code: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
    """
    Execute arbitrary Python code safely on Blender's main thread with full access to bpy and bmesh.
    Returns captured stdout, stderr, exception tracebacks, and any 'result' variable defined in the script.
    """
    return client.execute_python(code, timeout=timeout_seconds)


@mcp.tool(
    name="blender_query_objects",
    description="Filter objects in the active scene by name substring and/or type ('MESH', 'CAMERA', 'LIGHT', 'EMPTY', 'CURVE').",
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_query_objects(name_filter: str = "", object_type: str = "") -> List[Dict[str, Any]]:
    """Filter objects in the active scene by name substring and/or type ('MESH', 'CAMERA', 'LIGHT', 'EMPTY', 'CURVE')."""
    return client.query_objects(name_filter=name_filter, object_type=object_type)


@mcp.tool(
    name="blender_select_objects",
    description="Select objects by name in the 3D Viewport and optionally designate one as the active object.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_select_objects(
    object_names: List[str],
    active_object_name: Optional[str] = None,
    deselect_others: bool = True
) -> Dict[str, Any]:
    """Select objects by name in the 3D Viewport and optionally designate one as the active object."""
    return client.select_objects(object_names, active_name=active_object_name, deselect_others=deselect_others)


@mcp.tool(
    name="blender_create_primitive",
    description="Spawn parametric primitive mesh ('cube', 'cylinder', 'uv_sphere', 'ico_sphere', 'cone', 'plane').",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_create_primitive(
    primitive_type: str,
    name: Optional[str] = None,
    location: List[float] = [0.0, 0.0, 0.0],
    size: float = 2.0,
    radius: float = 1.0,
    depth: float = 2.0
) -> Dict[str, Any]:
    """Spawn parametric primitive mesh ('cube', 'cylinder', 'uv_sphere', 'ico_sphere', 'cone', 'plane')."""
    loc = (location[0], location[1], location[2]) if len(location) == 3 else (0.0, 0.0, 0.0)
    return client.create_primitive(primitive_type, name=name, location=loc, size=size, radius=radius, depth=depth)


@mcp.tool(
    name="blender_transform_object",
    description="Apply position, rotation (Euler radians), or scale to any scene object.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_transform_object(
    object_name: str,
    location: Optional[List[float]] = None,
    rotation_euler: Optional[List[float]] = None,
    scale: Optional[List[float]] = None,
    relative: bool = False
) -> Dict[str, Any]:
    """Apply position, rotation (Euler radians), or scale to any scene object."""
    return client.transform_object(object_name, location=location, rotation_euler=rotation_euler, scale=scale, relative=relative)


@mcp.tool(
    name="blender_apply_modifier",
    description="Add or configure a modifier ('SUBSURF', 'BEVEL', 'BOOLEAN', 'MIRROR', 'SOLIDIFY') and optionally apply it permanently.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_apply_modifier(
    object_name: str,
    modifier_type: str,
    modifier_name: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    apply: bool = False
) -> Dict[str, Any]:
    """Add or configure a modifier ('SUBSURF', 'BEVEL', 'BOOLEAN', 'MIRROR', 'SOLIDIFY') and optionally apply it permanently."""
    return client.apply_modifier(object_name, modifier_type, modifier_name=modifier_name, properties=properties, apply=apply)


@mcp.tool(
    name="blender_setup_camera_light",
    description="Configure or create the scene camera (aimed at a target point) and scene illumination.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_setup_camera_light(
    camera_location: Optional[List[float]] = None,
    camera_target: Optional[List[float]] = None,
    focal_length_mm: float = 50.0,
    light_type: str = "SUN",
    light_energy: float = 5.0,
    light_color_rgb: List[float] = [1.0, 1.0, 1.0]
) -> Dict[str, Any]:
    """Configure or create the scene camera (aimed at a target point) and scene illumination."""
    col = (light_color_rgb[0], light_color_rgb[1], light_color_rgb[2]) if len(light_color_rgb) == 3 else (1.0, 1.0, 1.0)
    return client.setup_camera_light(
        camera_loc=camera_location,
        camera_target=camera_target,
        focal_length=focal_length_mm,
        light_type=light_type,
        light_energy=light_energy,
        light_color=col
    )


@mcp.tool(
    name="blender_create_material",
    description="Create or configure a Principled BSDF PBR material with custom physical surface parameters.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_create_material(
    material_name: str,
    base_color_rgba: List[float] = [0.8, 0.8, 0.8, 1.0],
    metallic: float = 0.0,
    roughness: float = 0.5,
    transmission: float = 0.0
) -> Dict[str, Any]:
    """Create or configure a Principled BSDF PBR material with custom physical surface parameters."""
    rgba = tuple(base_color_rgba) if len(base_color_rgba) == 4 else (0.8, 0.8, 0.8, 1.0)
    return client.create_material(material_name, base_color=rgba, metallic=metallic, roughness=roughness, transmission=transmission)


@mcp.tool(
    name="blender_delete_objects",
    description="Delete scene objects by name and purge orphan mesh datablocks from memory.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_delete_objects(object_names: List[str]) -> Dict[str, Any]:
    """Delete scene objects by name and purge orphan mesh datablocks from memory."""
    return client.delete_objects(object_names)


@mcp.tool(
    name="blender_render_viewport",
    description="Render a frame from the active camera to an image file (PNG).",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_render_viewport(
    output_image_path: str,
    resolution_width: int = 1920,
    resolution_height: int = 1080,
    render_engine: str = "BLENDER_EEVEE_NEXT"
) -> Dict[str, Any]:
    """Render a frame from the active camera to an image file (PNG)."""
    return client.render_viewport(
        output_image_path,
        resolution=(resolution_width, resolution_height),
        render_engine=render_engine
    )


@mcp.tool(
    name="blender_import_model",
    description="Import a standard 3D file (.obj, .stl, .fbx, .gltf, .glb, .ply) into the active scene.",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_import_model(filepath: str) -> Dict[str, Any]:
    """Import a standard 3D file (.obj, .stl, .fbx, .gltf, .glb, .ply) into the active scene."""
    return client.import_model(filepath)


@mcp.tool(
    name="blender_export_model",
    description="Export scene or selected objects to standard 3D formats ('stl', 'obj', 'fbx', 'gltf', 'glb').",
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_export_model(
    output_filepath: str,
    format_type: str = "stl",
    selected_only: bool = False
) -> Dict[str, Any]:
    """Export scene or selected objects to standard 3D formats ('stl', 'obj', 'fbx', 'gltf', 'glb')."""
    return client.export_model(output_filepath, format_type=format_type, selected_only=selected_only)


def main():
    """CLI entry point for running the Blender MCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
