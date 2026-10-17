"""Mesh data MCP tools."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_mesh_data(name: str, include_vertices: bool = True,
                      include_faces: bool = True, world_space: bool = False, limit: int = 5000) -> str:
        """Get mesh vertex and face data.

        Returns vertex positions (rounded to 5 decimals, local or world space) and face
        vertex indices, capped at `limit` each ("truncated" is set when cut). Set
        include_vertices or include_faces to False to skip those sections.
        """
        return send("get_mesh_data", {
            "name": name,
            "include_vertices": include_vertices,
            "include_faces": include_faces,
            "world_space": world_space,
            "limit": limit,
        })

    @mcp.tool(annotations=EDIT)
    def set_vertex_positions(name: str, vertex_indices: Any, positions: Any) -> str:
        """Set vertex positions by index.

        vertex_indices: list of integer indices, e.g. [0, 1, 2].
        positions: list of [x, y, z] lists, e.g. [[1,0,0], [0,1,0], [0,0,1]].
        """
        return send("set_vertex_positions", {
            "name": name,
            "vertex_indices": jparse(vertex_indices),
            "positions": jparse(positions),
        })

    @mcp.tool(annotations=READ)
    def get_vertex_groups(name: str) -> str:
        """Get all vertex groups for an object.

        Returns group names and indices.
        """
        return send("get_vertex_groups", {"name": name})

    @mcp.tool(annotations=EDIT)
    def set_vertex_group(name: str, group_name: str, vertex_indices: Any,
                         weight: float = 1.0) -> str:
        """Set vertex weights in a vertex group.

        Creates the group if it doesn't exist. vertex_indices is a list of
        integer indices. Weight is 0.0-1.0.
        """
        return send("set_vertex_group", {
            "name": name,
            "group_name": group_name,
            "vertex_indices": jparse(vertex_indices),
            "weight": weight,
        })

    @mcp.tool(annotations=DESTRUCTIVE)
    def mesh_operation(name: str, operation: str, params: Optional[dict[str, Any]] = None) -> str:
        """Whole-mesh edits without entering edit mode. Operations (params):

        merge_by_distance (distance), recalculate_normals (inside), flip_normals,
        triangulate, quads_from_tris (angle), subdivide (cuts, smooth), smooth_vertices
        (iterations, factor), shade_smooth, shade_flat, shade_auto_smooth (angle deg),
        decimate (ratio), remesh_voxel (voxel_size, scene units), fill_holes (sides),
        dissolve_degenerate (distance), delete_loose, separate_loose,
        separate_by_material, solidify (thickness, offset), mirror (axis "X"/"XY"...),
        bevel (width, segments, angle deg), uv_smart_project (angle, island_margin),
        convex_hull. Returns vertex/face counts before and after.
        """
        return send("mesh_operation", params_of(name=name, operation=operation, params=params))
