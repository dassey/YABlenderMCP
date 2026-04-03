"""Scene and object MCP tools."""

import json
from typing import Optional

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def get_scene_info() -> str:
        """Get an overview of the current Blender scene.

        Returns all objects with name, type, location, visibility,
        and vertex/face counts for meshes. Also includes active and
        selected objects and the current frame.
        """
        conn = get_connection()
        result = conn.send_command("get_scene_info", {})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_object_info(name: str) -> str:
        """Get detailed information about a specific object.

        Returns transform, parent/children, materials, modifiers,
        constraints, and mesh stats with bounding box for mesh objects.
        """
        conn = get_connection()
        result = conn.send_command("get_object_info", {"name": name})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def create_object(type: str, name: str = "", location: Optional[list] = None) -> str:
        """Create a new object in the scene.

        Supported types: cube, sphere, ico_sphere, cylinder, cone,
        torus, plane, circle, monkey, empty, camera, light.
        Optionally set a name and [x, y, z] location.
        """
        conn = get_connection()
        params = {"type": type}
        if name:
            params["name"] = name
        if location is not None:
            params["location"] = location
        result = conn.send_command("create_object", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def delete_objects(names: list) -> str:
        """Delete objects from the scene by name.

        Accepts a list of object names to remove.
        Returns which objects were successfully deleted.
        """
        conn = get_connection()
        result = conn.send_command("delete_objects", {"names": names})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def select_objects(names: list, deselect_others: bool = True) -> str:
        """Select objects by name.

        By default deselects all other objects first.
        The last object in the list becomes the active object.
        """
        conn = get_connection()
        result = conn.send_command("select_objects", {"names": names, "deselect_others": deselect_others})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def set_transform(name: str, location: Optional[list] = None, rotation: Optional[list] = None, scale: Optional[list] = None) -> str:
        """Set the transform (location, rotation, scale) of an object.

        Each parameter is an [x, y, z] list. Only provided values are changed.
        """
        conn = get_connection()
        params = {"name": name}
        if location is not None:
            params["location"] = location
        if rotation is not None:
            params["rotation"] = rotation
        if scale is not None:
            params["scale"] = scale
        result = conn.send_command("set_transform", params)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def duplicate_object(name: str, linked: bool = False) -> str:
        """Duplicate an object.

        If linked=True, the duplicate shares the same mesh data.
        Returns the new object's name, type, and location.
        """
        conn = get_connection()
        result = conn.send_command("duplicate_object", {"name": name, "linked": linked})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def parent_objects(child: str, parent: str) -> str:
        """Set a parent-child relationship between two objects.

        The child object will inherit the parent's transforms.
        """
        conn = get_connection()
        result = conn.send_command("parent_objects", {"child": child, "parent": parent})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def get_collections() -> str:
        """Get the full collection hierarchy of the scene.

        Returns a nested structure with collection names,
        their objects, and child collections.
        """
        conn = get_connection()
        result = conn.send_command("get_collections", {})
        return json.dumps(result, indent=2)

    @mcp.tool()
    def move_to_collection(object_name: str, collection_name: str) -> str:
        """Move an object to a collection.

        Creates the collection if it doesn't exist.
        Removes the object from all current collections first.
        """
        conn = get_connection()
        result = conn.send_command("move_to_collection", {"object_name": object_name, "collection_name": collection_name})
        return json.dumps(result, indent=2)
