"""Build addon.zip for Blender's Add-ons > Install from Disk.

Blender rejects zips with __init__.py at the top level, so the files are
packed under a blendermcp/ folder.
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "addon")
ZIP = os.path.join(ROOT, "addon.zip")


def build(zip_path: str = ZIP) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith((".pyc", ".pyo")):
                    continue
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.join("blendermcp", os.path.relpath(full, SRC)))
    return zip_path


if __name__ == "__main__":
    print(f"Created {build()}")
