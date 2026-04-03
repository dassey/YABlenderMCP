"""Viewport screenshot, shading, and view handlers."""

import base64
import os
import tempfile

import bpy

from . import register_handler


def _find_view3d_area():
    """Find the first VIEW_3D area in the current screen."""
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            return area
    raise RuntimeError("No 3D Viewport area found")


def get_viewport_screenshot(max_size: int = 800, format: str = "png") -> dict:
    """Capture a screenshot of the 3D viewport."""
    area = _find_view3d_area()

    ext = format.lower()
    filepath = os.path.join(tempfile.gettempdir(), f"blender_mcp_screenshot.{ext}")

    # Take screenshot of the area
    with bpy.context.temp_override(area=area):
        bpy.ops.screen.screenshot_area(filepath=filepath)

    # Load, resize if needed, and read as base64
    img = bpy.data.images.load(filepath)
    try:
        w, h = img.size[0], img.size[1]
        max_dim = max(w, h)
        if max_dim > max_size:
            scale_factor = max_size / max_dim
            new_w = int(w * scale_factor)
            new_h = int(h * scale_factor)
            img.scale(new_w, new_h)
            img.save()
            w, h = new_w, new_h

        with open(filepath, "rb") as f:
            image_base64 = base64.b64encode(f.read()).decode("utf-8")
    finally:
        bpy.data.images.remove(img)
        if os.path.exists(filepath):
            os.remove(filepath)

    return {
        "image_base64": image_base64,
        "width": w,
        "height": h,
        "format": ext,
    }


def set_viewport_shading(mode: str) -> dict:
    """Set the viewport shading mode."""
    valid = ("WIREFRAME", "SOLID", "MATERIAL", "RENDERED")
    mode_upper = mode.upper()
    if mode_upper not in valid:
        raise ValueError(f"Invalid shading mode '{mode}'. Valid: {', '.join(valid)}")

    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = mode_upper
                    return {"shading": mode_upper}

    raise RuntimeError("No 3D Viewport area found")


def set_view(angle: str) -> dict:
    """Set the 3D viewport camera angle."""
    area = _find_view3d_area()
    angle_upper = angle.upper()

    axis_views = ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM")

    with bpy.context.temp_override(area=area):
        if angle_upper in axis_views:
            bpy.ops.view3d.view_axis(type=angle_upper)
        elif angle_upper == "CAMERA":
            bpy.ops.view3d.view_camera()
        else:
            raise ValueError(f"Invalid view angle '{angle}'. Valid: {', '.join(axis_views)}, CAMERA")

    return {"view": angle_upper}


def frame_selected() -> dict:
    """Frame the selected objects in the viewport."""
    area = _find_view3d_area()

    with bpy.context.temp_override(area=area):
        bpy.ops.view3d.view_selected()

    return {"framed": True}


register_handler("get_viewport_screenshot", get_viewport_screenshot)
register_handler("set_viewport_shading", set_viewport_shading)
register_handler("set_view", set_view)
register_handler("frame_selected", frame_selected)
