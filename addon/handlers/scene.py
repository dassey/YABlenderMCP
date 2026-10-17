"""Scene and object manipulation handlers."""

import bpy
import mathutils

from . import register_handler
from .common import get_object, object_mode, rounded, select_only, unit_scale_to_mm, world_bbox


def _evaluated_bbox(obj):
    """World bounding box of the evaluated object (modifiers included)."""
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    corners = [ev.matrix_world @ mathutils.Vector(c) for c in ev.bound_box]
    lo = mathutils.Vector([min(c[i] for c in corners) for i in range(3)])
    hi = mathutils.Vector([max(c[i] for c in corners) for i in range(3)])
    return lo, hi


def _ground_state(lo_z):
    tolerance = 0.0005 / max(bpy.context.scene.unit_settings.scale_length, 1e-9)  # 0.5 mm
    if abs(lo_z) <= tolerance:
        return "on ground"
    return f"floating {round(lo_z, 4)}" if lo_z > 0 else f"below ground by {round(-lo_z, 4)}"


def get_scene_info(query: str = "", types: list = None, limit: int = 100, offset: int = 0,
                   fields: list = None) -> dict:
    """List objects with summary info (filter by name/type, paginate, pick extra fields)."""
    scene = bpy.context.scene
    fields = set(fields or [])
    wanted = {t.upper() for t in (types or [])}
    matches = [o for o in scene.objects
               if (not query or query.lower() in o.name.lower()) and (not wanted or o.type in wanted)]
    limit = max(1, min(int(limit), 1000))
    page = matches[offset:offset + limit]

    objects = []
    for obj in page:
        info = {
            "name": obj.name,
            "type": obj.type,
            "location": [round(v, 4) for v in obj.location],
            "visible": obj.visible_get(),
        }
        if obj.type == "MESH":
            mesh = obj.data
            info["vertices"] = len(mesh.vertices)
            info["faces"] = len(mesh.polygons)
        if obj.type not in ("EMPTY", "LIGHT", "CAMERA"):
            lo, hi = _evaluated_bbox(obj)
            info["dimensions"] = rounded(hi - lo)
            if "ground" in fields:
                info["ground"] = _ground_state(lo.z)
            if "bbox" in fields:
                info["bbox"] = [rounded(lo), rounded(hi)]
        if obj.parent:
            info["parent"] = obj.parent.name
        if "rotation" in fields:
            info["rotation_euler"] = rounded(obj.rotation_euler)
        if "scale" in fields:
            info["scale"] = rounded(obj.scale)
        if "materials" in fields and obj.material_slots:
            info["materials"] = [s.material.name if s.material else None for s in obj.material_slots]
        if "modifiers" in fields and obj.modifiers:
            info["modifiers"] = [f"{m.name}:{m.type}" for m in obj.modifiers]
        if "collections" in fields:
            info["collections"] = [c.name for c in obj.users_collection]
        objects.append(info)

    counts = {}
    for o in scene.objects:
        counts[o.type] = counts.get(o.type, 0) + 1
    active = bpy.context.view_layer.objects.active
    selected = [o.name for o in bpy.context.selected_objects]
    result = {
        "scene_name": scene.name,
        "object_count": len(scene.objects),
        "type_counts": counts,
        "objects": objects,
        "active_object": active.name if active else None,
        "selected_objects": selected[:20] + ([f"+{len(selected) - 20} more"] if len(selected) > 20 else []),
        "frame_current": scene.frame_current,
        "mode": bpy.context.mode,
        "mm_per_unit": round(unit_scale_to_mm(), 6),
    }
    if offset + limit < len(matches):
        result["has_more"] = True
        result["next_offset"] = offset + limit
        result["matched"] = len(matches)
    return result


