# Blender AI MCP Server & Live Bridge

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-1.0+-green.svg)](https://modelcontextprotocol.io/)

An AI Model Context Protocol (MCP) server and bidirectional live bridge for **Blender 3D**. Connect AI assistants (such as Google Antigravity, Claude Desktop, Cursor, or OpenCode) directly to an active Blender session for real-time 3D scene inspection, geometry creation, Python script execution, and rendering.

---

## Architecture Overview

```
+-------------------------------------------------------------+
| AI Agent / Client (Claude, Antigravity, Cursor)             |
+-------------------------------------------------------------+
                               |
                        MCP Protocol (JSON-RPC stdio)
                               v
+-------------------------------------------------------------+
| Blender FastMCP Server (mcp_server.py)                      |
| Exposes standard MCP tools                                  |
+-------------------------------------------------------------+
                               |
                        HTTP REST API (Port 9876)
                               v
+-------------------------------------------------------------+
| Blender Live Bridge (blender_bridge.py / blender_addon.py)  |
| Main-Thread Execution Queue (bpy.app.timers)                |
+-------------------------------------------------------------+
                               |
                               v
+-------------------------------------------------------------+
| Blender 3D Engine (bpy / bmesh / cycles / eevee)            |
+-------------------------------------------------------------+
```

---

## Features

- **Thread-Safe Live Bridge**: Executes all `bpy` and `bmesh` commands exclusively on Blender's main thread via `bpy.app.timers` to eliminate UI locks and crashes.
- **Full Scene Inspection**: Retrieve detailed object hierarchies, types, locations, bounding boxes, mesh polygon counts, and active camera settings.
- **Arbitrary Python Automation**: Execute complex Blender Python scripts dynamically, with captured stdout, stderr, and returned dictionary results.
- **Parametric 3D Modeling**: Create primitive meshes (cubes, cylinders, UV spheres, icospheres, cones, planes), apply translations, rotations, scaling, and configure modifiers.
- **Lighting & Camera Setup**: Create and position cameras aimed at 3D targets, configure focal lengths, and set up scene illumination.
- **PBR Material Creation**: Generate and configure Principled BSDF materials with base color, metallic, roughness, and transmission.
- **Viewport Rendering**: Capture high-resolution viewport or Cycles/Eevee render frames and return image file paths directly to the AI model.
- **Two Integration Modes**: Run as a simple script inside Blender's Text Editor or install as a permanent Blender Add-on with a dedicated Sidebar (N-panel) UI.

---

## Installation & Quickstart

### 1. Install Package
```bash
git clone https://github.com/Ziad-Amr1/blender-ai-mcp.git
cd blender-ai-mcp
pip install -e .
```

### 2. Start the Live Bridge inside Blender

#### Option A: Quick Script (No installation needed)
1. Open Blender.
2. Go to the **Scripting** workspace.
3. Open `blender_bridge.py` and click **Run Script** (Alt+P).
4. The bridge starts listening on `http://127.0.0.1:9876`.

#### Option B: Install as Blender Add-on
1. In Blender, navigate to **Edit > Preferences > Add-ons > Install...**
2. Select `blender_addon.py`.
3. Enable the checkbox for **3D View: Blender AI Bridge**.
4. In the 3D Viewport, press **N** to open the sidebar, select the **AI Bridge** tab, and click **Start Bridge Server**.

---

## MCP Client Configuration

Add the server to your MCP client configuration file:

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "blender": {
      "command": "blender-mcp",
      "env": {
        "BLENDER_BRIDGE_URL": "http://127.0.0.1:9876"
      }
    }
  }
}
```

### Antigravity (`agy` / `settings.json`)
```json
{
  "mcp": {
    "servers": {
      "blender": {
        "command": "blender-mcp"
      }
    }
  }
}
```

---

## Security & Configuration

The Blender AI Bridge executes code directly within your Blender environment. It incorporates strict security defaults:

### 1. Python Execution Control (`BLENDER_ALLOW_PYTHON_EXEC`)
- **Default:** `false` (arbitrary Python script execution is disabled by default).
- When disabled, requests to `/execute` return **HTTP 403 Forbidden** before any code is parsed or queued. Read-only inspection (`/status`, `/inspect`) remains functional.
- To enable automation scripting in trusted environments, start Blender with:
  ```bash
  set BLENDER_ALLOW_PYTHON_EXEC=true
  blender --python blender_bridge.py
  ```

### 2. Network Binding & Remote Deployment
- **Default Host:** `127.0.0.1` (loopback only).
- **Transport Security Warning:** The bridge server communicates over plain HTTP. Setting an authentication token does **not** make plain HTTP secure on an untrusted network, as tokens and commands are transmitted in cleartext.
- **Non-Loopback Binding:** To bind to an external interface (e.g. `0.0.0.0`), you must explicitly provide:
  1. `BLENDER_BRIDGE_ALLOW_NON_LOOPBACK=true`
  2. `BLENDER_BRIDGE_AUTH_TOKEN=<secret>` (minimum 16 characters).
- **Token Generation:** Generate cryptographically secure tokens using Python's `secrets` module:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
  *(Note: A 16+ character count alone does not guarantee high entropy; always use a cryptographically secure random generator).*
- **Encrypted Transport Requirement:** Remote or cross-host deployments **must** terminate TLS using a reverse proxy (e.g. Nginx, Caddy) or connect through an encrypted tunnel (SSH port forwarding or WireGuard/VPN):
  ```bash
  # Example: Secure local port forwarding over SSH
  ssh -L 9876:localhost:9876 user@remote-gpu-workstation
  ```

---

## Recommended 3D Modeling & Rendering Workflow

To build and render 3D scenes reliably, execute tools in this sequence:

```
[blender_get_connection_status]       -> Verify bridge connection on port 9876
         |
