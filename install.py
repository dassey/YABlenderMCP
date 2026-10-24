"""One-step install of YABlenderMCP (close Blender first).

    python install.py [--blender PATH] [--port 9001] [--no-autostart] [--skip-verify] [--force]
                      [--skill-dir DIR]
    python install.py --uninstall [--blender PATH] [--skill-dir DIR]

Installs the mcp package for this Python if needed, builds addon.zip, installs and enables
the add-on in Blender with "Start server when Blender opens" on, tests it in a headless
Blender, and prints the MCP client entry. The last line starts with OK or FAILED; the exit
code is 0 on success.
"""

import argparse
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
MAIN = os.path.join(ROOT, "server", "main.py")
SKILL = os.path.join(ROOT, "skills", "blender-mcp")
MIN_BLENDER = (5, 1)
MIN_MCP = (1, 30)

# Runs inside Blender in background mode. Arguments after "--": action, zip path, port, auto start.
_IN_BLENDER = r'''
import json, os, sys
import addon_utils, bpy

action, zip_path, port, auto_start = sys.argv[sys.argv.index("--") + 1:][:4]
out = {"blender": bpy.app.version_string}
if action == "install":
    others = []
    for mod in addon_utils.modules():
        label = str(getattr(mod, "bl_info", {}).get("name", ""))
        if mod.__name__ != "blendermcp" and "mcp" in (mod.__name__ + label).lower() and addon_utils.check(mod.__name__)[1]:
            others.append(label or mod.__name__)
    out["other_mcp_addons"] = others
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
    # An older version may already be loaded in this session: unload it so the new files are imported.
    if "blendermcp" in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_disable(module="blendermcp")
    for name in [n for n in sys.modules if n == "blendermcp" or n.startswith("blendermcp.")]:
        del sys.modules[name]
    bpy.ops.preferences.addon_enable(module="blendermcp")
    prefs = bpy.context.preferences.addons["blendermcp"].preferences
    prefs.port = int(port)
    prefs.auto_start = auto_start == "1"
    import blendermcp
    out["installed_to"] = os.path.dirname(blendermcp.__file__)
else:
    import shutil
    if "blendermcp" in bpy.context.preferences.addons:
        bpy.ops.preferences.addon_disable(module="blendermcp")
    # preferences.addon_remove needs a UI area, so delete the add-on folder directly.
    for mod in addon_utils.modules():
        folder = os.path.dirname(mod.__file__)
        if mod.__name__ == "blendermcp" and os.path.basename(folder) == "blendermcp":
            shutil.rmtree(folder)
    out["removed"] = True
bpy.ops.wm.save_userpref()
print("BLENDERMCP_RESULT " + json.dumps(out), flush=True)
'''


class InstallError(Exception):
    pass


def _version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


def _tail(text, lines=25):
    return "\n".join(text.strip().splitlines()[-lines:])


def ensure_mcp():
    from importlib import metadata
    try:
        version = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        version = None
    if version and _version_tuple(version)[:2] >= MIN_MCP:
        print(f"mcp {version} is installed for {sys.executable}")
        return
    print(f"Installing requirements for {sys.executable} ...", flush=True)
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-r", os.path.join(ROOT, "requirements.txt")])
    if result.returncode != 0:
        raise InstallError("pip could not install requirements.txt (see the pip output above)")