def get_object_info(name: str) -> dict:
    """Detailed info for a single object."""
    obj = get_object(name)

    info = {
        "name": obj.name,
        "type": obj.type,
        "data": obj.data.name if obj.data else None,
        "location": list(obj.location),
        "rotation_mode": obj.rotation_mode,
        "rotation_euler": list(obj.rotation_euler),
        "rotation_degrees": [round(v * 57.29577951308232, 3) for v in obj.rotation_euler],
        "scale": list(obj.scale),
        "dimensions": rounded(obj.dimensions),
        "visible": obj.visible_get(),
        "hidden": {"viewport": obj.hide_get(), "render": obj.hide_render},
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "collections": [c.name for c in obj.users_collection],
        "materials": [m.name for m in obj.data.materials if m] if hasattr(obj.data, "materials") and obj.data.materials else [],
        "modifiers": [{"name": m.name, "type": m.type, "show_viewport": m.show_viewport} for m in obj.modifiers],
        "constraints": [{"name": c.name, "type": c.type, "target": getattr(getattr(c, "target", None), "name", None)}
                        for c in obj.constraints],
    }
    if obj.rotation_mode == "QUATERNION":
        info["rotation_quaternion"] = list(obj.rotation_quaternion)
    if obj.keys():
        info["custom_properties"] = {k: str(obj[k])[:100] for k in obj.keys()}
    ad = obj.animation_data
    if ad and ad.action:
        info["animation"] = {"action": ad.action.name, "frame_range": list(ad.action.frame_range)}

    if obj.type == "MESH":
        mesh = obj.data
        info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "vertex_groups": [vg.name for vg in obj.vertex_groups],
            "uv_maps": [uv.name for uv in mesh.uv_layers],
            "shape_keys": [k.name for k in mesh.shape_keys.key_blocks] if mesh.shape_keys else [],
        }
        if obj.modifiers:
            ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
            me = ev.to_mesh()
            info["mesh"]["evaluated"] = {"vertices": len(me.vertices), "polygons": len(me.polygons)}
            ev.to_mesh_clear()
    if obj.type not in ("EMPTY", "LIGHT", "CAMERA"):
        lo, hi = _evaluated_bbox(obj)
        info["bounding_box"] = [rounded(lo), rounded(hi)]
    if obj.type == "LIGHT":
        light = obj.data
        info["light"] = {"type": light.type, "energy": light.energy, "color": rounded(light.color)}
        if light.type == "AREA":
            info["light"].update(shape=light.shape, size=light.size)
        elif light.type == "SPOT":
            info["light"].update(spot_size=light.spot_size, spot_blend=light.spot_blend)
    if obj.type == "CAMERA":
        cam = obj.data
        info["camera"] = {"type": cam.type, "lens": cam.lens, "ortho_scale": cam.ortho_scale,
                          "clip": [cam.clip_start, cam.clip_end],
                          "active": bpy.context.scene.camera == obj}

    return info


_PRIMITIVES = {
    "cube": bpy.ops.mesh.primitive_cube_add,
    "sphere": bpy.ops.mesh.primitive_uv_sphere_add,
    "uv_sphere": bpy.ops.mesh.primitive_uv_sphere_add,
    "ico_sphere": bpy.ops.mesh.primitive_ico_sphere_add,
    "cylinder": bpy.ops.mesh.primitive_cylinder_add,
    "cone": bpy.ops.mesh.primitive_cone_add,
    "torus": bpy.ops.mesh.primitive_torus_add,
    "plane": bpy.ops.mesh.primitive_plane_add,
    "circle": bpy.ops.mesh.primitive_circle_add,
    "grid": bpy.ops.mesh.primitive_grid_add,
    "monkey": bpy.ops.mesh.primitive_monkey_add,
    "empty": bpy.ops.object.empty_add,
    "camera": bpy.ops.object.camera_add,
    "light": bpy.ops.object.light_add,
    "text": bpy.ops.object.text_add,
    "bezier_curve": bpy.ops.curve.primitive_bezier_curve_add,
    "bezier_circle": bpy.ops.curve.primitive_bezier_circle_add,
    "armature": bpy.ops.object.armature_add,
}


