"""Material creation and manipulation handlers."""

import bpy

from . import register_handler


def list_materials() -> dict:
    """List all materials with usage counts."""
    materials = []
    for mat in bpy.data.materials:
        materials.append({
            "name": mat.name,
            "users": mat.users,
        })
    return {"materials": materials}


def get_material_info(name: str) -> dict:
    """Get full node tree info for a material."""
    mat = bpy.data.materials.get(name)
    if mat is None:
        raise ValueError(f"Material '{name}' not found")

    if not mat.use_nodes or mat.node_tree is None:
        return {"name": mat.name, "use_nodes": False, "nodes": [], "links": []}

    tree = mat.node_tree
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

    return {"name": mat.name, "use_nodes": True, "nodes": nodes, "links": links}


def create_material(name: str, color=None, metallic: float = 0.0, roughness: float = 0.5) -> dict:
    """Create a new material with Principled BSDF."""
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    tree = mat.node_tree

    # Find the Principled BSDF node (created by default)
    bsdf = None
    for node in tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            bsdf = node
            break

    if bsdf is None:
        bsdf = tree.nodes.new("ShaderNodeBsdfPrincipled")

    if color is not None:
        bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness

    return {"name": mat.name, "created": True}


def assign_material(object_name: str, material_name: str, slot: int = -1) -> dict:
    """Assign a material to an object."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        raise ValueError(f"Object '{object_name}' not found")
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        raise ValueError(f"Material '{material_name}' not found")

    if slot < 0:
        obj.data.materials.append(mat)
        assigned_slot = len(obj.data.materials) - 1
    else:
        if slot >= len(obj.data.materials):
            raise ValueError(f"Slot {slot} out of range (object has {len(obj.data.materials)} slots)")
        obj.data.materials[slot] = mat
        assigned_slot = slot

    return {"object": obj.name, "material": mat.name, "slot": assigned_slot}


def set_material_property(material_name: str, property: str, value) -> dict:
    """Set a Principled BSDF input by name."""
    mat = bpy.data.materials.get(material_name)
    if mat is None:
        raise ValueError(f"Material '{material_name}' not found")

    if not mat.use_nodes or mat.node_tree is None:
        raise ValueError(f"Material '{material_name}' does not use nodes")

    bsdf = None
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            bsdf = node
            break

    if bsdf is None:
        raise ValueError(f"No Principled BSDF node found in material '{material_name}'")

    if property not in bsdf.inputs:
        available = [inp.name for inp in bsdf.inputs]
        raise ValueError(f"Input '{property}' not found. Available: {', '.join(available)}")

    inp = bsdf.inputs[property]
    if isinstance(value, list):
        inp.default_value = tuple(value)
    else:
        inp.default_value = value

    return {"material": mat.name, "property": property, "set": True}


register_handler("list_materials", list_materials)
register_handler("get_material_info", get_material_info)
register_handler("create_material", create_material)
register_handler("assign_material", assign_material)
register_handler("set_material_property", set_material_property)
