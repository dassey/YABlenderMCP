"""Animation, constraint and timeline MCP tools."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=EDIT)
    def set_keyframe(object_name: str, property: str, frame: int = -1, value: Any = None, index: int = -1,
                     interpolation: str = "") -> str:
        """Insert a keyframe on an object property.

        Property is a data path like "location", "rotation_euler", "scale", or a nested
        one like "data.energy" (light) or "data.lens" (camera). If frame is -1, uses the
        current frame. value is set before keying (e.g. [1, 2, 3]). index keys one
        component (0=X). interpolation: CONSTANT, LINEAR, BEZIER, SINE, EXPO, BOUNCE...
        """
        return send("set_keyframe", params_of(object_name=object_name, property=property, frame=frame,
                                              value=jparse(value), index=index,
                                              interpolation=interpolation or None))

    @mcp.tool(annotations=EDIT)
    def delete_keyframe(object_name: str, property: str, frame: int = -1) -> str:
        """Delete a keyframe from an object property.

        If frame is -1, deletes the keyframe at the current frame.
        """
        return send("delete_keyframe", {
            "object_name": object_name,
            "property": property,
            "frame": frame,
        })

    @mcp.tool(annotations=EDIT)
    def set_frame(frame: int) -> str:
        """Set the current frame in the timeline."""
        return send("set_frame", {"frame": frame})

    @mcp.tool(annotations=READ)
    def get_timeline_info() -> str:
        """Get timeline information.

        Returns frame start, frame end, current frame, and FPS.
        """
        return send("get_timeline_info")

    @mcp.tool(annotations=EDIT)
    def set_timeline(frame_start: int = -1, frame_end: int = -1, fps: int = -1) -> str:
        """Set timeline properties.

        Only non-negative values are applied. Set frame_start and frame_end
        to define the playback range. Set fps to change the frame rate.
        """
        return send("set_timeline", {
            "frame_start": frame_start,
            "frame_end": frame_end,
            "fps": fps,
        })

    @mcp.tool(annotations=READ)
    def get_animation_info(object_name: str) -> str:
        """List an object's animated channels (data path, index, key frames, interpolation) and
        constraints. Works with Blender 5's slotted actions."""
        return send("get_animation_info", {"object_name": object_name})

    @mcp.tool(annotations=EDIT)
    def set_interpolation(object_name: str, interpolation: str = "LINEAR", data_path: str = "") -> str:
        """Change the interpolation of an object's keyframes (all, or one data path)."""
        return send("set_interpolation", params_of(object_name=object_name, interpolation=interpolation,
                                                   data_path=data_path or None))

    @mcp.tool(annotations=DESTRUCTIVE)
    def clear_animation(object_name: str) -> str:
        """Remove all keyframes from an object and its data."""
        return send("clear_animation", {"object_name": object_name})

    @mcp.tool(annotations=EDIT)
    def add_constraint(object_name: str, type: str, target: str = "", name: str = "",
                       settings: Optional[dict[str, Any]] = None) -> str:
        """Add a constraint: TRACK_TO, DAMPED_TRACK, COPY_LOCATION, COPY_ROTATION, COPY_SCALE,
        CHILD_OF, LIMIT_LOCATION, LIMIT_ROTATION, FOLLOW_PATH, FLOOR, PIVOT, TRANSFORMATION...
        target: object name. settings: constraint properties (e.g. {"use_limit_x": true})."""
        return send("add_constraint", params_of(object_name=object_name, type=type, target=target or None,
                                                name=name or None, settings=settings))

    @mcp.tool(annotations=DESTRUCTIVE)
    def remove_constraint(object_name: str, constraint_name: str) -> str:
        """Remove a constraint from an object."""
        return send("remove_constraint", {"object_name": object_name, "constraint_name": constraint_name})

    @mcp.tool(annotations=EDIT)
    def create_turntable(objects: Optional[list[str]] = None, frames: int = 120, elevation_degrees: float = 20.0,
                         distance_factor: float = 2.5, lens: float = 50.0) -> str:
        """Make a camera orbit the objects once (seamless loop) and set it active - for previews,
        360° renders or checking an articulated print from every side."""
        return send("create_turntable", params_of(objects=objects, frames=frames,
                                                  elevation_degrees=elevation_degrees,
                                                  distance_factor=distance_factor, lens=lens))
