"""Modifier management handlers."""

import bpy

from . import register_handler
from .common import get_object, object_mode, rounded, select_only, world_bbox

# Settings that can freeze Blender if set too high.
_LIMITS = {("SUBSURF", "levels"): 6, ("SUBSURF", "render_levels"): 6, ("MULTIRES", "levels"): 6,
           ("ARRAY", "count"): 1000, ("BEVEL", "segments"): 100, ("SCREW", "steps"): 1000,
           ("SCREW", "iterations"): 100, ("REMESH", "octree_depth"): 12}


def _check_limits(mod, key, value):
    limit = _LIMITS.get((mod.type, key))
    if limit is not None and isinstance(value, (int, float)) and value > limit:
        raise ValueError(f"{mod.type}.{key}={value} is above the safe limit {limit}")


def _set_mod_attr(mod, key, val):
    if key not in mod.bl_rna.properties:
        writable = [p.identifier for p in mod.bl_rna.properties if not p.is_readonly and p.identifier != "rna_type"]
        raise ValueError(f"'{key}' is not a {mod.type} setting. Valid: {', '.join(writable)}")
    _check_limits(mod, key, val)
    if isinstance(val, str) and mod.bl_rna.properties[key].type == "POINTER":
        val = get_object(val) if key in ("object", "offset_object", "mirror_object", "target", "start_cap",
                                         "end_cap", "curve", "origin") else val
    setattr(mod, key, val)


def list_modifiers(object_name: str) -> dict:
    """List all modifiers on an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    modifiers = []
    for mod in obj.modifiers:
        settings = {}
        for prop in mod.bl_rna.properties:
            if prop.identifier in ("rna_type", "name", "type") or prop.is_readonly:
                continue
            if prop.type in ("BOOLEAN", "INT", "FLOAT", "ENUM", "STRING") and not getattr(prop, "array_length", 0):
                settings[prop.identifier] = getattr(mod, prop.identifier)
            elif prop.type == "POINTER":
                value = getattr(mod, prop.identifier)
                if value is not None and hasattr(value, "name"):
                    settings[prop.identifier] = value.name
        modifiers.append({
            "name": mod.name,
            "type": mod.type,
            "show_viewport": mod.show_viewport,
            "settings": settings,
        })
    return {"object": obj.name, "modifiers": modifiers}


def add_modifier(object_name: str, type: str, name: str = "", settings=None) -> dict:
    """Add a modifier to an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    mod_name = name or type
    try:
        mod = obj.modifiers.new(mod_name, type.upper())
    except TypeError:
        valid = [i.identifier for i in bpy.types.Modifier.bl_rna.properties["type"].enum_items]
        raise ValueError(f"Unknown modifier type '{type}'. Valid: {', '.join(valid)}")

    try:
        for key, val in (settings or {}).items():
            _set_mod_attr(mod, key, val)
    except Exception:
        obj.modifiers.remove(mod)
        raise

    return {"object": obj.name, "modifier": mod.name, "type": mod.type}


def set_modifier_property(object_name: str, modifier_name: str, property: str, value) -> dict:
    """Set a property on a modifier."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        raise ValueError(f"Modifier '{modifier_name}' not found on '{object_name}'")

    _set_mod_attr(mod, property, value)
    return {"object": obj.name, "modifier": mod.name, "property": property, "set": True}


def apply_modifier(object_name: str, modifier_name: str) -> dict:
    """Apply a modifier to an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    if obj.modifiers.get(modifier_name) is None:
        raise ValueError(f"Modifier '{modifier_name}' not found on '{object_name}'")

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=modifier_name)

    return {"object": obj.name, "modifier": modifier_name, "applied": True}


def remove_modifier(object_name: str, modifier_name: str) -> dict:
    """Remove a modifier from an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        raise ValueError(f"Modifier '{modifier_name}' not found on '{object_name}'")

    obj.modifiers.remove(mod)
    return {"object": obj.name, "modifier": modifier_name, "removed": True}


def boolean_operation(target: str, cutter: str, operation: str = "DIFFERENCE", solver: str = "EXACT",
                      apply: bool = True, cutter_action: str = "hide") -> dict:
    """Boolean target with cutter: DIFFERENCE, UNION or INTERSECT. Solvers: EXACT (robust), MANIFOLD
    (fast, needs closed meshes - good for 3D printing), FLOAT (fast, less robust).
    cutter_action after applying: hide, delete or keep."""
    obj, cut = get_object(target), get_object(cutter)
    if obj.type != "MESH" or cut.type != "MESH":
        raise ValueError("Both objects must be meshes")
    object_mode()
    if obj.data.users > 1:
        obj.data = obj.data.copy()
    mod = obj.modifiers.new(f"Bool_{cut.name}", "BOOLEAN")
    mod.operation = operation.upper()
    mod.solver = solver.upper()
    mod.object = cut
    result = {"target": obj.name, "cutter": cut.name, "operation": mod.operation, "solver": mod.solver}
    if apply:
        select_only([obj])
        bpy.ops.object.modifier_apply(modifier=mod.name)
        if cutter_action == "delete":
            bpy.data.objects.remove(cut, do_unlink=True)
        elif cutter_action == "hide":
            cut.hide_set(True)
            cut.hide_render = True
        result["applied"] = True
        bpy.context.view_layer.update()
        result["faces"] = len(obj.data.polygons)
        lo, hi = world_bbox([obj])
        result["dimensions"] = rounded(hi - lo)
        if not obj.data.polygons:
            result["warning"] = "Result is empty - check that the objects overlap and are closed meshes"
    else:
        cut.display_type = "WIRE"
        result["modifier"] = mod.name
    return result


register_handler("list_modifiers", list_modifiers)
register_handler("boolean_operation", boolean_operation)
register_handler("add_modifier", add_modifier)
register_handler("set_modifier_property", set_modifier_property)
register_handler("apply_modifier", apply_modifier)
register_handler("remove_modifier", remove_modifier)
