"""
Blender AI MCP Server Launcher
==============================
Main launcher for backwards-compatible direct execution:
    python mcp_server.py
"""

import sys
import os

# Ensure package is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from blender_mcp.mcp_server import mcp, main

if __name__ == "__main__":
    main()
