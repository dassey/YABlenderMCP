"""BlenderMCP Server - MCP entry point.

Speaks MCP (stdio) to Claude/antigravity, forwards commands to Blender addon over TCP.
"""

import sys
import os
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("BlenderMCP")

mcp = FastMCP("BlenderMCP", log_level="WARNING")

# Register tool modules
from server.tools import code, scene, viewport, materials, modifiers, io_tools, animation, nodes, render, mesh

for module in [code, scene, viewport, materials, modifiers, io_tools, animation, nodes, render, mesh]:
    module.register(mcp)


def main():
    logger.info("BlenderMCP server starting (stdio transport)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
