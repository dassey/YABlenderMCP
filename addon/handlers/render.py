"""Render settings, device selection and render execution handlers."""

import base64
import os
import tempfile

import bpy

from . import register_handler

_EEVEE_IDS = ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT")
_ENGINE_ALIASES = {
    "EEVEE": _EEVEE_IDS, "BLENDER_EEVEE": _EEVEE_IDS, "BLENDER_EEVEE_NEXT": _EEVEE_IDS,
    "CYCLES": ("CYCLES",), "WORKBENCH": ("BLENDER_WORKBENCH",), "BLENDER_WORKBENCH": ("BLENDER_WORKBENCH",),
}
_render_job = {}


def _set_engine(render, engine):
    """Set the engine accepting either EEVEE id (BLENDER_EEVEE in 5.x, BLENDER_EEVEE_NEXT in 4.2-4.4)."""
    errors = []
    for candidate in _ENGINE_ALIASES.get(engine.upper(), (engine.upper(),)):
        try:
            render.engine = candidate
            return
        except TypeError as e:
            errors.append(str(e))
    raise ValueError(errors[-1])


def _is_eevee(engine):
    return engine in _EEVEE_IDS


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
        "frame_range": [scene.frame_start, scene.frame_end],
        "fps": render.fps,
        "camera": scene.camera.name if scene.camera else None,
        "view_transform": scene.view_settings.view_transform,
    }

    if render.engine == "CYCLES":
        result["samples"] = scene.cycles.samples
        result["device"] = scene.cycles.device
        result["denoise"] = scene.cycles.use_denoising
    elif _is_eevee(render.engine):
        result["samples"] = scene.eevee.taa_render_samples

    return result


def set_render_settings(engine: str = "", resolution_x: int = 0, resolution_y: int = 0,
                        resolution_percentage: int = 0, film_transparent: bool = None,
                        output_path: str = "", file_format: str = "", samples: int = 0,
                        denoise: bool = None, view_transform: str = "") -> dict:
    """Set render settings. Only non-empty/non-zero values are applied."""
    scene = bpy.context.scene
    render = scene.render

    if engine:
        _set_engine(render, engine)
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
        fmt = file_format.upper()
        # Blender 5 lists FFMPEG only under the VIDEO media type, so pick that first.
        render.image_settings.media_type = "VIDEO" if fmt == "FFMPEG" else (
            "MULTI_LAYER_IMAGE" if fmt == "OPEN_EXR_MULTILAYER" else "IMAGE")
        render.image_settings.file_format = fmt
    if samples > 0:
        if render.engine == "CYCLES":
            scene.cycles.samples = samples
        elif _is_eevee(render.engine):
            scene.eevee.taa_render_samples = samples
    if denoise is not None and render.engine == "CYCLES":
        scene.cycles.use_denoising = denoise
    if view_transform:
        scene.view_settings.view_transform = view_transform

    return get_render_settings()


def set_render_device(device: str = "AUTO") -> dict:
    """Cycles compute device: AUTO (OPTIX > CUDA > HIP > ONEAPI > METAL), one of those, or CPU."""
    scene = bpy.context.scene
    addon = bpy.context.preferences.addons.get("cycles")
    if addon is None:
        raise RuntimeError("Cycles is not enabled")
    prefs = addon.preferences
    order = ["OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"]
    wanted = order if device.upper() == "AUTO" else ([] if device.upper() == "CPU" else [device.upper()])
    chosen = None
    for kind in wanted:
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        prefs.get_devices()
        devices = [d for d in prefs.devices if d.type == kind]
        if devices:
            for d in prefs.devices:
                d.use = d.type == kind
            chosen = kind
            break
    if chosen:
        scene.cycles.device = "GPU"
    else:
        if device.upper() not in ("AUTO", "CPU"):
            raise ValueError(f"No {device.upper()} device found")
        scene.cycles.device = "CPU"
    return {
        "compute_device_type": chosen or "NONE",
        "scene_device": scene.cycles.device,
        "devices": [{"name": d.name, "type": d.type, "use": d.use} for d in prefs.devices],
    }


