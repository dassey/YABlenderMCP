"""Viewport MCP tools - screenshot, shading, view control."""

import json

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def get_viewport_screenshot(max_size: int = 800) -> str:
        """Capture a screenshot of the Blender 3D viewport.

        Returns a base64-encoded PNG image. The max_size parameter
        limits the largest dimension in pixels (default 800).
        """
        conn = get_connection()
        result = conn.send_command("get_viewport_screenshot", {"max_size": max_size})
        w = result.get("width", 0)
        h = result.get("height", 0)
        b64 = result.get("image_base64", "")
        fmt = result.get("format", "png")
        return f"Screenshot captured ({w}x{h}). Base64 PNG:\ndata:image/{fmt};base64,{b64}"

    @mcp.tool()
    def set_viewport_shading(mode: str) -> str:
        """Set the viewport shading mode.

        Valid modes: WIREFRAME, SOLID, MATERIAL, RENDERED.
        """
        conn = get_connection()
        result = conn.send_command("set_viewport_shading", {"mode": mode})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_view(angle: str) -> str:
        """Set the 3D viewport camera angle.

        Valid angles: FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, CAMERA.
        """
        conn = get_connection()
        result = conn.send_command("set_view", {"angle": angle})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def frame_selected() -> str:
        """Frame the currently selected objects in the viewport.

        Adjusts the view to center and zoom on the selection.
        """
        conn = get_connection()
        result = conn.send_command("frame_selected", {})
        return json.dumps(result, indent=2)
