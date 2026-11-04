"""execute_code handler - runs arbitrary Python inside Blender."""

import ctypes
import io
import linecache
import math
import sys
import textwrap
import threading
import traceback
from contextlib import nullcontext, redirect_stderr, redirect_stdout

import bmesh
import bpy
import mathutils
import numpy

from . import register_handler
from .common import view3d_context

MAX_OUTPUT = 200_000
_FILENAME = "<mcp_code>"
_SET_ASYNC_EXC = ctypes.pythonapi.PyThreadState_SetAsyncExc  # looked up now: the guard blocks dlsym later

# While AI-sent code runs, Python may not reach the network or start programs, threads or native
# libraries (preference "Block internet and programs in Python code"). Agent code is recognised by its
# filename on the call stack, also when functions it defined run later (timers, handlers). An audit
# hook is not a sandbox; "Allow Python code" off is the hard switch.
_NET_EVENTS = {"socket.connect", "socket.getaddrinfo", "socket.sendto", "socket.bind"}
_SPAWN_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                 "os.fork", "os.forkpty", "webbrowser.open", "ctypes.dlopen", "ctypes.dlsym",
                 "_thread.start_new_thread", "_thread.start_joinable_thread"}
_GUARD_KEY = "_yab_mcp_guard"  # kept on sys, so a reloaded add-on reuses the one hook


def _loopback(host):
    host = host.decode(errors="ignore") if isinstance(host, (bytes, bytearray)) else str(host)
    return host in ("localhost", "::1") or host.startswith("127.")


def _in_agent_code():
    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_filename == _FILENAME:
            return True
        frame = frame.f_back
    return False


def _audit(event, args):
    if event not in _NET_EVENTS and event not in _SPAWN_EVENTS:
        return
    if not getattr(sys, _GUARD_KEY, {}).get("on") or not _in_agent_code():
        return
    preference = "add-on preference 'Block internet and programs in Python code'"
    if event in _NET_EVENTS:
        address = args[0] if event == "socket.getaddrinfo" else args[1]
        host = address[0] if isinstance(address, tuple) else (address if event == "socket.getaddrinfo" else None)
        if host is None or _loopback(host):
            return
        raise PermissionError(f"YABlenderMCP blocked a network connection to {host} from AI-sent code ({preference})")
    raise PermissionError(f"YABlenderMCP blocked {event} in AI-sent code: it may not start programs, threads or "
                          f"native libraries ({preference})")


def _guard(on):
    state = getattr(sys, _GUARD_KEY, None)
    if state is None:
        state = {"on": on}
        setattr(sys, _GUARD_KEY, state)
        sys.addaudithook(_audit)
    state["on"] = on


class CodeTimeout(BaseException):
    """Raised inside the agent's code when it runs past its time limit."""


class _ThreadCapture(io.TextIOBase):
    """Collects writes from one thread; writes from other threads pass through."""

    def __init__(self, original, thread_id):
        self.original = original
        self.thread_id = thread_id
        self.parts = []
        self.size = 0

    def write(self, text):
        if threading.get_ident() != self.thread_id:
            return self.original.write(text) if self.original else len(text)
        if self.size < MAX_OUTPUT:
            self.parts.append(text)
        self.size += len(text)
        return len(text)

    def flush(self):
        pass

    def getvalue(self):
        text = "".join(self.parts)
        if self.size > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + f"\n... [{self.size - MAX_OUTPUT} more characters cut]"
        return text


def _async_raise(thread_id, exc):
    _SET_ASYNC_EXC(ctypes.c_ulong(thread_id), ctypes.py_object(exc) if exc else None)


