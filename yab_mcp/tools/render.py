"""Render MCP tools."""

import base64
import json
from typing import Optional

from ..compat import EDIT, READ, FastMCP, Image
from ..connection import get_connection, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_render_settings() -> str:
        """Get current render settings.

        Returns engine, resolution, film transparency, output path, file format,
        samples, Cycles device and denoising, frame range, fps, camera, view transform.
        """
        return send("get_render_settings")

    @mcp.tool(annotations=EDIT)
    def set_render_settings(engine: str = "", resolution_x: int = 0,
                            resolution_y: int = 0, resolution_percentage: int = 0,
                            film_transparent: Optional[bool] = None,
                            output_path: str = "", file_format: str = "",
                            samples: int = 0, denoise: Optional[bool] = None, view_transform: str = "") -> str:
        """Set render settings. Only non-empty/non-zero values are applied.

        Engine: "CYCLES", "EEVEE" (BLENDER_EEVEE), "WORKBENCH".
        File format: "PNG", "JPEG", "OPEN_EXR", "FFMPEG" (video), etc.
        Samples sets the render sample count for the current engine.
        view_transform: "AgX", "Standard", "Filmic"... Other settings: set_properties("scene", ...).
        """
        return send("set_render_settings", params_of(engine=engine, resolution_x=resolution_x,
                                                     resolution_y=resolution_y,
                                                     resolution_percentage=resolution_percentage,
                                                     film_transparent=film_transparent, output_path=output_path,
                                                     file_format=file_format, samples=samples, denoise=denoise,
                                                     view_transform=view_transform))

    @mcp.tool(annotations=EDIT)
    def set_render_device(device: str = "AUTO") -> str:
        """Render Cycles on the GPU. AUTO picks OPTIX (NVIDIA RTX), then CUDA, HIP, ONEAPI, METAL;
        or name one, or CPU. Returns the devices found."""
        return send("set_render_device", {"device": device})

    @mcp.tool(annotations=EDIT)
    def render_frame(frame: int = -1, output_path: str = "", max_size: int = 1024,
                     timeout: float = 600.0) -> list:
        """Render a single frame with the scene camera and show the result.

        If frame is -1, renders the current frame. output_path keeps the file (otherwise
        a temp file is used). max_size limits the preview returned to you. Long renders:
        raise timeout, or lower samples/resolution first.
        """
        result = get_connection().send_command("render_frame", {"frame": frame, "output_path": output_path,
                                                                "max_size": max_size}, timeout=timeout)
        b64 = result.pop("image_base64", None)
        content = [json.dumps(result, ensure_ascii=False)]
        if b64:
            content.append(Image(data=base64.b64decode(b64), format="png"))
        return content

    @mcp.tool(annotations=EDIT)
    def render_animation(start: int = -1, end: int = -1, output_path: str = "", wait: bool = False) -> str:
        """Render an animation sequence.

        With Blender's UI the render runs in the background and this returns at once;
        poll get_render_status. wait=True blocks instead. If start/end are -1, uses the
        scene's frame range. output_path should include a frame placeholder (e.g. "//render_####").
        """
        return send("render_animation", params_of(start=start, end=end, output_path=output_path or None,
                                                  wait=wait), timeout=24 * 3600 if wait else None)

    @mcp.tool(annotations=READ)
    def get_render_status() -> str:
        """Progress of the background render started by render_animation (running, frames done)."""
        return send("get_render_status")
