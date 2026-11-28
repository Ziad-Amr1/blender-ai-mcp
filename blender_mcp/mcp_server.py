"""
Blender AI Model Context Protocol (MCP) Server
==============================================
Standard MCP server connecting AI assistants (Google Antigravity, OpenCode,
Claude Desktop, Cursor) directly to live Blender sessions with ToolAnnotations
metadata, strict thread-safety guarantees, and robust error handling.

Complies with Glama Tool Definition Quality Score (TDQS) guidelines:
- Explicit purpose clarity and usage guidelines (prerequisites, workflow sequence, alternatives).
- Behavioral transparency (filesystem side effects, overwrites, timeout limits).
- Complete parameter semantics (units, ranges, defaults, data structures, and concrete examples).
"""

import os
import sys
import logging
from typing import Annotated, Any, Dict, List, Optional, Tuple
from pydantic import Field
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
        "Blender 3D MCP server connects AI clients directly to live Blender 3D modeling and rendering sessions. "
        "Standard Modeling & Rendering Workflow: "
        "1. Diagnostics: Call blender_get_connection_status to confirm the live HTTP bridge is listening on port 9876. "
        "2. Scene Survey: Call blender_inspect_scene to view the active scene hierarchy, polygon counts, and world transforms. "
        "   Use blender_query_objects to filter objects by name or type ('MESH', 'LIGHT', 'CAMERA'). "
        "3. Geometry Generation: Call blender_create_primitive to add standard meshes ('cube', 'sphere', 'cylinder', 'plane') "
        "   or blender_import_model to load external 3D assets (.obj, .stl, .fbx, .gltf, .ply). "
        "4. Manipulation: Call blender_transform_object (location, rotation, scale), blender_select_objects, or "
        "   blender_apply_modifier ('SUBSURF', 'BEVEL', 'BOOLEAN', 'MIRROR', 'SOLIDIFY'). "
        "5. Materials & Shading: Call blender_create_material with Principled BSDF PBR settings (base color, roughness, metallic). "
        "6. Staging & Lighting: Call blender_setup_camera_light to position the camera and illuminate the scene. "
        "7. Output & Export: Call blender_render_viewport to capture a rendered image (EEVEE/Cycles) or "
        "   blender_export_model to export standard 3D assets (.obj, .stl, .fbx, .gltf, .ply). "
        "8. Advanced Automation: Call blender_execute_python for custom bpy/bmesh scripts (requires BLENDER_ALLOW_PYTHON_EXEC=true)."
    )
)


@mcp.tool(
    name="blender_get_connection_status",
    description=(
        "Check if the Blender live HTTP bridge server is active and retrieve active document status, "
        "Blender version, total scene object counts, and the currently active selected object.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Always run this as the very first diagnostic step before attempting any 3D operations.\n"
        "- Troubleshooting: If disconnected, ensure Blender is running, the bridge script 'blender_bridge.py' "
        "is executed inside Blender, and the bridge is listening on port 9876."
    ),
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
    description=(
        "Retrieve the comprehensive object hierarchy of the active Blender scene, including object types, "
        "world transform vectors (location, rotation, scale), active modifier stacks, vertex/polygon counts, "
        "and assigned material names.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Call to survey scene state, verify existing geometry, and locate target objects prior to modeling or rendering.\n"
        "- Distinction vs blender_query_objects: Returns deep technical metadata (poly counts, modifiers, materials) for all objects. "
        "Use blender_query_objects when you only need a quick, filtered list of object names and types."
    ),
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
    description=(
        "Execute arbitrary Python automation code safely on Blender's main thread with full access to bpy, bmesh, and mathutils.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Use for custom procedural modeling, complex procedural material node graphs, animation keyframing, "
        "or advanced operations not covered by high-level primitive/transform tools.\n"
        "- Security Notice: Arbitrary execution is disabled by default for safety. Requires 'BLENDER_ALLOW_PYTHON_EXEC=true' "
        "set in the environment on the host running the Blender bridge. Returns HTTP 403 Forbidden if disabled.\n"
        "- Main Thread Guarantee: Execution is dispatched to Blender's main thread via bpy.app.timers to prevent crashes.\n"
        "- Returning Data: Define a variable named 'result' inside your script to pass structured data back to the caller.\n"
        "- Output: Captures stdout, stderr, exception tracebacks, and the evaluated 'result' variable."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
        openWorldHint=True
    )
)
async def blender_execute_python(
    code: Annotated[
        str,
        Field(
            description=(
                "Python script source code to execute inside Blender. Full access to 'bpy', 'bmesh', and 'mathutils'. "
                "Assign to a variable named 'result' to return data back to the caller. "
                "Example: 'import bpy\\nresult = [obj.name for obj in bpy.data.objects if obj.type == \"MESH\"]'"
            )
        )
    ],
    timeout_seconds: Annotated[
        float,
        Field(
            default=30.0,
            description="Maximum execution timeout in seconds. Valid range: 1.0 to 600.0 seconds. Default: 30.0 s."
        )
    ] = 30.0
) -> Dict[str, Any]:
    """
    Execute arbitrary Python code safely on Blender's main thread with full access to bpy and bmesh.
    Returns captured stdout, stderr, exception tracebacks, and any 'result' variable defined in the script.
    """
    return client.execute_python(code, timeout=timeout_seconds)


