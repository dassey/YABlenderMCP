"""Measurement and verification handlers: distances, ray casts, picking, scene diffs, silhouettes."""

import base64
import hashlib
import os
import tempfile

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import register_handler
from .common import LAST_VIEW, get_object, rounded, unit_scale_to_mm, world_bbox

_snapshots = {}


def _object_bvh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        verts = [ev.matrix_world @ v.co for v in me.vertices]
        tris = [tuple(t.vertices) for t in me.loop_triangles]
    finally:
        ev.to_mesh_clear()
    return BVHTree.FromPolygons(verts, tris, all_triangles=True), verts


def measure_distance(a: str, b: str) -> dict:
    """Distance between two objects: origins, bounding boxes, and closest surfaces (gap; 0 if touching)."""
    oa, ob = get_object(a), get_object(b)
    result = {"a": oa.name, "b": ob.name,
              "origin_distance": round((oa.matrix_world.translation - ob.matrix_world.translation).length, 6)}
    (alo, ahi), (blo, bhi) = world_bbox([oa]), world_bbox([ob])
    gap = Vector([max(blo[i] - ahi[i], alo[i] - bhi[i], 0) for i in range(3)])
    result["bbox_gap"] = round(gap.length, 6)
    if oa.type in ("MESH", "CURVE", "FONT", "SURFACE", "META") and ob.type in ("MESH", "CURVE", "FONT", "SURFACE", "META"):
        bva, va = _object_bvh(oa)
        bvb, vb = _object_bvh(ob)
        if bva.overlap(bvb):
            result.update(surface_gap=0.0, intersecting=True)
        else:
            best = (None, None, None)
            for src, tree in ((va, bvb), (vb, bva)):
                step = max(1, len(src) // 20000)
                for v in src[::step]:
                    loc, _, _, dist = tree.find_nearest(v)
                    if loc is not None and (best[0] is None or dist < best[0]):
                        best = (dist, v, loc)
            if best[0] is not None:
                result.update(surface_gap=round(best[0], 6), intersecting=False,
                              closest_points=[rounded(best[1]), rounded(best[2])])
    result["mm_per_unit"] = round(unit_scale_to_mm(), 6)
    return result


def find_ray_hit(origin, direction, max_distance: float = 1e6) -> dict:
    """Cast a ray into the scene; returns the first object hit, location, normal and distance."""
    dg = bpy.context.evaluated_depsgraph_get()
    d = Vector(direction).normalized()
    hit, loc, normal, index, obj, _ = bpy.context.scene.ray_cast(dg, Vector(origin), d, distance=max_distance)
    if not hit:
        return {"hit": False}
    return {"hit": True, "object": obj.original.name if obj else None, "location": rounded(loc),
            "normal": rounded(normal), "distance": round((loc - Vector(origin)).length, 6), "face_index": index}


def find_object_at(x: float, y: float) -> dict:
    """Which object is at a point of the last viewport screenshot? x, y in 0..1 from the top-left."""
    if not LAST_VIEW:
        raise ValueError("Take a get_viewport_screenshot first")
    inv = (Matrix(LAST_VIEW["window_matrix"]) @ Matrix(LAST_VIEW["view_matrix"])).inverted()
    nx, ny = 2 * x - 1, 1 - 2 * y

    def unproject(z):
        p = inv @ Vector((nx, ny, z, 1.0))
        return p.xyz / p.w

    origin = unproject(-1.0)
    direction = (unproject(1.0) - origin).normalized()
    result = find_ray_hit(list(origin), list(direction))
    if not result["hit"]:
        # Lights, cameras and empties have no surface: pick the nearest origin on screen.
        proj = Matrix(LAST_VIEW["window_matrix"]) @ Matrix(LAST_VIEW["view_matrix"])
        best = None
        for obj in bpy.context.scene.objects:
            if obj.type not in ("LIGHT", "CAMERA", "EMPTY") or not obj.visible_get():
                continue
            p = proj @ obj.matrix_world.translation.to_4d()
            if p.w <= 0:
                continue
            sx, sy = (p.x / p.w + 1) / 2, (1 - p.y / p.w) / 2
            d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
            if d < 0.03 and (best is None or d < best[0]):
                best = (d, obj.name)
        if best:
            result = {"hit": True, "object": best[1], "note": "nearest light/camera/empty on screen"}
    return result


def _signature():
    bpy.context.view_layer.update()
    sig = {}
    for obj in bpy.context.scene.objects:
        entry = {
            "type": obj.type,
            "transform": [round(v, 5) for v in (*obj.location, *obj.rotation_euler, *obj.scale)],
            "matrix": [round(v, 5) for row in obj.matrix_world for v in row],
            "parent": obj.parent.name if obj.parent else None,
            "hidden": obj.hide_get(),
            "materials": [s.material.name if s.material else None for s in obj.material_slots],
            "modifiers": [f"{m.name}:{m.type}:{m.show_viewport}" for m in obj.modifiers],
        }
        if obj.type == "MESH":
            me = obj.data
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get("co", co)
            entry["mesh"] = hashlib.sha1(co.round(5).tobytes() + str(len(me.polygons)).encode()).hexdigest()[:16]
        elif obj.type == "LIGHT":
            entry["light"] = [obj.data.type, round(obj.data.energy, 4), *[round(c, 4) for c in obj.data.color]]
        elif obj.type == "CAMERA":
            entry["camera"] = [obj.data.type, round(obj.data.lens, 4), round(obj.data.ortho_scale, 4)]
        sig[obj.name] = entry
    for mat in bpy.data.materials:
        if mat.node_tree:
            values = []
            for node in mat.node_tree.nodes:
                for inp in node.inputs:
                    v = getattr(inp, "default_value", None)
                    try:
                        values.append(str([round(x, 4) for x in v]) if hasattr(v, "__len__") else str(v))
                    except TypeError:
                        values.append(str(v))
            values.append(str(len(mat.node_tree.links)))
            sig[f"material:{mat.name}"] = {"type": "MATERIAL", "values": hashlib.sha1("|".join(values).encode()).hexdigest()[:16]}
    return sig


def snapshot_scene(name: str = "default") -> dict:
    """Remember the scene state (transforms, mesh data, materials, lights...) to diff later."""
    _snapshots[name] = _signature()
    return {"snapshot": name, "items": len(_snapshots[name])}


def diff_scene(name: str = "default") -> dict:
    """What changed since snapshot_scene(name): added, removed and changed items (with fields)."""
    if name not in _snapshots:
        raise ValueError(f"No snapshot named '{name}'. Call snapshot_scene first.")
    old, new = _snapshots[name], _signature()
    changed = {}
    for key in old.keys() & new.keys():
        fields = [f for f in new[key] if old[key].get(f) != new[key].get(f)]
        if fields:
            changed[key] = fields
    return {"snapshot": name, "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": changed, "unchanged": len(old.keys() & new.keys()) - len(changed)}


def _mask_bbox(mask):
    rows, cols = np.any(mask, axis=1), np.any(mask, axis=0)
    if not rows.any():
        return None
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return r0, r1 + 1, c0, c1 + 1


def _resample(mask, size):
    """Nearest-neighbour resample of a cropped mask into a size x size box, aspect kept, centred."""
    h, w = mask.shape
    scale = size / max(h, w)
    nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
    ys = np.minimum((np.arange(nh) / scale).astype(int), h - 1)
    xs = np.minimum((np.arange(nw) / scale).astype(int), w - 1)
    out = np.zeros((size, size), bool)
    y0, x0 = (size - nh) // 2, (size - nw) // 2
    out[y0:y0 + nh, x0:x0 + nw] = mask[ys][:, xs]
    return out


def _render_mask(objects, view, size):
    """Orthographic silhouette of the objects (top row first), by ray casting - no GPU needed."""
    directions = {"front": (0, 1, 0), "back": (0, -1, 0), "left": (1, 0, 0), "right": (-1, 0, 0),
                  "top": (0, 0, -1), "bottom": (0, 0, 1)}
    if view not in directions:
        raise ValueError(f"view must be one of {', '.join(directions)}")
    dg = bpy.context.evaluated_depsgraph_get()
    verts, tris = [], []
    for obj in objects:
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            base = len(verts)
            verts.extend(ev.matrix_world @ v.co for v in me.vertices)
            tris.extend(tuple(base + i for i in t.vertices) for t in me.loop_triangles)
        finally:
            ev.to_mesh_clear()
    if not tris:
        raise ValueError("The objects have no surface")
    tree = BVHTree.FromPolygons(verts, tris, all_triangles=True)
    forward = Vector(directions[view])
    up = Vector((0, 1, 0)) if view in ("top", "bottom") else Vector((0, 0, 1))
    right = forward.cross(up).normalized()
    pts = np.array(verts, dtype=np.float64)
    r_axis, u_axis = np.array(right), np.array(up)
    xs, ys, depth = pts @ r_axis, pts @ u_axis, pts @ np.array(forward)
    span = max(xs.max() - xs.min(), ys.max() - ys.min(), 1e-9) * 1.04
    cx, cy = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
    start = depth.min() - span
    mask = np.zeros((size, size), bool)
    for row in range(size):
        v = cy + (0.5 - (row + 0.5) / size) * span
        for col in range(size):
            u = cx + ((col + 0.5) / size - 0.5) * span
            origin = right * u + up * v + forward * start
            if tree.ray_cast(origin, forward)[0] is not None:
                mask[row, col] = True
    return mask


def _image_mask(filepath, threshold):
    img = bpy.data.images.load(filepath)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    px = px.reshape(h, w, 4)[::-1]
    alpha = px[..., 3]
    if alpha.min() < 0.99:
        return alpha > threshold
    luminance = px[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return luminance < threshold  # dark shape on a light background


def compare_silhouette(objects: list, reference_image: str, view: str = "front", size: int = 256,
                       threshold: float = 0.5) -> dict:
    """How well does the model's outline match a 2D reference (drawing/photo with alpha or dark-on-light)?

    Renders the objects' silhouette from an orthographic view, fits both outlines to the same box
    (position and scale ignored, aspect kept) and returns IoU (1.0 = identical) plus an overlay
    image: gray = both, blue = model only, red = reference only.
    """
    if not os.path.isfile(reference_image):
        raise ValueError(f"File not found: {reference_image}")
    objs = [get_object(n) for n in objects]
    model = _render_mask(objs, view.lower(), max(64, min(int(size), 1024)))
    ref = _image_mask(reference_image, threshold)
    boxes = [_mask_bbox(model), _mask_bbox(ref)]
    if boxes[0] is None:
        raise ValueError("The model rendered empty from this view")
    if boxes[1] is None:
        raise ValueError("No shape found in the reference image (adjust threshold)")
    grid = 256
    m = _resample(model[boxes[0][0]:boxes[0][1], boxes[0][2]:boxes[0][3]], grid)
    r = _resample(ref[boxes[1][0]:boxes[1][1], boxes[1][2]:boxes[1][3]], grid)
    inter, union = np.logical_and(m, r).sum(), np.logical_or(m, r).sum()
    overlay = np.ones((grid, grid, 4), np.float32)
    overlay[m & r, :3] = (0.55, 0.55, 0.55)
    overlay[m & ~r, :3] = (0.2, 0.45, 1.0)
    overlay[~m & r, :3] = (1.0, 0.25, 0.2)
    img = bpy.data.images.new("_mcp_overlay", grid, grid, alpha=True)
    path = os.path.join(tempfile.gettempdir(), "blender_mcp_overlay.png")
    try:
        img.pixels.foreach_set(overlay[::-1].ravel())
        img.filepath_raw = path
        img.file_format = "PNG"
        img.save()
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
    finally:
        bpy.data.images.remove(img)
        if os.path.exists(path):
            os.remove(path)
    hm, wm = boxes[0][1] - boxes[0][0], boxes[0][3] - boxes[0][2]
    hr, wr = boxes[1][1] - boxes[1][0], boxes[1][3] - boxes[1][2]
    return {"iou": round(float(inter) / max(float(union), 1.0), 4), "view": view,
            "model_aspect": round(wm / hm, 4), "reference_aspect": round(wr / hr, 4),
            "model_only_fraction": round(float((m & ~r).sum()) / max(float(union), 1.0), 4),
            "reference_only_fraction": round(float((~m & r).sum()) / max(float(union), 1.0), 4),
            "image_base64": b64, "format": "png"}


register_handler("measure_distance", measure_distance)
register_handler("find_ray_hit", find_ray_hit)
register_handler("find_object_at", find_object_at)
register_handler("snapshot_scene", snapshot_scene)
register_handler("diff_scene", diff_scene)
register_handler("compare_silhouette", compare_silhouette)
