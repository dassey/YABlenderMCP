"""Modifier MCP tools."""

from typing import Any

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def list_modifiers(object_name: str) -> str:
        """List all modifiers on an object with their settings."""
        return send("list_modifiers", {"object_name": object_name})

    @mcp.tool(annotations=EDIT)
    def add_modifier(object_name: str, type: str, name: str = "", settings: Any = None) -> str:
        """Add a modifier to an object.

        Type is the Blender modifier type (e.g. "SUBSURF", "BOOLEAN", "ARRAY", "MIRROR",
        "SOLIDIFY", "BEVEL", "REMESH", "DECIMATE", "SCREW", "WELD", "NODES"). settings is
        an object of property names to values, e.g. {"levels": 2}; object references
        take object names. Unknown settings list the valid ones; values that could
        freeze Blender (subdivision > 6, array > 1000...) are refused.
        """
        return send("add_modifier", params_of(object_name=object_name, type=type, name=name or None,
                                              settings=jparse(settings)))

    @mcp.tool(annotations=EDIT)
    def set_modifier_property(object_name: str, modifier_name: str, property: str, value: Any) -> str:
        """Set a property on a modifier (value as a number, string, bool or list)."""
        return send("set_modifier_property", {
            "object_name": object_name,
            "modifier_name": modifier_name,
            "property": property,
            "value": jparse(value),
        })

    @mcp.tool(annotations=DESTRUCTIVE)
    def apply_modifier(object_name: str, modifier_name: str) -> str:
        """Apply a modifier, making its effect permanent.

        This removes the modifier and bakes its result into the mesh.
        """
        return send("apply_modifier", {
            "object_name": object_name,
            "modifier_name": modifier_name,
        })

    @mcp.tool(annotations=DESTRUCTIVE)
    def remove_modifier(object_name: str, modifier_name: str) -> str:
        """Remove a modifier from an object without applying it."""
        return send("remove_modifier", {
            "object_name": object_name,
            "modifier_name": modifier_name,
        })

    @mcp.tool(annotations=DESTRUCTIVE)
    def boolean_operation(target: str, cutter: str, operation: str = "DIFFERENCE", solver: str = "EXACT",
                          apply: bool = True, cutter_action: str = "hide") -> str:
        """Boolean the target with a cutter object: DIFFERENCE (cut), UNION (merge) or INTERSECT.

        solver: EXACT (most robust), MANIFOLD (fast, needs closed meshes - good for prints),
        FLOAT (fast). apply=False keeps a live modifier. cutter_action: hide, delete or keep.
        Returns resulting face count and dimensions; warns if the result is empty.
        """
        return send("boolean_operation", {"target": target, "cutter": cutter, "operation": operation,
                                          "solver": solver, "apply": apply, "cutter_action": cutter_action})
