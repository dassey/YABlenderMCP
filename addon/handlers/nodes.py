"""Node tree manipulation handlers."""

import bpy

from . import register_handler
from .common import get_object

_TREE_TYPES = ("ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree", "TextureNodeTree")
_BASE_NODE_PROPS = {p.identifier for p in bpy.types.Node.bl_rna.properties}


def _get_tree(owner: str):
    """Resolve a node tree from a material, an object (its Geometry Nodes modifier), a node group or a world."""
    # Try material first
    mat = bpy.data.materials.get(owner)
    if mat is not None:
        if mat.node_tree is None:
            raise ValueError(f"Material '{owner}' does not use nodes")
        return mat.node_tree

    # Try object with geometry nodes modifier ("Object" or "Object/ModifierName")
    obj_name, _, mod_name = owner.partition("/")
    obj = bpy.data.objects.get(obj_name)
    if obj is not None:
        for mod in obj.modifiers:
            if mod.type == "NODES" and mod.node_group and (not mod_name or mod.name == mod_name):
                return mod.node_group
        raise ValueError(f"Object '{obj_name}' has no Geometry Nodes modifier with a node group "
                         "(use create_geometry_nodes)")

    group = bpy.data.node_groups.get(owner.removeprefix("node_group:"))
    if group is not None:
        return group
    world = bpy.context.scene.world if owner == "world" else bpy.data.worlds.get(owner)
    if world is not None and world.node_tree is not None:
        return world.node_tree

    raise ValueError(f"No material, object, node group or world named '{owner}' found")


def _socket_value(sock):
    if not hasattr(sock, "default_value"):
        return None
    val = sock.default_value
    if hasattr(val, "__len__") and not isinstance(val, str):
        return [round(v, 4) for v in val]
    return round(val, 4) if isinstance(val, float) else val


def _node_props(node):
    props = {}
    for p in node.bl_rna.properties:
        if p.identifier in _BASE_NODE_PROPS or p.type not in ("ENUM", "BOOLEAN", "INT", "FLOAT", "STRING"):
            continue
        if getattr(p, "is_readonly", False):
            continue
        try:
            value = getattr(node, p.identifier)
        except Exception:
            continue
        if p.type == "FLOAT" and getattr(p, "array_length", 0):
            continue
        props[p.identifier] = value if not isinstance(value, set) else sorted(value)
    return props


def _socket_labels(sockets):
    """Socket names; the identifier is added when a name repeats (e.g. Math's two "Value" inputs)."""
    enabled = [s for s in sockets if s.enabled]
    names = [s.name for s in enabled]
    return [f"{s.name} [{s.identifier}]" if names.count(s.name) > 1 else s.name for s in enabled]


def get_node_tree(owner: str) -> dict:
    """Dump all nodes and links for a node tree."""
    tree = _get_tree(owner)

    nodes = []
    for node in tree.nodes:
        node_info = {
            "name": node.name,
            "type": node.type,
            "bl_idname": node.bl_idname,
            "label": node.label,
            "location": [round(node.location.x, 1), round(node.location.y, 1)],
            "inputs": [],
            "outputs": _socket_labels(node.outputs),
        }
        props = _node_props(node)
        if props:
            node_info["properties"] = props
        for inp in node.inputs:
            if not inp.enabled:
                continue
            inp_info = {"name": inp.name, "type": inp.type}
            if [i.name for i in node.inputs if i.enabled].count(inp.name) > 1:
                inp_info["identifier"] = inp.identifier
            if inp.is_linked:
                inp_info["linked"] = True
            else:
                val = _socket_value(inp)
                if val is not None:
                    inp_info["default_value"] = val
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

    return {"owner": owner, "tree_type": tree.bl_idname, "nodes": nodes, "links": links}


def _find_socket(sockets, key, node_name, kind):
    """Find a socket by index, identifier (e.g. "Value_001") or name."""
    if isinstance(key, int) or (isinstance(key, str) and key.isdigit()):
        index = int(key)
        if 0 <= index < len(sockets):
            return sockets[index]
    for s in sockets:
        if s.identifier == key:
            return s
    for s in sockets:
        if s.name == key and s.enabled:
            return s
    for s in sockets:
        if s.name == key:
            return s
    available = [f"{i}:{s.name}" + (f" ({s.identifier})" if s.identifier != s.name else "")
                 for i, s in enumerate(sockets) if s.enabled]
    raise ValueError(f"{kind} '{key}' not found on '{node_name}'. Available: {', '.join(available)}")


def add_node(owner: str, type: str, name: str = "", location=None, properties: dict = None) -> dict:
    """Add a node to a node tree."""
    tree = _get_tree(owner)
    try:
        node = tree.nodes.new(type)
    except RuntimeError as e:
        raise ValueError(f"{e}. Use the bl_idname, e.g. ShaderNodeTexNoise, GeometryNodeMeshCube, "
                         "ShaderNodeMath (get_node_type_info lists sockets)")

    if name:
        node.name = name
    if location is not None:
        node.location = location
    for key, value in (properties or {}).items():
        setattr(node, key, value)

    return {"owner": owner, "node": node.name, "type": node.type,
            "inputs": _socket_labels(node.inputs), "outputs": _socket_labels(node.outputs)}


