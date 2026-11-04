"""TCP server that runs inside Blender, receives commands, dispatches to handlers."""

import bpy
import hmac
import inspect
import json
import os
import queue
import socket
import sys
import threading
import time
import traceback
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import handlers

PROTOCOL_VERSION = 2
DEFAULT_PORT = 9001
DEFAULT_TIMEOUT = 180.0
MAX_TIMEOUT = 24 * 3600.0
MAX_MESSAGE_BYTES = 64 * 1024 * 1024
# Commands whose names start with these never touch scene data, so they get no undo step.
_READONLY_PREFIXES = (
    "get_", "list_", "find_", "measure_", "check_", "analyze_", "search_", "capture_",
    "compare_", "snapshot_", "diff_", "ping",
)
# Run outside the undo wrapper: they load files, walk the undo stack, or only write files.
_UNWRAPPED = {
    "open_blend", "save_blend", "save_checkpoint", "undo", "redo", "export_file", "export_print",
    "render_frame", "render_animation", "set_view", "set_viewport_shading", "set_frame",
}


class YABlenderMCPServer:
    """Socket threads only parse and queue commands; everything touching bpy runs on
    Blender's main thread when the queue is drained (bpy.app.timers is not thread-safe)."""

    def __init__(self, host="127.0.0.1", port=DEFAULT_PORT, token="", allow_code=None):
        self.host = host
        self.port = port
        self.token = token
        self.allow_code = allow_code  # None: follow the "Allow Python code" preference
        self.running = False
        self.socket = None
        self.server_thread = None
        self.jobs = queue.Queue()
        self.client_sockets = set()
        self.clients = 0
        self.commands = 0
        self.last_command = ""
        self.last_error = ""

    def start(self):
        if self.running:
            return True
        self.running = True
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if sys.platform == "win32":
                # On Windows SO_REUSEADDR would let another process bind the same port.
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
            self.server_thread.start()
            print(f"[YABlenderMCP] Server started on {self.host}:{self.port}")
            return True
        except Exception as e:
            self.last_error = str(e)
            print(f"[YABlenderMCP] Failed to start: {e}")
            self.stop()
            return False

    def stop(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        for client in list(self.client_sockets):
            try:
                client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2.0)
        self.server_thread = None
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            job["response"] = {"status": "error", "message": "YABlenderMCP server stopped"}
            job["done"].set()
        print("[YABlenderMCP] Server stopped")

    def _server_loop(self):
        self.socket.settimeout(1.0)
        while self.running:
            try:
                client, address = self.socket.accept()
                print(f"[YABlenderMCP] Client connected: {address}")
                threading.Thread(target=self._handle_client, args=(client,), daemon=True).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[YABlenderMCP] Accept error: {e}")

    def _handle_client(self, client):
        client.settimeout(1.0)
        self.client_sockets.add(client)
        self.clients += 1
        buffer = b""
        try:
            while self.running:
                try:
                    data = client.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                buffer += data
                if len(buffer) > MAX_MESSAGE_BYTES:
                    print("[YABlenderMCP] Message too large, dropping client")
                    return
                # Messages are newline-delimited JSON. A bare JSON object without a
                # trailing newline is still accepted for older MCP servers.
                while True:
                    if b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                    else:
                        line = buffer
                    try:
                        command = json.loads(line.decode("utf-8"))
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        if line is buffer:
                            break
                        # Not our protocol (e.g. an HTTP request from a web page): drop the client.
                        print("[YABlenderMCP] Rejected non-JSON data from client")
                        return
                    if line is buffer:
                        buffer = b""
                    if not isinstance(command, dict):
                        return
                    response = self._run_command(command)
                    payload = json.dumps(response, default=_json_default).encode("utf-8") + b"\n"
                    client.settimeout(60.0)
                    client.sendall(payload)
                    client.settimeout(1.0)
                    if not buffer:
                        break
        except Exception as e:
            print(f"[YABlenderMCP] Client error: {e}")
        finally:
            self.client_sockets.discard(client)
            self.clients -= 1
            try:
                client.close()
            except Exception:
                pass
            print("[YABlenderMCP] Client disconnected")

    def _run_command(self, command):
        if self.token and not hmac.compare_digest(str(command.get("token", "")).encode(), self.token.encode()):
            return {"status": "error", "message": "Invalid or missing token (set YAB_MCP_TOKEN to the Token in the add-on preferences)."}

        timeout = command.get("timeout") or DEFAULT_TIMEOUT
        timeout = max(1.0, min(float(timeout), MAX_TIMEOUT))
        job = {"command": command, "done": threading.Event(), "response": None,
               "deadline": time.monotonic() + timeout}
        self.jobs.put(job)
        if not job["done"].wait(timeout=timeout + 1.0):
            return {"status": "error", "message": f"Command timed out ({timeout:.0f}s). Blender may be busy; it may still finish."}
        return job["response"]

    def process_jobs(self, budget=0.05):
        """Run queued commands on the main thread. Returns True if any ran."""
        ran = False
        start = time.monotonic()
        while time.monotonic() - start < budget:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                break
            ran = True
            if time.monotonic() > job["deadline"]:
                job["response"] = {"status": "error", "message": "Skipped: Blender was busy past the command's timeout."}
            else:
                try:
                    job["response"] = self._dispatch(job["command"])
                except Exception as e:
                    traceback.print_exc()
                    job["response"] = {"status": "error", "message": str(e)}
            job["done"].set()
        return ran

    def _dispatch(self, command):
        cmd_type = command.get("type")
        params = command.get("params", {}) or {}
        handler = handlers.get_handler(cmd_type)
        self.last_command = str(cmd_type)
        self.commands += 1
        if handler is None:
            return {"status": "error", "message": f"Unknown command: {cmd_type}"}
        if not cmd_type.startswith(_READONLY_PREFIXES) and bpy.app.is_job_running("RENDER"):
            return {"status": "error", "message": "A render is running; wait for it (get_render_status) "
                                                  "before changing the scene."}
        try:
            inspect.signature(handler).bind(**params)
        except TypeError as e:
            expected = ", ".join(inspect.signature(handler).parameters)
            return {"status": "error", "message": f"Invalid parameters for '{cmd_type}': {e}. Expected: {expected}"}
        start = time.perf_counter()
        try:
            result = _call_handler(cmd_type, handler, params)
        except Exception as e:
            traceback.print_exc()
            return {"status": "error", "message": f"{type(e).__name__}: {e}"}
        return {"status": "success", "result": result, "elapsed": round(time.perf_counter() - start, 4)}


