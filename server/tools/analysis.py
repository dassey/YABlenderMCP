"""Measurement and verification MCP tools."""

import base64
import json

from ..compat import READ, FastMCP, Image
from ..connection import get_connection, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def measure_distance(a: str, b: str) -> str:
        """Distance between two objects: origins, bounding boxes and closest surfaces (gap, 0 when
        they touch or intersect), with the closest points."""
        return send("measure_distance", {"a": a, "b": b})

    @mcp.tool(annotations=READ)
    def find_ray_hit(origin: list[float], direction: list[float], max_distance: float = 1e6) -> str:
        """Cast a ray into the scene: first object hit, hit location, surface normal and distance."""
        return send("find_ray_hit", {"origin": origin, "direction": direction, "max_distance": max_distance})

    @mcp.tool(annotations=READ)
    def find_object_at(x: float, y: float) -> str:
        """Which object is at a point of the last get_viewport_screenshot? x, y from 0 to 1,
        measured from the image's top-left corner."""
        return send("find_object_at", {"x": x, "y": y})

    @mcp.tool(annotations=READ)
    def snapshot_scene(name: str = "default") -> str:
        """Remember the scene state (transforms, mesh data, materials, lights, cameras) so diff_scene
        can prove what an edit changed - and that nothing else did."""
        return send("snapshot_scene", {"name": name})

    @mcp.tool(annotations=READ)
    def diff_scene(name: str = "default") -> str:
        """What changed since snapshot_scene(name): added, removed, and changed items with the
        fields that differ."""
        return send("diff_scene", {"name": name})

    @mcp.tool(annotations=READ)
    def compare_silhouette(objects: list[str], reference_image: str, view: str = "front", size: int = 512,
                           threshold: float = 0.5) -> list:
        """Compare the model's outline with a 2D reference (drawing/photo with transparency, or a
        dark shape on a light background) - the check for 2D-to-3D work.

        Renders the objects' silhouette from an orthographic view (front, back, left,
        right, top, bottom), fits both outlines to the same box (position and scale
        ignored), and returns IoU (1.0 = identical) plus an overlay: gray = both,
        blue = model only, red = reference only.
        """
        result = get_connection().send_command("compare_silhouette", {
            "objects": objects, "reference_image": reference_image, "view": view, "size": size,
            "threshold": threshold}, timeout=300)
        b64 = result.pop("image_base64")
        result.pop("format", None)
        return [json.dumps(result), Image(data=base64.b64decode(b64), format="png")]
