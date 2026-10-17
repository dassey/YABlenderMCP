"""MCP SDK import shim (mcp 1.x ships FastMCP, mcp 2.x renamed it to MCPServer) plus shared tool settings."""

try:
    from mcp.server.mcpserver import MCPServer as _Base, Image
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Base, Image
    from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations


class FastMCP(_Base):
    async def call_tool(self, name, arguments, *args, **kwargs):
        # Some clients send null for every optional argument the model left out; treat it as omitted.
        if isinstance(arguments, dict):
            arguments = {k: v for k, v in arguments.items() if v is not None}
        return await super().call_tool(name, arguments, *args, **kwargs)


# Tool annotations let clients tell read-only tools from ones that change or delete things.
READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
EDIT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

__all__ = ["FastMCP", "Image", "ToolError", "READ", "EDIT", "DESTRUCTIVE"]
