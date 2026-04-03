"""Material MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def list_materials() -> str:
        """List all materials in the Blender file.

        Returns each material's name and number of users.
        """
        conn = get_connection()
        result = conn.send_command("list_materials", {})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_material_info(name: str) -> str:
        """Get detailed info about a material's node tree.

        Returns all nodes with their type, label, location, and input
        default values, plus all links between nodes.
        """
        conn = get_connection()
        result = conn.send_command("get_material_info", {"name": name})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def create_material(name: str, color: Optional[str] = None,
                        metallic: float = 0.0, roughness: float = 0.5) -> str:
        """Create a new material with a Principled BSDF shader.

        Color should be a JSON array of 3 floats [R, G, B] in 0-1 range.
        Example: "[1.0, 0.0, 0.0]" for red.
        """
        conn = get_connection()
        params = {"name": name, "metallic": metallic, "roughness": roughness}
        if color is not None:
            params["color"] = json.loads(color)
        result = conn.send_command("create_material", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def assign_material(object_name: str, material_name: str, slot: int = -1) -> str:
        """Assign a material to an object.

        If slot is -1 (default), appends a new material slot.
        Otherwise sets the material in the specified slot index.
        """
        conn = get_connection()
        result = conn.send_command("assign_material", {
            "object_name": object_name,
            "material_name": material_name,
            "slot": slot,
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_material_property(material_name: str, property: str, value: str) -> str:
        """Set a Principled BSDF input value on a material.

        The property is the input name (e.g. "Base Color", "Metallic", "Roughness").
        Value should be a JSON value: a number for scalar inputs, or an array
        like [R, G, B, A] for color inputs.
        """
        conn = get_connection()
        result = conn.send_command("set_material_property", {
            "material_name": material_name,
            "property": property,
            "value": json.loads(value),
        })
        return json.dumps(result, indent=2)
