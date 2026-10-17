"""Lights, cameras, world and camera framing handlers."""

import math
import os

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from . import register_handler
from .common import get_object, rounded, world_bbox

_GEOMETRY_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME", "GREASEPENCIL"}
_DEFAULT_ENERGY = {"POINT": 1000.0, "SPOT": 1000.0, "AREA": 500.0, "SUN": 3.0}


def _scene_targets(names=None):
    if names:
        return [get_object(n) for n in names]
    return [o for o in bpy.context.scene.objects if o.type in _GEOMETRY_TYPES and o.visible_get()]


def _bounds(objs):
    if not objs:
        return Vector((0, 0, 0)), 1.0
    lo, hi = world_bbox(objs)
    return (lo + hi) / 2, max((hi - lo).length / 2, 0.01)


def _point(target):
    """An object name (its bounding-box centre) or an [x, y, z] list."""
    if isinstance(target, str):
        obj = get_object(target)
        if obj.type in ("EMPTY", "LIGHT", "CAMERA"):
            return obj.matrix_world.translation.copy()
        return _bounds([obj])[0]
    return Vector(target)


def _aim(obj, point):
    direction = point - obj.matrix_world.translation
    if direction.length > 1e-9:
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _link(obj):
    bpy.context.collection.objects.link(obj)


def create_light(type: str = "AREA", name: str = "", location=None, energy: float = 0.0, color=None,
                 size: float = 0.0, look_at=None, spot_size_degrees: float = 0.0, shape: str = "") -> dict:
    """Create a light. Lights aim at look_at (object name or point), else at the scene centre."""
    kind = type.upper()
    if kind not in _DEFAULT_ENERGY:
        raise ValueError("type must be POINT, SUN, SPOT or AREA")
    data = bpy.data.lights.new(name or kind.title(), kind)
    if color is not None:
        data.color = color[:3]
    if size > 0:
        if kind == "AREA":
            data.size = size
        elif kind == "SUN":
            data.angle = math.radians(size)
        else:
            data.shadow_soft_size = size
    if kind == "AREA" and shape:
        data.shape = shape.upper()
    if kind == "SPOT" and spot_size_degrees > 0:
        data.spot_size = math.radians(spot_size_degrees)
    obj = bpy.data.objects.new(name or kind.title(), data)
    _link(obj)
    center, radius = _bounds(_scene_targets())
    obj.location = location if location is not None else center + Vector((radius * 2.5, -radius * 2.5, radius * 3))
    bpy.context.view_layer.update()
    aim_point = _point(look_at) if look_at is not None else center
    if kind != "POINT":
        _aim(obj, aim_point)
    if energy > 0:
        data.energy = energy
    elif kind == "SUN":
        data.energy = _DEFAULT_ENERGY[kind]
    else:
        # Same exposure at any scene scale: power grows with distance squared (in meters).
        dist_m = (obj.location - aim_point).length * bpy.context.scene.unit_settings.scale_length
        data.energy = max(0.1, round(_DEFAULT_ENERGY[kind] / 16.0 * dist_m * dist_m, 3))
    return {"name": obj.name, "type": kind, "energy": data.energy, "location": rounded(obj.location),
            "rotation_euler": rounded(obj.rotation_euler)}


def create_camera(name: str = "Camera", location=None, look_at=None, lens: float = 50.0,
                  type: str = "PERSP", ortho_scale: float = 0.0, set_active: bool = True) -> dict:
    """Create a camera aimed at look_at (object name or point), else at the scene centre."""
    data = bpy.data.cameras.new(name)
    data.type = type.upper()
    data.lens = lens
    if ortho_scale > 0:
        data.ortho_scale = ortho_scale
    obj = bpy.data.objects.new(name, data)
    _link(obj)
    center, radius = _bounds(_scene_targets())
    obj.location = location if location is not None else center + Vector((radius * 3, -radius * 3, radius * 2))
    bpy.context.view_layer.update()
    _aim(obj, _point(look_at) if look_at is not None else center)
    data.clip_end = max(data.clip_end, (obj.location - center).length + radius * 4)
    if set_active or bpy.context.scene.camera is None:
        bpy.context.scene.camera = obj
    return {"name": obj.name, "location": rounded(obj.location), "rotation_euler": rounded(obj.rotation_euler),
            "active": bpy.context.scene.camera == obj}


def set_active_camera(name: str) -> dict:
    obj = get_object(name)
    if obj.type != "CAMERA":
        raise ValueError(f"'{name}' is a {obj.type}, not a camera")
    bpy.context.scene.camera = obj
    return {"active_camera": obj.name}


