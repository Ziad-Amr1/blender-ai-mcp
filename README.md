# Blender AI MCP Server & Live Bridge

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
- **Parametric Geometry**: Create primitive meshes (cubes, cylinders, UV spheres, icospheres, cones, planes) programmatically.
- **Viewport Rendering**: Capture high-resolution viewport or Cycles/Eevee render frames and return image file paths directly to the AI model.
- **Two Integration Modes**: Run as a simple script inside Blender's Text Editor or install as a permanent Blender Add-on with a dedicated Sidebar (N-panel) UI.

---

## Quickstart Guide

### 1. Requirements
- Blender 3.0 or higher (compatible with Blender 4.x)
- Python 3.10+
- Dependencies:
```bash
pip install -r requirements.txt
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

## MCP Server Configuration

Add the server to your MCP client configuration file:

### Claude Desktop (`claude_desktop_config.json`)
```json
{
  "mcpServers": {
    "blender": {
      "command": "python",
      "args": [
        "E:/course/03_Programming_Data/AI/Projects/blender-ai-mcp/mcp_server.py"
      ],
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
        "command": "python",
        "args": [
          "E:/course/03_Programming_Data/AI/Projects/blender-ai-mcp/mcp_server.py"
        ]
      }
    }
  }
}
```

---

## Exposed MCP Tools

| Tool Name | Description |
| :--- | :--- |
| `blender_get_connection_status` | Check if Blender Live Bridge is active and view scene stats. |
| `blender_inspect_scene` | Retrieve list of all scene objects, bounding boxes, and active camera. |
| `blender_execute_python` | Run arbitrary `bpy`/`bmesh` Python code with captured outputs. |
| `blender_query_objects` | Query objects matching specific names or types (`MESH`, `CAMERA`, etc.). |
| `blender_select_objects` | Select, deselect, or set active object by name. |
| `blender_create_primitive` | Spawn parametric primitive geometry at specified coordinates. |
| `blender_delete_objects` | Safely remove scene objects and purge orphan mesh datablocks. |
| `blender_get_materials` | List all materials, node structures, and object material slots. |
| `blender_render_viewport` | Trigger viewport render or full F12 render and save image. |
| `blender_export_model` | Export scene or selected objects to STL, OBJ, FBX, or GLTF. |

---

## Author
Developed by **Ziad Amr**
