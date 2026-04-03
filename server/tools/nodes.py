"""Node tree MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def get_node_tree(owner: str) -> str:
        """Get the full node tree for a material or geometry nodes modifier.

        Owner can be a material name or an object name (which will use
        the first Geometry Nodes modifier found). Returns all nodes with
        their inputs and default values, plus all links.
        """
        conn = get_connection()
        result = conn.send_command("get_node_tree", {"owner": owner})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def add_node(owner: str, type: str, name: str = "",
                 location: Optional[str] = None) -> str:
        """Add a node to a node tree.

        Owner is a material or object name. Type is the Blender node type
        (e.g. "ShaderNodeMixRGB", "ShaderNodeTexImage"). Location is an
        optional JSON array [x, y].
        """
        conn = get_connection()
        params = {"owner": owner, "type": type}
        if name:
            params["name"] = name
        if location is not None:
            params["location"] = json.loads(location)
        result = conn.send_command("add_node", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def connect_nodes(owner: str, from_node: str, from_output: str,
                      to_node: str, to_input: str) -> str:
        """Connect two nodes in a node tree.

        Specify the output socket name on the source node and the input
        socket name on the destination node.
        """
        conn = get_connection()
        result = conn.send_command("connect_nodes", {
            "owner": owner,
            "from_node": from_node,
            "from_output": from_output,
            "to_node": to_node,
            "to_input": to_input,
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_node_value(owner: str, node_name: str, input_name: str,
                       value: str) -> str:
        """Set a node input's default value.

        Value should be a JSON value: a number for scalar inputs, or an
        array for vector/color inputs (e.g. "[1.0, 0.0, 0.0, 1.0]").
        """
        conn = get_connection()
        result = conn.send_command("set_node_value", {
            "owner": owner,
            "node_name": node_name,
            "input_name": input_name,
            "value": json.loads(value),
        })
        return json.dumps(result, indent=2)

    @mcp.tool()
    def remove_node(owner: str, node_name: str) -> str:
        """Remove a node from a node tree."""
        conn = get_connection()
        result = conn.send_command("remove_node", {
            "owner": owner,
            "node_name": node_name,
        })
        return json.dumps(result, indent=2)
