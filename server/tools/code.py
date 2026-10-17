"""execute_code MCP tool."""

import json

from ..compat import DESTRUCTIVE, FastMCP
from ..connection import get_connection


def register(mcp: FastMCP):
    @mcp.tool(annotations=DESTRUCTIVE)
    def execute_blender_code(code: str, timeout: float = 170.0) -> str:
        """Execute arbitrary Python code inside Blender.

        Pre-imported: bpy, bmesh, mathutils (Vector, Matrix, Euler, Quaternion),
        math, np (numpy), C (bpy.context), D (bpy.data). Stdout/stderr are captured.
        Assign a variable named `result` to get structured data back as JSON.
        Runaway code is stopped after `timeout` seconds. 3D-viewport operators work
        (the code runs with a viewport context). The whole run is one Ctrl+Z step.
        Use this for any operation that doesn't have a dedicated tool.
        """
        conn = get_connection()
        result = conn.send_command("execute_code", {"code": code, "timeout": timeout},
                                   timeout=timeout + 10 if timeout > 170 else None)
        output = result.get("result", "")
        parts = []
        if result.get("note"):
            parts.append(f"Note: {result['note']}")
        if output:
            parts.append(output if result.get("executed") else f"Partial output:\n{output}")
        if result.get("stderr"):
            parts.append(f"Stderr:\n{result['stderr']}")
        if "return_value" in result:
            parts.append("result = " + json.dumps(result["return_value"], ensure_ascii=False))
        if not result.get("executed"):
            parts.append(f"Error:\n{result.get('error', 'Unknown error')}")
        return "\n\n".join(parts) if parts else "(executed successfully, no output)"