def point_at(name: str, target, use_constraint: bool = False) -> dict:
    """Aim a camera/light (its -Z axis) at an object or point; optionally keep tracking it."""
    obj = get_object(name)
    if use_constraint:
        for c in [c for c in obj.constraints if c.type in ("TRACK_TO", "DAMPED_TRACK")]:
            obj.constraints.remove(c)
        con = obj.constraints.new("TRACK_TO")
        if isinstance(target, str):
            con.target = get_object(target)
        else:
            empty = bpy.data.objects.new(f"{obj.name}_Target", None)
            empty.location = target
            _link(empty)
            con.target = empty
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"
        return {"name": obj.name, "constraint": con.name, "target": con.target.name}
    _aim(obj, _point(target))
    return {"name": obj.name, "rotation_euler": rounded(obj.rotation_euler)}


def frame_camera(camera: str = "", objects: list = None, fill: float = 0.85, view: str = "") -> dict:
    """Move/zoom a camera so the objects fill `fill` of the frame (measured, not guessed).

    view: optionally re-aim first from front, back, left, right, top or iso.
    """
    scene = bpy.context.scene
    cam = get_object(camera) if camera else scene.camera
    if cam is None or cam.type != "CAMERA":
        raise ValueError("No camera given and the scene has no active camera")
    targets = _scene_targets(objects)
    if not targets:
        raise ValueError("Nothing to frame")
    center, radius = _bounds(targets)
    corners = []
    for o in targets:
        corners.extend(o.matrix_world @ Vector(c) for c in o.bound_box)

    directions = {"front": (0, -1, 0), "back": (0, 1, 0), "left": (-1, 0, 0), "right": (1, 0, 0),
                  "top": (0, -0.001, 1), "iso": (1, -1, 0.8)}
    if view:
        if view.lower() not in directions:
            raise ValueError(f"view must be one of {', '.join(directions)}")
        cam.location = center + Vector(directions[view.lower()]).normalized() * radius * 4
    bpy.context.view_layer.update()
    _aim(cam, center)
    bpy.context.view_layer.update()

    data = cam.data
    render = scene.render
    aspect = (render.resolution_x * render.pixel_aspect_x) / max(1, render.resolution_y * render.pixel_aspect_y)
    fill = max(0.1, min(fill, 1.0))
    if data.type == "ORTHO":
        inv = cam.matrix_world.inverted()
        pts = [inv @ p for p in corners]
        w = max(p.x for p in pts) - min(p.x for p in pts)
        h = max(p.y for p in pts) - min(p.y for p in pts)
        data.ortho_scale = max(w, h * aspect) / fill if aspect >= 1 else max(h, w / aspect) / fill
    else:
        for _ in range(6):
            bpy.context.view_layer.update()
            ndc = [world_to_camera_view(scene, cam, p) for p in corners]
            xs, ys = [c.x for c in ndc], [c.y for c in ndc]
            extent = max(max(xs) - min(xs), max(ys) - min(ys))
            if extent <= 0:
                break
            offset = cam.location - center
            cam.location = center + offset * (extent / fill)
            if abs(extent - fill) < 0.01:
                break
    dist = (cam.location - center).length
    data.clip_start = min(data.clip_start, max(0.0001, (dist - radius * 1.5) * 0.5))
    data.clip_end = max(data.clip_end, dist + radius * 4)
    bpy.context.view_layer.update()
    ndc = [world_to_camera_view(scene, cam, p) for p in corners]
    clipped = any(not (0 <= c.x <= 1 and 0 <= c.y <= 1) or c.z <= 0 for c in ndc)
    achieved = max(max(c.x for c in ndc) - min(c.x for c in ndc), max(c.y for c in ndc) - min(c.y for c in ndc))
    return {"camera": cam.name, "location": rounded(cam.location), "rotation_euler": rounded(cam.rotation_euler),
            "fill": round(achieved, 3), "clipped": clipped,
            "ortho_scale": round(data.ortho_scale, 4) if data.type == "ORTHO" else None}


_RIGS = {
    # (name, type, direction from target, energy factor, size factor)
    "three_point": [("Key", "AREA", (1.0, -1.0, 0.9), 60, 0.8), ("Fill", "AREA", (-1.2, -0.6, 0.4), 22, 1.2),
                    ("Rim", "AREA", (-0.2, 1.2, 1.0), 80, 0.6)],
    "studio": [("Top", "AREA", (0, -0.3, 1.2), 70, 2.0), ("Left", "AREA", (-1.2, -0.6, 0.5), 30, 1.5),
               ("Right", "AREA", (1.2, -0.6, 0.5), 30, 1.5)],
    "rim": [("RimLeft", "AREA", (-1.0, 1.0, 0.6), 90, 0.6), ("RimRight", "AREA", (1.0, 1.0, 0.6), 90, 0.6)],
    "outdoor": [("Sun", "SUN", (0.6, -0.4, 1.0), 0, 0)],
}


