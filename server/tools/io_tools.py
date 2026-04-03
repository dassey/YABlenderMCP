"""File I/O MCP tools - import, export, save, open, directory listing."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def import_file(filepath: str, options: Optional[str] = None) -> str:
        """Import a file into Blender.

        Supported formats: .fbx, .obj, .glb, .gltf, .stl, .ply, .abc.
        Options is an optional JSON object of format-specific import settings.
        """
        conn = get_connection()
        params = {"filepath": filepath}
        if options is not None:
            params["options"] = json.loads(options)
        result = conn.send_command("import_file", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def export_file(filepath: str, options: Optional[str] = None) -> str:
        """Export from Blender to a file.

        Supported formats: .fbx, .obj, .glb, .gltf, .stl, .ply, .abc.
        Options is an optional JSON object of format-specific export settings.
        """
        conn = get_connection()
        params = {"filepath": filepath}
        if options is not None:
            params["options"] = json.loads(options)
        result = conn.send_command("export_file", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def save_blend(filepath: str = "") -> str:
        """Save the current .blend file.

        If filepath is provided, saves as a new file (Save As).
        Otherwise saves to the current file path.
        """
        conn = get_connection()
        result = conn.send_command("save_blend", {"filepath": filepath})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def open_blend(filepath: str) -> str:
        """Open a .blend file.

        This replaces the current scene with the contents of the file.
        """
        conn = get_connection()
        result = conn.send_command("open_blend", {"filepath": filepath})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def list_directory(path: str, filter: str = "") -> str:
        """List files in a directory.

        Optionally filter by file extension (e.g. ".blend", ".fbx").
        Returns file names, whether each is a directory, and file sizes.
        """
        conn = get_connection()
        result = conn.send_command("list_directory", {"path": path, "filter": filter})
        return json.dumps(result, indent=2)
