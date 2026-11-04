"""Session MCP tools: Blender info, undo/redo, batches, units, scene cleanup, generic properties, API lookup."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_blender_info() -> str:
        """Blender version, open file and unsaved state, units (mm per Blender unit), render engine,
        data counts, GPU and Cycles devices."""
        return send("get_blender_info")

    @mcp.tool(annotations=EDIT)
    def undo(steps: int = 1) -> str:
        """Undo the last N steps. Every scene-changing tool call is exactly one undo step."""
        return send("undo", {"steps": steps})

    @mcp.tool(annotations=EDIT)
    def redo(steps: int = 1) -> str:
        """Redo N steps that were undone."""
        return send("redo", {"steps": steps})

    @mcp.tool(annotations=DESTRUCTIVE)
    def execute_batch(commands: list[dict[str, Any]], stop_on_error: bool = True) -> str:
        """Run several commands in one round trip and one undo step.

        commands: [{"type": "<tool name>", "params": {...}}, ...] using the same names
        and parameters as the tools (e.g. create_object, set_transform, assign_material).
        Returns each command's result. Stops at the first error unless stop_on_error=False.
        """
        return send("execute_batch", {"commands": commands, "stop_on_error": stop_on_error})

    @mcp.tool(annotations=EDIT)
    def set_units(preset: str = "", system: str = "METRIC", length_unit: str = "",
                  scale_length: float = 0.0) -> str:
        """Set scene units. preset="mm" makes 1 Blender unit = 1 millimeter (best for 3D printing);
        also "cm", "m", "inch" (1 unit = 1 cm / 1 m / 1 inch). Or set system/length_unit/scale_length."""
        return send("set_units", params_of(preset=preset or None, system=system, length_unit=length_unit or None,
                                           scale_length=scale_length or None))

    @mcp.tool(annotations=DESTRUCTIVE)
    def clear_scene(keep_types: Optional[list[str]] = None, purge: bool = True) -> str:
        """Delete every object in the scene except the given types (e.g. ["CAMERA", "LIGHT"]),
        then purge unused data. Undoable with the undo tool."""
        return send("clear_scene", params_of(keep_types=keep_types, purge=purge))

    @mcp.tool(annotations=READ)
    def get_properties(target: str = "scene", paths: Optional[list[str]] = None) -> str:
        """Read any Blender property by data path.

        target: an object name, "scene", "world", "view_layer", or kind:Name (material:,
        mesh:, light:, camera:, collection:, node_group:, image:, curve:, world:, action:).
        paths: e.g. ["location", "data.energy", "modifiers[\\"Bevel\\"].width",
        "render.resolution_x", "cycles.samples"]. Without paths, lists the target's properties.
        """
        return send("get_properties", params_of(target=target, paths=paths))

    @mcp.tool(annotations=EDIT)
    def set_properties(target: str, properties: dict[str, Any]) -> str:
        """Set any Blender properties by data path - lights, cameras, modifiers, render, materials...

        target as in get_properties. properties: {"data.energy": 800, "location[2]": 1.5,
        "modifiers[\\"Bevel\\"].segments": 4, "render.fps": 30, "cycles.samples": 64}.
        Errors list close property names.
        """
        return send("set_properties", {"target": target, "properties": properties})

    @mcp.tool(annotations=READ)
    def get_operator_history(limit: int = 20) -> str:
        """Recent operators run in Blender, including what the user did by hand
        (useful to see what changed since your last command)."""
        return send("get_operator_history", {"limit": limit})

    @mcp.tool(annotations=READ)
    def search_api(query: str, limit: int = 40) -> str:
        """Search this Blender's Python API (operators and types) by words, e.g. "bevel", "uv unwrap".

        Use before guessing operator names - Blender 5.1 renamed and removed several.
        """
        return send("search_api", {"query": query, "limit": limit})

    @mcp.tool(annotations=READ)
    def get_api_docs(path: str) -> str:
        """Exact parameters/properties from the running Blender, e.g. "bpy.ops.mesh.primitive_cylinder_add",
        "Object", "Object.location", "bpy.types.SolidifyModifier", "bmesh.ops.remove_doubles"."""
        return send("get_api_docs", {"path": path})
