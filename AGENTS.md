# AGENTS.md — YABlenderMCP

Guide for AI agents working on or with this project.

---

## Names

- **YABlenderMCP**: the long name, for anything people read (README, add-on name, N-panel tab, log lines, messages). Lowercase it is the MCP Registry name `io.github.dassey/yablendermcp`: the registry search only matches names, so the name must contain "blender" (2.3.0 was listed as `io.github.dassey/yab-mcp`, now deprecated).
- **yab-mcp**: the short name: MCP server name, `yab-mcp` command, PyPI package, client config key, skill (`yab_mcp/skills/yab-mcp`), `yab-mcp://guide`, zip.
- **yab_mcp** only where hyphens are not allowed: the Python package, add-on module/folder, operator ids (`yab_mcp.*`), classes (`YAB_MCP_*`), `blender -c yab_mcp`. Env vars are `YAB_MCP_*`.
- Never generic names like blender-mcp / BlenderMCP. The add-on was called `blendermcp` before 2.1; `yab-mcp install` replaces it.

---

## What This Project Is

**YABlenderMCP** — a custom MCP (Model Context Protocol) server that gives AI agents full control over Blender 5.1. Built from scratch because the user doesn't trust third-party MCPs that need API keys or phone home to external services.

**Core principle:** No external APIs. No keys. No cloud. No telemetry. Everything runs locally. If you're tempted to add a dependency on any external service — don't. Anything that would need a network connection is listed to the user for approval first, never added silently.

---

## Architecture at a Glance

Two processes that talk to each other over TCP:

```
AI Client  <--stdio/MCP-->  yab-mcp (python -m yab_mcp)  <--TCP:9001-->  Blender Addon (inside Blender)
```

1. **MCP Server** (`yab_mcp/`) — Standalone Python package. Speaks MCP (stdio) to AI clients. Forwards commands to Blender over TCP. An audit hook in `yab_mcp/server.py` blocks every network connection except loopback and `YAB_MCP_HOST`.
2. **Blender Addon** (`yab_mcp/addon/`, shipped inside the package and installed into Blender by `yab-mcp install`) — Runs *inside* Blender. Listens on 127.0.0.1:9001. Socket threads only queue jobs; a persistent main-thread timer (`_drain`) executes them.

Why two parts? `bpy` only works inside Blender's Python interpreter. The MCP server cannot `import bpy`. So the addon is the only thing that can touch Blender; the MCP server is a translator.

---

## File Layout

```
yab_mcp/              - the Python package (PyPI: yab-mcp; command: yab-mcp; python -m yab_mcp)
  __init__.py         - __version__
  __main__.py, cli.py - yab-mcp: serve (default), --check, install, uninstall, build-addon, --version
  server.py           - MCP server: loopback guard, instructions, toolsets, check(), serve()
  compat.py           - mcp 1.x (FastMCP) / 2.x (MCPServer) shim, ToolError, READ/EDIT/DESTRUCTIVE annotations,
                        strips null arguments
  connection.py       - TCP client (singleton BlenderConnection), env() (YAB_MCP_*, old BLENDER_MCP_*), send / params_of / jparse
  prompts.py          - 4 MCP prompts: print_prep, build_scene, review_scene, image_to_model
  guide.py            - serves skills/yab-mcp/SKILL.md as the get_usage_guide tool and yab-mcp://guide resource
  installer.py        - yab-mcp install/uninstall/build-addon: zip, install+enable via background Blender (auto
                        start, token, settings kept, old blendermcp migrated), headless self-test, client entry
  tools/              - one MCP tool module per domain (code, session, scene, viewport, materials, modifiers,
                        io_tools, animation, nodes, render, mesh, lighting, print3d, analysis)
  skills/yab-mcp/SKILL.md - the AI's playbook (Agent Skills format; also served over MCP)
  addon/              - the Blender add-on (never imported by the server)
    __init__.py       - bl_info (version 2.3.1), register/unregister delegate to server module
    server.py         - YABlenderMCPServer (TCP), job queue, undo wrapper operator, prefs, UI panel,
                        code_allowed()/code_isolated(), headless CLI command (-c yab_mcp)
    handlers/         - one file per domain, matching yab_mcp/tools (io_handlers named so to avoid clashing);
                        common.py has get_object, bbox helpers, view3d_context, unit scale, check_path;
                        code.py has execute_code and the audit-hook guard

install.py            - clone shim: pip install -e . into the running Python, then yab-mcp install
server/main.py        - shim for client configs from before 2.3 (python .../server/main.py)
pyproject.toml        - package metadata (setuptools); version comes from yab_mcp/__init__.py
server.json           - MCP Registry metadata (io.github.dassey/yablendermcp)
.github/workflows/publish.yml - on tag v*: version check, build, PyPI (trusted publishing), MCP Registry (OIDC)
.github/workflows/registry-status.yml - run by hand: change a registry listing's status (deprecate a version)
tests/test_connection.py - Standalone smoke test (direct TCP, no pytest; sends YAB_MCP_TOKEN)
install_addon.bat     - Windows dev sync: copies yab_mcp/addon into the installed add-on, or builds the zip
logo.jpg, LICENSE (MIT), README.md (user docs: every feature and how to use it)
.gitignore            - __pycache__, .pyc/.pyo, .zip, .claude/, docs/git2.md, .venv/, *.egg-info/, build/, dist/
```

