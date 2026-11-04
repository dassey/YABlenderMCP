"""Material MCP tools."""

from typing import Any, Optional

from ..compat import EDIT, READ, FastMCP
from ..connection import jparse, params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def list_materials() -> str:
        """List all materials in the Blender file.

        Returns each material's name and number of users.
        """
        return send("list_materials")

    @mcp.tool(annotations=READ)
    def get_material_info(name: str) -> str:
        """Get detailed info about a material's node tree.

        Returns all nodes with their type, label, location, and input
        default values, plus all links between nodes.
        """
        return send("get_material_info", {"name": name})

    @mcp.tool(annotations=EDIT)
    def create_material(name: str, color: Any = None, metallic: Optional[float] = None,
                        roughness: Optional[float] = None, preset: str = "", emission_color: Any = None,
                        emission_strength: Optional[float] = None, alpha: Optional[float] = None) -> str:
        """Create a new material with a Principled BSDF shader.

        color: [R, G, B] in 0-1. preset: plastic, matte, rubber, metal, brushed_metal,
        gold, copper, glass, frosted_glass, ceramic, emissive (explicit values override
        the preset). alpha < 1 makes it transparent.
        """
        return send("create_material", params_of(name=name, color=jparse(color), metallic=metallic,
                                                 roughness=roughness, preset=preset or None,
                                                 emission_color=jparse(emission_color),
                                                 emission_strength=emission_strength, alpha=alpha))

    @mcp.tool(annotations=EDIT)
    def create_pbr_material(name: str, folder: str = "", maps: Optional[dict[str, str]] = None,
                            object_name: str = "", scale: float = 1.0, projection: str = "auto") -> str:
        """Build a PBR material from local texture files and optionally assign it.

        folder: directory whose maps are recognised by filename (basecolor/albedo/diffuse,
        roughness, metallic, normal (GL preferred), displacement/height, ao, opacity,
        emission). maps: explicit {"base_color": path, "normal": path, ...}.
        projection: uv, box, or auto (box when the object has no UVs). scale tiles the texture.
        """
        return send("create_pbr_material", params_of(name=name, folder=folder or None, maps=maps,
                                                     object_name=object_name or None, scale=scale,
                                                     projection=projection))

    @mcp.tool(annotations=EDIT)
    def assign_material(object_name: str, material_name: str, slot: int = -1) -> str:
        """Assign a material to an object.

        If slot is -1 (default), appends a new material slot.
        Otherwise sets the material in the specified slot index.
        """
        return send("assign_material", {
            "object_name": object_name,
            "material_name": material_name,
            "slot": slot,
        })

    @mcp.tool(annotations=EDIT)
    def set_material_property(material_name: str, property: str, value: Any) -> str:
        """Set a Principled BSDF input value on a material.

        The property is the input name (e.g. "Base Color", "Metallic", "Roughness",
        "Transmission Weight", "Emission Strength"). Value is a number, or a list like
        [R, G, B, A] for colours.
        """
        return send("set_material_property", {
            "material_name": material_name,
            "property": property,
            "value": jparse(value),
        })
