"""Material creation and manipulation handlers."""

import os

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

    if mat.node_tree is None:
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


_PRESETS = {
    # Principled BSDF inputs per preset
    "plastic": {"Base Color": (0.8, 0.8, 0.8, 1), "Roughness": 0.4, "Metallic": 0.0},
    "matte": {"Roughness": 0.9, "Metallic": 0.0},
    "rubber": {"Base Color": (0.05, 0.05, 0.05, 1), "Roughness": 0.85},
    "metal": {"Base Color": (0.8, 0.8, 0.8, 1), "Metallic": 1.0, "Roughness": 0.25},
    "brushed_metal": {"Base Color": (0.75, 0.75, 0.75, 1), "Metallic": 1.0, "Roughness": 0.45},
    "gold": {"Base Color": (1.0, 0.766, 0.336, 1), "Metallic": 1.0, "Roughness": 0.2},
    "copper": {"Base Color": (0.955, 0.638, 0.538, 1), "Metallic": 1.0, "Roughness": 0.25},
    "glass": {"Roughness": 0.0, "Transmission Weight": 1.0, "IOR": 1.45},
    "frosted_glass": {"Roughness": 0.35, "Transmission Weight": 1.0, "IOR": 1.45},
    "ceramic": {"Base Color": (0.9, 0.9, 0.88, 1), "Roughness": 0.15, "Coat Weight": 0.5},
    "emissive": {"Emission Strength": 5.0},
}


def _principled(mat):
    if mat.node_tree is None:
        mat.use_nodes = True
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")


def create_material(name: str, color=None, metallic: float = None, roughness: float = None,
                    preset: str = "", emission_color=None, emission_strength: float = None,
                    alpha: float = None) -> dict:
    """Create a new material with Principled BSDF (optionally from a preset)."""
    mat = bpy.data.materials.new(name=name)
    bsdf = _principled(mat)

    if preset:
        values = _PRESETS.get(preset.lower())
        if values is None:
            raise ValueError(f"Unknown preset '{preset}'. Valid: {', '.join(_PRESETS)}")
        for key, val in values.items():
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = val
        if preset.lower() == "emissive":
            bsdf.inputs["Emission Color"].default_value = (*(color or (1, 1, 1))[:3], 1.0)
    if color is not None:
        bsdf.inputs["Base Color"].default_value = (*color[:3], 1.0)
        mat.diffuse_color = (*color[:3], 1.0)
    if metallic is not None:
        bsdf.inputs["Metallic"].default_value = metallic
    elif not preset:
        bsdf.inputs["Metallic"].default_value = 0.0
    if roughness is not None:
        bsdf.inputs["Roughness"].default_value = roughness
    elif not preset:
        bsdf.inputs["Roughness"].default_value = 0.5
    if emission_color is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission_color[:3], 1.0)
        if emission_strength is None:
            emission_strength = 1.0
    if emission_strength is not None:
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    if alpha is not None:
        bsdf.inputs["Alpha"].default_value = alpha
        if alpha < 1.0:
            mat.surface_render_method = "BLENDED"

    return {"name": mat.name, "created": True}


_MAP_PATTERNS = [
    # (role, filename keywords) - first match wins, so specific names come first
    ("normal", ("normal_gl", "nor_gl", "normalgl", "_normal", "_nor", "_nrm", "normal")),
    ("roughness", ("roughness", "_rough", "rough")),
    ("metallic", ("metallic", "metalness", "_metal")),
    ("displacement", ("displacement", "_disp", "height", "_bump")),
    ("ao", ("ambientocclusion", "_ao", "occlusion")),
    ("alpha", ("opacity", "alpha", "_mask")),
    ("emission", ("emissive", "emission")),
    ("base_color", ("basecolor", "base_color", "albedo", "diffuse", "_diff", "_col", "color")),
]
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp", ".tga", ".bmp")


def _classify_maps(folder):
    found = {}
    for entry in sorted(os.listdir(folder)):
        low = entry.lower()
        if not low.endswith(_IMAGE_EXT) or "preview" in low or "_dx" in low:
            continue
        for role, keys in _MAP_PATTERNS:
            if any(k in low for k in keys):
                found.setdefault(role, os.path.join(folder, entry))
                break
    return found


