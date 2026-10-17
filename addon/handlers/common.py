"""Shared helpers for handlers."""

import bpy
import mathutils

# View/projection matrices of the last viewport screenshot (used to pick objects at a pixel).
LAST_VIEW = {}


def get_object(name: str):
    obj = bpy.data.objects.get(name)
    if obj is None:
        names = list(bpy.data.objects.keys())
        exact = [n for n in names if n.lower() == str(name).lower()]
        if len(exact) == 1:
            return bpy.data.objects[exact[0]]
        import difflib
        close = difflib.get_close_matches(str(name), names, n=5, cutoff=0.5)
        raise ValueError(f"Object '{name}' not found" + (f". Did you mean: {', '.join(close)}?" if close else ""))
    return obj


def get_mesh_object(name: str):
    obj = get_object(name)
    if obj.type != "MESH":
        raise ValueError(f"Object '{name}' is not a mesh (type: {obj.type})")
    return obj


def rounded(values, ndigits: int = 4) -> list:
    return [round(float(v), ndigits) for v in values]


def world_bbox(objects) -> tuple:
    """World-space axis-aligned bounding box (min, max) over one or more objects."""
    corners = []
    for obj in objects:
        corners.extend(obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box)
    if not corners:
        raise ValueError("No objects to measure")
    lo = mathutils.Vector([min(c[i] for c in corners) for i in range(3)])
    hi = mathutils.Vector([max(c[i] for c in corners) for i in range(3)])
    return lo, hi


def view3d_context() -> dict:
    """Context override for the largest 3D Viewport (window, screen, area, region)."""
    best = None
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "VIEW_3D" and (best is None or area.width * area.height > best[1].width * best[1].height):
                best = (window, area)
    if best is None:
        raise RuntimeError("No 3D Viewport found (Blender must run with its UI, not in background mode)")
    window, area = best
    region = next(r for r in area.regions if r.type == "WINDOW")
    return {"window": window, "screen": window.screen, "area": area, "region": region}


def object_mode():
    """Leave edit/sculpt/paint modes so data-level edits are not overwritten."""
    obj = bpy.context.view_layer.objects.active
    if obj is not None and obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")


def select_only(objects, active=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or (objects[0] if objects else None)


def unit_scale_to_mm() -> float:
    """Factor converting Blender units to millimeters for the current scene."""
    return bpy.context.scene.unit_settings.scale_length * 1000.0
