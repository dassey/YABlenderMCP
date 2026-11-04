bl_info = {
    "name": "YABlenderMCP",
    "author": "Custom",
    "version": (2, 2, 0),
    "blender": (5, 1, 0),
    "location": "View3D > Sidebar > YABlenderMCP",
    "description": "MCP server for AI control of Blender",
    "category": "Interface",
}


def register():
    from . import server as _server_module
    _server_module.register()


def unregister():
    from . import server as _server_module
    _server_module.unregister()
