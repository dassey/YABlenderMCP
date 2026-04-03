"""Mesh data MCP tools."""

import json

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def get_mesh_data(name: str, include_vertices: bool = True,
                      include_faces: bool = True) -> str:
        """Get mesh vertex and face data.

        Returns vertex positions (rounded to 5 decimals) and face vertex
        indices. Set include_vertices or include_faces to False to skip
        those sections for large meshes.
        """
        conn = get_connection()
        result = conn.send_command("get_mesh_data", {
            "name": name,
            "include_vertices": include_vertices,
            "include_faces": include_faces,
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_vertex_positions(name: str, vertex_indices: str, positions: str) -> str:
        """Set vertex positions by index.

        vertex_indices: JSON array of integer indices, e.g. "[0, 1, 2]".
        positions: JSON array of [x, y, z] arrays, e.g. "[[1,0,0], [0,1,0], [0,0,1]]".
        """
        conn = get_connection()
        result = conn.send_command("set_vertex_positions", {
            "name": name,
            "vertex_indices": json.loads(vertex_indices),
            "positions": json.loads(positions),
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_vertex_groups(name: str) -> str:
        """Get all vertex groups for an object.

        Returns group names and indices.
        """
        conn = get_connection()
        result = conn.send_command("get_vertex_groups", {"name": name})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_vertex_group(name: str, group_name: str, vertex_indices: str,
                         weight: float = 1.0) -> str:
        """Set vertex weights in a vertex group.

        Creates the group if it doesn't exist. vertex_indices is a JSON
        array of integer indices. Weight is 0.0-1.0.
        """
        conn = get_connection()
        result = conn.send_command("set_vertex_group", {
            "name": name,
            "group_name": group_name,
            "vertex_indices": json.loads(vertex_indices),
            "weight": weight,
        })
        return json.dumps(result, indent=2)