def to_jsonable(value, depth=0):
    """Convert a `result` value (Vectors, Matrices, IDs, numpy, sets...) into JSON data."""
    if depth > 32:
        return repr(value)
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, bpy.types.ID):
        return value.name
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, depth + 1) for k, v in list(value.items())[:10000]}
    if hasattr(value, "tolist"):
        return to_jsonable(value.tolist(), depth + 1)
    if isinstance(value, (list, tuple, set, frozenset)) or (
            hasattr(value, "__len__") and (hasattr(value, "__iter__") or hasattr(value, "__getitem__"))):
        try:
            return [to_jsonable(v, depth + 1) for v in list(value)[:10000]]
        except TypeError:
            pass
    return repr(value)


def _compile(code):
    try:
        return compile(code, _FILENAME, "exec"), code, False
    except (IndentationError, TabError):
        fixed = textwrap.dedent(code.expandtabs(4))
        return compile(fixed, _FILENAME, "exec"), fixed, True


def execute_code(code: str, timeout: float = 170.0, view3d: bool = True) -> dict:
    """Run Python with bpy, bmesh, mathutils, numpy (np), C/D shortcuts.

    Assign a variable named `result` to get structured data back. Runaway code is
    interrupted after `timeout` seconds (a single long C call such as a render cannot be).
    """
    from ..server import code_allowed, code_isolated  # checked here so execute_batch can't bypass it
    if not code_allowed():
        raise PermissionError("Python code is turned off (YABlenderMCP add-on preferences: Allow Python code). "
                              "Use the structured tools, or ask the user to turn it on.")
    _guard(code_isolated())
    try:
        code_obj, source, fixed_indent = _compile(code)
    except SyntaxError:
        return {"executed": False, "error": traceback.format_exc(limit=0), "result": ""}
    linecache.cache[_FILENAME] = (len(source), None, source.splitlines(True), _FILENAME)

    namespace = {
        "__name__": "__main__",
        "bpy": bpy,
        "bmesh": bmesh,
        "mathutils": mathutils,
        "Vector": mathutils.Vector,
        "Matrix": mathutils.Matrix,
        "Euler": mathutils.Euler,
        "Quaternion": mathutils.Quaternion,
        "math": math,
        "np": numpy,
        "C": bpy.context,
        "D": bpy.data,
    }
    thread_id = threading.get_ident()
    out = _ThreadCapture(getattr(sys, "stdout", None), thread_id)
    err = _ThreadCapture(getattr(sys, "stderr", None), thread_id)
    lock = threading.Lock()
    state = {"done": False, "fired": False}

    def fire():
        with lock:
            if not state["done"]:
                state["fired"] = True
                _async_raise(thread_id, CodeTimeout)

    override = nullcontext()
    if view3d:
        try:
            override = bpy.context.temp_override(**view3d_context())
        except RuntimeError:
            pass

    watchdog = threading.Timer(timeout, fire) if timeout and timeout > 0 else None
    error = None
    try:
        try:
            if watchdog:
                watchdog.daemon = True
                watchdog.start()
            with override, redirect_stdout(out), redirect_stderr(err):
                exec(code_obj, namespace)
        finally:
            if watchdog:
                watchdog.cancel()
            with lock:
                state["done"] = True
                if state["fired"]:
                    _async_raise(thread_id, None)
    except CodeTimeout:
        error = f"TimeoutError: code was stopped after {timeout:g} s (pass a larger timeout if it needs longer)"
    except SystemExit:
        error = "SystemExit: exit()/sys.exit() is not allowed here; the script was stopped"
    except Exception:
        lines = traceback.format_exc().splitlines()
        # Drop the frames that belong to this handler; keep the agent's own lines.
        keep = [i for i, line in enumerate(lines) if _FILENAME in line]
        error = "\n".join([lines[0]] + lines[keep[0]:]) if keep else "\n".join(lines)

    result = {"executed": error is None, "result": out.getvalue()}
    stderr_text = err.getvalue()
    if stderr_text:
        result["stderr"] = stderr_text
    if error:
        result["error"] = error
    if "result" in namespace:
        result["return_value"] = to_jsonable(namespace["result"])
    if fixed_indent:
        result["note"] = "Code was dedented to fix its indentation."
    return result


register_handler("execute_code", execute_code)
