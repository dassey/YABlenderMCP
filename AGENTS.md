# AGENTS.md — YABlenderMCP

Guide for AI agents working on or with this project.

---

## What This Project Is

**YABlenderMCP** — a custom MCP (Model Context Protocol) server that gives AI agents full control over Blender 5.1. Built from scratch because the user doesn't trust third-party MCPs that need API keys or phone home to external services.

**Core principle:** No external APIs. No keys. No cloud. No telemetry. Everything runs locally. If you're tempted to add a dependency on any external service — don't. Anything that would need a network connection is listed to the user for approval first, never added silently.

---

## Architecture at a Glance

Two processes that talk to each other over TCP:

```
AI Client  <--stdio/MCP-->  server/main.py  <--TCP:9001-->  Blender Addon (inside Blender)
```

1. **MCP Server** (`server/`) — Standalone Python. Speaks MCP (stdio) to AI clients. Forwards commands to Blender over TCP. An audit hook in `main.py` blocks every network connection except loopback and `BLENDER_MCP_HOST`.
2. **Blender Addon** (`addon/`) — Runs *inside* Blender. Listens on 127.0.0.1:9001. Socket threads only queue jobs; a persistent main-thread timer (`_drain`) executes them.

Why two parts? `bpy` only works inside Blender's Python interpreter. The MCP server cannot `import bpy`. So the addon is the only thing that can touch Blender; the MCP server is a translator.

---

## File Layout

```
server/
  main.py           - entry point: loopback guard, instructions, toolsets, --check
  compat.py         - mcp 1.x (FastMCP) / 2.x (MCPServer) shim, ToolError, READ/EDIT/DESTRUCTIVE annotations,
                      strips null arguments
  connection.py     - TCP client (singleton BlenderConnection), send / params_of / jparse helpers
  prompts.py        - 4 MCP prompts: print_prep, build_scene, review_scene, image_to_model
  tools/
    code.py         - execute_blender_code (the workhorse)
    session.py      - 11: info, undo/redo, batch, units, clear, get/set properties, op history, API search/docs
    scene.py        - 17: scene info, objects, transforms, collections, place/origin/join/convert
    viewport.py     - 5: screenshot, capture_views, shading, view, frame selected
    materials.py    - 6: list/get/create/PBR/assign/set
    modifiers.py    - 6: list/add/set/apply/remove, boolean_operation
    io_tools.py     - 10: import/export, save/open/checkpoint, browse, append, asset libs, reference image
    animation.py    - 11: keyframes, timeline, interpolation, constraints, turntable
    nodes.py        - 8: node trees, node type info, geometry nodes
    render.py       - 6: settings, GPU device, frame, animation, status
    mesh.py         - 5: vertex data, vertex groups, mesh_operation
    lighting.py     - 7: lights, cameras, framing, light rigs, world
    print3d.py      - 6: printability, repair, orient, clearances, 3MF/STL export, SDF parts
    analysis.py     - 6: distance, ray hit, pick, snapshot/diff, silhouette compare

addon/
  __init__.py       - bl_info (version 2.0.0), register/unregister delegate to server module
  server.py         - BlenderMCPServer (TCP), job queue, undo wrapper operator, prefs, UI panel,
                      headless CLI command (-c blendermcp)
  handlers/
    __init__.py     - Handler registry: register_handler / get_handler + module imports
    common.py       - get_object (with "did you mean"), bbox helpers, view3d_context, unit scale
    code.py         - execute_code (stdout capture, `result` variable, watchdog timeout)
    session.py, scene.py, viewport.py, materials.py, modifiers.py, io_handlers.py,
    animation.py, nodes.py, render.py, mesh.py, lighting.py, print3d.py, analysis.py
                    - one file per domain, matching server/tools/ (io_handlers named so to avoid clashing)

tests/
  test_connection.py  - Standalone smoke test (direct TCP, no pytest)

docs/
  specs/              - Original design spec and implementation plan (historical)

build_addon.py      - builds addon.zip (files under blendermcp/, as Blender requires)
install_addon.bat   - Windows: syncs files into the installed addon, or builds the zip on first run
requirements.txt    - Only: mcp[cli]>=1.30 (1.x and 2.x both work)
logo.jpg            - Repo icon (orange Blender cube with glowing cyan logos)
README.md           - User-facing docs: every feature and how to use it
.gitignore          - __pycache__, .pyc/.pyo, .zip, .claude/, docs/git2.md
```

105 tools in total.

---

## The Protocol

Newline-delimited JSON over TCP. Simple and dumb on purpose.

