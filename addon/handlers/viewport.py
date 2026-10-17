"""Viewport screenshot, shading, view, and multi-angle capture handlers."""

import base64
import math
import os
import tempfile

import bpy
import gpu
import numpy as np
from mathutils import Euler, Matrix, Vector

from . import register_handler
from .common import LAST_VIEW, rounded, select_only, view3d_context, world_bbox

# Direction from the target toward the camera for each named view.
_VIEW_DIRECTIONS = {
    "front": (0, -1, 0),
    "back": (0, 1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "top": (0, 0, 1),
    "bottom": (0, 0, -1),
    "iso": (1, -1, 0.8),
    "iso_back": (-1, 1, 0.8),
}
_GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}


def _image_file_to_base64(filepath, max_size):
    img = bpy.data.images.load(filepath)
    try:
        w, h = img.size[0], img.size[1]
        max_dim = max(w, h)
        if max_dim > max_size:
            scale_factor = max_size / max_dim
            w, h = max(1, int(w * scale_factor)), max(1, int(h * scale_factor))
            img.scale(w, h)
            img.save()
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8"), w, h
    finally:
        bpy.data.images.remove(img)


def _require_ui():
    if bpy.app.background:
        raise RuntimeError("Viewport images need Blender's UI (not available in background mode); "
                           "use render_frame or compare_silhouette instead")


def get_viewport_screenshot(max_size: int = 800, format: str = "png") -> dict:
    """Capture what the 3D viewport currently shows (offscreen redraw, no UI chrome)."""
    _require_ui()
    ctx = view3d_context()
    space, region = ctx["area"].spaces.active, ctx["region"]
    r3d = space.region_3d

    scale = min(1.0, max_size / max(region.width, region.height))
    w, h = max(1, int(region.width * scale)), max(1, int(region.height * scale))
    LAST_VIEW.update(view_matrix=[list(r) for r in r3d.view_matrix],
                     window_matrix=[list(r) for r in r3d.window_matrix])
    try:
        pixels = _offscreen_pixels(space, region, r3d.view_matrix, r3d.window_matrix, w, h)
        image_base64 = _pixels_to_base64(pixels)
    except Exception:
        # Fallback: grab the window's area (forces a redraw first so the capture is current).
        ext = format.lower()
        filepath = os.path.join(tempfile.gettempdir(), f"blender_mcp_screenshot.{ext}")
        with bpy.context.temp_override(window=ctx["window"], area=ctx["area"]):
            bpy.ops.wm.redraw_timer(type="DRAW_WIN_SWAP", iterations=1)
            bpy.ops.screen.screenshot_area(filepath=filepath)
        try:
            image_base64, w, h = _image_file_to_base64(filepath, max_size)
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)

    return {
        "image_base64": image_base64,
        "width": w,
        "height": h,
        "format": "png",
    }


def set_viewport_shading(mode: str, xray: bool = None) -> dict:
    """Set the viewport shading mode."""
    valid = ("WIREFRAME", "SOLID", "MATERIAL", "RENDERED")
    mode_upper = mode.upper()
    if mode_upper not in valid:
        raise ValueError(f"Invalid shading mode '{mode}'. Valid: {', '.join(valid)}")

    space = view3d_context()["area"].spaces.active
    space.shading.type = mode_upper
    if xray is not None:
        space.shading.show_xray = xray
    return {"shading": mode_upper, "xray": space.shading.show_xray}


def set_view(angle: str) -> dict:
    """Set the 3D viewport camera angle."""
    ctx = view3d_context()
    r3d = ctx["area"].spaces.active.region_3d
    angle_upper = angle.upper()

    axis_views = ("FRONT", "BACK", "LEFT", "RIGHT", "TOP", "BOTTOM")

    if angle_upper in axis_views:
        with bpy.context.temp_override(**ctx):
            bpy.ops.view3d.view_axis(type=angle_upper)
    elif angle_upper == "CAMERA":
        if bpy.context.scene.camera is None:
            raise ValueError("The scene has no active camera")
        r3d.view_perspective = "CAMERA"
    elif angle_upper in ("ISO", "USER"):
        r3d.view_rotation = Euler((math.radians(60), 0, math.radians(45))).to_quaternion()
        r3d.view_perspective = "PERSP"
    else:
        raise ValueError(f"Invalid view angle '{angle}'. Valid: {', '.join(axis_views)}, ISO, CAMERA")

    return {"view": angle_upper}


def frame_selected(names: list = None) -> dict:
    """Frame the selected objects (or the named ones, or everything if nothing is selected)."""
    ctx = view3d_context()
    if names:
        objs = [bpy.data.objects[n] for n in names if n in bpy.data.objects]
        if not objs:
            raise ValueError(f"None of these objects exist: {names}")
        select_only(objs)

    with bpy.context.temp_override(**ctx):
        if bpy.context.selected_objects:
            bpy.ops.view3d.view_selected()
        else:
            bpy.ops.view3d.view_all()

    return {"framed": [o.name for o in bpy.context.selected_objects] or "all"}