def create_object(type: str, name: str = "", location=None, rotation=None, scale=None,
                  params: dict = None) -> dict:
    """Create a new object of the given type.

    params go to the primitive operator, e.g. {"radius": 0.5, "depth": 2, "vertices": 6}.
    """
    key = type.lower()
    if key not in _PRIMITIVES:
        raise ValueError(f"Unknown object type '{type}'. Valid: {', '.join(_PRIMITIVES)}")

    object_mode()
    op_params = dict(params or {})
    body = op_params.pop("body", None) if key == "text" else None
    if location is not None:
        op_params["location"] = location
    if rotation is not None:
        op_params["rotation"] = rotation
    try:
        _PRIMITIVES[key](**op_params)
    except TypeError as e:
        valid = [p.identifier for p in _PRIMITIVES[key].get_rna_type().properties if p.identifier != "rna_type"]
        raise ValueError(f"{e}. Valid params for {key}: {', '.join(valid)}")
    obj = bpy.context.active_object

    if name:
        obj.name = name
        if obj.data is not None and obj.data.users == 1:
            obj.data.name = name
    if body is not None:
        obj.data.body = str(body)
    note = None
    if scale is not None:
        obj.scale = scale
        if obj.type == "MESH" and obj.data.users == 1:
            # Bake creation scale into the mesh so later booleans/exports see real sizes.
            obj.data.transform(mathutils.Matrix.Diagonal((*obj.scale, 1.0)))
            obj.scale = (1.0, 1.0, 1.0)
            note = "scale was applied to the mesh (object scale is 1)"

    bpy.context.view_layer.update()
    result = {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
    }
    if obj.type not in ("EMPTY", "LIGHT", "CAMERA"):
        lo, hi = world_bbox([obj])
        result["dimensions"] = rounded(hi - lo)
        result["bbox"] = [rounded(lo), rounded(hi)]
    if note:
        result["note"] = note
    return result


def delete_objects(names: list) -> dict:
    """Delete objects by name."""
    deleted = []
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(n)
    missing = [n for n in names if n not in deleted]
    result = {"deleted": deleted}
    if missing:
        result["not_found"] = missing
    return result


def select_objects(names: list, deselect_others: bool = True) -> dict:
    """Select objects by name."""
    if deselect_others:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)

    selected = []
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj:
            obj.select_set(True)
            selected.append(n)

    if selected:
        bpy.context.view_layer.objects.active = bpy.data.objects.get(selected[-1])

    return {"selected": selected}


def set_transform(name: str, location=None, rotation=None, scale=None, relative: bool = False,
                  degrees: bool = False) -> dict:
    """Set transform properties on an object (absolute, or added to the current values)."""
    obj = get_object(name)
    before = {"location": rounded(obj.location), "rotation_euler": rounded(obj.rotation_euler),
              "scale": rounded(obj.scale)}
    if rotation is not None and degrees:
        rotation = [v * 0.017453292519943295 for v in rotation]

    if location is not None:
        obj.location = [a + b for a, b in zip(obj.location, location)] if relative else location
    if rotation is not None:
        obj.rotation_euler = [a + b for a, b in zip(obj.rotation_euler, rotation)] if relative else rotation
    if scale is not None:
        obj.scale = [a * b for a, b in zip(obj.scale, scale)] if relative else scale

    return {
        "name": obj.name,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "before": before,
    }


def duplicate_object(name: str, linked: bool = False, new_name: str = "", offset=None) -> dict:
    """Duplicate an object."""
    obj = get_object(name)
    object_mode()
    select_only([obj])

    if linked:
        bpy.ops.object.duplicate_move_linked()
    else:
        bpy.ops.object.duplicate_move()

    new_obj = bpy.context.active_object
    if new_name:
        new_obj.name = new_name
    if offset is not None:
        new_obj.location = [a + b for a, b in zip(new_obj.location, offset)]
    return {
        "name": new_obj.name,
        "type": new_obj.type,
        "location": list(new_obj.location),
    }


