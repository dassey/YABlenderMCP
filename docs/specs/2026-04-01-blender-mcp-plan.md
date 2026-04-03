# Blender MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a two-part MCP (server + Blender addon) that gives Claude/antigravity full control over Blender 5.1, with execute_code as the foundation and structured tools for common operations.

**Architecture:** MCP server (FastMCP, stdio transport) communicates with a Blender addon over TCP (localhost:9876). The addon executes all commands on Blender's main thread via bpy.app.timers.register(). Modular tool files on both sides organized by domain.

**Tech Stack:** Python 3.11 (Blender bundled for addon), Python 3.x + mcp for server, bpy/bmesh/mathutils inside Blender.

---

## File Structure

```
C:\Users\msist\Desktop\Agents\MCP\Blender\
  server/
    __init__.py
    main.py                 - MCP entry point (FastMCP, stdio)
    connection.py           - TCP connection manager to Blender addon
    tools/
      __init__.py
      code.py               - execute_code escape hatch
      scene.py              - scene and object tools
      viewport.py           - screenshot, shading, view tools
      materials.py          - material tools
      modifiers.py          - modifier tools
      io_tools.py           - import/export tools
      animation.py          - keyframe/timeline tools
      nodes.py              - node editor tools
      render.py             - render tools
      mesh.py               - mesh data tools
  addon/
    __init__.py             - bl_info, register/unregister
    server.py               - TCP server + UI panel
    handlers/
      __init__.py           - handler registry
      code.py               - execute_code handler
      scene.py              - scene/object handlers
      viewport.py           - screenshot handlers
      materials.py          - material handlers
      modifiers.py          - modifier handlers
      io_handlers.py        - import/export handlers
      animation.py          - keyframe handlers
      nodes.py              - node tree handlers
      render.py             - render handlers
      mesh.py               - mesh data handlers
  tests/
    __init__.py
    test_connection.py      - smoke test
  install_addon.bat         - installs addon into Blender 5.1
  requirements.txt          - mcp[cli]>=1.0.0
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `server/__init__.py`, `server/tools/__init__.py`, `addon/__init__.py`, `addon/handlers/__init__.py`, `tests/__init__.py`, `requirements.txt`

- [ ] **Step 1: Create directories**

```bash
cd "C:/Users/msist/Desktop/Agents/MCP/Blender"
mkdir -p server/tools addon/handlers tests
```

- [ ] **Step 2: Create requirements.txt**

```
mcp[cli]>=1.0.0
```

- [ ] **Step 3: Create empty init files**

Create empty files: `server/__init__.py`, `server/tools/__init__.py`, `tests/__init__.py`

Write `server/tools/__init__.py`:
```python
"""MCP tool modules. Each module exposes a register(mcp) function."""
```

- [ ] **Step 4: Create addon/__init__.py**

```python
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
```

- [ ] **Step 5: Install dependencies**

```bash
pip install "mcp[cli]>=1.0.0"
```

- [ ] **Step 6: Init git and commit**

```bash
cd "C:/Users/msist/Desktop/Agents/MCP/Blender"
git init
git add requirements.txt server/__init__.py server/tools/__init__.py addon/__init__.py tests/__init__.py
git commit -m "feat: project scaffolding"
```

---

### Task 2: Addon TCP Server + UI Panel

**Files:**
- Create: `addon/server.py`

- [ ] **Step 1: Write addon/server.py**

This file contains:
- `BlenderMCPServer` class: TCP socket server on a daemon thread. Accepts JSON commands, dispatches to handlers on Blender's main thread via `bpy.app.timers.register()`, waits for result with `threading.Event`, sends JSON response back. 180s timeout.
- `BLENDERMCP_PT_Panel`: N-panel UI with port field, start/stop button, status label.
- `BLENDERMCP_OT_StartServer` / `BLENDERMCP_OT_StopServer`: Operators.
- `register()` / `unregister()`: Class registration, scene properties.

Key implementation details:
- Server socket: `socket.AF_INET`, `SO_REUSEADDR`, `listen(1)`, `settimeout(1.0)` on accept loop
- Client handling: `recv(65536)`, accumulate in buffer, try `json.loads`, on success dispatch
- Main thread dispatch: `threading.Event` + `bpy.app.timers.register(callback, first_interval=0.0)`. The callback sets `result_holder[0]` and calls `event.set()`. The client thread calls `event.wait(timeout=180)`.
- Dispatch method `_dispatch(command)`: extracts `type` and `params`, calls `handlers.get_handler(type)(**params)`, wraps in `{"status": "success", "result": ...}` or `{"status": "error", "message": ...}`

```python
"""TCP server that runs inside Blender, receives commands, dispatches to handlers."""