**Request (MCP server → addon):**
```json
{"type": "execute_code", "params": {"code": "bpy.ops.mesh.primitive_cube_add()"}, "timeout": 170, "token": "..."}
```
`timeout` and `token` are optional.

**Response (addon → MCP server):**
```json
{"status": "success", "result": {"executed": true, "result": "stdout here"}, "elapsed": 0.012}
```
or
```json
{"status": "error", "message": "ValueError: Object 'Foo' not found. Did you mean: Foo.001?"}
```

- Default timeout 180 s (`BLENDER_MCP_TIMEOUT`); long tools pass their own.
- The addon also accepts old un-terminated JSON messages; a line that is not JSON drops the client (cross-protocol protection).
- `_dispatch` checks, in order: known command, render running (non-read-only commands are refused), parameters bind to the handler signature, then runs it.
- **Undo:** commands run inside the internal operator `blendermcp.run_command` (`bl_options={"UNDO","INTERNAL"}`), called with `("EXEC_DEFAULT", True)` so exactly one undo step is pushed per command. Read-only commands (name starts with `get_`, `list_`, `find_`, `measure_`, `check_`, `analyze_`, `search_`, `capture_`, `compare_`, `snapshot_`, `diff_`, `ping`) and `_UNWRAPPED` ones (file load/save, undo/redo, renders, view changes) skip the wrapper.
- Errors reach the client as `ToolError`, so mcp 2.x shows the real message.

---

## How to Add a New Tool

To add tool `foo_bar`:

**1. Add the handler** in `addon/handlers/<domain>.py`:
```python
def foo_bar(some_arg: str, optional: int = 0) -> dict:
    # Do the bpy work. Raise ValueError with a helpful message on bad input.
    return {"result": "..."}

register_handler("foo_bar", foo_bar)
```

If it's a new domain, create a new file and add `from . import <new_domain>` to `addon/handlers/__init__.py`.

Name it with a read-only prefix (`get_`, `list_`, `find_`, ...) only if it never changes the scene; everything else gets its own undo step automatically. If it loads files, walks the undo stack or renders, add it to `_UNWRAPPED` in `addon/server.py`.

**2. Add the MCP tool** in `server/tools/<domain>.py`:
```python
from ..compat import EDIT, READ, FastMCP
from ..connection import params_of, send


def register(mcp: FastMCP):
    # ... existing tools ...

    @mcp.tool(annotations=EDIT)
    def foo_bar(some_arg: str, optional: int = 0) -> str:
        """Docstring describing what this does — the AI reads this to decide when to use it."""
        return send("foo_bar", params_of(some_arg=some_arg, optional=optional))
```

Use `READ` for read-only tools and `DESTRUCTIVE` for deletes. If it's a new domain, create a new file and add it to the imports and `TOOLSETS` in `server/main.py`.

**3. Reinstall the addon into Blender** (re-run `install_addon.bat` to sync the addon folder, then restart Blender). Restart the MCP client to pick up the new tool.

---

## The `execute_blender_code` Tool Is the Workhorse

Most new functionality does NOT need a new structured tool. If a user asks for something exotic, the AI can just call `execute_blender_code` with arbitrary Python. The structured tools exist as convenience shortcuts for common operations, not as a complete coverage of bpy.

**Don't** create structured tools for one-off needs. Only add them when:
- The operation is called frequently enough that the token cost of writing raw bpy every time exceeds the context cost of having another tool
- Type safety / parameter validation genuinely matters
- The operation has a clean conceptual boundary
- It needs measurement the model can't do by eye (bounding boxes, clearances, printability)

---

## Running / Testing

**Check the server and the addon connection** (Blender running, addon server started):
```bash
python server/main.py --check
```
Prints `MCP server OK: 105 tools` and the addon version, or why the addon is not reachable.

**Smoke test** (direct TCP):
```bash
python tests/test_connection.py
```

**Headless Blender** (addon installed and enabled once):
```bash
blender -b scene.blend -c blendermcp --port 9001
```

**Install addon into Blender:**
- First time: `python build_addon.py` (or run `install_addon.bat`), it builds `addon.zip`. In Blender: Edit > Preferences > Add-ons > dropdown > Install from Disk > pick `addon.zip` > enable.
- Afterward for dev iteration: re-run `install_addon.bat` — it detects the addon is already installed and syncs source files directly (restart Blender to pick up changes).

---

## Configuring MCP Clients

User-level MCP client config is at `C:/Users/msist/.claude.json`. The entry is:
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

