# <img src="logo.jpg" width="48" align="center"> YABlenderMCP

MCP server that gives AI agents (Claude, antigravity, etc.) full control over Blender 5.1.

**48 tools** across 10 domains. No external APIs, no keys, no cloud. Everything runs locally.

## Setup

### 1. Install the Blender addon

Download or build the addon zip, then in Blender:

1. Edit > Preferences > Add-ons
2. Click the dropdown arrow (top right) > **Install from Disk...**
3. Browse to `addon.zip` (or drag-drop it onto the Blender window)
4. Enable "BlenderMCP" in the addon list

On Windows, run `install_addon.bat` — on first run it builds the zip for you. After the addon is installed in Blender, re-running the script syncs your source code changes directly into Blender's addon folder so you don't have to reinstall the zip every time you edit the code.

On Linux/Mac:
```bash
cd addon && zip -r ../addon.zip . && cd ..
```

### 2. Start the addon server

In the 3D viewport, press N to open the sidebar. Find the **BlenderMCP** tab and click **Start Server**.

### 3. Configure your MCP client

Add to your MCP client config (Claude Code, antigravity, etc.):

```json
{
  "mcpServers": {
    "blender": {
      "command": "python",
      "args": ["<path-to>/server/main.py"],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

### 4. Install Python dependency

```bash
pip install "mcp[cli]>=1.0.0"
```

## Architecture

```
AI Client  <--stdio/MCP-->  server/main.py  <--TCP:9001-->  Blender Addon
```

Two parts:
- **server/** — Standalone Python process. Speaks MCP (stdio) to AI clients. Forwards commands to Blender over TCP.
- **addon/** — Runs inside Blender. Listens on TCP, executes commands on Blender's main thread, sends results back.

## Tools

| Domain | Tools | Examples |
|--------|-------|---------|
| Code | 1 | `execute_blender_code` — run any Python in Blender |
| Scene | 10 | get/create/delete objects, transforms, collections |
| Mesh | 4 | vertex data, positions, vertex groups |
| Materials | 5 | create, assign, inspect, modify materials |
| Modifiers | 5 | add, remove, apply, configure modifiers |
| Viewport | 4 | screenshots, shading, view angles |
| I/O | 5 | import/export FBX, OBJ, GLB, STL, PLY, ABC |
| Animation | 5 | keyframes, timeline |
| Nodes | 5 | shader and geometry node trees |
| Render | 4 | settings, render frames/animations |

The `execute_blender_code` tool is the workhorse — the AI can run any Python in Blender directly. The structured tools are shortcuts for common operations.

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `BLENDER_MCP_HOST` | `127.0.0.1` | Addon host |
| `BLENDER_MCP_PORT` | `9001` | Addon port |
| `PYTHONUTF8` | — | Set to `1` on Windows |

## Testing

With Blender running and the addon server started:

```bash
python tests/test_connection.py
```