def create_pbr_material(name: str, folder: str = "", maps: dict = None, object_name: str = "",
                        scale: float = 1.0, projection: str = "auto") -> dict:
    """Build a PBR material from local texture files.

    folder: directory with maps recognised by filename (basecolor/albedo, roughness, metallic,
    normal, displacement/height, ao, opacity, emission). maps: explicit {role: filepath}.
    projection: uv, box or auto (box when the object has no UV map).
    """
    textures = {}
    if folder:
        if not os.path.isdir(folder):
            raise ValueError(f"Directory not found: {folder}")
        textures.update(_classify_maps(folder))
    textures.update(maps or {})
    if not textures:
        raise ValueError("No texture maps found (pass folder= or maps=)")
    for role, path in textures.items():
        if not os.path.isfile(path):
            raise ValueError(f"{role} map not found: {path}")

    obj = bpy.data.objects.get(object_name) if object_name else None
    use_box = projection == "box" or (projection == "auto" and obj is not None and obj.type == "MESH"
                                      and not obj.data.uv_layers)
    mat = bpy.data.materials.new(name=name)
    bsdf = _principled(mat)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    output = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")
    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-1200, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-1000, 0)
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    links.new(coord.outputs["Object" if use_box else "UV"], mapping.inputs["Vector"])

    def image_node(role, y, non_color=True):
        tex = nodes.new("ShaderNodeTexImage")
        tex.location = (-700, y)
        tex.image = bpy.data.images.load(textures[role], check_existing=True)
        if non_color:
            tex.image.colorspace_settings.is_data = True
        if use_box:
            tex.projection = "BOX"
            tex.projection_blend = 0.2
        links.new(mapping.outputs["Vector"], tex.inputs["Vector"])
        return tex

    used = {}
    if "base_color" in textures:
        tex = image_node("base_color", 400, non_color=False)
        color_out = tex.outputs["Color"]
        if "ao" in textures:
            ao = image_node("ao", 650)
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.location = (-350, 450)
            mix.inputs["Factor"].default_value = 1.0
            links.new(color_out, mix.inputs[6])
            links.new(ao.outputs["Color"], mix.inputs[7])
            color_out = mix.outputs[2]
            used["ao"] = textures["ao"]
        links.new(color_out, bsdf.inputs["Base Color"])
        used["base_color"] = textures["base_color"]
    for role, socket, y in (("roughness", "Roughness", 150), ("metallic", "Metallic", -100),
                            ("alpha", "Alpha", -350)):
        if role in textures:
            tex = image_node(role, y)
            links.new(tex.outputs["Color"], bsdf.inputs[socket])
            used[role] = textures[role]
    if "alpha" in textures:
        mat.surface_render_method = "BLENDED"
    if "emission" in textures:
        tex = image_node("emission", -600, non_color=False)
        links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = 1.0
        used["emission"] = textures["emission"]
    if "normal" in textures:
        tex = image_node("normal", -850)
        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-350, -850)
        links.new(tex.outputs["Color"], normal_map.inputs["Color"])
        links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])
        used["normal"] = textures["normal"]
    if "displacement" in textures:
        tex = image_node("displacement", -1100)
        disp = nodes.new("ShaderNodeDisplacement")
        disp.location = (-100, -1100)
        disp.inputs["Midlevel"].default_value = 0.5
        disp.inputs["Scale"].default_value = 0.1
        links.new(tex.outputs["Color"], disp.inputs["Height"])
        links.new(disp.outputs["Displacement"], output.inputs["Displacement"])
        mat.displacement_method = "BOTH"
        used["displacement"] = textures["displacement"]

    if obj is not None and hasattr(obj.data, "materials"):
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
    return {"name": mat.name, "maps": used, "projection": "box" if use_box else "uv",
            "assigned_to": obj.name if obj else None}


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

    if mat.node_tree is None:
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
register_handler("create_pbr_material", create_pbr_material)
register_handler("assign_material", assign_material)
register_handler("set_material_property", set_material_property)