[blender_inspect_scene]               -> Survey scene hierarchy, poly counts, and cameras
         |
+--------+----------------------------+
|                                     |
v                                     v
[blender_create_primitive]            [blender_import_model]
(Spawn parametric cube/sphere/plane)   (Import .obj/.stl/.fbx/.gltf/.ply)
         |                                    |
         +-----------------+------------------+
                           |
                           v
         [blender_transform_object]   -> Position, rotate, scale (absolute or relative)
                           |
         [blender_apply_modifier]     -> Add procedural bevel, subsurf, boolean, solidify
                           |
         [blender_create_material]    -> Assign Principled BSDF PBR shader (color, roughness)
                           |
         [blender_setup_camera_light] -> Position camera with tracking constraint and lights
                           |
         +-----------------+------------------+
         |                                    |
         v                                    v
[blender_render_viewport]             [blender_export_model]
(Render image via EEVEE/Cycles)       (Export scene/selected to .obj/.stl/.gltf)
```

---

## Exposed MCP Tools

The server exposes 14 tools with full MCP `ToolAnnotations` metadata:

| Tool Name | Type | Annotations | Description |
| :--- | :--- | :--- | :--- |
| `blender_get_connection_status` | Inspection | `readOnly: true`, `destructive: false` | Verify Blender live HTTP bridge status, version, and object counts. |
| `blender_inspect_scene` | Inspection | `readOnly: true`, `destructive: false` | Retrieve full hierarchy of objects, world transforms, modifiers, and poly counts. |
| `blender_execute_python` | Automation | `readOnly: false`, `destructive: true`, `openWorld: true` | Run arbitrary `bpy`/`bmesh` Python code safely on Blender's main thread. |
| `blender_query_objects` | Search | `readOnly: true`, `destructive: false` | Filter scene objects by name substring or type ('MESH', 'LIGHT', 'CAMERA'). |
| `blender_select_objects` | Selection | `readOnly: false`, `destructive: false` | Select objects by name, set active object, and optionally deselect others. |
| `blender_create_primitive` | Modeling | `readOnly: false`, `destructive: false` | Spawn parametric primitive geometry ('cube', 'sphere', 'cylinder', 'plane', 'cone'). |
| `blender_transform_object` | Modeling | `readOnly: false`, `destructive: false` | Move, rotate (degrees), or scale objects in world or relative coordinates. |
| `blender_apply_modifier` | Modeling | `readOnly: false`, `destructive: false` | Add/configure modifiers (Subsurf, Bevel, Boolean, Mirror, Solidify) or bake them. |
| `blender_setup_camera_light` | Staging | `readOnly: false`, `destructive: false` | Position camera aimed at a target point and configure scene lighting. |
| `blender_create_material` | Shading | `readOnly: false`, `destructive: false` | Create PBR Principled BSDF materials with custom surface parameters. |
| `blender_delete_objects` | Cleanup | `readOnly: false`, `destructive: true` | Safely remove scene objects and purge orphan mesh datablocks. |
| `blender_render_viewport` | Rendering | `readOnly: false`, `destructive: true` | Capture still render from camera to disk using EEVEE or Cycles. |
| `blender_import_model` | Exchange | `readOnly: false`, `destructive: false` | Import standard 3D formats (.stl, .obj, .fbx, .gltf, .glb, .ply). |
| `blender_export_model` | Exchange | `readOnly: false`, `destructive: true` | Export scene or selected objects to STL, OBJ, FBX, or GLTF. |

---

## License
Open source under the MIT License.
