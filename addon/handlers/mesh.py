"""Mesh data access and manipulation handlers."""

import bpy

from . import register_handler


def get_mesh_data(name: str, include_vertices: bool = True, include_faces: bool = True) -> dict:
    """Get mesh vertex and face data."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")
    if obj.type != "MESH":
        raise ValueError(f"Object '{name}' is not a mesh (type: {obj.type})")

    mesh = obj.data
    result = {
        "name": mesh.name,
        "vertex_count": len(mesh.vertices),
        "face_count": len(mesh.polygons),
    }

    if include_vertices:
        result["vertices"] = [
            [round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5)]
            for v in mesh.vertices
        ]

    if include_faces:
        result["faces"] = [
            list(p.vertices)
            for p in mesh.polygons
        ]

    return result


def set_vertex_positions(name: str, vertex_indices: list, positions: list) -> dict:
    """Set vertex positions by index."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")
    if obj.type != "MESH":
        raise ValueError(f"Object '{name}' is not a mesh (type: {obj.type})")

    mesh = obj.data
    for idx, pos in zip(vertex_indices, positions):
        if idx < 0 or idx >= len(mesh.vertices):
            raise ValueError(f"Vertex index {idx} out of range (mesh has {len(mesh.vertices)} vertices)")
        mesh.vertices[idx].co = pos

    mesh.update()
    return {"object": obj.name, "updated_vertices": len(vertex_indices)}


def get_vertex_groups(name: str) -> dict:
    """Get all vertex groups for an object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")

    groups = []
    for vg in obj.vertex_groups:
        groups.append({
            "name": vg.name,
            "index": vg.index,
        })
    return {"object": obj.name, "vertex_groups": groups}


def set_vertex_group(name: str, group_name: str, vertex_indices: list, weight: float = 1.0) -> dict:
    """Set vertex weights in a vertex group (creates group if needed)."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")

    vg = obj.vertex_groups.get(group_name)
    if vg is None:
        vg = obj.vertex_groups.new(name=group_name)

    vg.add(vertex_indices, weight, "REPLACE")
    return {"object": obj.name, "group": vg.name, "vertices": len(vertex_indices), "weight": weight}


register_handler("get_mesh_data", get_mesh_data)
register_handler("set_vertex_positions", set_vertex_positions)
register_handler("get_vertex_groups", get_vertex_groups)
register_handler("set_vertex_group", set_vertex_group)
