"""Modifier MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def list_modifiers(object_name: str) -> str:
        """List all modifiers on an object.

        Returns each modifier's name and type.
        """
        conn = get_connection()
        result = conn.send_command("list_modifiers", {"object_name": object_name})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def add_modifier(object_name: str, type: str, name: str = "",
                     settings: Optional[str] = None) -> str:
        """Add a modifier to an object.

        Type should be the Blender modifier type (e.g. "SUBSURF", "BOOLEAN",
        "ARRAY", "MIRROR", "SOLIDIFY"). Settings is a JSON object of
        property names to values, e.g. '{"levels": 2}'.
        """
        conn = get_connection()
        params = {"object_name": object_name, "type": type}
        if name:
            params["name"] = name
        if settings is not None:
            params["settings"] = json.loads(settings)
        result = conn.send_command("add_modifier", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_modifier_property(object_name: str, modifier_name: str,
                              property: str, value: str) -> str:
        """Set a property on a modifier.

        Value should be a JSON value matching the property type.
        """
        conn = get_connection()
        result = conn.send_command("set_modifier_property", {
            "object_name": object_name,
            "modifier_name": modifier_name,
            "property": property,
            "value": json.loads(value),
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def apply_modifier(object_name: str, modifier_name: str) -> str:
        """Apply a modifier, making its effect permanent.

        This removes the modifier and bakes its result into the mesh.
        """
        conn = get_connection()
        result = conn.send_command("apply_modifier", {
            "object_name": object_name,
            "modifier_name": modifier_name,
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def remove_modifier(object_name: str, modifier_name: str) -> str:
        """Remove a modifier from an object without applying it."""
        conn = get_connection()
        result = conn.send_command("remove_modifier", {
            "object_name": object_name,
            "modifier_name": modifier_name,
        })
        return json.dumps(result, indent=2)