@mcp.tool(
    name="blender_query_objects",
    description=(
        "Search and filter objects in the active scene by name substring and/or object type.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Fast, lightweight search to check if an object exists or find all objects of a specific category "
        "(e.g. all 'LIGHT' or 'CAMERA' objects) without the full overhead of scene inspection.\n"
        "- Distinction vs blender_inspect_scene: Lightweight filtered list returning name, type, and location."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_query_objects(
    name_filter: Annotated[
        str,
        Field(
            default="",
            description=(
                "Case-insensitive substring filter for object names (e.g. 'Wall', 'Chair', 'Speaker', 'Light'). "
                "Empty string (default) matches all object names."
            )
        )
    ] = "",
    object_type: Annotated[
        str,
        Field(
            default="",
            description=(
                "Blender datablock object type filter. Allowed values: 'MESH', 'CAMERA', 'LIGHT', 'EMPTY', 'CURVE', 'ARMATURE'. "
                "Empty string (default) matches all object types."
            )
        )
    ] = ""
) -> List[Dict[str, Any]]:
    """Filter objects in the active scene by name substring and/or type ('MESH', 'CAMERA', 'LIGHT', 'EMPTY', 'CURVE')."""
    return client.query_objects(name_filter=name_filter, object_type=object_type)


@mcp.tool(
    name="blender_select_objects",
    description=(
        "Select one or more objects by name in the 3D Viewport, set the active object, and optionally deselect others.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Use prior to operations that depend on context selection, such as applying modifiers, "
        "parenting, or selective exporting (blender_export_model with selected_only=True).\n"
        "- Prerequisites: Target objects must exist in the scene."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_select_objects(
    object_names: Annotated[
        List[str],
        Field(
            description="List of exact object names to select in the 3D Viewport. Example: ['Room_Floor', 'Acoustic_Panel_01']."
        )
    ],
    active_object_name: Annotated[
        Optional[str],
        Field(
            default=None,
            description=(
                "Optional name of the object to designate as the primary active object (context.view_layer.objects.active). "
                "If omitted, the first object in object_names is set as active."
            )
        )
    ] = None,
    deselect_others: Annotated[
        bool,
        Field(
            default=True,
            description="If True (default), deselects all other scene objects before selecting the specified objects."
        )
    ] = True
) -> Dict[str, Any]:
    """Select objects by name in the 3D Viewport and optionally designate one as the active object."""
    return client.select_objects(object_names, active_object_name=active_object_name, deselect_others=deselect_others)


@mcp.tool(
    name="blender_create_primitive",
    description=(
        "Create a standard 3D geometric mesh primitive in the active scene with custom dimensions and world coordinates.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Rapidly create base geometric primitives (floors, walls, enclosures, props, sound sources, microphones).\n"
        "- Supported Primitives: 'cube', 'sphere' (UV sphere), 'cylinder', 'plane', 'cone', 'torus', 'ico_sphere', 'circle'.\n"
        "- Side Effects: Instantiates a new mesh object in the active collection. Returns the created object name."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_create_primitive(
    primitive_type: Annotated[
        str,
        Field(
            default="cube",
            description=(
                "Type of geometric primitive to spawn. Allowed values: 'cube', 'sphere', 'cylinder', 'plane', "
                "'cone', 'torus', 'ico_sphere', 'circle'. Default: 'cube'."
            )
        )
    ] = "cube",
    name: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional custom identifier for the created object. If omitted, Blender assigns default name (e.g. 'Cube.001')."
        )
    ] = None,
    location: Annotated[
        List[float],
        Field(
            default=[0.0, 0.0, 0.0],
            description="World space [X, Y, Z] placement coordinates in meters (m). Example: [0.0, 5.0, 1.2]. Default: [0.0, 0.0, 0.0]."
        )
    ] = [0.0, 0.0, 0.0],
    size: Annotated[
        float,
        Field(
            default=2.0,
            description="Overall dimension/scale in meters (m). Used for 'cube' side length and 'plane' width. Default: 2.0 m."
        )
    ] = 2.0,
    radius: Annotated[
        float,
        Field(
            default=1.0,
            description="Base radius in meters (m). Used for 'sphere', 'cylinder', 'cone', and 'torus'. Default: 1.0 m."
        )
    ] = 1.0,
    depth: Annotated[
        float,
        Field(
            default=2.0,
            description="Extrusion height/depth in meters (m). Used for 'cylinder' and 'cone'. Default: 2.0 m."
        )
    ] = 2.0
) -> Dict[str, Any]:
    """Create a 3D primitive ('cube', 'sphere', 'cylinder', 'plane', 'cone', 'torus') at a given location with dimensions."""
    loc = (location[0], location[1], location[2]) if len(location) == 3 else (0.0, 0.0, 0.0)
    return client.create_primitive(primitive_type, name=name, location=loc, size=size, radius=radius, depth=depth)


@mcp.tool(
    name="blender_transform_object",
    description=(
        "Modify the world space location, Euler rotation, and/or scale of an existing scene object.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Reposition, orient, or resize 3D objects, cameras, or light sources.\n"
        "- Absolute vs Relative: Set relative=False (default) to set exact world coordinates. Set relative=True to apply offsets.\n"
        "- Rotation Units: Specify rotation_euler in degrees (automatically converted to radians internally)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_transform_object(
    object_name: Annotated[
        str,
        Field(
            description="Exact name of the scene object to transform (e.g. 'Cube', 'Auditorium_Ceiling', 'Camera')."
        )
    ],
    location: Annotated[
        Optional[List[float]],
        Field(
            default=None,
            description="Translation vector [X, Y, Z] in meters (m). Example: [2.5, 0.0, 1.5]."
        )
    ] = None,
    rotation_euler: Annotated[
        Optional[List[float]],
        Field(
            default=None,
            description="Euler rotation angles [X, Y, Z] in degrees (°). Example: [0.0, 45.0, 90.0]."
        )
    ] = None,
    scale: Annotated[
        Optional[List[float]],
        Field(
            default=None,
            description="Scaling multipliers [X, Y, Z] (dimensionless). Example: [1.0, 2.0, 0.5]."
        )
    ] = None,
    relative: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "If True, adds the supplied location/rotation/scale values to current object transforms. "
                "If False (default), replaces current transforms with the new absolute values."
            )
        )
    ] = False
) -> Dict[str, Any]:
    """Transform an object by setting or offsetting location (meters), Euler rotation (degrees), and scale."""
    loc = tuple(location) if location and len(location) == 3 else None
    rot = tuple(rotation_euler) if rotation_euler and len(rotation_euler) == 3 else None
    scl = tuple(scale) if scale and len(scale) == 3 else None
    return client.transform_object(object_name, location=loc, rotation_euler=rot, scale=scl, relative=relative)


@mcp.tool(
    name="blender_apply_modifier",
    description=(
        "Add and configure a procedural modifier on a mesh object, with optional permanent application (baking).\n\n"
        "Usage Guidelines:\n"
        "- When to use: Use for non-destructive mesh operations such as rounding edges (BEVEL), smoothing (SUBSURF), "
        "shell extrusion (SOLIDIFY), symmetry (MIRROR), or Boolean CSG cuts (BOOLEAN).\n"
        "- Non-Destructive vs Permanent: Set apply=False (default) to keep the modifier in the object's modifier stack for editing. "
        "Set apply=True to bake the modifier permanently into vertex geometry (required before exporting to some formats)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_apply_modifier(
    object_name: Annotated[
        str,
        Field(
            description="Exact name of the target mesh object (e.g. 'Wall_North')."
        )
    ],
    modifier_type: Annotated[
        str,
        Field(
            description=(
                "Modifier type identifier. Supported types:\n"
                "- 'SUBSURF': Catmull-Clark subdivision surface smoothing.\n"
                "- 'BEVEL': Chamfer or round sharp geometric edges.\n"
                "- 'BOOLEAN': Constructive Solid Geometry union, difference, or intersection.\n"
                "- 'MIRROR': Symmetric reflection across an axis.\n"
                "- 'SOLIDIFY': Extrude surface faces into volumetric thickness.\n"
                "- 'DECIMATE': Reduce polygon face count while preserving topology.\n"
                "- 'ARRAY': Create repeated linear or circular instances."
            )
        )
    ],
    modifier_name: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional custom identifier for the modifier entry in the stack. If omitted, uses modifier_type."
        )
    ] = None,
    properties: Annotated[
        Optional[Dict[str, Any]],
        Field(
            default=None,
            description=(
                "Key-value dictionary configuring modifier parameters. Examples:\n"
                "- For 'SUBSURF': {'levels': 2, 'render_levels': 3}\n"
                "- For 'BEVEL': {'width': 0.05, 'segments': 3, 'profile': 0.7}\n"
                "- For 'SOLIDIFY': {'thickness': 0.15, 'offset': 1.0}\n"
                "- For 'BOOLEAN': {'operation': 'DIFFERENCE', 'object': 'Cutter_Mesh'}\n"
                "- For 'DECIMATE': {'ratio': 0.5}"
            )
        )
    ] = None,
    apply: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "If True, bakes/applies the modifier permanently into mesh vertex data. "
                "If False (default), leaves the modifier live in the modifier stack."
            )
        )
    ] = False
) -> Dict[str, Any]:
    """Add or configure a modifier ('SUBSURF', 'BEVEL', 'BOOLEAN', 'MIRROR', 'SOLIDIFY') and optionally apply it permanently."""
    return client.apply_modifier(object_name, modifier_type, modifier_name=modifier_name, properties=properties, apply=apply)