import bpy
import json
import socket
import threading
import traceback
from bpy.props import IntProperty, BoolProperty

from . import handlers


class BlenderMCPServer:
    def __init__(self, host="localhost", port=9876):
        self.host = host
        self.port = port
        self.running = False
        self.socket = None
        self.server_thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(1)
            self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
            self.server_thread.start()
            print(f"[BlenderMCP] Server started on {self.host}:{self.port}")
        except Exception as e:
            print(f"[BlenderMCP] Failed to start: {e}")
            self.stop()

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        self.server_thread = None
        print("[BlenderMCP] Server stopped")

    def _server_loop(self):
        self.socket.settimeout(1.0)
        while self.running:
            try:
                client, address = self.socket.accept()
                print(f"[BlenderMCP] Client connected: {address}")
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[BlenderMCP] Accept error: {e}")

    def _handle_client(self, client):
        client.settimeout(None)
        buffer = b""
        try:
            while self.running:
                data = client.recv(65536)
                if not data:
                    break
                buffer += data
                try:
                    command = json.loads(buffer.decode("utf-8"))
                    buffer = b""
                    result_event = threading.Event()
                    result_holder = [None]

                    def run_on_main():
                        try:
                            result_holder[0] = self._dispatch(command)
                        except Exception as e:
                            result_holder[0] = {"status": "error", "message": str(e)}
                            traceback.print_exc()
                        finally:
                            result_event.set()
                        return None

                    bpy.app.timers.register(run_on_main, first_interval=0.0)
                    result_event.wait(timeout=180.0)

                    response = result_holder[0] or {"status": "error", "message": "Command timed out (180s)"}
                    client.sendall(json.dumps(response).encode("utf-8"))
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"[BlenderMCP] Client error: {e}")
        finally:
            try:
                client.close()
            except Exception:
                pass
            print("[BlenderMCP] Client disconnected")

    def _dispatch(self, command):
        cmd_type = command.get("type")
        params = command.get("params", {})
        handler = handlers.get_handler(cmd_type)
        if handler is None:
            return {"status": "error", "message": f"Unknown command: {cmd_type}"}
        try:
            result = handler(**params)
            return {"status": "success", "result": result}
        except Exception as e:
            traceback.print_exc()
            return {"status": "error", "message": str(e)}


class BLENDERMCP_PT_Panel(bpy.types.Panel):
    bl_label = "BlenderMCP"
    bl_idname = "BLENDERMCP_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "BlenderMCP"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "blendermcp_port")
        if not scene.blendermcp_server_running:
            layout.operator("blendermcp.start_server", text="Start Server")
        else:
            layout.operator("blendermcp.stop_server", text="Stop Server")
            layout.label(text=f"Running on port {scene.blendermcp_port}")


class BLENDERMCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "blendermcp.start_server"
    bl_label = "Start BlenderMCP Server"

    def execute(self, context):
        if not hasattr(bpy.types, "_blendermcp_server") or bpy.types._blendermcp_server is None:
            bpy.types._blendermcp_server = BlenderMCPServer(port=context.scene.blendermcp_port)
        bpy.types._blendermcp_server.start()
        context.scene.blendermcp_server_running = True
        return {"FINISHED"}


class BLENDERMCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "blendermcp.stop_server"
    bl_label = "Stop BlenderMCP Server"

    def execute(self, context):
        if hasattr(bpy.types, "_blendermcp_server") and bpy.types._blendermcp_server:
            bpy.types._blendermcp_server.stop()
            bpy.types._blendermcp_server = None
        context.scene.blendermcp_server_running = False
        return {"FINISHED"}


_classes = (BLENDERMCP_PT_Panel, BLENDERMCP_OT_StartServer, BLENDERMCP_OT_StopServer)


def register():
    bpy.types.Scene.blendermcp_port = IntProperty(name="Port", default=9876, min=1024, max=65535)
    bpy.types.Scene.blendermcp_server_running = BoolProperty(default=False)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    if hasattr(bpy.types, "_blendermcp_server") and bpy.types._blendermcp_server:
        bpy.types._blendermcp_server.stop()
        bpy.types._blendermcp_server = None
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.blendermcp_port
    del bpy.types.Scene.blendermcp_server_running
```

- [ ] **Step 2: Commit**

```bash
git add addon/server.py
git commit -m "feat: addon TCP server with UI panel and main-thread dispatch"
```

---

### Task 3: Handler Registry + execute_code Handler

**Files:**
- Create: `addon/handlers/__init__.py`
- Create: `addon/handlers/code.py`

- [ ] **Step 1: Write addon/handlers/__init__.py**

```python
"""Handler registry - maps command type strings to handler functions."""

from typing import Callable, Optional

_HANDLERS: dict[str, Callable] = {}


def register_handler(name: str, func: Callable):
    _HANDLERS[name] = func


def get_handler(name: str) -> Optional[Callable]:
    return _HANDLERS.get(name)


# Import handler modules to trigger registration
from . import code  # noqa: F401, E402
```

- [ ] **Step 2: Write addon/handlers/code.py**

```python
"""execute_code handler - runs arbitrary Python inside Blender."""

import io
import traceback
from contextlib import redirect_stdout

import bpy

from . import register_handler


def execute_code(code: str) -> dict:
    namespace = {"bpy": bpy}
    capture = io.StringIO()
    try:
        with redirect_stdout(capture):
            exec(code, namespace)
        return {"executed": True, "result": capture.getvalue()}
    except Exception:
        return {"executed": False, "error": traceback.format_exc(), "result": capture.getvalue()}


register_handler("execute_code", execute_code)
```

- [ ] **Step 3: Commit**

```bash
git add addon/handlers/__init__.py addon/handlers/code.py
git commit -m "feat: handler registry and execute_code escape hatch"
```

---

### Task 4: MCP Server - Connection Manager

**Files:**
- Create: `server/connection.py`

- [ ] **Step 1: Write server/connection.py**

```python
"""TCP connection manager - talks to the Blender addon over localhost."""

import json
import os
import socket
from dataclasses import dataclass, field
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9876


@dataclass
class BlenderConnection:
    host: str = field(default_factory=lambda: os.getenv("BLENDER_MCP_HOST", DEFAULT_HOST))
    port: int = field(default_factory=lambda: int(os.getenv("BLENDER_MCP_PORT", str(DEFAULT_PORT))))
    _sock: socket.socket | None = field(default=None, repr=False)

    def connect(self) -> bool:
        if self._sock is not None:
            return True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((self.host, self.port))
            self._sock = s
            return True
        except Exception:
            self._sock = None
            return False

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send_command(self, command_type: str, params: dict[str, Any] | None = None) -> dict:
        if self._sock is None and not self.connect():
            raise ConnectionError(
                "Not connected to Blender. Make sure Blender is running "
                "and the BlenderMCP addon server is started."
            )
        command = {"type": command_type, "params": params or {}}
        self._sock.settimeout(180.0)
        try:
            self._sock.sendall(json.dumps(command).encode("utf-8"))
        except (BrokenPipeError, OSError):
            self.disconnect()
            raise ConnectionError("Lost connection to Blender.")

        chunks: list[bytes] = []
        while True:
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                raise TimeoutError("Blender command timed out (180s).")
            if not chunk:
                self.disconnect()
                raise ConnectionError("Blender closed the connection.")
            chunks.append(chunk)
            try:
                response = json.loads(b"".join(chunks).decode("utf-8"))
                break
            except json.JSONDecodeError:
                continue

        if response.get("status") == "error":
            raise Exception(response.get("message", "Unknown error from Blender"))
        return response.get("result", {})


