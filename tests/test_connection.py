import json
import os
import socket
import sys


def test_blender_connection(host="127.0.0.1", port=9001):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
        print(f"Connected to Blender at {host}:{port}")

        # ping works whatever the add-on's switches say (execute_code may be turned off)
        command = {"type": "ping", "params": {},
                   "token": os.environ.get("YAB_MCP_TOKEN", os.environ.get("BLENDER_MCP_TOKEN", ""))}
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
                if response["status"] != "success":
                    print(f"FAIL: {response.get('message')}")
                    return False
                assert response["result"]["pong"] is True
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9001
    sys.exit(0 if test_blender_connection(port=port) else 1)
