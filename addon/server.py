"""TCP server that runs inside Blender, receives commands, dispatches to handlers."""

import bpy
import json
import socket
import threading
import traceback
from bpy.props import IntProperty, BoolProperty

from . import handlers


class BlenderMCPServer:
    def __init__(self, host="localhost", port=9001):
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
    bpy.types.Scene.blendermcp_port = IntProperty(name="Port", default=9001, min=1024, max=65535)
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
