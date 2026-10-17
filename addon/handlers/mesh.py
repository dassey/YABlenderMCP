"""Mesh data access and manipulation handlers."""

import math

import bmesh
import bpy

from . import register_handler
from .common import get_mesh_object, object_mode, select_only


def get_mesh_data(name: str, include_vertices: bool = True, include_faces: bool = True,
                  world_space: bool = False, limit: int = 5000) -> dict:
    """Get mesh vertex and face data (capped at `limit` entries each)."""
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
    m = obj.matrix_world

    if include_vertices:
        verts = mesh.vertices[:limit]
        result["vertices"] = [
            [round(c, 5) for c in ((m @ v.co) if world_space else v.co)]
            for v in verts
        ]

    if include_faces:
        result["faces"] = [
            list(p.vertices)
            for p in mesh.polygons[:limit]
        ]
    if len(mesh.vertices) > limit or len(mesh.polygons) > limit:
        result["truncated"] = True

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


def _apply_modifier(obj, kind, **settings):
    mod = obj.modifiers.new(f"MCP_{kind}", kind)
    for key, value in settings.items():
        setattr(mod, key, value)
    select_only([obj])
    bpy.ops.object.modifier_apply(modifier=mod.name)


_OPERATIONS = (
    "merge_by_distance", "recalculate_normals", "flip_normals", "triangulate", "quads_from_tris",
    "subdivide", "smooth_vertices", "shade_smooth", "shade_flat", "shade_auto_smooth", "decimate",
    "remesh_voxel", "fill_holes", "dissolve_degenerate", "delete_loose", "separate_loose",
    "separate_by_material", "solidify", "mirror", "bevel", "uv_smart_project", "convex_hull",
)


def mesh_operation(name: str, operation: str, params: dict = None) -> dict:
    """Run a whole-mesh edit. See _OPERATIONS for the list; params depend on the operation."""
    obj = get_mesh_object(name)
    op = operation.lower()
    p = dict(params or {})
    if op not in _OPERATIONS:
        raise ValueError(f"Unknown operation '{operation}'. Valid: {', '.join(_OPERATIONS)}")
    object_mode()
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    me = obj.data
    before = {"vertices": len(me.vertices), "faces": len(me.polygons)}
    extra = {}

    bmesh_ops = {"merge_by_distance", "recalculate_normals", "flip_normals", "triangulate", "quads_from_tris",
                 "subdivide", "smooth_vertices", "fill_holes", "dissolve_degenerate", "delete_loose", "convex_hull"}
    if op in bmesh_ops:
        bm = bmesh.new()
        bm.from_mesh(me)
        if op == "merge_by_distance":
            dist = p.get("distance", 0.0001)
            bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
        elif op == "recalculate_normals":
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            if p.get("inside"):
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
        elif op == "flip_normals":
            bmesh.ops.reverse_faces(bm, faces=bm.faces)
        elif op == "triangulate":
            bmesh.ops.triangulate(bm, faces=bm.faces)
        elif op == "quads_from_tris":
            bmesh.ops.join_triangles(bm, faces=bm.faces, angle_face_threshold=math.radians(p.get("angle", 40)),
                                     angle_shape_threshold=math.radians(p.get("angle", 40)))
        elif op == "subdivide":
            bmesh.ops.subdivide_edges(bm, edges=bm.edges, cuts=int(p.get("cuts", 1)), use_grid_fill=True,
                                      smooth=float(p.get("smooth", 0.0)))
        elif op == "smooth_vertices":
            for _ in range(int(p.get("iterations", 1))):
                bmesh.ops.smooth_vert(bm, verts=bm.verts, factor=float(p.get("factor", 0.5)),
                                      use_axis_x=True, use_axis_y=True, use_axis_z=True)
        elif op == "fill_holes":
            res = bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary], sides=int(p.get("sides", 0)))
            extra["faces_added"] = len(res["faces"])
        elif op == "dissolve_degenerate":
            bmesh.ops.dissolve_degenerate(bm, dist=p.get("distance", 0.0001), edges=bm.edges)
        elif op == "delete_loose":
            loose = [v for v in bm.verts if not v.link_faces]
            bmesh.ops.delete(bm, geom=[e for e in bm.edges if not e.link_faces], context="EDGES")
            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_edges], context="VERTS")
            extra["removed_vertices"] = len(loose)
        elif op == "convex_hull":
            hull = bmesh.new()
            for v in bm.verts:
                hull.verts.new(v.co)
            res = bmesh.ops.convex_hull(hull, input=hull.verts)
            drop = list({g for g in res["geom_interior"] + res["geom_unused"] if isinstance(g, bmesh.types.BMVert)})
            bmesh.ops.delete(hull, geom=drop, context="VERTS")
            bm.free()
            bm = hull
        bm.to_mesh(me)
        bm.free()
        me.update()
    elif op in ("shade_smooth", "shade_flat"):
        me.shade_smooth() if op == "shade_smooth" else me.shade_flat()
    elif op == "shade_auto_smooth":
        select_only([obj])
        bpy.ops.object.shade_auto_smooth(angle=math.radians(p.get("angle", 30)))
    elif op == "decimate":
        _apply_modifier(obj, "DECIMATE", ratio=float(p.get("ratio", 0.5)))
    elif op == "remesh_voxel":
        size = float(p.get("voxel_size", 0.0))
        if size <= 0:
            raise ValueError("params.voxel_size (scene units) is required")
        cells = math.prod(max(d / size, 1) for d in obj.dimensions)
        if cells > 40_000_000:
            raise ValueError(f"voxel_size {size} gives {cells:.0f} cells; use at least "
                             f"{size * (cells / 40_000_000) ** (1 / 3):.4g}")
        _apply_modifier(obj, "REMESH", mode="VOXEL", voxel_size=size)
    elif op in ("separate_loose", "separate_by_material"):
        before_objs = set(bpy.data.objects)
        select_only([obj])
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.separate(type="LOOSE" if op == "separate_loose" else "MATERIAL")
        bpy.ops.object.mode_set(mode="OBJECT")
        extra["new_objects"] = [o.name for o in bpy.data.objects if o not in before_objs]
    elif op == "solidify":
        _apply_modifier(obj, "SOLIDIFY", thickness=float(p.get("thickness", 0.1)),
                        offset=float(p.get("offset", -1.0)), use_even_offset=bool(p.get("even", False)))
    elif op == "mirror":
        axis = p.get("axis", "X").upper()
        _apply_modifier(obj, "MIRROR", use_axis=[a in axis for a in "XYZ"], use_clip=True,
                        use_mirror_merge=True)
    elif op == "bevel":
        _apply_modifier(obj, "BEVEL", width=float(p.get("width", 0.02)), segments=int(p.get("segments", 3)),
                        limit_method="ANGLE", angle_limit=math.radians(p.get("angle", 30)))
    elif op == "uv_smart_project":
        select_only([obj])
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(p.get("angle", 66)),
                                 island_margin=float(p.get("island_margin", 0.02)))
        bpy.ops.object.mode_set(mode="OBJECT")
        extra["uv_maps"] = [uv.name for uv in me.uv_layers]

    obj = bpy.data.objects.get(name) or obj
    return {"object": obj.name, "operation": op, "before": before,
            "after": {"vertices": len(obj.data.vertices), "faces": len(obj.data.polygons)}, **extra}


register_handler("get_mesh_data", get_mesh_data)
register_handler("mesh_operation", mesh_operation)
register_handler("set_vertex_positions", set_vertex_positions)
register_handler("get_vertex_groups", get_vertex_groups)
register_handler("set_vertex_group", set_vertex_group)
