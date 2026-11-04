"""Viewport MCP tools - screenshot, shading, view control, multi-angle capture."""

import base64
from typing import Any, Optional

from ..compat import EDIT, READ, FastMCP, Image
from ..connection import get_connection, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_viewport_screenshot(max_size: int = 800) -> Image:
        """Capture what the Blender 3D viewport shows and return it as an image.

        The max_size parameter limits the largest dimension in pixels (default 800).
        Smaller images keep long sessions cheap. find_object_at(x, y) identifies what
        is at a point of this image.
        """
        result = get_connection().send_command("get_viewport_screenshot", {"max_size": max_size})
        return Image(data=base64.b64decode(result["image_base64"]), format=result.get("format", "png"))

    @mcp.tool(annotations=READ)
    def capture_views(views: Optional[list[Any]] = None, objects: Optional[list[str]] = None,
                      size: int = 512, shading: str = "", overlays: bool = True,
                      perspective: bool = False, frames: Optional[list[int]] = None) -> list:
        """See the scene from several angles at once: returns one labeled grid image.

        views: front, back, left, right, top, bottom, iso, iso_back, "camera" (through
        the scene camera) or [x, y, z] directions (default front, right, top, iso).
        objects: frame only these (default all visible geometry). size: pixels per tile.
        shading: solid, material, wireframe (edges over the surface), wireframe_only,
        xray (see internal parts, e.g. print-in-place joints), clay, rendered (EEVEE
        only). frames: one tile per frame of the first view (check animation/motion).
        Orthographic unless perspective=True. The user's viewport is never changed.
        Use after modeling steps to verify shape, proportions and placement.
        """
        params = {"size": size, "overlays": overlays, "perspective": perspective}
        if views:
            params["views"] = views
        if objects:
            params["objects"] = objects
        if shading:
            params["shading"] = shading
        if frames:
            params["frames"] = frames
        result = get_connection().send_command("capture_views", params)
        image = Image(data=base64.b64decode(result.pop("image_base64")), format="png")
        info = (f"Tiles (left-to-right, top-to-bottom): {', '.join(result['views'])} ({result['projection']}); "
                f"{len(result['objects'])} object(s); bbox {result['bbox_min']} to {result['bbox_max']}")
        return [info, image]

    @mcp.tool(annotations=EDIT)
    def set_viewport_shading(mode: str, xray: Optional[bool] = None) -> str:
        """Set the viewport shading mode.

        Valid modes: WIREFRAME, SOLID, MATERIAL, RENDERED. Optionally toggle X-ray.
        """
        params = {"mode": mode}
        if xray is not None:
            params["xray"] = xray
        return send("set_viewport_shading", params)

    @mcp.tool(annotations=EDIT)
    def set_view(angle: str) -> str:
        """Set the 3D viewport camera angle.

        Valid angles: FRONT, BACK, LEFT, RIGHT, TOP, BOTTOM, ISO, CAMERA.
        """
        return send("set_view", {"angle": angle})

    @mcp.tool(annotations=EDIT)
    def frame_selected(names: Optional[list[str]] = None) -> str:
        """Frame objects in the viewport.

        With names, selects and frames those objects; otherwise frames the
        current selection (or the whole scene if nothing is selected).
        """
        return send("frame_selected", {"names": names} if names else None)