def parent_objects(child: str, parent: str, keep_transform: bool = True) -> dict:
    """Set (or clear, with parent="") a parent-child relationship."""
    child_obj = get_object(child)
    world = child_obj.matrix_world.copy()
    if not parent:
        child_obj.parent = None
        child_obj.matrix_world = world
        return {"child": child_obj.name, "parent": None}
    parent_obj = bpy.data.objects.get(parent)
    if parent_obj is None:
        raise ValueError(f"Parent object '{parent}' not found")

    child_obj.parent = parent_obj
    if keep_transform:
        child_obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        child_obj.matrix_world = world
    return {"child": child_obj.name, "parent": parent_obj.name}


def _collect(col) -> dict:
    """Recursively collect collection info."""
    return {
        "name": col.name,
        "objects": [o.name for o in col.objects],
        "children": [_collect(c) for c in col.children],
    }


def get_collections() -> dict:
    """Get the full collection hierarchy."""
    root = bpy.context.scene.collection
    return _collect(root)


def move_to_collection(object_name: str, collection_name: str, parent_collection: str = "") -> dict:
    """Move an object to a collection (creating it if needed)."""
    obj = get_object(object_name)

    target = bpy.data.collections.get(collection_name)
    if target is None:
        target = bpy.data.collections.new(collection_name)
        parent = bpy.data.collections.get(parent_collection) if parent_collection else None
        (parent or bpy.context.scene.collection).children.link(target)

    # Unlink from current collections
    for col in obj.users_collection:
        col.objects.unlink(obj)

    target.objects.link(obj)
    return {"object": obj.name, "collection": target.name}


def rename_object(name: str, new_name: str, rename_data: bool = True) -> dict:
    """Rename an object (and its data-block when it is not shared)."""
    obj = get_object(name)
    obj.name = new_name
    if rename_data and obj.data is not None and obj.data.users == 1:
        obj.data.name = new_name
    return {"old_name": name, "name": obj.name}


def set_visibility(names: list, hide: bool = None, hide_render: bool = None, hide_select: bool = None) -> dict:
    """Show/hide objects in the viewport and/or renders."""
    changed = []
    for n in names:
        obj = get_object(n)
        if hide is not None:
            obj.hide_set(hide)
        if hide_render is not None:
            obj.hide_render = hide_render
        if hide_select is not None:
            obj.hide_select = hide_select
        changed.append({"name": obj.name, "hidden": obj.hide_get(), "hide_render": obj.hide_render})
    return {"objects": changed}


def join_objects(names: list, new_name: str = "") -> dict:
    """Join several objects of the same type into the first one."""
    objs = [get_object(n) for n in names]
    if len(objs) < 2:
        raise ValueError("Need at least two objects to join")
    kinds = {o.type for o in objs}
    if len(kinds) != 1:
        raise ValueError(f"All objects must have the same type, got {sorted(kinds)}")
    object_mode()
    select_only(objs, active=objs[0])
    bpy.ops.object.join()
    result = bpy.context.active_object
    if new_name:
        result.name = new_name
    return {"name": result.name, "removed": [n for n in names[1:]],
            "note": f"Refer to '{result.name}' from now on; the other objects no longer exist."}


def apply_transforms(names: list, location: bool = False, rotation: bool = True, scale: bool = True) -> dict:
    """Bake rotation/scale (and optionally location) into the object data."""
    objs = [get_object(n) for n in names]
    object_mode()
    for o in objs:
        if o.data is not None and o.data.users > 1:
            o.data = o.data.copy()
    select_only(objs)
    bpy.ops.object.transform_apply(location=location, rotation=rotation, scale=scale)
    return {"applied": [o.name for o in objs], "location": location, "rotation": rotation, "scale": scale}