def _encode_preview(path, max_size):
    """Downscale a rendered file with imbuf (no image datablocks) and return base64 PNG."""
    import imbuf
    img = imbuf.load(path)
    w, h = img.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        img.resize((max(1, int(w * scale)), max(1, int(h * scale))), method="BILINEAR")
    tmp = os.path.join(tempfile.gettempdir(), "blender_mcp_render_preview.png")
    imbuf.write(img, filepath=tmp)
    try:
        with open(tmp, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8"), list(img.size)
    finally:
        os.remove(tmp)


def render_frame(frame: int = -1, output_path: str = "", max_size: int = 1024) -> dict:
    """Render a single frame (blocking) and return a preview of the result."""
    scene = bpy.context.scene

    if frame >= 0:
        scene.frame_set(frame)

    old_path = scene.render.filepath
    old_media = scene.render.image_settings.media_type
    target = output_path or os.path.join(tempfile.gettempdir(), "blender_mcp_render.png")
    scene.render.filepath = target
    if scene.render.image_settings.media_type == "VIDEO":
        scene.render.image_settings.media_type = "IMAGE"
        scene.render.image_settings.file_format = "PNG"
    try:
        bpy.ops.render.render(write_still=True)
        result_path = bpy.path.abspath(scene.render.frame_path(frame=scene.frame_current)) \
            if not os.path.isfile(bpy.path.abspath(target)) else bpy.path.abspath(target)
    finally:
        scene.render.filepath = old_path
        if scene.render.image_settings.media_type != old_media:
            scene.render.image_settings.media_type = old_media

    result = {
        "rendered": True,
        "frame": scene.frame_current,
        "output_path": result_path if output_path else None,
        "engine": scene.render.engine,
        "device": scene.cycles.device if scene.render.engine == "CYCLES" else None,
    }

    if os.path.isfile(result_path) and max_size > 0:
        result["image_base64"], result["preview_size"] = _encode_preview(result_path, max_size)
    if not output_path and os.path.isfile(result_path):
        os.remove(result_path)

    return result


def _render_done(*_args):
    _render_job["finished"] = True


def _render_frame_done(scene, *_args):
    _render_job["last_frame"] = scene.frame_current
    _render_job["frames_done"] = _render_job.get("frames_done", 0) + 1


def _render_cancelled(*_args):
    _render_job["cancelled"] = True


def render_animation(start: int = -1, end: int = -1, output_path: str = "", wait: bool = False) -> dict:
    """Render an animation. With Blender's UI it runs in the background (check get_render_status)."""
    scene = bpy.context.scene

    if start >= 0:
        scene.frame_start = start
    if end >= 0:
        scene.frame_end = end
    if output_path:
        scene.render.filepath = output_path

    wm = bpy.context.window_manager
    if wait or bpy.app.background or not wm.windows:
        bpy.ops.render.render(animation=True)
        return {"rendered": True, "frame_start": scene.frame_start, "frame_end": scene.frame_end,
                "output_path": scene.render.filepath}

    if bpy.app.is_job_running("RENDER"):
        raise RuntimeError("A render is already running")
    _render_job.clear()
    _render_job.update(frame_start=scene.frame_start, frame_end=scene.frame_end, output_path=scene.render.filepath)
    for handlers, fn in ((bpy.app.handlers.render_complete, _render_done),
                         (bpy.app.handlers.render_cancel, _render_cancelled),
                         (bpy.app.handlers.render_post, _render_frame_done)):
        if fn not in handlers:
            handlers.append(fn)
    with bpy.context.temp_override(window=wm.windows[0]):
        bpy.ops.render.render("INVOKE_DEFAULT", animation=True)
    return {"started": True, "frame_start": scene.frame_start, "frame_end": scene.frame_end,
            "output_path": scene.render.filepath, "note": "Poll get_render_status until finished"}


def get_render_status() -> dict:
    """Progress of a render started by render_animation."""
    running = bpy.app.is_job_running("RENDER")
    status = dict(_render_job)
    status["running"] = running
    if status.get("frame_start") is not None:
        status["total_frames"] = status["frame_end"] - status["frame_start"] + 1
    return status


register_handler("get_render_settings", get_render_settings)
register_handler("set_render_settings", set_render_settings)
register_handler("set_render_device", set_render_device)
register_handler("render_frame", render_frame)
register_handler("render_animation", render_animation)
register_handler("get_render_status", get_render_status)
