"""TCP connection manager - talks to the Blender addon over localhost."""

import json
import os
import select
import socket
import threading
from dataclasses import dataclass, field
from typing import Any

from .compat import ToolError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001
DEFAULT_TIMEOUT = 180.0


@dataclass
class BlenderConnection:
    host: str = field(default_factory=lambda: os.getenv("BLENDER_MCP_HOST", DEFAULT_HOST))
    port: int = field(default_factory=lambda: int(os.getenv("BLENDER_MCP_PORT", str(DEFAULT_PORT))))
    timeout: float = field(default_factory=lambda: float(os.getenv("BLENDER_MCP_TIMEOUT", str(DEFAULT_TIMEOUT))))
    token: str = field(default_factory=lambda: os.getenv("BLENDER_MCP_TOKEN", ""))
    _sock: socket.socket | None = field(default=None, repr=False)
    _buffer: bytes = field(default=b"", repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def connect(self) -> bool:
        if self._sock is not None:
            if self._alive():
                return True
            self.disconnect()
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=5.0)
            self._buffer = b""
            return True
        except Exception:
            self._sock = None
            return False

    def _alive(self) -> bool:
        """Detect a socket whose peer went away (e.g. Blender was restarted)."""
        try:
            readable, _, _ = select.select([self._sock], [], [], 0)
            if readable:
                return self._sock.recv(1, socket.MSG_PEEK) != b""
            return True
        except (OSError, ValueError):
            return False

    def disconnect(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._buffer = b""

    def send_command(self, command_type: str, params: dict[str, Any] | None = None,
                     timeout: float | None = None) -> dict:
        with self._lock:
            if not self.connect():
                raise ToolError(
                    "Not connected to Blender. Make sure Blender is running "
                    "and the BlenderMCP addon server is started."
                )
            command: dict[str, Any] = {"type": command_type, "params": params or {}}
            if timeout:
                command["timeout"] = timeout
            if self.token:
                command["token"] = self.token
            wait = timeout or self.timeout
            try:
                self._sock.sendall(json.dumps(command).encode("utf-8") + b"\n")
            except OSError:
                self.disconnect()
                raise ToolError("Lost connection to Blender.")

            # Blender reports its own timeout first; the socket waits a little longer.
            self._sock.settimeout(wait + 15.0)
            response = self._read_response(wait)

        if response.get("status") == "error":
            message = response.get("message", "Unknown error from Blender")
            if message.startswith("Unknown command"):
                message += (" (the Blender addon may be older than this MCP server: reinstall it with"
                            " install_addon.bat / build_addon.py and restart Blender)")
            raise ToolError(message)
        return response.get("result", {})

    def _read_response(self, wait: float) -> dict:
        while True:
            if b"\n" in self._buffer:
                line, self._buffer = self._buffer.split(b"\n", 1)
                if line.strip():
                    return json.loads(line.decode("utf-8"))
                continue
            try:
                chunk = self._sock.recv(1 << 20)
            except socket.timeout:
                # A late reply would be read as the answer to the next command, so drop the socket.
                self.disconnect()
                raise ToolError(f"Blender command timed out ({wait:.0f}s); it may still be running in Blender.")
            except OSError:
                self.disconnect()
                raise ToolError("Lost connection to Blender.")
            if not chunk:
                self.disconnect()
                raise ToolError("Blender closed the connection (was it restarted?). Try again.")
            self._buffer += chunk
            if b"\n" not in self._buffer:
                # Older addons reply with a bare JSON object and no newline.
                try:
                    response = json.loads(self._buffer.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                self._buffer = b""
                return response


_connection: BlenderConnection | None = None


def get_connection() -> BlenderConnection:
    global _connection
    if _connection is None:
        _connection = BlenderConnection()
    if not _connection.connect():
        _connection = None
        raise ToolError(
            "Could not connect to Blender. Make sure Blender is running "
            "and the BlenderMCP addon server is started on port "
            f"{os.getenv('BLENDER_MCP_PORT', str(DEFAULT_PORT))}."
        )
    return _connection


def to_json(result: Any) -> str:
    """Compact JSON for tool results (indentation costs the model tokens)."""
    return json.dumps(result, ensure_ascii=False)


def send(command_type: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> str:
    """Send a command to Blender and return its result as JSON text."""
    return to_json(get_connection().send_command(command_type, params, timeout))


def jparse(value: Any) -> Any:
    """Accept JSON given as text (older clients) as well as native values."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def params_of(**kwargs: Any) -> dict[str, Any]:
    """Build a command's params, leaving out arguments that were not given (None)."""
    return {k: v for k, v in kwargs.items() if v is not None}