def set_origin(names: list, mode: str = "bottom_center") -> dict:
    """Move object origins: bottom_center, geometry, center_of_mass, center_of_volume, cursor, world_origin."""
    modes = {
        "geometry": "ORIGIN_GEOMETRY",
        "center_of_mass": "ORIGIN_CENTER_OF_MASS",
        "center_of_volume": "ORIGIN_CENTER_OF_VOLUME",
        "cursor": "ORIGIN_CURSOR",
    }
    key = mode.lower()
    if key not in modes and key not in ("bottom_center", "world_origin"):
        raise ValueError(f"Unknown mode '{mode}'. Valid: bottom_center, world_origin, {', '.join(modes)}")
    objs = [get_object(n) for n in names]
    object_mode()
    cursor = bpy.context.scene.cursor
    saved = cursor.location.copy()
    try:
        for o in objs:
            select_only([o])
            if key == "bottom_center":
                lo, hi = world_bbox([o])
                cursor.location = ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            elif key == "world_origin":
                cursor.location = (0, 0, 0)
                bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            else:
                bpy.ops.object.origin_set(type=modes[key], center="BOUNDS")
    finally:
        if key != "cursor":
            cursor.location = saved
    return {"objects": [{"name": o.name, "origin": rounded(o.matrix_world.translation)} for o in objs]}


def place_object(name: str, target: str = "", position: str = "on_top", gap: float = 0.0,
                 align: str = "center") -> dict:
    """Put an object against another by bounding boxes (or on the ground plane z=0).

    position: on_top, below, left, right, front, back, on_ground, center.
    align: center (centre the other axes on the target) or keep (leave them).
    """
    obj = get_object(name)
    bpy.context.view_layer.update()
    lo, hi = world_bbox([obj])
    size, center = hi - lo, (lo + hi) / 2
    pos = position.lower()
    delta = mathutils.Vector((0, 0, 0))

    if pos == "on_ground" or not target:
        if pos not in ("on_ground", "on_top"):
            raise ValueError("A target is required for this position")
        delta.z = gap - lo.z
    else:
        tlo, thi = world_bbox([get_object(target)])
        tcenter = (tlo + thi) / 2
        if align.lower() == "center":
            delta = tcenter - center
        if pos == "on_top":
            delta.z = thi.z + gap - lo.z
        elif pos == "below":
            delta.z = tlo.z - gap - hi.z
        elif pos == "right":
            delta.x = thi.x + gap - lo.x
        elif pos == "left":
            delta.x = tlo.x - gap - hi.x
        elif pos == "back":
            delta.y = thi.y + gap - lo.y
        elif pos == "front":
            delta.y = tlo.y - gap - hi.y
        elif pos != "center":
            raise ValueError("position must be on_top, below, left, right, front, back, on_ground or center")
        if pos in ("left", "right", "front", "back") and align.lower() == "center":
            delta.z = tlo.z - lo.z  # stand on the same floor as the target
    obj.matrix_world.translation += delta
    bpy.context.view_layer.update()
    nlo, nhi = world_bbox([obj])
    return {"name": obj.name, "moved_by": rounded(delta), "location": rounded(obj.location),
            "bbox": [rounded(nlo), rounded(nhi)], "dimensions": rounded(size)}


def convert_to_mesh(names: list, keep_original: bool = False) -> dict:
    """Convert curves, text, metaballs, surfaces (and modifier stacks) into plain meshes."""
    objs = [get_object(n) for n in names]
    object_mode()
    select_only(objs)
    bpy.ops.object.convert(target="MESH", keep_original=keep_original)
    return {"converted": [o.name for o in bpy.context.selected_objects]}


# Register all handlers
register_handler("get_scene_info", get_scene_info)
register_handler("get_object_info", get_object_info)
register_handler("create_object", create_object)
register_handler("delete_objects", delete_objects)
register_handler("select_objects", select_objects)
register_handler("set_transform", set_transform)
register_handler("duplicate_object", duplicate_object)
register_handler("parent_objects", parent_objects)
register_handler("get_collections", get_collections)
register_handler("move_to_collection", move_to_collection)
register_handler("rename_object", rename_object)
register_handler("set_visibility", set_visibility)
register_handler("join_objects", join_objects)
register_handler("apply_transforms", apply_transforms)
register_handler("set_origin", set_origin)
register_handler("place_object", place_object)
register_handler("convert_to_mesh", convert_to_mesh)
