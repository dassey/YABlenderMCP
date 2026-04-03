"""Animation and timeline MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def set_keyframe(object_name: str, property: str, frame: int = -1,
                     value: Optional[str] = None) -> str:
        """Insert a keyframe on an object property.

        Property is a data path like "location", "rotation_euler", "scale".
        If frame is -1, uses the current frame. Value is an optional JSON
        value to set before keying (e.g. "[1, 2, 3]" for location).
        """
        conn = get_connection()
        params = {"object_name": object_name, "property": property, "frame": frame}
        if value is not None:
            params["value"] = json.loads(value)
        result = conn.send_command("set_keyframe", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def delete_keyframe(object_name: str, property: str, frame: int = -1) -> str:
        """Delete a keyframe from an object property.

        If frame is -1, deletes the keyframe at the current frame.
        """
        conn = get_connection()
        result = conn.send_command("delete_keyframe", {
            "object_name": object_name,
            "property": property,
            "frame": frame,
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_frame(frame: int) -> str:
        """Set the current frame in the timeline."""
        conn = get_connection()
        result = conn.send_command("set_frame", {"frame": frame})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_timeline_info() -> str:
        """Get timeline information.

        Returns frame start, frame end, current frame, and FPS.
        """
        conn = get_connection()
        result = conn.send_command("get_timeline_info", {})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_timeline(frame_start: int = -1, frame_end: int = -1, fps: int = -1) -> str:
        """Set timeline properties.

        Only non-negative values are applied. Set frame_start and frame_end
        to define the playback range. Set fps to change the frame rate.
        """
        conn = get_connection()
        result = conn.send_command("set_timeline", {
            "frame_start": frame_start,
            "frame_end": frame_end,
            "fps": fps,
        })
        return json.dumps(result, indent=2)
