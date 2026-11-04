"""yab-mcp install / uninstall / build-addon (close Blender first).

    yab-mcp install [--blender PATH] [--port N] [--no-autostart] [--no-code] [--no-token]
                    [--skill-dir DIR] [--skip-verify] [--force]
    yab-mcp uninstall [--blender PATH] [--skill-dir DIR] [--force]
    yab-mcp build-addon [--out FILE]

install builds the add-on zip, installs and enables it in Blender (the server starts when Blender
opens and a random token protects it), tests it with a headless Blender and prints the MCP client
entry. The last line starts with OK or FAILED; the exit code is 0 on success.
"""

import argparse
import glob
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile

from . import __version__

PACKAGE = os.path.dirname(os.path.abspath(__file__))
ADDON_SRC = os.path.join(PACKAGE, "addon")
SKILL = os.path.join(PACKAGE, "skills", "yab-mcp")
MIN_BLENDER = (5, 1)
_SETTINGS = ("port", "token", "auto_start", "allow_code", "isolate_code", "allowed_folders")

# Runs inside Blender in background mode. Arguments after "--": action, zip path, port ("" = keep),
# auto start and allow code ("0" = off, "" = keep / on), token ("none" or "new" = keep, else the
# new token from the YAB_MCP_NEW_TOKEN environment variable).
_IN_BLENDER = r'''
import json, os, shutil, sys
import addon_utils, bpy

NAME, OLD_NAME = "yab_mcp", "blendermcp"  # the add-on was called blendermcp before 2.1
SETTINGS = %r
action, zip_path, port, auto_start, allow_code, token_mode = sys.argv[sys.argv.index("--") + 1:][:6]
addons = bpy.context.preferences.addons
out = {"blender": bpy.app.version_string}


def remove(module):
    """Disable one of our add-ons and delete its folder (preferences.addon_remove needs a UI area)."""
    for mod in addon_utils.modules():
        folder = os.path.dirname(mod.__file__)
        if (mod.__name__ == module and os.path.basename(folder) == module
                and os.path.isfile(os.path.join(folder, "handlers", "__init__.py"))):
            if module in addons:
                bpy.ops.preferences.addon_disable(module=module)
            shutil.rmtree(folder)
            return True
    if module in addons:  # still listed in the preferences, but its files are gone
        bpy.ops.preferences.addon_disable(module=module)
    return False


if action == "install":
    keep = {}  # disabling an add-on resets its preferences, so carry the current ones over
    for module in (NAME, OLD_NAME):
        entry = addons.get(module)
        if entry is not None and entry.preferences is not None:
            keep = {k: getattr(entry.preferences, k) for k in SETTINGS if hasattr(entry.preferences, k)}
            break
    out["migrated_from"] = OLD_NAME if remove(OLD_NAME) else None
    others = []
    for mod in addon_utils.modules():
        label = str(getattr(mod, "bl_info", {}).get("name", ""))
        if mod.__name__ != NAME and "mcp" in (mod.__name__ + label).lower() and addon_utils.check(mod.__name__)[1]:
            others.append(label or mod.__name__)
    out["other_mcp_addons"] = others
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
    # An older version may already be loaded in this session: unload it so the new files are imported.
    if NAME in addons:
        bpy.ops.preferences.addon_disable(module=NAME)
    for name in [n for n in sys.modules if n == NAME or n.startswith(NAME + ".")]:
        del sys.modules[name]
    bpy.ops.preferences.addon_enable(module=NAME)
    prefs = addons[NAME].preferences
    for key in ("isolate_code", "allowed_folders"):
        if key in keep:
            setattr(prefs, key, keep[key])
    prefs.port = int(port) if port else keep.get("port", prefs.port)
    prefs.auto_start = False if auto_start == "0" else keep.get("auto_start", True)
    prefs.allow_code = False if allow_code == "0" else keep.get("allow_code", True)
    if token_mode == "none":
        prefs.token = ""
    elif keep.get("token"):
        prefs.token = keep["token"]
    else:
        prefs.token = os.environ.get("YAB_MCP_NEW_TOKEN", "")
    import yab_mcp
    out.update(installed_to=os.path.dirname(yab_mcp.__file__), port=prefs.port, auto_start=prefs.auto_start,
               allow_code=prefs.allow_code, token=prefs.token, token_kept=bool(keep.get("token")))
else:
    out["removed"] = [m for m in (NAME, OLD_NAME) if remove(m)]
bpy.ops.wm.save_userpref()
print("YAB_MCP_RESULT " + json.dumps(out), flush=True)
''' % (_SETTINGS,)