106 tools in total (105 Blender tools + get_usage_guide).

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

- Default timeout 180 s (`YAB_MCP_TIMEOUT`); long tools pass their own.
- The addon also accepts old un-terminated JSON messages; a line that is not JSON drops the client (cross-protocol protection).
- `_dispatch` checks, in order: known command, render running (non-read-only commands are refused), parameters bind to the handler signature, then runs it.
- **Undo:** commands run inside the internal operator `yab_mcp.run_command` (`bl_options={"UNDO","INTERNAL"}`), called with `("EXEC_DEFAULT", True)` so exactly one undo step is pushed per command. Read-only commands (name starts with `get_`, `list_`, `find_`, `measure_`, `check_`, `analyze_`, `search_`, `capture_`, `compare_`, `snapshot_`, `diff_`, `ping`) and `_UNWRAPPED` ones (file load/save, undo/redo, renders, view changes) skip the wrapper.
- Errors reach the client as `ToolError`, so mcp 2.x shows the real message.
- **Python code switch:** `code_allowed()` in `yab_mcp/addon/server.py` (preference `allow_code`, or `--no-code` headless). It is checked inside the `execute_code` handler, so `execute_batch` can't bypass it, and in `set_properties` for `expression` / `use_module`. `get_api_docs` only resolves modules that are already loaded (importing runs code).
- **Code guard:** while AI-sent code runs (`code_isolated()`, preference `isolate_code`, default on), an audit hook in `handlers/code.py` refuses non-loopback sockets, process starts, `ctypes` loading and new threads. It recognises agent code by the `<mcp_code>` filename anywhere on the stack, so functions the code leaves behind stay blocked. Not a sandbox; `allow_code` off is the hard switch.
- **Allowed folders:** `check_path()` in `handlers/common.py` (preference `allowed_folders`, `;`-separated, empty = anywhere) is called by every handler that takes a file path, and by `set_properties` for `filepath` / `directory` values.

---

## How to Add a New Tool

To add tool `foo_bar`:

**1. Add the handler** in `yab_mcp/addon/handlers/<domain>.py`:
```python
def foo_bar(some_arg: str, optional: int = 0) -> dict:
    # Do the bpy work. Raise ValueError with a helpful message on bad input.
    return {"result": "..."}

register_handler("foo_bar", foo_bar)
```

If it's a new domain, create a new file and add `from . import <new_domain>` to `yab_mcp/addon/handlers/__init__.py`.

Name it with a read-only prefix (`get_`, `list_`, `find_`, ...) only if it never changes the scene; everything else gets its own undo step automatically. If it loads files, walks the undo stack or renders, add it to `_UNWRAPPED` in `yab_mcp/addon/server.py`. If it takes a file path, call `check_path()` on it.

**2. Add the MCP tool** in `yab_mcp/tools/<domain>.py`:
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

Use `READ` for read-only tools and `DESTRUCTIVE` for deletes. If it's a new domain, create a new file and add it to the imports and `TOOLSETS` in `yab_mcp/server.py`.

**3. Update the playbook**: if the tool changes how a task is best done, add it to `yab_mcp/skills/yab-mcp/SKILL.md` (the "Which tool for what" table) and to the README feature tables.