@mcp.tool(
    name="blender_setup_camera_light",
    description=(
        "Configure or create the scene camera (pointed at a 3D focal point) and illumination light source.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Staging step before viewport rendering or image export (blender_render_viewport).\n"
        "- Camera Tracking: When camera_target is supplied, automatically applies a Track-To constraint pointing "
        "the camera directly at the target coordinate.\n"
        "- Light Types: Supports 'SUN' (distant directional, default), 'POINT' (omnidirectional), 'SPOT', and 'AREA'."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_setup_camera_light(
    camera_location: Annotated[
        Optional[List[float]],
        Field(
            default=None,
            description="Camera world space [X, Y, Z] placement coordinates in meters (m). Example: [7.35, -6.92, 4.95]."
        )
    ] = None,
    camera_target: Annotated[
        Optional[List[float]],
        Field(
            default=None,
            description="3D world coordinates [X, Y, Z] in meters (m) that the camera will center and aim at. Example: [0.0, 0.0, 1.0]."
        )
    ] = None,
    focal_length_mm: Annotated[
        float,
        Field(
            default=50.0,
            description=(
                "Camera lens focal length in millimeters (mm). Valid range: 1.0 to 1000.0 mm. "
                "24mm-35mm for wide-angle room views; 50mm for human eye perspective; 85mm+ for telephoto details. Default: 50.0 mm."
            )
        )
    ] = 50.0,
    light_type: Annotated[
        str,
        Field(
            default="SUN",
            description="Light emission pattern. Allowed values: 'POINT', 'SUN', 'SPOT', 'AREA'. Default: 'SUN'."
        )
    ] = "SUN",
    light_energy: Annotated[
        float,
        Field(
            default=5.0,
            description="Light source radiant power/intensity. Watts (W) for POINT/SPOT/AREA; Watts/m² for SUN. Default: 5.0."
        )
    ] = 5.0,
    light_color_rgb: Annotated[
        List[float],
        Field(
            default=[1.0, 1.0, 1.0],
            description="RGB color components in [0.0, 1.0] range. Example: [1.0, 0.95, 0.8] for warm sunlight. Default: [1.0, 1.0, 1.0]."
        )
    ] = [1.0, 1.0, 1.0]
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
    description=(
        "Create or configure a Principled BSDF Physically Based Rendering (PBR) material with physical surface attributes.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Apply realistic surface colors, reflectivity, and roughness to 3D architectural elements.\n"
        "- Parameters: Controls base color (RGBA), metallic reflection, microfacet roughness, and glass transmission."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_create_material(
    material_name: Annotated[
        str,
        Field(
            description="Unique identifier for the material datablock (e.g. 'Acoustic_Panel_Wood', 'Floor_Concrete')."
        )
    ],
    base_color_rgba: Annotated[
        List[float],
        Field(
            default=[0.8, 0.8, 0.8, 1.0],
            description=(
                "Diffuse base surface color as [Red, Green, Blue, Alpha] floats in [0.0, 1.0]. "
                "Example: [0.8, 0.2, 0.2, 1.0] for matte red. Default: [0.8, 0.8, 0.8, 1.0]."
            )
        )
    ] = [0.8, 0.8, 0.8, 1.0],
    metallic: Annotated[
        float,
        Field(
            default=0.0,
            description="Metallic reflection factor in [0.0, 1.0]. 0.0 for dielectrics (wood, plaster, carpet); 1.0 for metals (steel, copper). Default: 0.0."
        )
    ] = 0.0,
    roughness: Annotated[
        float,
        Field(
            default=0.5,
            description="Microfacet surface roughness in [0.0, 1.0]. 0.0 for glossy mirror polish; 1.0 for fully diffuse matte. Default: 0.5."
        )
    ] = 0.5,
    transmission: Annotated[
        float,
        Field(
            default=0.0,
            description="Glass/refraction transmission factor in [0.0, 1.0]. 0.0 for solid opaque; 1.0 for clear glass or water. Default: 0.0."
        )
    ] = 0.0
) -> Dict[str, Any]:
    """Create or configure a Principled BSDF PBR material with custom physical surface parameters."""
    rgba = tuple(base_color_rgba) if len(base_color_rgba) == 4 else (0.8, 0.8, 0.8, 1.0)
    return client.create_material(material_name, base_color=rgba, metallic=metallic, roughness=roughness, transmission=transmission)


@mcp.tool(
    name="blender_delete_objects",
    description=(
        "Delete one or more scene objects by name and purge orphan mesh datablocks from memory.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Clean up temporary modeling geometry, old iterations, or unwanted objects.\n"
        "- Side Effects: Permanently deletes objects from all collections in the active scene."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_delete_objects(
    object_names: Annotated[
        List[str],
        Field(
            description="List of exact object names to permanently remove from the scene. Example: ['Cube.001', 'Temp_Geometry']."
        )
    ]
) -> Dict[str, Any]:
    """Delete scene objects by name and purge orphan mesh datablocks from memory."""
    return client.delete_objects(object_names)


@mcp.tool(
    name="blender_render_viewport",
    description=(
        "Render a still image frame from the perspective of the active camera to an image file on disk.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Capture visual verification screenshots, presentation renders, or architectural perspective diagrams.\n"
        "- Prerequisites: Ensure an active camera exists and is aimed at the scene (via blender_setup_camera_light).\n"
        "- Side Effects: Writes or overwrites the rendered image file (PNG/JPEG) at output_image_path.\n"
        "- Rendering Engines: 'BLENDER_EEVEE_NEXT' (fast real-time rasterizer, default in modern Blender), "
        "'CYCLES' (physically accurate path tracer), 'BLENDER_WORKBENCH' (fast non-photorealistic technical display)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_render_viewport(
    output_image_path: Annotated[
        str,
        Field(
            description="Destination filesystem path where the rendered image will be written (e.g. 'C:/renders/preview.png')."
        )
    ],
    resolution_width: Annotated[
        int,
        Field(
            default=1920,
            description="Horizontal image resolution in pixels. Valid range: 16 to 16384. Default: 1920 px (Full HD)."
        )
    ] = 1920,
    resolution_height: Annotated[
        int,
        Field(
            default=1080,
            description="Vertical image resolution in pixels. Valid range: 16 to 16384. Default: 1080 px (Full HD)."
        )
    ] = 1080,
    render_engine: Annotated[
        str,
        Field(
            default="BLENDER_EEVEE_NEXT",
            description=(
                "Blender rendering engine to use. Allowed values: 'BLENDER_EEVEE_NEXT' (real-time GPU rasterizer), "
                "'CYCLES' (path-tracing raytracer), 'BLENDER_WORKBENCH' (fast viewport wireframe/clay). Default: 'BLENDER_EEVEE_NEXT'."
            )
        )
    ] = "BLENDER_EEVEE_NEXT"
) -> Dict[str, Any]:
    """Render a frame from the active camera to an image file (PNG)."""
    return client.render_viewport(
        output_image_path,
        resolution=(resolution_width, resolution_height),
        render_engine=render_engine
    )


@mcp.tool(
    name="blender_import_model",
    description=(
        "Import an external 3D file (.obj, .stl, .fbx, .gltf, .glb, .ply) into the active scene.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Bring external architectural CAD geometry, furniture meshes, or simulation boundaries into Blender.\n"
        "- Prerequisites: Target file must exist on disk.\n"
        "- Supported Formats: Wavefront OBJ (.obj), Stereolithography (.stl), Autodesk FBX (.fbx), glTF/GLB (.gltf, .glb), Stanford PLY (.ply)."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False
    )
)
async def blender_import_model(
    filepath: Annotated[
        str,
        Field(
            description=(
                "Filesystem path to the 3D model asset to import. "
                "Supported file extensions: .obj, .stl, .fbx, .gltf, .glb, .ply."
            )
        )
    ]
) -> Dict[str, Any]:
    """Import a standard 3D file (.obj, .stl, .fbx, .gltf, .glb, .ply) into the active scene."""
    return client.import_model(filepath)


@mcp.tool(
    name="blender_export_model",
    description=(
        "Export the entire scene or currently selected objects to a standard 3D interchange file format.\n\n"
        "Usage Guidelines:\n"
        "- When to use: Export room boundaries, acoustic surfaces, or visual assets for external simulation solvers (such as I-SIMPA) "
        "or external 3D pipelines.\n"
        "- Supported Formats: 'stl', 'obj', 'fbx', 'gltf', 'glb', 'ply'.\n"
        "- Side Effects: Writes or overwrites the 3D file at output_filepath."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=True,
        openWorldHint=False
    )
)
async def blender_export_model(
    output_filepath: Annotated[
        str,
        Field(
            description="Destination filesystem path where the exported 3D file will be written (e.g. 'C:/models/auditorium.obj')."
        )
    ],
    format_type: Annotated[
        str,
        Field(
            default="stl",
            description="Export file format type. Allowed values: 'stl', 'obj', 'fbx', 'gltf', 'glb', 'ply'. Default: 'stl'."
        )
    ] = "stl",
    selected_only: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "If True, exports only the currently selected objects in the scene. "
                "If False (default), exports all visible objects in the scene."
            )
        )
    ] = False
) -> Dict[str, Any]:
    """Export scene or selected objects to standard 3D formats ('stl', 'obj', 'fbx', 'gltf', 'glb')."""
    return client.export_model(output_filepath, format_type=format_type, selected_only=selected_only)


def main():
    """CLI entry point for running the Blender MCP stdio server."""
    mcp.run()


if __name__ == "__main__":
    main()