class InstallError(Exception):
    pass


def _tail(text, lines=25):
    return "\n".join(text.strip().splitlines()[-lines:])


def _clean_env(**extra):
    """This environment without our settings (they would override the add-on's), plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("YAB_MCP_", "BLENDER_MCP_"))}
    env.update(extra)
    return env


def build_zip(path):
    """Pack the add-on the way Blender's Install from Disk expects it: files under a yab_mcp/ folder."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ADDON_SRC):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py"):
                    full = os.path.join(dirpath, name)
                    zf.write(full, os.path.join("yab_mcp", os.path.relpath(full, ADDON_SRC)))
    return path


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


def run_in_blender(blender, action, zip_path="", port=None, auto_start=None, allow_code=None, token_mode="new"):
    env = _clean_env(YAB_MCP_NEW_TOKEN=secrets.token_urlsafe(24))  # not on the command line: ps would show it
    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "yab_mcp_setup.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(_IN_BLENDER)
        cmd = [blender, "-b", "--python-exit-code", "1", "--python", script,
               "--", action, zip_path, str(port or ""), "0" if auto_start is False else "",
               "0" if allow_code is False else "", token_mode]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, encoding="utf-8",
                                errors="replace", env=env)
    for line in result.stdout.splitlines():
        if line.startswith("YAB_MCP_RESULT "):
            return json.loads(line.split(" ", 1)[1])
    raise InstallError(f"Blender could not {action} the add-on:\n{_tail(result.stdout + result.stderr)}")


