bl_info = {
    "name": "BlenderMCP",
    "author": "Custom",
    "version": (1, 0, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > BlenderMCP",
    "description": "MCP server for AI control of Blender",
    "category": "Interface",
}


def register():
    from . import server as _server_module
    _server_module.register()


def unregister():
    from . import server as _server_module
    _server_module.unregister()