_pending = {}


def _call_handler(cmd_type, handler, params):
    """Run a handler; scene-changing commands run inside an UNDO operator so each
    command becomes exactly one Ctrl+Z step."""
    wm = bpy.context.window_manager
    if (cmd_type.startswith(_READONLY_PREFIXES) or cmd_type in _UNWRAPPED
            or bpy.app.background or not wm.windows):
        if bpy.app.background and wm.windows and bpy.context.window is None and cmd_type != "open_blend":
            # Headless command mode (-c yab_mcp) starts with an empty context; use the file's window.
            with bpy.context.temp_override(window=wm.windows[0]):
                return handler(**params)
        return handler(**params)
    _pending.clear()
    _pending.update(handler=handler, params=params)
    try:
        with bpy.context.temp_override(window=wm.windows[0]):
            # Python operator calls only push an undo step when asked to (second argument).
            bpy.ops.yab_mcp.run_command("EXEC_DEFAULT", True)
    except RuntimeError:
        if "handler" in _pending:
            _pending.clear()
            return handler(**params)
    outcome = dict(_pending)
    _pending.clear()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("result")


class YAB_MCP_OT_RunCommand(bpy.types.Operator):
    """Internal: executes one MCP command as a single undo step"""
    bl_idname = "yab_mcp.run_command"
    bl_label = "YABlenderMCP"
    bl_options = {"UNDO", "INTERNAL"}

    def execute(self, context):
        handler = _pending.pop("handler", None)
        params = _pending.pop("params", {})
        if handler is None:
            return {"CANCELLED"}
        try:
            _pending["result"] = handler(**params)
        except Exception as e:
            traceback.print_exc()
            _pending["error"] = e
        # FINISHED even on error, so partial changes still get their own undo step.
        return {"FINISHED"}


def _json_default(value):
    """Serialize mathutils/bpy values (Vector, Color, Euler, Matrix, prop arrays) as lists."""
    if isinstance(value, (set, tuple)):
        return list(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, bpy.types.ID):
        return value.name
    try:
        return list(value)
    except TypeError:
        return str(value)


_server = None


def get_server():
    return _server


def _drain():
    """Persistent main-thread timer that executes queued commands."""
    if _server is None or not _server.running:
        return None
    ran = _server.process_jobs()
    return 0.01 if ran else 0.05


def start_server(port=None, token=None, allow_code=None):
    """Start (or restart on a new port) the TCP server. Call on the main thread."""
    global _server
    prefs = _prefs()
    port = port or (prefs.port if prefs else DEFAULT_PORT)
    token = token if token is not None else (prefs.token if prefs else "")
    if (_server and _server.running and _server.port == port and _server.token == token
            and _server.allow_code == allow_code):
        return _server
    stop_server()
    _server = YABlenderMCPServer(port=port, token=token, allow_code=allow_code)
    if _server.start() and not bpy.app.background and not bpy.app.timers.is_registered(_drain):
        bpy.app.timers.register(_drain, first_interval=0.05, persistent=True)
    return _server


def stop_server():
    global _server
    if _server:
        _server.stop()
    _server = None
    if bpy.app.timers.is_registered(_drain):
        bpy.app.timers.unregister(_drain)


