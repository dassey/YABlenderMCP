# AGENTS.md — YABlenderMCP

Guide for AI agents working on or with this project.

---

## What This Project Is

**YABlenderMCP** — a custom MCP (Model Context Protocol) server that gives AI agents full control over Blender 5.1. Built from scratch because the user doesn't trust third-party MCPs that need API keys or phone home to external services.

**Core principle:** No external APIs. No keys. No cloud. No telemetry. Everything runs locally. If you're tempted to add a dependency on any external service — don't.

---

## Architecture at a Glance

Two processes that talk to each other over TCP:

```
AI Client  <--stdio/MCP-->  server/main.py  <--TCP:9001-->  Blender Addon (inside Blender)
```

1. **MCP Server** (`server/`) — Standalone Python. Speaks MCP (stdio) to Claude/antigravity. Forwards commands to Blender over TCP.
2. **Blender Addon** (`addon/`) — Runs *inside* Blender. Listens on TCP port 9001. Executes commands on Blender's main thread via `bpy.app.timers.register()`.

Why two parts? `bpy` only works inside Blender's Python interpreter. The MCP server cannot `import bpy`. So the addon is the only thing that can touch Blender; the MCP server is a translator.

---

## File Layout

```
server/
  main.py           - FastMCP entry point, stdio transport, tool registration
  connection.py     - TCP client (singleton BlenderConnection with send_command)
  tools/
    __init__.py     - Docstring only
    code.py         - execute_blender_code (the workhorse)
    scene.py        - 10 tools: scene info, objects, transforms, collections
    viewport.py     - 4 tools: screenshot, shading, view, frame selected
    materials.py    - 5 tools: list/get/create/assign/set Principled BSDF
    modifiers.py    - 5 tools: list/add/set/apply/remove modifiers
    io_tools.py     - 5 tools: import/export FBX/OBJ/GLB/STL/PLY/ABC
    animation.py    - 5 tools: keyframes, timeline
    nodes.py        - 5 tools: shader/geometry node trees
    render.py       - 4 tools: settings, render frame/animation
    mesh.py         - 4 tools: vertex data, positions, vertex groups

addon/
  __init__.py       - bl_info, register/unregister delegates to server module
  server.py         - BlenderMCPServer class (TCP), UI panel, operators
  handlers/
    __init__.py     - Handler registry: register_handler / get_handler + module imports
    code.py         - execute_code handler (captures stdout, returns traceback on error)
    scene.py        - 10 handlers matching server/tools/scene.py
    viewport.py     - 4 handlers
    materials.py    - 5 handlers
    modifiers.py    - 5 handlers
    io_handlers.py  - 5 handlers (named io_handlers, not io_tools, to avoid clashing)
    animation.py    - 5 handlers
    nodes.py        - 5 handlers
    render.py       - 4 handlers
    mesh.py         - 4 handlers

tests/
  test_connection.py  - Standalone smoke test (direct TCP, no pytest)

docs/
  specs/              - Original design spec and implementation plan (historical)

install_addon.bat   - Windows install script (builds zip or syncs files)
requirements.txt    - Only: mcp[cli]>=1.0.0
logo.jpg            - Repo icon (orange Blender cube with glowing cyan logos)
README.md           - User-facing docs
.gitignore          - __pycache__, .pyc/.pyo, .zip, .claude/, docs/git2.md
```

---

## The Protocol

Newline-delimited JSON over TCP. Simple and dumb on purpose.

**Request (MCP server → addon):**
```json
{"type": "execute_code", "params": {"code": "bpy.ops.mesh.primitive_cube_add()"}}
```

**Response (addon → MCP server):**
```json
{"status": "success", "result": {"executed": true, "result": "stdout here"}}
```
or
```json
{"status": "error", "message": "Object not found: Foo"}
```

180s timeout. Thread safety: TCP accept loop runs on a daemon thread; each command hops to Blender's main thread via `bpy.app.timers.register()` and waits on a `threading.Event` for the result.

---

## How to Add a New Tool

The pattern is dead simple. To add tool `foo_bar`:

**1. Add the handler** in `addon/handlers/<domain>.py`:
```python
def foo_bar(some_arg: str, optional: int = 0) -> dict:
    # Do the bpy work
    return {"result": "..."}

register_handler("foo_bar", foo_bar)
```

If it's a new domain, create a new file and add `from . import <new_domain>` to `addon/handlers/__init__.py`.