def connect_nodes(owner: str, from_node: str, from_output, to_node: str, to_input) -> dict:
    """Connect two nodes in a node tree (sockets by name, identifier or index)."""
    tree = _get_tree(owner)

    src = tree.nodes.get(from_node)
    if src is None:
        raise ValueError(f"Node '{from_node}' not found")
    dst = tree.nodes.get(to_node)
    if dst is None:
        raise ValueError(f"Node '{to_node}' not found")

    out_socket = _find_socket(src.outputs, from_output, from_node, "Output")
    in_socket = _find_socket(dst.inputs, to_input, to_node, "Input")
    tree.links.new(out_socket, in_socket)
    return {"from": f"{from_node}.{out_socket.name}", "to": f"{to_node}.{in_socket.name}", "connected": True}


def set_node_value(owner: str, node_name: str, input_name, value) -> dict:
    """Set a node input's default value."""
    tree = _get_tree(owner)

    node = tree.nodes.get(node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found")

    inp = _find_socket(node.inputs, input_name, node_name, "Input")
    if isinstance(value, list):
        inp.default_value = tuple(value)
    else:
        inp.default_value = value

    return {"node": node_name, "input": inp.name, "set": True}


def set_node_property(owner: str, node_name: str, property: str, value) -> dict:
    """Set a node setting that is not a socket (Math operation, Mix data_type/blend_type, image...)."""
    tree = _get_tree(owner)
    node = tree.nodes.get(node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found")
    if property not in node.bl_rna.properties:
        raise ValueError(f"'{property}' is not a property of {node.bl_idname}. Available: "
                         f"{', '.join(_node_props(node))}")
    if property == "image" and isinstance(value, str):
        value = bpy.data.images.load(value, check_existing=True)
    setattr(node, property, value)
    return {"node": node.name, "property": property, "value": str(getattr(node, property)),
            "inputs": _socket_labels(node.inputs), "outputs": _socket_labels(node.outputs)}


def remove_node(owner: str, node_name: str) -> dict:
    """Remove a node from a node tree."""
    tree = _get_tree(owner)

    node = tree.nodes.get(node_name)
    if node is None:
        raise ValueError(f"Node '{node_name}' not found")

    tree.nodes.remove(node)
    return {"owner": owner, "node": node_name, "removed": True}


def get_node_type_info(node_type: str, properties: dict = None) -> dict:
    """Real sockets and settings of a node type in this Blender version (mode settings applied first)."""
    for tree_type in _TREE_TYPES:
        group = bpy.data.node_groups.new("__mcp_node_info", tree_type)
        try:
            try:
                node = group.nodes.new(node_type)
            except RuntimeError:
                continue
            for key, value in (properties or {}).items():
                setattr(node, key, value)

            def sockets(items):
                return [{"index": i, "name": s.name, "identifier": s.identifier, "type": s.type,
                         **({"default": _socket_value(s)} if _socket_value(s) is not None else {})}
                        for i, s in enumerate(items) if s.enabled]

            settings = {}
            for p in node.bl_rna.properties:
                if p.identifier in _BASE_NODE_PROPS or p.is_readonly:
                    continue
                entry = {"type": p.type}
                if p.type == "ENUM":
                    entry["items"] = [i.identifier for i in p.enum_items]
                try:
                    entry["value"] = str(getattr(node, p.identifier))
                except Exception:
                    pass
                settings[p.identifier] = entry
            return {"node_type": node_type, "tree_type": tree_type, "name": node.name,
                    "inputs": sockets(node.inputs), "outputs": sockets(node.outputs), "settings": settings}
        finally:
            bpy.data.node_groups.remove(group)
    import difflib
    known = [t for t in dir(bpy.types)
             if t.startswith(("ShaderNode", "GeometryNode", "CompositorNode", "TextureNode", "FunctionNode"))]
    close = difflib.get_close_matches(node_type, known, n=8, cutoff=0.6)
    raise ValueError(f"Unknown node type '{node_type}'." + (f" Did you mean: {', '.join(close)}" if close else ""))


def create_geometry_nodes(object_name: str, name: str = "") -> dict:
    """Add a Geometry Nodes modifier with a new node group (Group Input -> Group Output wired)."""
    obj = get_object(object_name)
    group = bpy.data.node_groups.new(name or f"{obj.name}_GeoNodes", "GeometryNodeTree")
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin = group.nodes.new("NodeGroupInput")
    gin.location = (-300, 0)
    gout = group.nodes.new("NodeGroupOutput")
    gout.location = (300, 0)
    group.links.new(gin.outputs[0], gout.inputs[0])
    mod = obj.modifiers.new(group.name, "NODES")
    mod.node_group = group
    return {"object": obj.name, "modifier": mod.name, "node_group": group.name,
            "nodes": [gin.name, gout.name], "owner_for_node_tools": f"{obj.name}/{mod.name}"}


register_handler("get_node_tree", get_node_tree)
register_handler("add_node", add_node)
register_handler("connect_nodes", connect_nodes)
register_handler("set_node_value", set_node_value)
register_handler("set_node_property", set_node_property)
register_handler("remove_node", remove_node)
register_handler("get_node_type_info", get_node_type_info)
register_handler("create_geometry_nodes", create_geometry_nodes)