**4. Reinstall the addon into Blender** (`python install.py`, or `install_addon.bat` to sync the add-on folder, then restart Blender). Restart the MCP client to pick up the new tool.

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

**Check the server and the addon connection** (Blender running, addon server started; the token is required):
```bash
YAB_MCP_TOKEN=<token> python -m yab_mcp --check
```
Prints `MCP server OK: 106 tools (yab-mcp 2.3.1)`, the add-on version and whether Python code is allowed, or why the add-on is not reachable. `python server/main.py --check` (old path) still works.

**Smoke test** (direct TCP, reads `YAB_MCP_TOKEN`):
```bash
python tests/test_connection.py
```

**Headless Blender** (addon installed and enabled once; `YAB_MCP_TOKEN` or the preference sets the token):
```bash
blender -b scene.blend -c yab_mcp --port 9001
```

**Install addon into Blender** (Blender closed):
- From the clone: `.venv\Scripts\python install.py` — `pip install -e .` into the venv, then `yab-mcp install`: builds and installs the zip, enables the add-on with auto start, keeps existing settings (port, token, auto start, allow_code, isolate_code, allowed_folders), sets a random token if there is none, runs a headless self-test with that token, prints the client entry. Last line `OK:` / `FAILED:`. Never use `--factory-startup` for this (it would save factory preferences).
- Manual: `python -m yab_mcp build-addon`, then in Blender: Edit > Preferences > Add-ons > dropdown > Install from Disk > pick `yab-mcp-addon.zip` > enable.
- Afterward for dev iteration: re-run `install_addon.bat` — it detects the addon is already installed and syncs source files directly (restart Blender to pick up changes).

**Release** (only when the user says so):
1. Bump the version in `yab_mcp/__init__.py`, `bl_info` in `yab_mcp/addon/__init__.py`, and both versions in `server.json`.
2. Commit to master, then tag `vX.Y.Z` and push the tag. `.github/workflows/publish.yml` checks the versions match the tag, builds, publishes to PyPI (trusted publisher, environment `pypi`) and then to the MCP Registry. A version can only be published once on PyPI.
3. A broken release: Actions > Registry status > Run workflow deprecates it in the registry (yank it on pypi.org too). `mcp-publisher status --all-versions` asks for confirmation, so CI must pass `--yes`.

---

## Configuring MCP Clients

User-level MCP client config is at `C:/Users/msist/.claude.json`. The entry is:
```json
{
  "mcpServers": {
    "yab-mcp": {
      "command": "C:/Users/msist/Desktop/Agents/MCP/Blender/.venv/Scripts/python.exe",
      "args": ["-m", "yab_mcp"],
      "env": {"PYTHONUTF8": "1", "YAB_MCP_TOKEN": "<printed by yab-mcp install>"}
    }
  }
}
```

The client must be restarted to pick up config changes. Optional env: `YAB_MCP_PORT`, `YAB_MCP_HOST`, `YAB_MCP_TIMEOUT`, `YAB_MCP_TOKEN`, `YAB_MCP_TOOLSETS` (see README; the old `BLENDER_MCP_*` names still work).

---

## Gotchas & Things That Bit Us

1. **Port confusion**: Default is **9001**, not 9876. Early in development the spec called for 9876, but the user already had Blender's addon running on 9001 from a previous project. We aligned everything to 9001. If you see 9876 anywhere in the code, fix it.

2. **Blender's Python is NOT thread-safe**. All bpy operations MUST run on the main thread. Even `bpy.app.timers.register()` must not be called from the socket thread: the socket thread only appends to a queue, and the persistent `_drain` timer runs the jobs. Don't bypass this.

3. **Blender 5.1 changed import operators**. It's `bpy.ops.wm.obj_import` not `bpy.ops.import_scene.obj`. Same for STL, PLY. If you're copying code from Blender 3.x tutorials, update the ops names.

4. **Windows line endings**: Git complains about LF→CRLF conversion on commit. Harmless. Ignore.

