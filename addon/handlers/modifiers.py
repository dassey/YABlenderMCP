"""Modifier management handlers."""

import bpy

from . import register_handler


def list_modifiers(object_name: str) -> dict:
    """List all modifiers on an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    modifiers = []
    for mod in obj.modifiers:
        modifiers.append({
            "name": mod.name,
            "type": mod.type,
        })
    return {"object": obj.name, "modifiers": modifiers}


def add_modifier(object_name: str, type: str, name: str = "", settings=None) -> dict:
    """Add a modifier to an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    mod_name = name or type
    mod = obj.modifiers.new(mod_name, type.upper())

    if settings:
        for key, val in settings.items():
            setattr(mod, key, val)

    return {"object": obj.name, "modifier": mod.name, "type": mod.type}


def set_modifier_property(object_name: str, modifier_name: str, property: str, value) -> dict:
    """Set a property on a modifier."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    mod = obj.modifiers.get(modifier_name)
    if mod is None:
        raise ValueError(f"Modifier '{modifier_name}' not found on '{object_name}'")

    setattr(mod, property, value)
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


register_handler("list_modifiers", list_modifiers)
register_handler("add_modifier", add_modifier)
register_handler("set_modifier_property", set_modifier_property)
register_handler("apply_modifier", apply_modifier)
register_handler("remove_modifier", remove_modifier)