_connection: BlenderConnection | None = None


def get_connection() -> BlenderConnection:
    global _connection
    if _connection is None:
        _connection = BlenderConnection()
    if not _connection.connect():
        _connection = None
        raise ConnectionError(
            "Could not connect to Blender. Make sure Blender is running "
            "and the BlenderMCP addon server is started on port "
            f"{os.getenv('BLENDER_MCP_PORT', str(DEFAULT_PORT))}."
        )
    return _connection
```

- [ ] **Step 2: Commit**

```bash
git add server/connection.py
git commit -m "feat: TCP connection manager"
```

---

### Task 5: MCP Server Entry Point + execute_code Tool

**Files:**
- Create: `server/tools/code.py`
- Create: `server/main.py`

- [ ] **Step 1: Write server/tools/code.py**

```python
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
```

- [ ] **Step 2: Write server/main.py**

```python
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
from server.tools import code as tools_code
tools_code.register(mcp)


def main():
    logger.info("BlenderMCP server starting (stdio transport)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Verify import works**

```bash
cd "C:/Users/msist/Desktop/Agents/MCP/Blender"
python -c "import server.main; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 4: Commit**

```bash
git add server/main.py server/tools/code.py
git commit -m "feat: MCP server entry point with execute_code tool"
```

---

### Task 6: Scene Handlers (addon side)

**Files:**
- Create: `addon/handlers/scene.py`
- Modify: `addon/handlers/__init__.py`

- [ ] **Step 1: Write addon/handlers/scene.py**

Handlers to create:
- `get_scene_info()` - lists all objects with type, location, visibility, vertex/face counts for meshes, active/selected objects, current frame
- `get_object_info(name)` - detailed info: transform, materials, modifiers, constraints, parent/children, mesh stats, AABB bounding box
- `create_object(type, name="", location=None)` - create primitives via ops_map dict: cube, sphere, ico_sphere, cylinder, cone, torus, plane, circle, monkey, empty, camera, light
- `delete_objects(names)` - delete by name via `bpy.data.objects.remove(obj, do_unlink=True)`
- `select_objects(names, deselect_others=True)` - set selection state
- `set_transform(name, location=None, rotation=None, scale=None)` - set object transform
- `duplicate_object(name, linked=False)` - duplicate via ops
- `parent_objects(child, parent)` - set parent
- `get_collections()` - recursive collection tree
- `move_to_collection(object_name, collection_name)` - move between collections, create if needed

Each function raises `ValueError` for missing objects. All registered via `register_handler()` at module level.

The AABB helper `_get_aabb(obj)` transforms `obj.bound_box` corners to world space and returns `[min_corner, max_corner]`.

Full code: see spec Task 6 in the detailed version. All 10 handlers follow the same pattern: validate inputs, call bpy, return dict.

- [ ] **Step 2: Update addon/handlers/__init__.py imports**

Add at bottom:
```python
from . import scene  # noqa: F401, E402
```

- [ ] **Step 3: Commit**

```bash
git add addon/handlers/scene.py addon/handlers/__init__.py
git commit -m "feat: scene and object handlers"
```

---

### Task 7: Scene MCP Tools (server side)

**Files:**
- Create: `server/tools/scene.py`
- Modify: `server/main.py`

- [ ] **Step 1: Write server/tools/scene.py**

10 tools wrapping the scene handlers: `get_scene_info`, `get_object_info`, `create_object`, `delete_objects`, `select_objects`, `set_transform`, `duplicate_object`, `parent_objects`, `get_collections`, `move_to_collection`. Each is a `@mcp.tool()` function that calls `get_connection().send_command(...)` and returns `json.dumps(result, indent=2)`.

- [ ] **Step 2: Update server/main.py**

Add import and registration:
```python
from server.tools import scene as tools_scene
tools_scene.register(mcp)
```

- [ ] **Step 3: Commit**

```bash
git add server/tools/scene.py server/main.py
git commit -m "feat: scene MCP tools"
```

---

### Task 8: Viewport Handlers + MCP Tools

**Files:**
- Create: `addon/handlers/viewport.py`
- Create: `server/tools/viewport.py`
- Modify: `addon/handlers/__init__.py`
- Modify: `server/main.py`

- [ ] **Step 1: Write addon/handlers/viewport.py**

4 handlers:
- `get_viewport_screenshot(max_size=800, format="png")` - finds VIEW_3D area, `bpy.ops.screen.screenshot_area()` to temp file, resize if needed, read as base64, cleanup
- `set_viewport_shading(mode)` - WIREFRAME/SOLID/MATERIAL/RENDERED on VIEW_3D space
- `set_view(angle)` - FRONT/BACK/LEFT/RIGHT/TOP/BOTTOM/CAMERA via `bpy.ops.view3d.view_axis()` or `view_camera()`
- `frame_selected()` - `bpy.ops.view3d.view_selected()`

- [ ] **Step 2: Write server/tools/viewport.py**

4 matching MCP tools. The screenshot tool returns the base64 data inline.

- [ ] **Step 3: Update imports in both __init__.py and main.py**

- [ ] **Step 4: Commit**

```bash
git add addon/handlers/viewport.py server/tools/viewport.py addon/handlers/__init__.py server/main.py
git commit -m "feat: viewport screenshot, shading, and view tools"
```

---

### Task 9: All Remaining Domain Handlers + Tools

**Files:**
- Create: `addon/handlers/materials.py`, `addon/handlers/modifiers.py`, `addon/handlers/io_handlers.py`, `addon/handlers/animation.py`, `addon/handlers/nodes.py`, `addon/handlers/render.py`, `addon/handlers/mesh.py`
- Create: `server/tools/materials.py`, `server/tools/modifiers.py`, `server/tools/io_tools.py`, `server/tools/animation.py`, `server/tools/nodes.py`, `server/tools/render.py`, `server/tools/mesh.py`
- Modify: `addon/handlers/__init__.py`, `server/main.py`

- [ ] **Step 1: Write addon/handlers/materials.py**

5 handlers: `list_materials`, `get_material_info` (dumps full node tree), `create_material` (Principled BSDF with color/metallic/roughness), `assign_material`, `set_material_property`.

- [ ] **Step 2: Write addon/handlers/modifiers.py**

5 handlers: `list_modifiers`, `add_modifier` (type.upper(), optional settings dict), `set_modifier_property` (setattr), `apply_modifier` (ops), `remove_modifier`.

- [ ] **Step 3: Write addon/handlers/io_handlers.py**

5 handlers: `import_file` (ext-to-op map for fbx/obj/glb/gltf/stl/ply/abc), `export_file`, `save_blend`, `open_blend`, `list_directory`. Uses Blender 5.1 import ops (`bpy.ops.wm.obj_import` not `import_scene.obj`).

- [ ] **Step 4: Write addon/handlers/animation.py**

5 handlers: `set_keyframe`, `delete_keyframe`, `set_frame`, `get_timeline_info`, `set_timeline`.

- [ ] **Step 5: Write addon/handlers/nodes.py**

5 handlers: `get_node_tree` (resolves from material name or object geonodes), `add_node`, `connect_nodes`, `set_node_value`, `remove_node`.

- [ ] **Step 6: Write addon/handlers/render.py**

4 handlers: `get_render_settings`, `set_render_settings` (supports CYCLES + EEVEE_NEXT samples), `render_frame` (returns base64), `render_animation`.

- [ ] **Step 7: Write addon/handlers/mesh.py**

4 handlers: `get_mesh_data` (vertices + faces, optional), `set_vertex_positions`, `get_vertex_groups`, `set_vertex_group`.

- [ ] **Step 8: Write matching server/tools/ files**

One file per domain, each with a `register(mcp)` function that creates `@mcp.tool()` wrappers calling `get_connection().send_command(...)`.

- [ ] **Step 9: Update addon/handlers/__init__.py with all imports**

```python
from . import code, scene, viewport, materials, modifiers, io_handlers, animation, nodes, render, mesh  # noqa: F401
```

- [ ] **Step 10: Update server/main.py with all tool registrations**

```python
from server.tools import code, scene, viewport, materials, modifiers, io_tools, animation, nodes, render, mesh

for module in [code, scene, viewport, materials, modifiers, io_tools, animation, nodes, render, mesh]:
    module.register(mcp)
```

- [ ] **Step 11: Commit**

```bash
git add addon/handlers/ server/tools/ server/main.py
git commit -m "feat: all domain handlers and tools (materials, modifiers, I/O, animation, nodes, render, mesh)"
```

---

### Task 10: Install Script + Smoke Test

**Files:**
- Create: `install_addon.bat`
- Create: `tests/test_connection.py`

- [ ] **Step 1: Write install_addon.bat**

```batch
@echo off
echo Installing BlenderMCP addon...
set DEST=%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blendermcp
if exist "%DEST%" rmdir /s /q "%DEST%"
xcopy /E /I /Y "%~dp0addon" "%DEST%"
echo Done! Restart Blender and enable the BlenderMCP addon in preferences.
pause
```

- [ ] **Step 2: Write tests/test_connection.py**

Direct TCP test: connect to port 9876, send `{"type": "execute_code", "params": {"code": "print('test OK')"}}`, verify response has `status: success` and `executed: true`.

```python
import json
import socket
import sys


def test_blender_connection(host="127.0.0.1", port=9876):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
        print(f"Connected to Blender at {host}:{port}")

        command = {"type": "execute_code", "params": {"code": "print('BlenderMCP test OK')"}}
        sock.sendall(json.dumps(command).encode("utf-8"))

        chunks = []
        sock.settimeout(10.0)
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            try:
                response = json.loads(b"".join(chunks).decode("utf-8"))
                print(f"Response: {json.dumps(response, indent=2)}")
                assert response["status"] == "success"
                assert response["result"]["executed"] is True
                print("PASS")
                return True
            except json.JSONDecodeError:
                continue
    except ConnectionRefusedError:
        print(f"FAIL: Could not connect to {host}:{port}")
        return False
    finally:
        sock.close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9876
    sys.exit(0 if test_blender_connection(port=port) else 1)
```

- [ ] **Step 3: Commit**

```bash
git add install_addon.bat tests/test_connection.py
git commit -m "feat: install script and smoke test"
```

---

### Task 11: End-to-End Verification

- [ ] **Step 1: Verify server import and tool count**

```bash
cd "C:/Users/msist/Desktop/Agents/MCP/Blender"
python -c "from server.main import mcp; print(f'Tools: {len(mcp._tool_manager._tools)}')"
```

Expected: approximately 45 tools registered.

- [ ] **Step 2: Install addon into Blender**

Run `install_addon.bat`.

- [ ] **Step 3: Test end-to-end**

1. Open Blender 5.1
2. Enable BlenderMCP addon (Edit > Preferences > Add-ons)
3. In N-panel > BlenderMCP tab, click Start Server
4. Run: `python tests/test_connection.py`
5. Expected: `PASS`

- [ ] **Step 4: Configure Claude Code**

Add to Claude Code MCP settings:

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

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: BlenderMCP v1.0 complete"
```
