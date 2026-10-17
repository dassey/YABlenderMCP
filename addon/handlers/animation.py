"""Animation, constraint and timeline handlers."""

import math

import bpy
from mathutils import Vector

from . import register_handler
from .common import get_object, rounded, world_bbox


def _resolve(obj, path):
    """'location' -> (obj, 'location'); 'data.energy' -> (obj.data, 'energy')."""
    owner_path, _, prop = path.rpartition(".")
    owner = obj.path_resolve(owner_path) if owner_path else obj
    return owner, prop


def _fcurves(id_block):
    """F-curves of an ID's action; Blender 5 keeps them in slotted-action channelbags."""
    ad = getattr(id_block, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    action = ad.action
    if hasattr(action, "fcurves"):
        return list(action.fcurves)
    from bpy_extras import anim_utils
    bag = anim_utils.action_get_channelbag_for_slot(action, ad.action_slot)
    return list(bag.fcurves) if bag else []


def set_keyframe(object_name: str, property: str, frame: int = -1, value=None, index: int = -1,
                 interpolation: str = "") -> dict:
    """Insert a keyframe on an object property (or a nested one like "data.energy")."""
    obj = get_object(object_name)

    scene = bpy.context.scene
    if frame >= 0:
        scene.frame_set(frame)

    owner, prop = _resolve(obj, property)
    if value is not None:
        if isinstance(value, list):
            value = tuple(value)
        if index >= 0:
            getattr(owner, prop)[index] = value
        else:
            setattr(owner, prop, value)

    owner.keyframe_insert(data_path=prop, index=index, frame=scene.frame_current)
    if interpolation:
        for fc in _fcurves(owner):
            if fc.data_path == prop and (index < 0 or fc.array_index == index):
                for kp in fc.keyframe_points:
                    if abs(kp.co.x - scene.frame_current) < 0.5:
                        kp.interpolation = interpolation.upper()
    return {"object": obj.name, "property": property, "frame": scene.frame_current}


def delete_keyframe(object_name: str, property: str, frame: int = -1) -> dict:
    """Delete a keyframe from an object property."""
    obj = get_object(object_name)

    scene = bpy.context.scene
    if frame >= 0:
        scene.frame_set(frame)

    owner, prop = _resolve(obj, property)
    owner.keyframe_delete(data_path=prop, frame=scene.frame_current)
    return {"object": obj.name, "property": property, "frame": scene.frame_current, "deleted": True}


def set_frame(frame: int) -> dict:
    """Set the current frame."""
    bpy.context.scene.frame_set(frame)
    return {"frame": bpy.context.scene.frame_current}


def get_timeline_info() -> dict:
    """Get timeline information."""
    scene = bpy.context.scene
    return {
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "fps": scene.render.fps,
    }


def set_timeline(frame_start: int = -1, frame_end: int = -1, fps: int = -1) -> dict:
    """Set timeline properties."""
    scene = bpy.context.scene
    if frame_start >= 0:
        scene.frame_start = frame_start
    if frame_end >= 0:
        scene.frame_end = frame_end
    if fps > 0:
        scene.render.fps = fps

    return {
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "fps": scene.render.fps,
    }


def get_animation_info(object_name: str) -> dict:
    """Keyframed channels of an object (and its data): data path, index, key frames, interpolation."""
    obj = get_object(object_name)
    channels = []
    for label, block in (("object", obj), ("data", obj.data)):
        if block is None:
            continue
        for fc in _fcurves(block):
            frames = [round(kp.co.x, 2) for kp in fc.keyframe_points]
            channels.append({
                "on": label,
                "data_path": fc.data_path,
                "index": fc.array_index,
                "keyframes": len(frames),
                "frames": frames[:50],
                "interpolation": sorted({kp.interpolation for kp in fc.keyframe_points}),
            })
    ad = obj.animation_data
    return {
        "object": obj.name,
        "action": ad.action.name if ad and ad.action else None,
        "channels": channels,
        "constraints": [{"name": c.name, "type": c.type} for c in obj.constraints],
    }


def set_interpolation(object_name: str, interpolation: str = "LINEAR", data_path: str = "") -> dict:
    """Set keyframe interpolation (CONSTANT, LINEAR, BEZIER, SINE, EXPO, BOUNCE, ELASTIC...)."""
    obj = get_object(object_name)
    changed = 0
    for block in (obj, obj.data):
        for fc in _fcurves(block) if block is not None else []:
            if data_path and fc.data_path != data_path:
                continue
            for kp in fc.keyframe_points:
                kp.interpolation = interpolation.upper()
                changed += 1
    return {"object": obj.name, "interpolation": interpolation.upper(), "keyframes_changed": changed}


def clear_animation(object_name: str) -> dict:
    """Remove all keyframes (the action) from an object and its data."""
    obj = get_object(object_name)
    cleared = []
    for block in (obj, obj.data):
        if block is not None and getattr(block, "animation_data", None):
            block.animation_data_clear()
            cleared.append(block.name)
    return {"cleared": cleared}


def add_constraint(object_name: str, type: str, target: str = "", name: str = "", settings: dict = None) -> dict:
    """Add a constraint (TRACK_TO, DAMPED_TRACK, COPY_LOCATION, COPY_ROTATION, CHILD_OF, LIMIT_ROTATION,
    LIMIT_LOCATION, FOLLOW_PATH, FLOOR, PIVOT, ...). settings: constraint properties."""
    obj = get_object(object_name)
    try:
        con = obj.constraints.new(type.upper())
    except TypeError:
        valid = [i.identifier for i in bpy.types.Constraint.bl_rna.properties["type"].enum_items]
        raise ValueError(f"Unknown constraint type '{type}'. Valid: {', '.join(valid)}")
    if name:
        con.name = name
    if target:
        con.target = get_object(target)
    if con.type in ("TRACK_TO",) and not (settings or {}).get("track_axis"):
        con.track_axis = "TRACK_NEGATIVE_Z"
        con.up_axis = "UP_Y"
    for key, value in (settings or {}).items():
        setattr(con, key, value)
    return {"object": obj.name, "constraint": con.name, "type": con.type,
            "target": con.target.name if getattr(con, "target", None) else None}


def remove_constraint(object_name: str, constraint_name: str) -> dict:
    obj = get_object(object_name)
    con = obj.constraints.get(constraint_name)
    if con is None:
        raise ValueError(f"Constraint '{constraint_name}' not found on '{object_name}'. "
                         f"Existing: {[c.name for c in obj.constraints]}")
    obj.constraints.remove(con)
    return {"object": obj.name, "removed": constraint_name}


def create_turntable(objects: list = None, frames: int = 120, elevation_degrees: float = 20.0,
                     distance_factor: float = 2.5, lens: float = 50.0) -> dict:
    """Camera orbiting the objects once over `frames` frames (linear), aimed at their centre."""
    scene = bpy.context.scene
    targets = [get_object(n) for n in objects] if objects else \
        [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
    if not targets:
        raise ValueError("Nothing to orbit")
    lo, hi = world_bbox(targets)
    center, radius = (lo + hi) / 2, max((hi - lo).length / 2, 1e-4)

    pivot = bpy.data.objects.new("Turntable_Pivot", None)
    pivot.location = center
    aim = bpy.data.objects.new("Turntable_Target", None)
    aim.location = center
    cam_data = bpy.data.cameras.new("Turntable_Camera")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Turntable_Camera", cam_data)
    for o in (pivot, aim, cam):
        bpy.context.collection.objects.link(o)
    distance = radius * distance_factor * lens / 50.0
    elev = math.radians(elevation_degrees)
    cam.parent = pivot
    cam.location = Vector((0, -distance * math.cos(elev), distance * math.sin(elev)))
    cam_data.clip_start = min(cam_data.clip_start, distance * 0.01)
    cam_data.clip_end = max(cam_data.clip_end, distance * 4)
    track = cam.constraints.new("TRACK_TO")
    track.target = aim
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    start = scene.frame_start
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", index=2, frame=start)
    pivot.rotation_euler = (0, 0, math.tau)
    pivot.keyframe_insert("rotation_euler", index=2, frame=start + frames)
    for fc in _fcurves(pivot):
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
    scene.frame_end = start + frames - 1  # last frame differs from the first, so the loop is seamless
    scene.camera = cam
    return {"camera": cam.name, "pivot": pivot.name, "target": aim.name, "frames": [start, scene.frame_end],
            "center": rounded(center), "distance": round(distance, 4)}


register_handler("set_keyframe", set_keyframe)
register_handler("delete_keyframe", delete_keyframe)
register_handler("set_frame", set_frame)
register_handler("get_timeline_info", get_timeline_info)
register_handler("set_timeline", set_timeline)
register_handler("get_animation_info", get_animation_info)
register_handler("set_interpolation", set_interpolation)
register_handler("clear_animation", clear_animation)
register_handler("add_constraint", add_constraint)
register_handler("remove_constraint", remove_constraint)
register_handler("create_turntable", create_turntable)