def create_light_rig(preset: str = "three_point", objects: list = None, intensity: float = 1.0) -> dict:
    """Add a lighting setup sized to the targets: three_point, studio, rim or outdoor."""
    key = preset.lower()
    if key not in _RIGS:
        raise ValueError(f"preset must be one of {', '.join(_RIGS)}")
    center, radius = _bounds(_scene_targets(objects))
    collection = bpy.data.collections.get("MCP Lights") or bpy.data.collections.new("MCP Lights")
    if collection.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(collection)
    created = []
    meters = bpy.context.scene.unit_settings.scale_length
    for label, kind, direction, energy, size in _RIGS[key]:
        dist = radius * 4
        dist_m = dist * meters
        data = bpy.data.lights.new(f"{key}_{label}", kind)
        if kind == "SUN":
            data.energy = 3.0 * intensity
            data.angle = math.radians(2)
        else:
            data.energy = energy * dist_m * dist_m * intensity
            data.size = max(radius * size * 2, 0.01)
        obj = bpy.data.objects.new(f"{key}_{label}", data)
        collection.objects.link(obj)
        obj.location = center + Vector(direction).normalized() * dist
        bpy.context.view_layer.update()
        _aim(obj, center)
        created.append({"name": obj.name, "type": kind, "energy": round(data.energy, 2)})
    if key == "outdoor":
        set_world(color=[0.45, 0.6, 0.85], strength=1.0)
    return {"preset": key, "collection": collection.name, "lights": created}


def set_world(color=None, strength: float = 1.0, hdri_path: str = "", rotation_degrees: float = 0.0) -> dict:
    """Set the world background to a colour, or to a local HDRI/EXR file."""
    scene = bpy.context.scene
    if hdri_path:
        if not os.path.isfile(hdri_path):
            raise ValueError(f"File not found: {hdri_path}")
        world = bpy.data.worlds.new("HDRI World")
        if world.node_tree is None:
            world.use_nodes = True
        nodes, links = world.node_tree.nodes, world.node_tree.links
        nodes.clear()
        coord = nodes.new("ShaderNodeTexCoord")
        mapping = nodes.new("ShaderNodeMapping")
        env = nodes.new("ShaderNodeTexEnvironment")
        background = nodes.new("ShaderNodeBackground")
        output = nodes.new("ShaderNodeOutputWorld")
        for i, n in enumerate((coord, mapping, env, background, output)):
            n.location = (-900 + i * 250, 0)
        env.image = bpy.data.images.load(hdri_path, check_existing=True)
        mapping.inputs["Rotation"].default_value[2] = math.radians(rotation_degrees)
        background.inputs["Strength"].default_value = strength
        links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
        links.new(mapping.outputs["Vector"], env.inputs["Vector"])
        links.new(env.outputs["Color"], background.inputs["Color"])
        links.new(background.outputs["Background"], output.inputs["Surface"])
        scene.world = world
        return {"world": world.name, "hdri": env.image.name, "strength": strength}

    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    if world.node_tree is None:
        world.use_nodes = True
    background = next((n for n in world.node_tree.nodes if n.type == "BACKGROUND"), None)
    if background is None:
        background = world.node_tree.nodes.new("ShaderNodeBackground")
        output = next((n for n in world.node_tree.nodes if n.type == "OUTPUT_WORLD"), None) \
            or world.node_tree.nodes.new("ShaderNodeOutputWorld")
        world.node_tree.links.new(background.outputs["Background"], output.inputs["Surface"])
    if color is not None:
        background.inputs["Color"].default_value = (*color[:3], 1.0)
    background.inputs["Strength"].default_value = strength
    world.color = background.inputs["Color"].default_value[:3]
    return {"world": world.name, "color": rounded(background.inputs["Color"].default_value[:3]),
            "strength": strength}


register_handler("create_light", create_light)
register_handler("create_camera", create_camera)
register_handler("set_active_camera", set_active_camera)
register_handler("point_at", point_at)
register_handler("frame_camera", frame_camera)
register_handler("create_light_rig", create_light_rig)
register_handler("set_world", set_world)