def _candidates():
    found = [os.environ.get("BLENDER", ""), shutil.which("blender") or ""]
    if os.name == "nt":
        for base in {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")}:
            if base:
                found += glob.glob(os.path.join(base, "Blender Foundation", "Blender*", "blender.exe"))
        steam = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Steam")
        found.append(os.path.join(steam, "steamapps", "common", "Blender", "blender.exe"))
    elif sys.platform == "darwin":
        found += glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
        found += glob.glob(os.path.expanduser("~/Applications/Blender*.app/Contents/MacOS/Blender"))
    else:
        found += glob.glob("/opt/blender*/blender") + glob.glob(os.path.expanduser("~/blender*/blender"))
        found.append("/snap/bin/blender")
    unique = []
    for path in found:
        if path and os.path.isfile(path) and os.path.realpath(path) not in {os.path.realpath(p) for p in unique}:
            unique.append(path)
    return unique


def blender_version(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=180,
                             encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Blender (\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(g or 0) for g in match.groups()) if match else None


def find_blender(explicit):
    if explicit and not os.path.isfile(explicit):
        raise InstallError(f"No file at {explicit}")
    paths = [explicit] if explicit else _candidates()
    if not paths:
        raise InstallError("Blender not found. Pass --blender PATH (e.g. "
                           r'--blender "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe")')
    versions = [(blender_version(p), p) for p in paths]
    usable = [(v, p) for v, p in versions if v and v[:2] >= MIN_BLENDER]
    if not usable:
        seen = ", ".join(f"{p} ({'.'.join(map(str, v)) if v else 'not runnable'})" for v, p in versions)
        raise InstallError(f"Need Blender {'.'.join(map(str, MIN_BLENDER))} or newer. Found: {seen}")
    version, path = max(usable)
    print(f"Blender {'.'.join(map(str, version))}: {path}")
    others = [p for v, p in usable if p != path]
    if others:
        print(f"  (also found: {', '.join(others)}; use --blender to pick another)")
    if version[:2] != MIN_BLENDER:
        print(f"  Note: tested with Blender {'.'.join(map(str, MIN_BLENDER))}; {'.'.join(map(str, version[:2]))} is untested")
    return path


def blender_running():
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq blender.exe", "/NH"],
                                 capture_output=True, text=True, timeout=30).stdout
            return "blender.exe" in out.lower()
        return subprocess.run(["pgrep", "-ix", "blender"], capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run_in_blender(blender, action, zip_path="", port=9001, auto_start=True):
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "blendermcp_setup.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_IN_BLENDER)
        cmd = [blender, "-b", "--python-exit-code", "1", "--python", script,
               "--", action, zip_path, str(port), "1" if auto_start else "0"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
    for line in result.stdout.splitlines():
        if line.startswith("BLENDERMCP_RESULT "):
            return json.loads(line.split(" ", 1)[1])
    raise InstallError(f"Blender could not {action} the add-on:\n{_tail(result.stdout + result.stderr)}")


def verify(blender):
    """Start a headless Blender with the installed add-on and run `server/main.py --check` against it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log_path = os.path.join(tempfile.gettempdir(), f"blendermcp_verify_{port}.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([blender, "-b", "-c", "blendermcp", "--port", str(port), "--token", ""],
                                stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.time() + 120
            while time.time() < deadline and proc.poll() is None:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.5)
            env = {k: v for k, v in os.environ.items() if k not in ("BLENDER_MCP_TOKEN", "BLENDER_MCP_HOST")}
            env.update(BLENDER_MCP_PORT=str(port), PYTHONUTF8="1")
            check = subprocess.run([sys.executable, MAIN, "--check"], capture_output=True, text=True, env=env,
                                   timeout=180, encoding="utf-8", errors="replace")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
    print("  " + check.stdout.strip().replace("\n", "\n  "))
    if check.returncode != 0:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            blender_log = f.read()
        raise InstallError(f"Self-test failed.\n{_tail(check.stderr)}\nBlender output:\n{_tail(blender_log)}")
    os.remove(log_path)


def skill_target(skill_dir):
    return os.path.join(os.path.abspath(os.path.expanduser(skill_dir)), os.path.basename(SKILL))


def client_entry(port):
    entry = {"command": sys.executable, "args": [MAIN], "env": {"PYTHONUTF8": "1"}}
    if port != 9001:
        entry["env"]["BLENDER_MCP_PORT"] = str(port)
    return {"mcpServers": {"blender": entry}}


def main():
    parser = argparse.ArgumentParser(description="Install YABlenderMCP into Blender and test it.")
    parser.add_argument("--blender", help="path to the Blender executable (default: search the usual places)")
    parser.add_argument("--port", type=int, default=9001, help="add-on port (default 9001)")
    parser.add_argument("--no-autostart", action="store_true", help="don't start the server when Blender opens")
    parser.add_argument("--skip-verify", action="store_true", help="skip the headless self-test")
    parser.add_argument("--force", action="store_true", help="install even if Blender seems to be running")
    parser.add_argument("--uninstall", action="store_true", help="disable and remove the add-on")
    parser.add_argument("--skill-dir", help="also copy the blender-mcp skill into this skills folder "
                                            "(for clients that support Agent Skills)")
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        raise InstallError(f"Python 3.10 or newer is needed (this is {sys.version.split()[0]})")
    if blender_running() and not args.force:
        raise InstallError("Blender is running. Close it first (it would overwrite the new preferences "
                           "when it quits), then run this again. Use --force to skip this check.")
    blender = find_blender(args.blender)

    if args.uninstall:
        run_in_blender(blender, "uninstall")
        if args.skill_dir and os.path.isdir(skill_target(args.skill_dir)):
            shutil.rmtree(skill_target(args.skill_dir))
            print(f"Skill removed: {skill_target(args.skill_dir)}")
        print("OK: add-on removed from Blender. Also remove the \"blender\" entry from your MCP client config.")
        return

    ensure_mcp()
    sys.path.insert(0, ROOT)
    from build_addon import build
    zip_path = build()
    print(f"Built {zip_path}")
    result = run_in_blender(blender, "install", zip_path, args.port, not args.no_autostart)
    print(f"Add-on installed and enabled: {result['installed_to']}")
    print(f"  port {args.port}, start server when Blender opens: {'off' if args.no_autostart else 'on'}")
    if result.get("other_mcp_addons"):
        print(f"  Warning: other MCP add-ons are enabled: {', '.join(result['other_mcp_addons'])}. "
              "Disable them in Edit > Preferences > Add-ons if they clash.")
    if not args.skip_verify:
        print("Self-test with a headless Blender ...", flush=True)
        verify(blender)
    if args.skill_dir:
        target = skill_target(args.skill_dir)
        if os.path.isdir(target):
            shutil.rmtree(target)
        shutil.copytree(SKILL, target)
        print(f"Skill copied to {target}")
    print("\nAdd this entry to your MCP client's config, then restart the client:")
    print(json.dumps(client_entry(args.port), indent=2))
    print("\nOK: YABlenderMCP is installed. Open Blender; the server "
          + ("starts by itself." if not args.no_autostart else "starts from the BlenderMCP tab (press N)."))


if __name__ == "__main__":
    try:
        main()
    except (InstallError, OSError, subprocess.SubprocessError) as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
