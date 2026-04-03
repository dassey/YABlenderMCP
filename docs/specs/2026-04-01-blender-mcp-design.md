# Blender MCP — Design Spec

**Date:** 2026-04-01
**Goal:** Build a custom MCP server that gives Claude (and antigravity) full control over Blender 5.1 — no external APIs, no third-party keys, maximum power.

---

## 1. Architecture Overview

Two processes that talk to each other:

1. **MCP Server** — A standalone Python script that Claude/antigravity launch. Communicates with AI clients via stdio (standard MCP protocol). Forwards commands to Blender over a local TCP socket.

2. **Blender Addon** — A Python addon installed in Blender 5.1. Opens a TCP socket on `localhost:9876`. Receives commands from the MCP server, executes them inside Blender, sends results back.

```
Claude/Antigravity  <--stdio-->  MCP Server  <--TCP:9876-->  Blender Addon (inside Blender)
```

Why two parts? Blender's Python interpreter is locked inside Blender's process. You can't run `import bpy` from outside. So the MCP server acts as a translator: it speaks MCP to the AI client and speaks simple JSON to the addon running inside Blender.

---

## 2. Project Structure

```
C:\Users\msist\Desktop\Agents\MCP\Blender\
├── server/                     # MCP Server (standalone Python)
│   ├── __init__.py
│   ├── main.py                 # Entry point — starts MCP server
│   ├── connection.py           # TCP connection manager to Blender
│   └── tools/                  # MCP tool definitions, one file per domain
│       ├── __init__.py
│       ├── scene.py            # Scene & object tools
│       ├── mesh.py             # Mesh/geometry tools
│       ├── materials.py        # Material & shader tools
│       ├── modifiers.py        # Modifier stack tools
│       ├── viewport.py         # Screenshot & viewport tools
│       ├── io_tools.py         # Import/export tools
│       ├── animation.py        # Keyframe & timeline tools
│       ├── nodes.py            # Node editor tools (shader, geometry, compositor)
│       ├── render.py           # Render tools
│       └── code.py             # execute_code (the escape hatch)
├── addon/                      # Blender Addon
│   ├── __init__.py             # bl_info, register/unregister
│   ├── server.py               # TCP server (runs inside Blender)
│   └── handlers/               # Command handlers by domain
│       ├── __init__.py
│       ├── scene.py
│       ├── mesh.py
│       ├── materials.py
│       ├── modifiers.py
│       ├── viewport.py
│       ├── io_handlers.py
│       ├── animation.py
│       ├── nodes.py
│       ├── render.py
│       └── code.py
├── docs/
│   └── specs/
│       └── 2026-04-01-blender-mcp-design.md  (this file)
├── tests/
│   ├── test_connection.py
│   └── test_tools.py
└── requirements.txt            # mcp>=0.9.0 (only dependency)
```

---

## 3. Communication Protocol

### MCP Server <-> Blender Addon (TCP, port 9876)

Newline-delimited JSON. Each message is one JSON object followed by `\n`.

**Request (server -> addon):**
```json
{"type": "get_scene_info", "params": {}}
{"type": "execute_code", "params": {"code": "bpy.ops.mesh.primitive_cube_add()"}}
{"type": "get_object_info", "params": {"name": "Cube"}}
```

**Response (addon -> server):**
```json
{"status": "success", "result": {"name": "Scene", "object_count": 3, ...}}
{"status": "error", "message": "Object not found: Foo"}
```

### Windows binary mode

On Windows, the MCP server sets stdin/stdout to binary mode to prevent `\r\n` corruption (the same fix antigravity uses):
```python
if sys.platform == 'win32':
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
```

### Thread safety

The Blender addon receives commands on a background TCP thread but executes them on Blender's main thread using `bpy.app.timers.register()`. This is required because `bpy` operations are not thread-safe.

---

## 4. Tool Catalog

### 4.1 The Escape Hatch: `execute_code`

The most important tool. Executes arbitrary Python inside Blender. This means Claude can do *anything* — if a structured tool doesn't exist for something, Claude writes the bpy Python directly.

```
execute_code(code: str) -> {executed: bool, result: str, error?: str}
```