5. **The addon gets installed to** `%APPDATA%\Blender Foundation\Blender\5.1\scripts\addons\yab_mcp\` (before 2.1: `blendermcp\`, which `install.py` removes). If there's an old Siddharth Ahuja BlenderMCP addon there, it might clash (same bl_info name). Uninstall it first.

6. **User has `execute_code` name collision awareness**: the handler is `execute_code`, the MCP tool is `execute_blender_code`. Don't rename either — the protocol depends on the handler name matching across both sides.

7. **`tests/__init__.py` doesn't exist** — the test is a standalone script, not pytest. Don't add it back.

8. **`docs/git2.md` is gitignored** — it contains personal git recovery notes for the user. Don't remove it from `.gitignore`.

9. **mcp 2.x renamed FastMCP to MCPServer** (`mcp.server.mcpserver`). Import from `yab_mcp/compat.py`, never from `mcp.server.fastmcp` directly. Raise `ToolError` (connection.py does) or 2.x hides the message.

10. **Blender 5 API changes**: EEVEE is `BLENDER_EEVEE` (`BLENDER_EEVEE_NEXT` is gone); `Action.fcurves` is gone (use `bpy_extras.anim_utils.action_get_channelbag_for_slot`); `Material.use_nodes` / `World.use_nodes` are deprecated; set `image_settings.media_type` before `file_format`; boolean solvers are FLOAT / EXACT / MANIFOLD.

11. **Undo from Python**: `bpy.ops.x.y()` only pushes an undo step when called as `bpy.ops.x.y("EXEC_DEFAULT", True)`. Calling `ed.undo` inside a running script is unreliable; the `undo` tool runs it with a window override from the queue.

12. **Addon zip layout**: Blender 5.1 rejects zips with `__init__.py` at the top level ("ZIP packaged incorrectly"). `build_zip()` in `yab_mcp/installer.py` puts files under `yab_mcp/`.

13. **Headless `-c yab_mcp`** (Blender command ids must be identifiers, so no hyphen) starts with an empty context (no `selected_objects`); handlers run inside a window override there. Viewport tools and undo need the UI.

14. **Offscreen capture**: read `GPUOffScreen` pixels as FLOAT and convert; UBYTE readback through numpy came back garbled.

15. **Upgrading the add-on from a script**: `addon_enable` does nothing when the add-on is already enabled, so the old code stays loaded (v1 had no preferences class). The installer disables it and drops `yab_mcp*` from `sys.modules` before enabling. It also removes the pre-2.1 add-on `blendermcp` (keeping its port, token and auto start) and an old `blender-mcp` skill folder, but only after checking they are ours. `preferences.addon_remove` needs a UI area and fails in background mode, so `--uninstall` deletes the folder itself.


16. **Disabling an add-on resets its preferences.** The installer reads all add-on settings before it disables the old copy and writes them back after enabling the new one (the 2.1.0 installer lost them).

17. **Python 3.13 threads**: `threading.Thread.start()` raises the audit event `_thread.start_joinable_thread`, not `_thread.start_new_thread`. The guard blocks both.

18. **The add-on lives inside the package** (`yab_mcp/addon`) but must never be imported by the server: it imports `bpy`. It is only zipped and installed into Blender.

---

## User Profile & Working Style

The user is solo, builds for themselves, values trust and simplicity over features. Read their preferences in `C:/Users/msist/.claude/projects/C--Users-msist-Desktop-Agents-aitools/memory/` — especially relevant are project-level memories about their 2D-to-articulated-print pipeline (VibeCut). They also have an existing BlenderMCP reference they liked at `C:/Users/msist/MCP/blender-mcp-antigravity-main/` and a ComfyUI MCP at `C:/Users/msist/MCP/comfyui-mcp-server-main/`.

When they say "I don't know, you decide" — make the call. They trust you. Don't bounce decisions back unless there's something only they can answer.

**They don't read long technical walls of text.** Keep explanations short. Show results, not process.

Hardware: NVIDIA RTX 5090 (Cycles: `set_render_device("AUTO")` picks OptiX), Bambu Lab H2C printer (pass `printer="H2C"` to the print tools; profiles are in `PRINTERS` in `yab_mcp/addon/handlers/print3d.py`; the `print_prep` prompt defaults to H2C).

---

## Repo

GitHub: https://github.com/dassey/YABlenderMCP (public)

The user owns the repo. Commit straight to `master` (no PRs, no feature branches) and keep commits minimal. If a commit message is needed, use `hi`. No AI attribution anywhere (no Co-Authored-By or session lines), and never use the user's Gmail address as author or committer.
