"""File import/export and directory listing handlers."""

import os

import bpy

from . import register_handler


_IMPORT_MAP = {
    ".fbx": lambda fp, **kw: bpy.ops.import_scene.fbx(filepath=fp, **kw),
    ".obj": lambda fp, **kw: bpy.ops.wm.obj_import(filepath=fp, **kw),
    ".glb": lambda fp, **kw: bpy.ops.import_scene.gltf(filepath=fp, **kw),
    ".gltf": lambda fp, **kw: bpy.ops.import_scene.gltf(filepath=fp, **kw),
    ".stl": lambda fp, **kw: bpy.ops.wm.stl_import(filepath=fp, **kw),
    ".ply": lambda fp, **kw: bpy.ops.wm.ply_import(filepath=fp, **kw),
    ".abc": lambda fp, **kw: bpy.ops.wm.alembic_import(filepath=fp, **kw),
}

_EXPORT_MAP = {
    ".fbx": lambda fp, **kw: bpy.ops.export_scene.fbx(filepath=fp, **kw),
    ".obj": lambda fp, **kw: bpy.ops.wm.obj_export(filepath=fp, **kw),
    ".glb": lambda fp, **kw: bpy.ops.export_scene.gltf(filepath=fp, export_format="GLB", **kw),
    ".gltf": lambda fp, **kw: bpy.ops.export_scene.gltf(filepath=fp, export_format="GLTF_SEPARATE", **kw),
    ".stl": lambda fp, **kw: bpy.ops.wm.stl_export(filepath=fp, **kw),
    ".ply": lambda fp, **kw: bpy.ops.wm.ply_export(filepath=fp, **kw),
    ".abc": lambda fp, **kw: bpy.ops.wm.alembic_export(filepath=fp, **kw),
}


def import_file(filepath: str, options=None) -> dict:
    """Import a file into Blender."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _IMPORT_MAP:
        raise ValueError(f"Unsupported import format '{ext}'. Supported: {', '.join(_IMPORT_MAP)}")

    kw = options or {}
    before = set(bpy.data.objects.keys())
    _IMPORT_MAP[ext](filepath, **kw)
    after = set(bpy.data.objects.keys())
    new_objects = list(after - before)

    return {"imported": True, "filepath": filepath, "new_objects": new_objects}


def export_file(filepath: str, options=None) -> dict:
    """Export from Blender to a file."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _EXPORT_MAP:
        raise ValueError(f"Unsupported export format '{ext}'. Supported: {', '.join(_EXPORT_MAP)}")

    kw = options or {}
    _EXPORT_MAP[ext](filepath, **kw)

    return {"exported": True, "filepath": filepath}


def save_blend(filepath: str = "") -> dict:
    """Save the current .blend file."""
    if filepath:
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
    else:
        bpy.ops.wm.save_mainfile()

    return {"saved": True, "filepath": bpy.data.filepath}


def open_blend(filepath: str) -> dict:
    """Open a .blend file."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")

    bpy.ops.wm.open_mainfile(filepath=filepath)
    return {"opened": True, "filepath": filepath}


def list_directory(path: str, filter: str = "") -> dict:
    """List files in a directory, optionally filtered by extension."""
    if not os.path.isdir(path):
        raise ValueError(f"Directory not found: {path}")

    entries = []
    for entry in os.listdir(path):
        if filter and not entry.lower().endswith(filter.lower()):
            continue
        full = os.path.join(path, entry)
        entries.append({
            "name": entry,
            "is_dir": os.path.isdir(full),
            "size": os.path.getsize(full) if os.path.isfile(full) else 0,
        })

    return {"path": path, "entries": entries}


register_handler("import_file", import_file)
register_handler("export_file", export_file)
register_handler("save_blend", save_blend)
register_handler("open_blend", open_blend)
register_handler("list_directory", list_directory)
