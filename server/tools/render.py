"""Render MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def get_render_settings() -> str:
        """Get current render settings.

        Returns engine, resolution, film transparency, output path,
        file format, and sample count.
        """
        conn = get_connection()
        result = conn.send_command("get_render_settings", {})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_render_settings(engine: str = "", resolution_x: int = 0,
                            resolution_y: int = 0, resolution_percentage: int = 0,
                            film_transparent: Optional[bool] = None,
                            output_path: str = "", file_format: str = "",
                            samples: int = 0) -> str:
        """Set render settings. Only non-empty/non-zero values are applied.

        Engine: "CYCLES", "BLENDER_EEVEE_NEXT", "BLENDER_WORKBENCH".
        File format: "PNG", "JPEG", "BMP", "OPEN_EXR", etc.
        Samples sets the render sample count for the current engine.
        """
        conn = get_connection()
        params = {
            "engine": engine,
            "resolution_x": resolution_x,
            "resolution_y": resolution_y,
            "resolution_percentage": resolution_percentage,
            "output_path": output_path,
            "file_format": file_format,
            "samples": samples,
        }
        if film_transparent is not None:
            params["film_transparent"] = film_transparent
        result = conn.send_command("set_render_settings", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def render_frame(frame: int = -1, output_path: str = "") -> str:
        """Render a single frame.

        If frame is -1, renders the current frame. If output_path is set,
        saves the render there. Returns the rendered image as base64 if
        the output file exists.
        """
        conn = get_connection()
        result = conn.send_command("render_frame", {"frame": frame, "output_path": output_path})

        b64 = result.pop("image_base64", None)
        summary = json.dumps(result, indent=2)
        if b64:
            summary += f"\n\ndata:image/png;base64,{b64}"
        return summary

    @mcp.tool()
    def render_animation(start: int = -1, end: int = -1, output_path: str = "") -> str:
        """Render an animation sequence.

        If start/end are -1, uses the scene's current frame range.
        Output path should include a frame number placeholder (e.g. "//render_####").
        """
        conn = get_connection()
        result = conn.send_command("render_animation", {
            "start": start,
            "end": end,
            "output_path": output_path,
        })
        return json.dumps(result, indent=2)