def _look_at(cam_pos, target):
    forward = (target - cam_pos).normalized()
    world_up = Vector((0, 1, 0)) if abs(forward.z) > 0.99 else Vector((0, 0, 1))
    right = forward.cross(world_up).normalized()
    up = right.cross(forward)
    rot = Matrix((right, up, -forward)).transposed().to_4x4()
    return (Matrix.Translation(cam_pos) @ rot).inverted()


def _projection(perspective, half_height, aspect, near, far):
    if perspective:
        f = 1.0 / math.tan(math.radians(40) / 2)
        return Matrix((
            (f / aspect, 0, 0, 0),
            (0, f, 0, 0),
            (0, 0, (far + near) / (near - far), 2 * far * near / (near - far)),
            (0, 0, -1, 0),
        ))
    return Matrix((
        (1 / (half_height * aspect), 0, 0, 0),
        (0, 1 / half_height, 0, 0),
        (0, 0, -2 / (far - near), -(far + near) / (far - near)),
        (0, 0, 0, 1),
    ))


def _draw_label(text, w, h):
    import blf
    with gpu.matrix.push_pop():
        gpu.matrix.load_matrix(Matrix.Identity(4))
        gpu.matrix.load_projection_matrix(Matrix((
            (2 / w, 0, 0, -1), (0, 2 / h, 0, -1), (0, 0, 1, 0), (0, 0, 0, 1),
        )))
        blf.size(0, max(12, h // 24))
        blf.color(0, 1.0, 0.85, 0.2, 1.0)
        blf.position(0, 8, h - max(12, h // 24) - 6, 0)
        blf.draw(0, text)


def _offscreen_pixels(space, region, view_matrix, projection_matrix, w, h, label=""):
    """Draw the scene from a given view into an offscreen buffer; returns float RGBA (h, w, 4)."""
    offscreen = gpu.types.GPUOffScreen(w, h)
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            offscreen.draw_view3d(bpy.context.scene, bpy.context.view_layer, space, region,
                                  view_matrix, projection_matrix, do_color_management=True)
            if label:
                _draw_label(label, w, h)
            buf = fb.read_color(0, 0, w, h, 4, 0, "FLOAT")
    finally:
        offscreen.free()
    # Buffer -> list is slow-ish but numpy views of gpu buffers are not reliable across versions.
    return np.array(buf.to_list(), dtype=np.float32).reshape(h, w, 4)


def _pixels_to_base64(pixels):
    """Encode float RGBA pixels (bottom-up rows, Blender order) as base64 PNG."""
    height, width = pixels.shape[0], pixels.shape[1]
    pixels = pixels.copy()
    pixels[..., 3] = 1.0
    img = bpy.data.images.new("_blendermcp_capture", width, height, alpha=True)
    filepath = os.path.join(tempfile.gettempdir(), "blender_mcp_capture.png")
    try:
        img.pixels.foreach_set(np.clip(pixels, 0.0, 1.0).ravel())
        img.filepath_raw = filepath
        img.file_format = "PNG"
        img.save()
        with open(filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    finally:
        bpy.data.images.remove(img)
        if os.path.exists(filepath):
            os.remove(filepath)


def _apply_preset(space, shading, saved):
    """Temporarily switch viewport shading; every touched attribute is recorded in saved."""
    def set_attr(owner, attr, value):
        saved.append((owner, attr, getattr(owner, attr)))
        setattr(owner, attr, value)

    preset = shading.lower()
    if preset in ("solid", "material", "rendered", "wireframe_only"):
        set_attr(space.shading, "type", "WIREFRAME" if preset == "wireframe_only" else preset.upper())
    elif preset == "wireframe":
        set_attr(space.shading, "type", "SOLID")
        set_attr(space.shading, "color_type", "SINGLE")
        set_attr(space.overlay, "show_overlays", True)
        set_attr(space.overlay, "show_wireframes", True)
        set_attr(space.overlay, "wireframe_threshold", 1.0)
    elif preset == "xray":
        set_attr(space.shading, "type", "SOLID")
        set_attr(space.shading, "show_xray", True)
        set_attr(space.shading, "xray_alpha", 0.35)
    elif preset == "clay":
        set_attr(space.shading, "type", "SOLID")
        set_attr(space.shading, "light", "STUDIO")
        set_attr(space.shading, "color_type", "SINGLE")
        set_attr(space.shading, "show_cavity", True)
    elif preset:
        raise ValueError("shading must be solid, material, rendered, wireframe, wireframe_only, xray or clay")


def capture_views(views: list = None, objects: list = None, size: int = 512,
                  shading: str = "", overlays: bool = True, perspective: bool = False,
                  frames: list = None) -> dict:
    """Render several viewpoints (or animation frames) of the scene into one labeled grid image.

    views: names (front, back, left, right, top, bottom, iso, iso_back), "camera", or [x, y, z]
    directions. frames: if given, one tile per frame using the first view. Uses an offscreen
    buffer, so the user's viewport is not moved; every changed setting is restored.
    """
    _require_ui()
    views = list(views or ["front", "right", "top", "iso"])
    resolved = []
    for v in views:
        if isinstance(v, (list, tuple)):
            resolved.append((f"[{', '.join(f'{c:g}' for c in v)}]", Vector(v)))
        elif str(v).lower() == "camera":
            if bpy.context.scene.camera is None:
                raise ValueError("The scene has no active camera")
            resolved.append(("CAMERA", None))
        elif str(v).lower() in _VIEW_DIRECTIONS:
            resolved.append((str(v).upper(), Vector(_VIEW_DIRECTIONS[str(v).lower()])))
        else:
            raise ValueError(f"Unknown view '{v}'. Valid: {', '.join(_VIEW_DIRECTIONS)}, camera or [x, y, z]")
    size = max(64, min(int(size), 2048))
    scene = bpy.context.scene
    if shading.lower() == "rendered" and scene.render.engine == "CYCLES":
        raise ValueError("Cycles draws nothing offscreen; use shading='material', or render_frame for a real render")

    ctx = view3d_context()
    space, region = ctx["area"].spaces.active, ctx["region"]

    if objects:
        targets = [bpy.data.objects[n] for n in objects if n in bpy.data.objects]
        if not targets:
            raise ValueError(f"None of these objects exist: {objects}")
    else:
        targets = [o for o in scene.objects if o.type in _GEOMETRY_TYPES and o.visible_get()]

    tiles = [(label, d, None) for label, d in resolved]
    if frames:
        tiles = [(f"{resolved[0][0]} f{int(f)}", resolved[0][1], int(f)) for f in frames[:16]]
    saved = []
    old_frame = scene.frame_current
    cols = math.ceil(math.sqrt(len(tiles)))
    rows = math.ceil(len(tiles) / cols)
    sheet = np.zeros((rows * size, cols * size, 4), dtype=np.float32)
    try:
        saved.append((space.overlay, "show_overlays", space.overlay.show_overlays))
        space.overlay.show_overlays = overlays
        if shading:
            _apply_preset(space, shading, saved)
        for i, (label, direction, frame) in enumerate(tiles):
            if frame is not None:
                scene.frame_set(frame)
            if targets:
                lo, hi = world_bbox(targets)
            else:
                lo, hi = Vector((-1, -1, -1)), Vector((1, 1, 1))
            center = (lo + hi) / 2
            radius = max((hi - lo).length / 2, 0.05)
            if direction is None:
                cam = scene.camera
                view_matrix = cam.matrix_world.inverted()
                proj = cam.calc_matrix_camera(bpy.context.evaluated_depsgraph_get(), x=size, y=size)
            else:
                d = direction.normalized()
                if abs(d.z) > 0.999:
                    d = Vector((0, -0.001 if d.z > 0 else 0.001, d.z)).normalized()
                dist = radius * (3.2 if perspective else 4.0)
                view_matrix = _look_at(center + d * dist, center)
                proj = _projection(perspective, radius * 1.1, 1.0, max(0.001, dist - radius * 2), dist + radius * 2)
            tile = _offscreen_pixels(space, region, view_matrix, proj, size, size, label=label)
            r, c = divmod(i, cols)
            y0 = (rows - 1 - r) * size
            sheet[y0:y0 + size, c * size:(c + 1) * size] = tile
    finally:
        for owner, attr, value in reversed(saved):
            setattr(owner, attr, value)
        if frames:
            scene.frame_set(old_frame)

    lo, hi = world_bbox(targets) if targets else (Vector((-1, -1, -1)), Vector((1, 1, 1)))
    return {
        "image_base64": _pixels_to_base64(sheet),
        "width": sheet.shape[1],
        "height": sheet.shape[0],
        "format": "png",
        "views": [t[0] for t in tiles],
        "objects": [o.name for o in targets][:50],
        "bbox_min": rounded(lo),
        "bbox_max": rounded(hi),
        "projection": "perspective" if perspective else "orthographic",
    }


register_handler("get_viewport_screenshot", get_viewport_screenshot)
register_handler("set_viewport_shading", set_viewport_shading)
register_handler("set_view", set_view)
register_handler("frame_selected", frame_selected)
register_handler("capture_views", capture_views)