The client must be restarted to pick up config changes. Optional env: `BLENDER_MCP_PORT`, `BLENDER_MCP_HOST`, `BLENDER_MCP_TIMEOUT`, `BLENDER_MCP_TOKEN`, `BLENDER_MCP_TOOLSETS` (see README).

---

## Gotchas & Things That Bit Us

1. **Port confusion**: Default is **9001**, not 9876. Early in development the spec called for 9876, but the user already had Blender's addon running on 9001 from a previous project. We aligned everything to 9001. If you see 9876 anywhere in the code, fix it.

2. **Blender's Python is NOT thread-safe**. All bpy operations MUST run on the main thread. Even `bpy.app.timers.register()` must not be called from the socket thread: the socket thread only appends to a queue, and the persistent `_drain` timer runs the jobs. Don't bypass this.

3. **Blender 5.1 changed import operators**. It's `bpy.ops.wm.obj_import` not `bpy.ops.import_scene.obj`. Same for STL, PLY. If you're copying code from Blender 3.x tutorials, update the ops names.

4. **Windows line endings**: Git complains about LF→CRLF conversion on commit. Harmless. Ignore.

5. **The addon gets installed to** `%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blendermcp\`. If there's an old Siddharth Ahuja BlenderMCP addon there, it might clash (same bl_info name). Uninstall it first.

6. **User has `execute_code` name collision awareness**: the handler is `execute_code`, the MCP tool is `execute_blender_code`. Don't rename either — the protocol depends on the handler name matching across both sides.

7. **`tests/__init__.py` doesn't exist** — the test is a standalone script, not pytest. Don't add it back.

8. **`docs/git2.md` is gitignored** — it contains personal git recovery notes for the user. Don't remove it from `.gitignore`.

9. **mcp 2.x renamed FastMCP to MCPServer** (`mcp.server.mcpserver`). Import from `server/compat.py`, never from `mcp.server.fastmcp` directly. Raise `ToolError` (connection.py does) or 2.x hides the message.

10. **Blender 5 API changes**: EEVEE is `BLENDER_EEVEE` (`BLENDER_EEVEE_NEXT` is gone); `Action.fcurves` is gone (use `bpy_extras.anim_utils.action_get_channelbag_for_slot`); `Material.use_nodes` / `World.use_nodes` are deprecated; set `image_settings.media_type` before `file_format`; boolean solvers are FLOAT / EXACT / MANIFOLD.

11. **Undo from Python**: `bpy.ops.x.y()` only pushes an undo step when called as `bpy.ops.x.y("EXEC_DEFAULT", True)`. Calling `ed.undo` inside a running script is unreliable; the `undo` tool runs it with a window override from the queue.

12. **Addon zip layout**: Blender 5.1 rejects zips with `__init__.py` at the top level ("ZIP packaged incorrectly"). `build_addon.py` puts files under `blendermcp/`.

13. **Headless `-c blendermcp`** starts with an empty context (no `selected_objects`); handlers run inside a window override there. Viewport tools and undo need the UI.

14. **Offscreen capture**: read `GPUOffScreen` pixels as FLOAT and convert; UBYTE readback through numpy came back garbled.

---

## User Profile & Working Style

The user is solo, builds for themselves, values trust and simplicity over features. Read their preferences in `C:/Users/msist/.claude/projects/C--Users-msist-Desktop-Agents-aitools/memory/` — especially relevant are project-level memories about their 2D-to-articulated-print pipeline (VibeCut). They also have an existing BlenderMCP reference they liked at `C:/Users/msist/MCP/blender-mcp-antigravity-main/` and a ComfyUI MCP at `C:/Users/msist/MCP/comfyui-mcp-server-main/`.

When they say "I don't know, you decide" — make the call. They trust you. Don't bounce decisions back unless there's something only they can answer.

**They don't read long technical walls of text.** Keep explanations short. Show results, not process.

Hardware: NVIDIA RTX 5090 (Cycles: `set_render_device("AUTO")` picks OptiX), Bambu Lab H2C printer (pass `printer="H2C"` to the print tools; profiles are in `PRINTERS` in `addon/handlers/print3d.py`; the `print_prep` prompt defaults to H2C).

---

## Repo

GitHub: https://github.com/dassey/YABlenderMCP (public)

The user owns the repo. Commit straight to `master` (no PRs, no feature branches) and keep commits minimal. If a commit message is needed, use `hi`. No AI attribution anywhere (no Co-Authored-By or session lines), and never use the user's Gmail address as author or committer.