def verify(blender, token):
    """Start a headless Blender with the installed add-on and run `yab-mcp --check` against it."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    log_path = os.path.join(tempfile.gettempdir(), f"yab_mcp_verify_{port}.log")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([blender, "-b", "-c", "yab_mcp", "--port", str(port)],
                                stdout=log, stderr=subprocess.STDOUT, env=_clean_env())
        try:
            deadline = time.time() + 120
            while time.time() < deadline and proc.poll() is None:
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                    break
                except OSError:
                    time.sleep(0.5)
            env = _clean_env(YAB_MCP_PORT=str(port), YAB_MCP_TOKEN=token, PYTHONUTF8="1")
            check = subprocess.run([sys.executable, "-m", "yab_mcp", "--check"], capture_output=True, text=True,
                                   env=env, timeout=180, encoding="utf-8", errors="replace")
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


def skill_target(skill_dir, name=None):
    return os.path.join(os.path.abspath(os.path.expanduser(skill_dir)), name or os.path.basename(SKILL))


def remove_skill(skill_dir):
    """Remove the skill, and its pre-2.1 copy (folder blender-mcp) when that copy is ours."""
    removed = []
    for name in (os.path.basename(SKILL), "blender-mcp"):
        target = skill_target(skill_dir, name)
        doc = os.path.join(target, "SKILL.md")
        if os.path.isfile(doc):
            with open(doc, encoding="utf-8", errors="replace") as f:
                ours = "YABlenderMCP" in f.read()
            if ours:
                shutil.rmtree(target)
                removed.append(target)
    return removed


def client_entry(port, token):
    if "archive-v0" in sys.prefix.replace("\\", "/").split("/"):  # run through uvx: a throwaway environment
        command, args = "uvx", ["yab-mcp"]
    else:
        command, args = sys.executable, ["-m", "yab_mcp"]
    entry = {"command": command, "args": args, "env": {"PYTHONUTF8": "1"}}
    if port != 9001:
        entry["env"]["YAB_MCP_PORT"] = str(port)
    if token:
        entry["env"]["YAB_MCP_TOKEN"] = token
    return {"mcpServers": {"yab-mcp": entry}}


def install(args):
    blender = find_blender(args.blender)
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = build_zip(os.path.join(tmp, "yab-mcp-addon.zip"))
        result = run_in_blender(blender, "install", zip_path, args.port, False if args.no_autostart else None,
                                False if args.no_code else None, "none" if args.no_token else "new")
    print(f"YABlenderMCP {__version__} installed and enabled: {result['installed_to']}")
    if result.get("migrated_from"):
        print(f"  Replaced the old add-on '{result['migrated_from']}' (settings kept)")
    token_state = "kept" if result["token_kept"] else ("new" if result["token"] else "off")
    print(f"  port {result['port']}, start server when Blender opens: {'on' if result['auto_start'] else 'off'}, "
          f"Python code: {'allowed' if result['allow_code'] else 'blocked'}, token: {token_state}")
    if result.get("other_mcp_addons"):
        print(f"  Warning: other MCP add-ons are enabled: {', '.join(result['other_mcp_addons'])}. "
              "Disable them in Edit > Preferences > Add-ons if they clash.")
    if not args.skip_verify:
        print("Self-test with a headless Blender ...", flush=True)
        verify(blender, result["token"])
    if args.skill_dir:
        remove_skill(args.skill_dir)
        shutil.copytree(SKILL, skill_target(args.skill_dir))
        print(f"Skill copied to {skill_target(args.skill_dir)}")
    print("\nPut this entry in your MCP client's config (replace an older \"yab-mcp\" or \"blender\" entry), "
          "then restart the client:")
    print(json.dumps(client_entry(result["port"], result["token"]), indent=2))
    print("\nOK: YABlenderMCP is installed. Open Blender; the server "
          + ("starts by itself." if result["auto_start"] else "starts from the YABlenderMCP tab (press N)."))
    return 0


def uninstall(args):
    blender = find_blender(args.blender)
    run_in_blender(blender, "uninstall")
    for path in remove_skill(args.skill_dir) if args.skill_dir else []:
        print(f"Skill removed: {path}")
    print("OK: add-on removed from Blender. Also remove the \"yab-mcp\" entry from your MCP client config.")
    return 0


def main(argv):
    command, rest = argv[0], argv[1:]
    if command == "build-addon":
        parser = argparse.ArgumentParser(prog="yab-mcp build-addon",
                                         description="Write the add-on zip for Blender's Install from Disk.")
        parser.add_argument("--out", default="yab-mcp-addon.zip", help="zip file to write")
        print(f"Created {build_zip(os.path.abspath(parser.parse_args(rest).out))}")
        return 0
    parser = argparse.ArgumentParser(prog=f"yab-mcp {command}",
                                     description=f"{command.capitalize()} the YABlenderMCP add-on (close Blender first).")
    parser.add_argument("--blender", help="path to the Blender executable (default: search the usual places)")
    parser.add_argument("--skill-dir", help="also copy (or remove) the yab-mcp skill in this skills folder")
    parser.add_argument("--force", action="store_true", help="go ahead even if Blender seems to be running")
    if command == "install":
        parser.add_argument("--port", type=int, help="add-on port (default: keep the current one, else 9001)")
        parser.add_argument("--no-autostart", action="store_true", help="don't start the server when Blender opens")
        parser.add_argument("--no-code", action="store_true",
                            help="block execute_blender_code (only the structured tools work)")
        parser.add_argument("--no-token", action="store_true", help="no token: any local program may connect")
        parser.add_argument("--skip-verify", action="store_true", help="skip the headless self-test")
    args = parser.parse_args(rest)
    try:
        if blender_running() and not args.force:
            raise InstallError("Blender is running. Close it first (it would overwrite the new preferences "
                               "when it quits), then run this again. Use --force to skip this check.")
        return install(args) if command == "install" else uninstall(args)
    except (InstallError, OSError, subprocess.SubprocessError) as e:
        print(f"\nFAILED: {e}")
        return 1