**2. Add the MCP tool** in `server/tools/<domain>.py`:
```python
def register(mcp: FastMCP):
    # ... existing tools ...

    @mcp.tool()
    def foo_bar(some_arg: str, optional: int = 0) -> str:
        """Docstring describing what this does — Claude reads this to decide when to use it."""
        result = get_connection().send_command("foo_bar", {"some_arg": some_arg, "optional": optional})
        return json.dumps(result, indent=2)
```

If it's a new domain, create a new file and add an import+`.register(mcp)` call in `server/main.py`.

**3. Reinstall the addon into Blender** (re-run `install_addon.bat` to sync the addon folder, then restart Blender). Restart the MCP client (Claude Code) to pick up the new tool.

---

## The `execute_blender_code` Tool Is the Workhorse

Most new functionality does NOT need a new structured tool. If a user asks for something exotic, Claude can just call `execute_blender_code` with arbitrary Python. The structured tools exist as convenience shortcuts for common operations, not as a complete coverage of bpy.

**Don't** create structured tools for one-off needs. Only add them when:
- The operation is called frequently enough that the token cost of writing raw bpy every time exceeds the context cost of having another tool
- Type safety / parameter validation genuinely matters
- The operation has a clean conceptual boundary

---

## Running / Testing

**Smoke test** (requires Blender running with addon server started on port 9001):
```bash
python tests/test_connection.py
```

**Verify server imports cleanly and tools register:**
```bash
python -c "from server.main import mcp; print(f'Tools: {len(mcp._tool_manager._tools)}')"
```
Should print `Tools: 48` (or higher if tools were added).

**Install addon into Blender:**
- First time: run `install_addon.bat`, it builds `addon.zip`. In Blender: Edit > Preferences > Add-ons > dropdown > Install from Disk > pick `addon.zip` > enable.
- Afterward for dev iteration: re-run `install_addon.bat` — it detects the addon is already installed and syncs source files directly (restart Blender to pick up changes).

---

## Configuring MCP Clients

User-level Claude Code config is at `C:/Users/msist/.claude.json`. The entry is:
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

Claude Code must be restarted to pick up config changes.

---

## Gotchas & Things That Bit Us

1. **Port confusion**: Default is **9001**, not 9876. Early in development the spec called for 9876, but the user already had Blender's addon running on 9001 from a previous project. We aligned everything to 9001. If you see 9876 anywhere in the code, fix it.

2. **Blender's Python is NOT thread-safe**. All bpy operations MUST run on the main thread. The addon uses `bpy.app.timers.register()` + `threading.Event` to bridge the TCP thread to the main thread. Don't bypass this.

3. **Blender 5.1 changed import operators**. It's `bpy.ops.wm.obj_import` not `bpy.ops.import_scene.obj`. Same for STL, PLY. If you're copying code from Blender 3.x tutorials, update the ops names.

4. **Windows line endings**: Git complains about LF→CRLF conversion on commit. Harmless. Ignore.

5. **The addon gets installed to** `%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\blendermcp\`. If there's an old Siddharth Ahuja BlenderMCP addon there, it might clash (same bl_info name). Uninstall it first.

6. **User has `execute_code` name collision awareness**: the handler is `execute_code`, the MCP tool is `execute_blender_code`. Don't rename either — the protocol depends on the handler name matching across both sides.

7. **`tests/__init__.py` doesn't exist** — the test is a standalone script, not pytest. Don't add it back.

8. **`docs/git2.md` is gitignored** — it contains personal git recovery notes for the user. Don't remove it from `.gitignore`.

---

## User Profile & Working Style

The user is solo, builds for themselves, values trust and simplicity over features. Read their preferences in `C:/Users/msist/.claude/projects/C--Users-msist-Desktop-Agents-aitools/memory/` — especially relevant are project-level memories about their 2D-to-articulated-print pipeline (VibeCut). They also have an existing BlenderMCP reference they liked at `C:/Users/msist/MCP/blender-mcp-antigravity-main/` and a ComfyUI MCP at `C:/Users/msist/MCP/comfyui-mcp-server-main/`.

When they say "I don't know, you decide" — make the call. They trust you. Don't bounce decisions back unless there's something only they can answer.

**They don't read long technical walls of text.** Keep explanations short. Show results, not process.

---

## Repo

GitHub: https://github.com/dassey/YABlenderMCP (public)

Push freely — user owns the repo. Use conventional commit prefixes (`feat:`, `fix:`, `docs:`). Always include the Co-Authored-By line in commits.
