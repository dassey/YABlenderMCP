"""The usage guide (skills/blender-mcp/SKILL.md) served over MCP, for clients without Agent Skills support."""

import os

from .compat import READ, FastMCP

GUIDE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "skills", "blender-mcp", "SKILL.md")


def guide_text() -> str:
    """SKILL.md without its YAML front matter."""
    with open(GUIDE_PATH, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        text = text.split("---", 2)[2]
    return text.strip()


def register(mcp: FastMCP, groups: list[str]):
    @mcp.tool(annotations=READ)
    def get_usage_guide() -> str:
        """How to work well with these Blender tools: what is available, which tool to use for
        what, how to check results, units, undo, the 3D-print and 2D-to-3D workflows, Blender 5.1
        API pitfalls and what errors mean. Read it once before multi-step work."""
        return guide_text() + f"\n\nTool groups enabled in this session: {', '.join(groups)}."

    @mcp.resource("blender://guide", name="usage_guide", mime_type="text/markdown",
                  description="How to use the Blender tools well (same text as get_usage_guide)")
    def usage_guide() -> str:
        return guide_text()
