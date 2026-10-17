"""Node tree MCP tools."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_node_tree(owner: str) -> str:
        """Get the full node tree of a material, an object's Geometry Nodes modifier
        ("Object" or "Object/Modifier"), a node group, or a world ("world").

        Returns nodes with bl_idname, settings (e.g. Math operation), inputs with
        default values or links, outputs, plus all links.
        """
        return send("get_node_tree", {"owner": owner})

    @mcp.tool(annotations=READ)
    def get_node_type_info(node_type: str, properties: Optional[dict[str, Any]] = None) -> str:
        """Real input/output sockets and settings of a node type in this Blender version, e.g.
        "ShaderNodeMix", "GeometryNodeMeshCube", "ShaderNodeMath". properties are applied first
        because modes change sockets (e.g. {"data_type": "RGBA"} on ShaderNodeMix)."""
        return send("get_node_type_info", params_of(node_type=node_type, properties=properties))

    @mcp.tool(annotations=EDIT)
    def add_node(owner: str, type: str, name: str = "", location: Any = None,
                 properties: Optional[dict[str, Any]] = None) -> str:
        """Add a node to a node tree.

        Type is the node bl_idname (e.g. "ShaderNodeTexNoise", "ShaderNodeMath",
        "GeometryNodeMeshCube"). location: [x, y]. properties: node settings like
        {"operation": "MULTIPLY"}. Returns the node's input and output names.
        """
        return send("add_node", params_of(owner=owner, type=type, name=name or None, location=jparse(location),
                                          properties=properties))

    @mcp.tool(annotations=EDIT)
    def connect_nodes(owner: str, from_node: str, from_output: str, to_node: str, to_input: str) -> str:
        """Connect two nodes in a node tree.

        Sockets by name, identifier (e.g. "Value_001" for the second "Value" input of a
        Math node) or index ("0", "1").
        """
        return send("connect_nodes", {
            "owner": owner,
            "from_node": from_node,
            "from_output": from_output,
            "to_node": to_node,
            "to_input": to_input,
        })

    @mcp.tool(annotations=EDIT)
    def set_node_value(owner: str, node_name: str, input_name: str, value: Any) -> str:
        """Set a node input's default value (input by name, identifier or index).

        Value: a number, or a list for vector/color inputs (e.g. [1.0, 0.0, 0.0, 1.0]).
        """
        return send("set_node_value", {
            "owner": owner,
            "node_name": node_name,
            "input_name": input_name,
            "value": jparse(value),
        })

    @mcp.tool(annotations=EDIT)
    def set_node_property(owner: str, node_name: str, property: str, value: Any) -> str:
        """Set a node setting that is not a socket: Math "operation", Mix "data_type"/"blend_type",
        Image Texture "image" (a file path loads it), interpolation, etc."""
        return send("set_node_property", {"owner": owner, "node_name": node_name, "property": property,
                                          "value": jparse(value)})

    @mcp.tool(annotations=DESTRUCTIVE)
    def remove_node(owner: str, node_name: str) -> str:
        """Remove a node from a node tree."""
        return send("remove_node", {
            "owner": owner,
            "node_name": node_name,
        })

    @mcp.tool(annotations=EDIT)
    def create_geometry_nodes(object_name: str, name: str = "") -> str:
        """Add a Geometry Nodes modifier with a new node group (Group Input wired to Group Output).
        Then build it with add_node/connect_nodes using owner "Object/Modifier"."""
        return send("create_geometry_nodes", params_of(object_name=object_name, name=name or None))
