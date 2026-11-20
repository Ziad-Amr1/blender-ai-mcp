"""
Blender AI MCP Package
======================
Model Context Protocol (MCP) server and live bidirectional bridge for Blender 3D.
"""

__version__ = "1.0.0"
__author__ = "Ziad Amr"

from .blender_client import BlenderClient
from .mcp_server import mcp, main

__all__ = ["BlenderClient", "mcp", "main", "__version__"]
