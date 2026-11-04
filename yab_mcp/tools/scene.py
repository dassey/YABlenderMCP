"""Scene and object MCP tools."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def get_scene_info(query: str = "", types: Optional[list[str]] = None, limit: int = 100, offset: int = 0,
                       fields: Optional[list[str]] = None) -> str:
        """Get an overview of the current Blender scene.

        Returns objects with name, type, location, visibility, dimensions (modifiers
        included) and vertex/face counts, plus active/selected objects, mode and units.
        query filters by name, types by object type (MESH, LIGHT...). Paginate with
        limit/offset (has_more/next_offset). Extra fields: ground (on ground / floating),
        bbox, rotation, scale, materials, modifiers, collections.
        """
        return send("get_scene_info", params_of(query=query or None, types=types, limit=limit, offset=offset,
                                                fields=fields))

    @mcp.tool(annotations=READ)
    def get_object_info(name: str) -> str:
        """Get detailed information about a specific object.

        Returns transform (rotation also in degrees), dimensions, world bounding box,
        parent/children, collections, materials, modifiers, constraints, mesh stats
        (with modifiers evaluated), UV maps, shape keys, light or camera settings.
        """
        return send("get_object_info", {"name": name})

    @mcp.tool(annotations=EDIT)
    def create_object(type: str, name: str = "", location: Optional[list[float]] = None,
                      rotation: Optional[list[float]] = None, scale: Optional[list[float]] = None,
                      params: Optional[dict[str, Any]] = None) -> str:
        """Create a new object in the scene and return its world bounding box.

        Types: cube, sphere, ico_sphere, cylinder, cone, torus, plane, circle, grid,
        monkey, empty, camera, light, text, bezier_curve, bezier_circle, armature.
        rotation is in radians. scale is baked into the mesh (object scale stays 1).
        params go to the primitive operator, e.g. {"radius": 0.5, "depth": 2,
        "vertices": 6} for a cylinder, {"size": 20} for a cube, {"body": "Hello"} for text.
        Note: Blender's default cube is 2 units wide and the cylinder 2 units tall.
        """
        return send("create_object", params_of(type=type, name=name or None, location=location,
                                               rotation=rotation, scale=scale, params=params))

    @mcp.tool(annotations=DESTRUCTIVE)
    def delete_objects(names: list[str]) -> str:
        """Delete objects from the scene by name.

        Returns which objects were deleted and which were not found.
        """
        return send("delete_objects", {"names": names})

    @mcp.tool(annotations=EDIT)
    def select_objects(names: list[str], deselect_others: bool = True) -> str:
        """Select objects by name.

        By default deselects all other objects first.
        The last object in the list becomes the active object.
        """
        return send("select_objects", {"names": names, "deselect_others": deselect_others})

    @mcp.tool(annotations=EDIT)
    def set_transform(name: str, location: Optional[list[float]] = None, rotation: Optional[list[float]] = None,
                      scale: Optional[list[float]] = None, relative: bool = False, degrees: bool = False) -> str:
        """Set the transform (location, rotation, scale) of an object.

        Each parameter is an [x, y, z] list; only provided values change. Rotation is
        in radians unless degrees=True. relative=True adds to location/rotation and
        multiplies scale. Returns the new and previous values.
        """
        return send("set_transform", params_of(name=name, location=location, rotation=rotation, scale=scale,
                                               relative=relative, degrees=degrees))

    @mcp.tool(annotations=EDIT)
    def duplicate_object(name: str, linked: bool = False, new_name: str = "",
                         offset: Optional[list[float]] = None) -> str:
        """Duplicate an object.

        If linked=True, the duplicate shares the same mesh data. offset moves the copy.
        Returns the new object's name, type, and location.
        """
        return send("duplicate_object", params_of(name=name, linked=linked, new_name=new_name or None,
                                                  offset=offset))

    @mcp.tool(annotations=EDIT)
    def parent_objects(child: str, parent: str, keep_transform: bool = True) -> str:
        """Set a parent-child relationship between two objects (parent="" clears it).

        keep_transform keeps the child where it is in the world.
        """
        return send("parent_objects", {"child": child, "parent": parent, "keep_transform": keep_transform})

    @mcp.tool(annotations=READ)
    def get_collections() -> str:
        """Get the full collection hierarchy of the scene.

        Returns a nested structure with collection names,
        their objects, and child collections.
        """
        return send("get_collections")

    @mcp.tool(annotations=EDIT)
    def move_to_collection(object_name: str, collection_name: str, parent_collection: str = "") -> str:
        """Move an object to a collection.

        Creates the collection if it doesn't exist (inside parent_collection if given).
        Removes the object from all current collections first.
        """
        return send("move_to_collection", params_of(object_name=object_name, collection_name=collection_name,
                                                    parent_collection=parent_collection or None))

    @mcp.tool(annotations=EDIT)
    def rename_object(name: str, new_name: str) -> str:
        """Rename an object (and its mesh/curve data when not shared)."""
        return send("rename_object", {"name": name, "new_name": new_name})

    @mcp.tool(annotations=EDIT)
    def set_visibility(names: list[str], hide: Optional[bool] = None, hide_render: Optional[bool] = None,
                       hide_select: Optional[bool] = None) -> str:
        """Hide or show objects in the viewport (hide), in renders (hide_render), or lock selection."""
        return send("set_visibility", params_of(names=names, hide=hide, hide_render=hide_render,
                                                hide_select=hide_select))

    @mcp.tool(annotations=DESTRUCTIVE)
    def join_objects(names: list[str], new_name: str = "") -> str:
        """Join objects of the same type into the first one; the others stop existing."""
        return send("join_objects", params_of(names=names, new_name=new_name or None))

    @mcp.tool(annotations=EDIT)
    def apply_transforms(names: list[str], location: bool = False, rotation: bool = True,
                         scale: bool = True) -> str:
        """Bake rotation/scale (and optionally location) into the object data.

        Do this before booleans, modifiers that depend on scale, and exports.
        """
        return send("apply_transforms", {"names": names, "location": location, "rotation": rotation,
                                         "scale": scale})

    @mcp.tool(annotations=EDIT)
    def set_origin(names: list[str], mode: str = "bottom_center") -> str:
        """Move object origins without moving the geometry.

        Modes: bottom_center (centre of the bounding box floor - good for placing on a
        surface or print bed), geometry, center_of_mass, center_of_volume, cursor,
        world_origin.
        """
        return send("set_origin", {"names": names, "mode": mode})

    @mcp.tool(annotations=EDIT)
    def place_object(name: str, target: str = "", position: str = "on_top", gap: float = 0.0,
                     align: str = "center") -> str:
        """Place an object against another using bounding boxes - no coordinate guessing.

        position: on_top, below, left, right, front, back, center, or on_ground (z=0,
        no target needed). gap: distance between the boxes. align: center (centre on the
        target's other axes; side placements share its floor) or keep.
        """
        return send("place_object", params_of(name=name, target=target or None, position=position, gap=gap,
                                              align=align))

    @mcp.tool(annotations=EDIT)
    def convert_to_mesh(names: list[str], keep_original: bool = False) -> str:
        """Convert curves, text, surfaces or metaballs (and their modifiers) into meshes.

        Needed before mesh editing, booleans on text/curves, and print export.
        """
        return send("convert_to_mesh", {"names": names, "keep_original": keep_original})
