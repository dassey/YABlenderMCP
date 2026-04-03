"""Scene and object manipulation handlers."""

import bpy
import mathutils

from . import register_handler


def _get_aabb(obj):
    """Compute world-space axis-aligned bounding box as [min_corner, max_corner]."""
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    min_corner = [
        round(min(c[i] for c in corners), 4) for i in range(3)
    ]
    max_corner = [
        round(max(c[i] for c in corners), 4) for i in range(3)
    ]
    return [min_corner, max_corner]


def get_scene_info() -> dict:
    """List all objects with summary info."""
    scene = bpy.context.scene
    objects = []
    for obj in scene.objects:
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
        objects.append(info)

    active = bpy.context.view_layer.objects.active
    return {
        "scene_name": scene.name,
        "object_count": len(objects),
        "objects": objects,
        "active_object": active.name if active else None,
        "selected_objects": [o.name for o in bpy.context.selected_objects],
        "frame_current": scene.frame_current,
    }


def get_object_info(name: str) -> dict:
    """Detailed info for a single object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")

    info = {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
        "visible": obj.visible_get(),
        "parent": obj.parent.name if obj.parent else None,
        "children": [c.name for c in obj.children],
        "materials": [m.name for m in obj.data.materials] if hasattr(obj.data, "materials") and obj.data.materials else [],
        "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
        "constraints": [{"name": c.name, "type": c.type} for c in obj.constraints],
    }

    if obj.type == "MESH":
        mesh = obj.data
        info["mesh"] = {
            "vertices": len(mesh.vertices),
            "edges": len(mesh.edges),
            "polygons": len(mesh.polygons),
            "vertex_groups": [vg.name for vg in obj.vertex_groups],
        }
        info["bounding_box"] = _get_aabb(obj)

    return info


def create_object(type: str, name: str = "", location=None) -> dict:
    """Create a new object of the given type."""
    ops_map = {
        "cube": lambda: bpy.ops.mesh.primitive_cube_add(),
        "sphere": lambda: bpy.ops.mesh.primitive_uv_sphere_add(),
        "ico_sphere": lambda: bpy.ops.mesh.primitive_ico_sphere_add(),
        "cylinder": lambda: bpy.ops.mesh.primitive_cylinder_add(),
        "cone": lambda: bpy.ops.mesh.primitive_cone_add(),
        "torus": lambda: bpy.ops.mesh.primitive_torus_add(),
        "plane": lambda: bpy.ops.mesh.primitive_plane_add(),
        "circle": lambda: bpy.ops.mesh.primitive_circle_add(),
        "monkey": lambda: bpy.ops.mesh.primitive_monkey_add(),
        "empty": lambda: bpy.ops.object.empty_add(),
        "camera": lambda: bpy.ops.object.camera_add(),
        "light": lambda: bpy.ops.object.light_add(),
    }

    key = type.lower()
    if key not in ops_map:
        raise ValueError(f"Unknown object type '{type}'. Valid: {', '.join(ops_map)}")

    ops_map[key]()
    obj = bpy.context.active_object

    if name:
        obj.name = name

    if location is not None:
        obj.location = location

    return {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
    }


def delete_objects(names: list) -> dict:
    """Delete objects by name."""
    deleted = []
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)
            deleted.append(n)
    return {"deleted": deleted}


def select_objects(names: list, deselect_others: bool = True) -> dict:
    """Select objects by name."""
    if deselect_others:
        bpy.ops.object.select_all(action="DESELECT")

    selected = []
    for n in names:
        obj = bpy.data.objects.get(n)
        if obj:
            obj.select_set(True)
            selected.append(n)

    if selected:
        bpy.context.view_layer.objects.active = bpy.data.objects.get(selected[-1])

    return {"selected": selected}


def set_transform(name: str, location=None, rotation=None, scale=None) -> dict:
    """Set transform properties on an object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")

    if location is not None:
        obj.location = location
    if rotation is not None:
        obj.rotation_euler = rotation
    if scale is not None:
        obj.scale = scale

    return {
        "name": obj.name,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
    }


def duplicate_object(name: str, linked: bool = False) -> dict:
    """Duplicate an object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise ValueError(f"Object '{name}' not found")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    if linked:
        bpy.ops.object.duplicate_move_linked()
    else:
        bpy.ops.object.duplicate_move()

    new_obj = bpy.context.active_object
    return {
        "name": new_obj.name,
        "type": new_obj.type,
        "location": list(new_obj.location),
    }


def parent_objects(child: str, parent: str) -> dict:
    """Set parent-child relationship."""
    child_obj = bpy.data.objects.get(child)
    parent_obj = bpy.data.objects.get(parent)
    if child_obj is None:
        raise ValueError(f"Child object '{child}' not found")
    if parent_obj is None:
        raise ValueError(f"Parent object '{parent}' not found")

    child_obj.parent = parent_obj
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


def move_to_collection(object_name: str, collection_name: str) -> dict:
    """Move an object to a collection (creating it if needed)."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    target = bpy.data.collections.get(collection_name)
    if target is None:
        target = bpy.data.collections.new(collection_name)
        bpy.context.scene.collection.children.link(target)

    # Unlink from current collections
    for col in obj.users_collection:
        col.objects.unlink(obj)

    target.objects.link(obj)
    return {"object": obj.name, "collection": target.name}


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