def _cli_serve(argv):
    """Headless mode: blender -b [file.blend] -c yab_mcp [--port N] [--token T]"""
    import argparse
    parser = argparse.ArgumentParser(prog="blender -b -c yab_mcp")
    parser.add_argument("--port", type=int, default=None, help="default: the add-on's Port preference")
    parser.add_argument("--token", default=None,
                        help="default: YAB_MCP_TOKEN, else the add-on's Token preference (the environment "
                             "variable keeps it out of process lists)")
    parser.add_argument("--no-code", action="store_true",
                        help="block execute_blender_code (default: the add-on's Allow Python code preference)")
    args = parser.parse_args(argv)
    token = args.token if args.token is not None else (os.environ.get("YAB_MCP_TOKEN") or None)
    srv = start_server(args.port, token, False if args.no_code else None)
    if not srv.running:
        return 1
    print(f"[YABlenderMCP] Headless server ready on 127.0.0.1:{srv.port}, Python code "
          f"{'allowed' if code_allowed() else 'blocked'} (Ctrl+C to stop)", flush=True)
    try:
        while srv.running:
            if not srv.process_jobs(budget=0.5):
                time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    stop_server()
    return 0


def _prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def code_allowed() -> bool:
    """May MCP clients run arbitrary Python? The headless --no-code flag, else the preference."""
    if _server is not None and _server.allow_code is not None:
        return _server.allow_code
    prefs = _prefs()
    return True if prefs is None else bool(prefs.allow_code)


def code_isolated() -> bool:
    """Block internet, programs, threads and native libraries while AI-sent Python runs?"""
    prefs = _prefs()
    return True if prefs is None else bool(prefs.isolate_code)


class YAB_MCP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    port: IntProperty(name="Port", default=DEFAULT_PORT, min=1024, max=65535)
    auto_start: BoolProperty(
        name="Start server when Blender opens",
        description="Start the YABlenderMCP server automatically after Blender launches",
        default=False,
    )
    token: StringProperty(
        name="Token",
        description="Optional shared secret. If set, the MCP server must send the same value (YAB_MCP_TOKEN)",
        default="",
        subtype="PASSWORD",
    )
    allow_code: BoolProperty(
        name="Allow Python code",
        description="Let MCP clients run any Python inside Blender (execute_blender_code). "
                    "Off: only the structured tools work",
        default=True,
    )
    isolate_code: BoolProperty(
        name="Block internet and programs in Python code",
        description="While AI-sent Python runs, refuse internet connections and starting programs, threads "
                    "or native libraries. Not a sandbox: Allow Python code off is the hard switch",
        default=True,
    )
    allowed_folders: StringProperty(
        name="Allowed folders",
        description="Folders the file tools may read and write, separated by ; (empty: any folder). "
                    "Python code is not limited by this",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "port")
        layout.prop(self, "auto_start")
        layout.prop(self, "token")
        layout.prop(self, "allow_code")
        layout.prop(self, "isolate_code")
        layout.prop(self, "allowed_folders")


class YAB_MCP_PT_Panel(bpy.types.Panel):
    bl_label = "YABlenderMCP"
    bl_idname = "YAB_MCP_PT_Panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "YABlenderMCP"

    def draw(self, context):
        layout = self.layout
        prefs = _prefs()
        if prefs:
            layout.prop(prefs, "port")
            layout.prop(prefs, "auto_start")
            layout.prop(prefs, "allow_code")
        srv = get_server()
        if srv is None or not srv.running:
            layout.operator("yab_mcp.start_server", text="Start Server")
            if srv and srv.last_error:
                layout.label(text=srv.last_error, icon="ERROR")
        else:
            layout.operator("yab_mcp.stop_server", text="Stop Server")
            col = layout.column(align=True)
            col.label(text=f"Running on 127.0.0.1:{srv.port}", icon="CHECKMARK")
            col.label(text=f"Clients: {srv.clients}   Commands: {srv.commands}")
            if srv.last_command:
                col.label(text=f"Last: {srv.last_command}")


class YAB_MCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "yab_mcp.start_server"
    bl_label = "Start YABlenderMCP Server"

    def execute(self, context):
        srv = start_server()
        if not srv.running:
            self.report({"ERROR"}, f"YABlenderMCP could not start: {srv.last_error}")
            return {"CANCELLED"}
        return {"FINISHED"}


class YAB_MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "yab_mcp.stop_server"
    bl_label = "Stop YABlenderMCP Server"

    def execute(self, context):
        stop_server()
        return {"FINISHED"}


_classes = (YAB_MCP_Preferences, YAB_MCP_PT_Panel, YAB_MCP_OT_StartServer, YAB_MCP_OT_StopServer,
            YAB_MCP_OT_RunCommand)
_cli_command = None


def _auto_start():
    prefs = _prefs()
    if prefs and prefs.auto_start:
        start_server()
    return None


def register():
    global _cli_command
    for cls in _classes:
        bpy.utils.register_class(cls)
    if not bpy.app.background and not bpy.app.timers.is_registered(_auto_start):
        bpy.app.timers.register(_auto_start, first_interval=1.0)
    if hasattr(bpy.utils, "register_cli_command"):
        _cli_command = bpy.utils.register_cli_command("yab_mcp", _cli_serve)


def unregister():
    global _cli_command
    if bpy.app.timers.is_registered(_auto_start):
        bpy.app.timers.unregister(_auto_start)
    stop_server()
    if _cli_command is not None:
        bpy.utils.unregister_cli_command(_cli_command)
        _cli_command = None
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
