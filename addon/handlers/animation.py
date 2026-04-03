"""Animation and timeline handlers."""

import bpy

from . import register_handler


def set_keyframe(object_name: str, property: str, frame: int = -1, value=None) -> dict:
    """Insert a keyframe on an object property."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    scene = bpy.context.scene
    if frame >= 0:
        scene.frame_set(frame)

    if value is not None:
        if isinstance(value, list):
            value = tuple(value)
        setattr(obj, property, value)

    obj.keyframe_insert(data_path=property, frame=scene.frame_current)
    return {"object": obj.name, "property": property, "frame": scene.frame_current}


def delete_keyframe(object_name: str, property: str, frame: int = -1) -> dict:
    """Delete a keyframe from an object property."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")

    scene = bpy.context.scene
    if frame >= 0:
        scene.frame_set(frame)

    obj.keyframe_delete(data_path=property, frame=scene.frame_current)
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


register_handler("set_keyframe", set_keyframe)
register_handler("delete_keyframe", delete_keyframe)
register_handler("set_frame", set_frame)
register_handler("get_timeline_info", get_timeline_info)
register_handler("set_timeline", set_timeline)
