"""Node tree manipulation handlers."""

import bpy

from . import register_handler


def _get_tree(owner: str):
    """Resolve a node tree from a material name or object+modifier name."""
    # Try material first
    mat = bpy.data.materials.get(owner)
    if mat is not None:
        if not mat.use_nodes or mat.node_tree is None:
            raise ValueError(f"Material '{owner}' does not use nodes")
        return mat.node_tree

    # Try object with geometry nodes modifier
    obj = bpy.data.objects.get(owner)
    if obj is not None:
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group:
                return mod.node_group
        raise ValueError(f"Object '{owner}' has no Geometry Nodes modifier with a node group")

    raise ValueError(f"No material or object named '{owner}' found")


def get_node_tree(owner: str) -> dict:
    """Dump all nodes and links for a node tree."""
    tree = _get_tree(owner)

    nodes = []
    for node in tree.nodes:
        node_info = {
            "name": node.name,
            "type": node.type,
            "label": node.label,
            "location": [round(node.location.x, 1), round(node.location.y, 1)],
            "inputs": [],
        }
        for inp in node.inputs:
            inp_info = {"name": inp.name, "type": inp.type}
            if hasattr(inp, "default_value"):
                val = inp.default_value
                if hasattr(val, "__iter__"):
                    inp_info["default_value"] = [round(v, 4) for v in val]
                else:
                    inp_info["default_value"] = round(val, 4) if isinstance(val, float) else val
            node_info["inputs"].append(inp_info)
        nodes.append(node_info)

    links = []
    for link in tree.links:
        links.append({
            "from_node": link.from_node.name,
            "from_socket": link.from_socket.name,
            "to_node": link.to_node.name,
            "to_socket": link.to_socket.name,
        })

    return {"owner": owner, "nodes": nodes, "links": links}


def add_node(owner: str, type: str, name: str = "", location=None) -> dict:
    """Add a node to a node tree."""
    tree = _get_tree(owner)
    node = tree.nodes.new(type)

    if name:
        node.name = name
    if location is not None:
        node.location = location

    return {"owner": owner, "node": node.name, "type": node.type}


def connect_nodes(owner: str, from_node: str, from_output: str, to_node: str, to_input: str) -> dict:
    """Connect two nodes in a node tree."""
    tree = _get_tree(owner)

    src = tree.nodes.get(from_node)
    if src is None:
        raise ValueError(f"Node '{from_node}' not found")
    dst = tree.nodes.get(to_node)
    if dst is None:
        raise ValueError(f"Node '{to_node}' not found")

    # Resolve sockets by name
    out_socket = None
    for s in src.outputs:
        if s.name == from_output:
            out_socket = s
            break
    if out_socket is None:
        available = [s.name for s in src.outputs]
        raise ValueError(f"Output '{from_output}' not found on '{from_node}'. Available: {', '.join(available)}")

    in_socket = None
    for s in dst.inputs:
        if s.name == to_input:
            in_socket = s
            break
    if in_socket is None:
        available = [s.name for s in dst.inputs]
        raise ValueError(f"Input '{to_input}' not found on '{to_node}'. Available: {', '.join(available)}")

    tree.links.new(out_socket, in_socket)
    return {"from": f"{from_node}.{from_output}", "to": f"{to_node}.{to_input}", "connected": True}


def set_node_value(owner: str, node_name: str, input_name: str, value) -> dict:
    """Set a node input's default value."""
    tree = _get_tree(owner)

    node = tree.nodes.get(node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found")

    if input_name not in node.inputs:
        available = [inp.name for inp in node.inputs]
        raise ValueError(f"Input '{input_name}' not found on '{node_name}'. Available: {', '.join(available)}")

    inp = node.inputs[input_name]
    if isinstance(value, list):
        inp.default_value = tuple(value)
    else:
        inp.default_value = value

    return {"node": node_name, "input": input_name, "set": True}


def remove_node(owner: str, node_name: str) -> dict:
    """Remove a node from a node tree."""
    tree = _get_tree(owner)

    node = tree.nodes.get(node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found")

    tree.nodes.remove(node)
    return {"owner": owner, "node": node_name, "removed": True}


register_handler("get_node_tree", get_node_tree)
register_handler("add_node", add_node)
register_handler("connect_nodes", connect_nodes)
register_handler("set_node_value", set_node_value)
register_handler("remove_node", remove_node)
