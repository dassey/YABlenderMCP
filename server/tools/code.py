"""execute_code MCP tool."""

from mcp.server.fastmcp import FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool()
    def execute_blender_code(code: str) -> str:
        """Execute arbitrary Python code inside Blender.

        The code runs with access to bpy, bmesh, mathutils, numpy, and everything
        in Blender's scripting console. Stdout is captured and returned.
        Use this for any operation that doesn't have a dedicated tool.
        """
        conn = get_connection()
        result = conn.send_command("execute_code", {"code": code})
        if result.get("executed"):
            output = result.get("result", "")
            return output if output else "(executed successfully, no output)"
        else:
            error = result.get("error", "Unknown error")
            output = result.get("result", "")
            msg = f"Error:\n{error}"
            if output:
                msg = f"Partial output:\n{output}\n\n{msg}"
            return msg