- Captures stdout output and returns it
- Returns exceptions as error messages (doesn't crash)
- Has access to `bpy`, `bmesh`, `mathutils`, `numpy`, and everything in Blender's Python environment

### 4.2 Scene Tools (`tools/scene.py`)

| Tool | Description |
|------|-------------|
| `get_scene_info()` | List all objects with types, locations. Scene metadata. |
| `get_object_info(name)` | Detailed info: transform, materials, mesh stats, bounding box, modifiers, constraints, parent/children. |
| `create_object(type, name?, location?, ...)` | Create primitives (cube, sphere, cylinder, plane, etc.) or empties. |
| `delete_objects(names)` | Delete one or more objects by name. |
| `select_objects(names)` | Set selection state. |
| `set_transform(name, location?, rotation?, scale?)` | Set object transform. |
| `duplicate_object(name, linked?)` | Duplicate an object. |
| `parent_objects(child, parent)` | Set parent-child relationship. |
| `get_collections()` | List collections and their contents. |
| `move_to_collection(object_name, collection_name)` | Move object between collections. |

### 4.3 Mesh Tools (`tools/mesh.py`)

| Tool | Description |
|------|-------------|
| `get_mesh_data(name, include_vertices?, include_faces?)` | Get vertex positions, face indices, normals. Optionally limited to selection. |
| `set_vertex_positions(name, vertex_indices, positions)` | Directly move vertices. |
| `get_vertex_groups(name)` | List vertex groups and their weights. |
| `set_vertex_group(name, group_name, vertex_indices, weight)` | Assign vertices to groups. |
| `mesh_select(name, mode, indices)` | Select vertices/edges/faces by index. |
| `apply_mesh_operation(name, operation, params)` | Subdivide, extrude, inset, bevel, dissolve, merge, separate, join. |

### 4.4 Material Tools (`tools/materials.py`)

| Tool | Description |
|------|-------------|
| `list_materials()` | All materials in the file. |
| `get_material_info(name)` | Node tree structure, settings. |
| `create_material(name, color?, metallic?, roughness?)` | Quick PBR material creation. |
| `assign_material(object_name, material_name, slot?)` | Assign material to object. |
| `set_material_property(material_name, property, value)` | Set Principled BSDF inputs. |

### 4.5 Modifier Tools (`tools/modifiers.py`)

| Tool | Description |
|------|-------------|
| `list_modifiers(object_name)` | All modifiers on an object. |
| `add_modifier(object_name, type, name?, settings?)` | Add modifier (subdivision, boolean, mirror, array, solidify, etc.). |
| `set_modifier_property(object_name, modifier_name, property, value)` | Change modifier settings. |
| `apply_modifier(object_name, modifier_name)` | Apply a modifier. |
| `remove_modifier(object_name, modifier_name)` | Remove a modifier. |

### 4.6 Viewport Tools (`tools/viewport.py`)

| Tool | Description |
|------|-------------|
| `get_viewport_screenshot(max_size?, format?)` | Capture 3D viewport as base64 image. Returns PNG or JPEG. Claude can see the scene. |
| `render_image(width?, height?, format?, camera?)` | Render from camera, return as base64. |
| `set_viewport_shading(mode)` | Wireframe, solid, material preview, rendered. |
| `set_view(angle)` | Front, back, left, right, top, bottom, or camera view. |
| `frame_selected()` | Zoom to fit selected objects. |

### 4.7 Import/Export Tools (`tools/io_tools.py`)

| Tool | Description |
|------|-------------|
| `import_file(filepath, format?)` | Import FBX, OBJ, GLB/GLTF, STL, PLY, ABC. Auto-detects format from extension. |
| `export_file(filepath, format?, selection_only?)` | Export to any supported format. |
| `save_blend(filepath?)` | Save the .blend file. |
| `open_blend(filepath)` | Open a .blend file. |
| `list_directory(path, filter?)` | List files in a directory (for finding models to import). |

### 4.8 Animation Tools (`tools/animation.py`)

| Tool | Description |
|------|-------------|
| `set_keyframe(object_name, property, frame?, value?)` | Insert keyframe. |
| `delete_keyframe(object_name, property, frame)` | Remove keyframe. |
| `set_frame(frame)` | Set current frame. |
| `get_timeline_info()` | Frame range, current frame, FPS. |
| `set_timeline(start?, end?, fps?)` | Configure timeline. |

### 4.9 Node Tools (`tools/nodes.py`)

| Tool | Description |
|------|-------------|
| `get_node_tree(material_name_or_object)` | Full node tree: nodes, connections, values. |
| `add_node(tree_owner, node_type, location?)` | Add a node to a node tree. |
| `connect_nodes(tree_owner, from_node, from_output, to_node, to_input)` | Connect two nodes. |
| `set_node_value(tree_owner, node_name, input_name, value)` | Set a node input value. |
| `remove_node(tree_owner, node_name)` | Remove a node. |

### 4.10 Render Tools (`tools/render.py`)

| Tool | Description |
|------|-------------|
| `get_render_settings()` | Engine, resolution, samples, output path, format. |
| `set_render_settings(engine?, resolution_x?, resolution_y?, samples?, ...)` | Configure render settings. |
| `render_frame(frame?, output_path?)` | Render a single frame. |
| `render_animation(start?, end?, output_path?)` | Render animation sequence. |

---

## 5. Addon UI

Minimal N-panel in the 3D viewport sidebar under a "BlenderMCP" tab:

- **Port** field (default: 9876)
- **Start/Stop Server** button
- **Status indicator** (running/stopped, connected clients count)

No external API toggles, no third-party integrations. Clean and simple.

---

## 6. Key Design Decisions

### Why stdio transport?
Both Claude Code and antigravity support it natively. Zero network configuration. The MCP server is launched as a subprocess — it just reads stdin and writes stdout. Simplest possible setup.

### Why port 9876?
Arbitrary, but different from the 9001 you used before and 9876 from the old BlenderMCP addon. Actually, let's use **9876** since that's what the reference addon used and it's a clean number. Configurable via the addon UI.

### Why modular tool files?
Each domain (scene, mesh, materials...) is one file on both sides. To add a new tool category (e.g., physics simulation), you add one file in `server/tools/` and one in `addon/handlers/`. Nothing else changes.

### Why execute_code is the foundation?
It's impossible to predict every Blender operation an AI might need. The structured tools handle the common 80%. The `execute_code` escape hatch handles the other 20% — Claude just writes Python. This means V1 is immediately useful even before all structured tools are built.

### No external dependencies in the addon
The Blender addon uses only `bpy`, stdlib, and `numpy` (bundled with Blender). No pip installs inside Blender's Python. The MCP server needs only the `mcp` package.

---

## 7. Configuration

### Claude Code (`claude_desktop_config.json` or MCP settings):
```json
{
  "mcpServers": {
    "blender": {
      "command": "python",
      "args": ["C:/Users/msist/Desktop/Agents/MCP/Blender/server/main.py"],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

### Antigravity:
Same pattern — point it at `server/main.py` via stdio.

### Environment variables:
- `BLENDER_MCP_HOST` — default `127.0.0.1`
- `BLENDER_MCP_PORT` — default `9876`
- `PYTHONUTF8` — should be `1` on Windows

---

## 8. Error Handling

- **Connection lost**: MCP server returns clear error "Not connected to Blender. Make sure Blender is running and the addon server is started." Tools fail gracefully, not crash.
- **Command timeout**: 180 second timeout per command. Long operations (rendering) get polled instead.
- **Code execution errors**: `execute_code` catches all exceptions and returns the traceback as a string. Never crashes the addon.
- **Blender thread safety**: All commands execute on Blender's main thread via `bpy.app.timers.register()`. The TCP listener runs on a daemon thread.

---

## 9. What This Does NOT Include

- No PolyHaven, Sketchfab, Hyper3D, Hunyuan3D, or any external API
- No API keys of any kind
- No telemetry or analytics
- No cloud connectivity
- No authentication (localhost only)

Everything runs locally on your machine. Period.

---

## 10. V1 Build Order

1. **Addon TCP server** — Get Blender listening on a socket, executing `execute_code`
2. **MCP server with `execute_code` only** — Minimal but fully functional. Claude can already do everything.
3. **Viewport screenshot tool** — So Claude can see what it's doing
4. **Scene tools** — `get_scene_info`, `get_object_info`, `create_object`, etc.
5. **Remaining structured tools** — Mesh, materials, modifiers, I/O, animation, nodes, render
6. **Polish** — Error messages, edge cases, documentation

After step 2, the MCP is already usable. Steps 3-6 add convenience.
