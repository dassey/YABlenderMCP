"""Light, camera, world and framing MCP tools."""

from typing import Any, Optional

from ..compat import EDIT, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=EDIT)
    def create_light(type: str = "AREA", name: str = "", location: Optional[list[float]] = None,
                     energy: float = 0.0, color: Optional[list[float]] = None, size: float = 0.0,
                     look_at: Any = None, spot_size_degrees: float = 0.0, shape: str = "") -> str:
        """Create a light (POINT, SUN, SPOT, AREA) aimed at look_at (object name or [x,y,z]),
        or at the scene centre. Without energy, power is scaled to the distance so exposure is
        sensible at any scene scale. size: area size / sun angle (deg) / soft shadow radius."""
        return send("create_light", params_of(type=type, name=name or None, location=location, energy=energy,
                                              color=color, size=size, look_at=jparse(look_at),
                                              spot_size_degrees=spot_size_degrees, shape=shape or None))

    @mcp.tool(annotations=EDIT)
    def create_camera(name: str = "Camera", location: Optional[list[float]] = None, look_at: Any = None,
                      lens: float = 50.0, type: str = "PERSP", ortho_scale: float = 0.0,
                      set_active: bool = True) -> str:
        """Create a camera aimed at look_at (object name or [x,y,z]) or the scene centre, and make it
        the active camera. type: PERSP or ORTHO. Use frame_camera to fit objects in view."""
        return send("create_camera", params_of(name=name, location=location, look_at=jparse(look_at), lens=lens,
                                               type=type, ortho_scale=ortho_scale, set_active=set_active))

    @mcp.tool(annotations=EDIT)
    def set_active_camera(name: str) -> str:
        """Make a camera the scene's active (render) camera."""
        return send("set_active_camera", {"name": name})

    @mcp.tool(annotations=EDIT)
    def point_at(name: str, target: Any, use_constraint: bool = False) -> str:
        """Aim a camera or light at an object or [x,y,z]. use_constraint=True keeps tracking it
        (TRACK_TO constraint)."""
        return send("point_at", {"name": name, "target": jparse(target), "use_constraint": use_constraint})

    @mcp.tool(annotations=EDIT)
    def frame_camera(camera: str = "", objects: Optional[list[str]] = None, fill: float = 0.85,
                     view: str = "") -> str:
        """Move/zoom the camera until the objects fill `fill` of the frame (measured from the real
        projection, not guessed). view optionally re-aims first: front, back, left, right, top, iso.
        Returns the achieved fill and whether anything is clipped."""
        return send("frame_camera", params_of(camera=camera or None, objects=objects, fill=fill,
                                              view=view or None))

    @mcp.tool(annotations=EDIT)
    def create_light_rig(preset: str = "three_point", objects: Optional[list[str]] = None,
                         intensity: float = 1.0) -> str:
        """Add a lighting setup sized to the objects: three_point, studio, rim, or outdoor (sun + sky).
        Lights go in the "MCP Lights" collection."""
        return send("create_light_rig", params_of(preset=preset, objects=objects, intensity=intensity))

    @mcp.tool(annotations=EDIT)
    def set_world(color: Optional[list[float]] = None, strength: float = 1.0, hdri_path: str = "",
                  rotation_degrees: float = 0.0) -> str:
        """Set the world background: a colour, or a local .hdr/.exr environment (hdri_path, rotated
        around Z by rotation_degrees). An HDRI world is created new; the old one is kept."""
        return send("set_world", params_of(color=color, strength=strength, hdri_path=hdri_path or None,
                                           rotation_degrees=rotation_degrees))
