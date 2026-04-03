"""TCP connection manager - talks to the Blender addon over localhost."""

import json
import os
import socket
from dataclasses import dataclass, field
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9001


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
