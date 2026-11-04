"""File I/O MCP tools - import, export, .blend files, libraries, checkpoints, reference images."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=EDIT)
    def import_file(filepath: str, options: Any = None, target_size: float = 0.0, drop_to_ground: bool = False,
                    center: bool = False) -> str:
        """Import a file into Blender.

        Formats: .fbx, .obj, .glb, .gltf, .stl, .ply, .abc, .usd/.usda/.usdc/.usdz,
        .svg (as curves - extrude them for 2D-to-3D), .3mf (geometry of 3MF/Bambu Studio
        projects). target_size scales the import so its largest side has that size (scene
        units); drop_to_ground puts it on z=0; center centres it on the origin in X/Y.
        options: format-specific importer settings. Returns new objects and dimensions.
        """
        return send("import_file", params_of(filepath=filepath, options=jparse(options), target_size=target_size,
                                             drop_to_ground=drop_to_ground, center=center))

    @mcp.tool(annotations=EDIT)
    def export_file(filepath: str, objects: Optional[list[str]] = None, options: Any = None) -> str:
        """Export from Blender to a file (whole scene, or only the listed objects).

        Formats: .fbx, .obj, .glb, .gltf, .stl, .ply, .abc, .usd/.usda/.usdc/.usdz.
        options: format-specific exporter settings. For 3D printing use export_print
        (millimeters, .3mf/.stl, checks).
        """
        return send("export_file", params_of(filepath=filepath, objects=objects, options=jparse(options)))

    @mcp.tool(annotations=EDIT)
    def save_blend(filepath: str = "") -> str:
        """Save the current .blend file.

        If filepath is provided, saves as a new file (Save As).
        Otherwise saves to the current file path.
        """
        return send("save_blend", {"filepath": filepath})

    @mcp.tool(annotations=DESTRUCTIVE)
    def open_blend(filepath: str, discard_changes: bool = False) -> str:
        """Open a .blend file, replacing the current scene.

        Refuses when the current file has unsaved changes unless discard_changes=True
        (save or save_checkpoint first). Scripts inside the file are never auto-run.
        """
        return send("open_blend", {"filepath": filepath, "discard_changes": discard_changes})

    @mcp.tool(annotations=EDIT)
    def save_checkpoint(label: str = "") -> str:
        """Save a timestamped copy of the scene (next to the .blend, or in the temp folder) without
        changing the open file. Make one before risky multi-step work; open_blend restores it."""
        return send("save_checkpoint", {"label": label})

    @mcp.tool(annotations=READ)
    def list_directory(path: str, filter: str = "") -> str:
        """List files in a directory.

        Optionally filter by file extension (e.g. ".blend", ".fbx").
        Returns file names, whether each is a directory, and file sizes.
        """
        return send("list_directory", {"path": path, "filter": filter})

    @mcp.tool(annotations=READ)
    def list_blend_contents(filepath: str) -> str:
        """List the objects, collections, materials, node groups... inside a .blend file without opening it
        (and which are marked as assets)."""
        return send("list_blend_contents", {"filepath": filepath})

    @mcp.tool(annotations=EDIT)
    def append_from_blend(filepath: str, names: Optional[list[str]] = None, data_type: str = "objects",
                          link: bool = False) -> str:
        """Append (or link) data from another .blend: objects, collections, materials, node_groups,
        meshes, worlds, actions, images. Use with a personal library of parts (hinges, joints, pins)."""
        return send("append_from_blend", params_of(filepath=filepath, names=names, data_type=data_type, link=link))

    @mcp.tool(annotations=READ)
    def list_asset_libraries() -> str:
        """The user's local asset libraries (Preferences > File Paths) and the .blend files in them."""
        return send("list_asset_libraries")

    @mcp.tool(annotations=EDIT)
    def add_reference_image(filepath: str, name: str = "", mode: str = "empty", size: float = 1.0,
                            location: Optional[list[float]] = None, view: str = "front",
                            opacity: float = 0.5) -> str:
        """Add a drawing/photo/blueprint as a modeling reference.

        mode: empty (image empty, not rendered) or plane (textured mesh plane). view:
        front, back, left, right or top. size: height in scene units.
        """
        return send("add_reference_image", params_of(filepath=filepath, name=name or None, mode=mode, size=size,
                                                     location=location, view=view, opacity=opacity))
