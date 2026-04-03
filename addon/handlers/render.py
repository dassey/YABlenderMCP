"""Render settings and execution handlers."""

import base64
import os

import bpy

from . import register_handler


def get_render_settings() -> dict:
    """Get current render settings."""
    scene = bpy.context.scene
    render = scene.render

    result = {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "film_transparent": render.film_transparent,
        "output_path": render.filepath,
        "file_format": render.image_settings.file_format,
    }

    if render.engine == "CYCLES":
        result["samples"] = scene.cycles.samples
    elif render.engine == "BLENDER_EEVEE_NEXT":
        result["samples"] = scene.eevee.taa_render_samples

    return result


def set_render_settings(engine: str = "", resolution_x: int = 0, resolution_y: int = 0,
                        resolution_percentage: int = 0, film_transparent: bool = None,
                        output_path: str = "", file_format: str = "", samples: int = 0) -> dict:
    """Set render settings. Only non-empty/non-zero values are applied."""
    scene = bpy.context.scene
    render = scene.render

    if engine:
        render.engine = engine
    if resolution_x > 0:
        render.resolution_x = resolution_x
    if resolution_y > 0:
        render.resolution_y = resolution_y
    if resolution_percentage > 0:
        render.resolution_percentage = resolution_percentage
    if film_transparent is not None:
        render.film_transparent = film_transparent
    if output_path:
        render.filepath = output_path
    if file_format:
        render.image_settings.file_format = file_format
    if samples > 0:
        if render.engine == "CYCLES":
            scene.cycles.samples = samples
        elif render.engine == "BLENDER_EEVEE_NEXT":
            scene.eevee.taa_render_samples = samples

    return get_render_settings()


def render_frame(frame: int = -1, output_path: str = "") -> dict:
    """Render a single frame."""
    scene = bpy.context.scene

    if frame >= 0:
        scene.frame_set(frame)

    old_path = scene.render.filepath
    if output_path:
        scene.render.filepath = output_path

    bpy.ops.render.render(write_still=True)

    result_path = scene.render.filepath
    result = {
        "rendered": True,
        "frame": scene.frame_current,
        "output_path": result_path,
    }

    # Try to return base64 of the rendered image
    if os.path.isfile(bpy.path.abspath(result_path)):
        abs_path = bpy.path.abspath(result_path)
        with open(abs_path, "rb") as f:
            result["image_base64"] = base64.b64encode(f.read()).decode("utf-8")

    if output_path:
        scene.render.filepath = old_path

    return result


def render_animation(start: int = -1, end: int = -1, output_path: str = "") -> dict:
    """Render an animation sequence."""
    scene = bpy.context.scene

    if start >= 0:
        scene.frame_start = start
    if end >= 0:
        scene.frame_end = end

    old_path = scene.render.filepath
    if output_path:
        scene.render.filepath = output_path

    bpy.ops.render.render(animation=True)

    result = {
        "rendered": True,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "output_path": scene.render.filepath,
    }

    if output_path:
        scene.render.filepath = old_path

    return result


register_handler("get_render_settings", get_render_settings)
register_handler("set_render_settings", set_render_settings)
register_handler("render_frame", render_frame)
register_handler("render_animation", render_animation)
