"""Install YABlenderMCP from this folder (close Blender first):

    python install.py [options]        options as for `yab-mcp install --help`
    python install.py --uninstall      same as `yab-mcp uninstall`

Installs this folder into the running Python as the yab-mcp package (editable, so `git pull`
updates it), then runs `yab-mcp install`.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    if sys.version_info < (3, 10):
        print(f"\nFAILED: Python 3.10 or newer is needed (this is {sys.version.split()[0]})")
        sys.exit(1)
    print(f"Installing {ROOT} into {sys.executable} ...", flush=True)
    pip = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-e", ROOT])
    if pip.returncode != 0:
        print("\nFAILED: pip could not install this folder (see the pip output above)")
        sys.exit(1)
    args = sys.argv[1:]
    command = ["uninstall"] + [a for a in args if a != "--uninstall"] if "--uninstall" in args else ["install"] + args
    sys.exit(subprocess.call([sys.executable, "-m", "yab_mcp", *command]))
