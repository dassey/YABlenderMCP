"""File import/export, .blend files, local libraries, checkpoints and reference images."""

import math
import os
import re
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector

from . import register_handler
from .common import object_mode, rounded, select_only, unit_scale_to_mm, world_bbox


def _import_3mf(fp, **kw):
    return _read_3mf(fp)


_IMPORT_MAP = {
    ".fbx": lambda fp, **kw: bpy.ops.import_scene.fbx(filepath=fp, **kw),
    ".obj": lambda fp, **kw: bpy.ops.wm.obj_import(filepath=fp, **kw),
    ".glb": lambda fp, **kw: bpy.ops.import_scene.gltf(filepath=fp, **kw),
    ".gltf": lambda fp, **kw: bpy.ops.import_scene.gltf(filepath=fp, **kw),
    ".stl": lambda fp, **kw: bpy.ops.wm.stl_import(filepath=fp, **kw),
    ".ply": lambda fp, **kw: bpy.ops.wm.ply_import(filepath=fp, **kw),
    ".abc": lambda fp, **kw: bpy.ops.wm.alembic_import(filepath=fp, **kw),
    ".usd": lambda fp, **kw: bpy.ops.wm.usd_import(filepath=fp, **kw),
    ".usda": lambda fp, **kw: bpy.ops.wm.usd_import(filepath=fp, **kw),
    ".usdc": lambda fp, **kw: bpy.ops.wm.usd_import(filepath=fp, **kw),
    ".usdz": lambda fp, **kw: bpy.ops.wm.usd_import(filepath=fp, **kw),
    ".svg": lambda fp, **kw: bpy.ops.import_curve.svg(filepath=fp, **kw),
    ".3mf": _import_3mf,
}

_EXPORT_MAP = {
    ".fbx": lambda fp, **kw: bpy.ops.export_scene.fbx(filepath=fp, **kw),
    ".obj": lambda fp, **kw: bpy.ops.wm.obj_export(filepath=fp, **kw),
    ".glb": lambda fp, **kw: bpy.ops.export_scene.gltf(filepath=fp, export_format="GLB", **kw),
    ".gltf": lambda fp, **kw: bpy.ops.export_scene.gltf(filepath=fp, export_format="GLTF_SEPARATE", **kw),
    ".stl": lambda fp, **kw: bpy.ops.wm.stl_export(filepath=fp, **kw),
    ".ply": lambda fp, **kw: bpy.ops.wm.ply_export(filepath=fp, **kw),
    ".abc": lambda fp, **kw: bpy.ops.wm.alembic_export(filepath=fp, **kw),
    ".usd": lambda fp, **kw: bpy.ops.wm.usd_export(filepath=fp, **kw),
    ".usda": lambda fp, **kw: bpy.ops.wm.usd_export(filepath=fp, **kw),
    ".usdc": lambda fp, **kw: bpy.ops.wm.usd_export(filepath=fp, **kw),
    ".usdz": lambda fp, **kw: bpy.ops.wm.usd_export(filepath=fp, **kw),
}
# The "selected objects only" option is named differently per exporter.
_SELECTED_FLAG = {
    ".fbx": "use_selection", ".glb": "use_selection", ".gltf": "use_selection", ".obj": "export_selected_objects",
    ".stl": "export_selected_objects", ".ply": "export_selected_objects", ".abc": "selected",
    ".usd": "selected_objects_only", ".usda": "selected_objects_only", ".usdc": "selected_objects_only",
    ".usdz": "selected_objects_only",
}

_NS_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_NS_PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"
_UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}


def _3mf_matrix(text):
    if not text:
        return Matrix.Identity(4)
    m = [float(v) for v in text.split()]
    return Matrix(((m[0], m[3], m[6], m[9]), (m[1], m[4], m[7], m[10]), (m[2], m[5], m[8], m[11]), (0, 0, 0, 1)))


def _read_3mf(filepath):
    """Import the geometry of a .3mf (core spec + production components, e.g. Bambu Studio projects)."""
    with zipfile.ZipFile(filepath) as zf:
        names = set(zf.namelist())
        root_path = "3D/3dmodel.model"
        if "_rels/.rels" in names:
            rels = ET.fromstring(zf.read("_rels/.rels"))
            for rel in rels:
                if rel.get("Type", "").endswith("/3dmodel"):
                    root_path = rel.get("Target", root_path).lstrip("/")
        models = {}

        def load(path):
            path = path.lstrip("/")
            if path not in models:
                root = ET.fromstring(zf.read(path))
                unit = _UNIT_MM.get(root.get("unit", "millimeter"), 1.0)
                objects = {}
                resources = root.find(f"{_NS_CORE}resources")
                for obj in (resources if resources is not None else []):
                    if obj.tag != f"{_NS_CORE}object":
                        continue
                    entry = {"name": obj.get("name") or f"3mf_object_{obj.get('id')}"}
                    mesh = obj.find(f"{_NS_CORE}mesh")
                    if mesh is not None:
                        vs = mesh.find(f"{_NS_CORE}vertices")
                        ts = mesh.find(f"{_NS_CORE}triangles")
                        entry["verts"] = np.array([(float(v.get("x")), float(v.get("y")), float(v.get("z")))
                                                   for v in vs], dtype=np.float64) if vs is not None else np.zeros((0, 3))
                        entry["tris"] = np.array([(int(t.get("v1")), int(t.get("v2")), int(t.get("v3")))
                                                  for t in ts], dtype=np.int64) if ts is not None else np.zeros((0, 3), np.int64)
                    comps = obj.find(f"{_NS_CORE}components")
                    if comps is not None:
                        entry["components"] = [(c.get("objectid"), c.get(f"{_NS_PROD}path") or path,
                                                _3mf_matrix(c.get("transform"))) for c in comps]
                    objects[obj.get("id")] = entry
                build = root.find(f"{_NS_CORE}build")
                items = [(i.get("objectid"), i.get(f"{_NS_PROD}path") or path, _3mf_matrix(i.get("transform")))
                         for i in (build if build is not None else [])]
                models[path] = (unit, objects, items)
            return models[path]

        unit, _, items = load(root_path)
        scale = unit / unit_scale_to_mm()
        created = []

        def emit(object_id, path, matrix, label, depth=0):
            if depth > 16:
                return
            _, objects, _ = load(path)
            entry = objects.get(object_id)
            if entry is None:
                return
            if "verts" in entry and len(entry["tris"]):
                me = bpy.data.meshes.new(entry["name"])
                verts = entry["verts"] @ np.array(matrix.to_3x3()).T + np.array(matrix.translation)
                me.from_pydata((verts * scale).tolist(), [], entry["tris"].tolist())
                me.validate()
                obj = bpy.data.objects.new(label or entry["name"], me)
                bpy.context.collection.objects.link(obj)
                created.append(obj)
            for child_id, child_path, child_matrix in entry.get("components", []):
                emit(child_id, child_path, matrix @ child_matrix, None, depth + 1)

        for object_id, path, matrix in items:
            emit(object_id, path, matrix, None)
    return created


def _new_objects_after(fn):
    before = set(bpy.data.objects)
    out = fn()
    if isinstance(out, list):
        return out
    return [o for o in bpy.data.objects if o not in before]


def import_file(filepath: str, options=None, target_size: float = 0.0, drop_to_ground: bool = False,
                center: bool = False) -> dict:
    """Import a file into Blender, optionally scaling it to target_size (largest side, scene units)."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _IMPORT_MAP:
        raise ValueError(f"Unsupported import format '{ext}'. Supported: {', '.join(_IMPORT_MAP)}")

    object_mode()
    kw = options or {}
    new_objects = _new_objects_after(lambda: _IMPORT_MAP[ext](filepath, **kw))
    result = {"imported": True, "filepath": filepath, "new_objects": [o.name for o in new_objects]}
    geometry = [o for o in new_objects if o.type not in ("EMPTY", "LIGHT", "CAMERA")]
    if not geometry:
        return result

    roots = [o for o in new_objects if o.parent not in new_objects]
    bpy.context.view_layer.update()
    lo, hi = world_bbox(geometry)
    if target_size > 0:
        factor = target_size / max(max(hi - lo), 1e-12)
        pivot = (lo + hi) / 2
        pivot.z = lo.z
        m = Matrix.Translation(pivot) @ Matrix.Scale(factor, 4) @ Matrix.Translation(-pivot)
        for o in roots:
            o.matrix_world = m @ o.matrix_world
        result["scale_applied"] = round(factor, 6)
        bpy.context.view_layer.update()
        lo, hi = world_bbox(geometry)
    shift = [0.0, 0.0, 0.0]
    if center:
        shift[0], shift[1] = -(lo.x + hi.x) / 2, -(lo.y + hi.y) / 2
    if drop_to_ground:
        shift[2] = -lo.z
    if any(shift):
        for o in roots:
            o.matrix_world.translation += Vector(shift)
        bpy.context.view_layer.update()
        lo, hi = world_bbox(geometry)
    result["dimensions"] = rounded(hi - lo)
    result["bbox"] = [rounded(lo), rounded(hi)]
    return result


def export_file(filepath: str, options=None, objects: list = None) -> dict:
    """Export from Blender to a file (everything, or only the listed objects)."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in _EXPORT_MAP:
        raise ValueError(f"Unsupported export format '{ext}'. Supported: {', '.join(_EXPORT_MAP)}")

    kw = dict(options or {})
    if objects:
        missing = [n for n in objects if n not in bpy.data.objects]
        if missing:
            raise ValueError(f"Objects not found: {missing}")
        object_mode()
        select_only([bpy.data.objects[n] for n in objects])
        kw.setdefault(_SELECTED_FLAG[ext], True)
    _EXPORT_MAP[ext](filepath, **kw)

    result = {"exported": True, "filepath": filepath}
    if os.path.isfile(filepath):
        result["size_bytes"] = os.path.getsize(filepath)
    return result


def save_blend(filepath: str = "") -> dict:
    """Save the current .blend file."""
    if filepath:
        bpy.ops.wm.save_as_mainfile(filepath=filepath)
    elif not bpy.data.filepath:
        raise ValueError("This file has never been saved; pass a filepath")
    else:
        bpy.ops.wm.save_mainfile()

    return {"saved": True, "filepath": bpy.data.filepath}


def open_blend(filepath: str, discard_changes: bool = False) -> dict:
    """Open a .blend file (embedded scripts are never auto-run)."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")
    if bpy.data.is_dirty and not discard_changes and not bpy.app.background:
        raise ValueError("The current file has unsaved changes. Save it first (save_blend or save_checkpoint), "
                         "or pass discard_changes=True.")

    bpy.ops.wm.open_mainfile(filepath=filepath, use_scripts=False)
    return {"opened": True, "filepath": filepath}


def save_checkpoint(label: str = "") -> dict:
    """Save a timestamped copy of the current scene; the open file and its path stay untouched."""
    source = bpy.data.filepath
    stem = os.path.splitext(os.path.basename(source))[0] if source else "untitled"
    folder = os.path.join(os.path.dirname(source), f"{stem}_checkpoints") if source else \
        os.path.join(tempfile.gettempdir(), "blendermcp_checkpoints")
    os.makedirs(folder, exist_ok=True)
    tag = re.sub(r"[^A-Za-z0-9_-]+", "_", label).strip("_")[:40]
    path = os.path.join(folder, f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}{'_' + tag if tag else ''}.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, relative_remap=True)
    return {"checkpoint": path, "size_bytes": os.path.getsize(path), "active_file": bpy.data.filepath or None,
            "restore": "open_blend(checkpoint) to go back"}


def list_directory(path: str, filter: str = "") -> dict:
    """List files in a directory, optionally filtered by extension."""
    if not os.path.isdir(path):
        raise ValueError(f"Directory not found: {path}")

    entries = []
    for entry in sorted(os.listdir(path)):
        if filter and not entry.lower().endswith(filter.lower()):
            continue
        full = os.path.join(path, entry)
        entries.append({
            "name": entry,
            "is_dir": os.path.isdir(full),
            "size": os.path.getsize(full) if os.path.isfile(full) else 0,
        })

    return {"path": path, "entries": entries}


_BLEND_KINDS = ("objects", "collections", "materials", "node_groups", "meshes", "worlds", "actions", "images")


def _same_file(a, b):
    try:
        return bool(b) and os.path.samefile(a, b)
    except OSError:
        return False


def list_blend_contents(filepath: str) -> dict:
    """List what a .blend file contains (objects, collections, materials, node groups...) without opening it."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")
    if _same_file(filepath, bpy.data.filepath):
        raise ValueError("That is the file currently open; use get_scene_info / get_blender_info instead")
    contents = {}
    with bpy.data.libraries.load(filepath, link=False) as (src, _):
        for kind in _BLEND_KINDS:
            names = list(getattr(src, kind))
            if names:
                contents[kind] = names[:500]
    with bpy.data.libraries.load(filepath, link=False, assets_only=True) as (src, _):
        assets = {kind: list(getattr(src, kind)) for kind in _BLEND_KINDS if list(getattr(src, kind))}
    return {"filepath": filepath, "contents": contents, "marked_assets": assets}


def append_from_blend(filepath: str, names: list = None, data_type: str = "objects", link: bool = False) -> dict:
    """Append (or link) objects, collections, materials, node groups... from another .blend file."""
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")
    if data_type not in _BLEND_KINDS:
        raise ValueError(f"data_type must be one of {', '.join(_BLEND_KINDS)}")
    if _same_file(filepath, bpy.data.filepath):
        raise ValueError("Cannot append from the file that is currently open (use duplicate_object instead)")
    with bpy.data.libraries.load(filepath, link=link) as (src, dst):
        available = list(getattr(src, data_type))
        wanted = [n for n in available if not names or n in names]
        setattr(dst, data_type, wanted)
    loaded = [x for x in getattr(dst, data_type) if x is not None]
    if data_type == "objects":
        for obj in loaded:
            if not obj.users_collection:
                bpy.context.collection.objects.link(obj)
    elif data_type == "collections":
        for col in loaded:
            if col.name not in bpy.context.scene.collection.children:
                bpy.context.scene.collection.children.link(col)
    result = {"loaded": [x.name for x in loaded], "data_type": data_type, "linked": link}
    if names:
        missing = [n for n in names if n not in available]
        if missing:
            result["missing"] = missing
            result["available"] = available[:100]
    return result


def list_asset_libraries() -> dict:
    """The user's asset libraries (Preferences > File Paths) and the .blend files inside them."""
    libraries = []
    for lib in bpy.context.preferences.filepaths.asset_libraries:
        files = []
        if os.path.isdir(lib.path):
            for dirpath, _, filenames in os.walk(lib.path):
                files.extend(os.path.join(dirpath, f) for f in filenames if f.endswith(".blend"))
                if len(files) > 300:
                    break
        libraries.append({"name": lib.name, "path": lib.path, "blend_files": files[:300]})
    return {"libraries": libraries}


def add_reference_image(filepath: str, name: str = "", mode: str = "empty", size: float = 1.0,
                        location=None, view: str = "front", opacity: float = 0.5) -> dict:
    """Add a reference image (drawing, photo, blueprint) as an image empty or a textured plane.

    view: front (faces -Y), right (faces +X), top (faces +Z). size: height in scene units.
    """
    if not os.path.isfile(filepath):
        raise ValueError(f"File not found: {filepath}")
    rotations = {"front": (90, 0, 0), "back": (90, 0, 180), "right": (90, 0, 90), "left": (90, 0, -90),
                 "top": (0, 0, 0)}
    if view not in rotations:
        raise ValueError(f"view must be one of {', '.join(rotations)}")
    object_mode()
    img = bpy.data.images.load(filepath, check_existing=True)
    label = name or os.path.splitext(os.path.basename(filepath))[0]
    if mode == "plane":
        new = _new_objects_after(lambda: bpy.ops.image.import_as_mesh_planes(
            files=[{"name": os.path.basename(filepath)}], directory=os.path.dirname(filepath) + os.sep))
        if not new:
            raise RuntimeError("Image plane import failed")
        obj = new[0]
        obj.name = label
        bpy.context.view_layer.update()
        h = max(obj.dimensions.y, 1e-9)
        obj.scale = [s * size / h for s in obj.scale]
    else:
        obj = bpy.data.objects.new(label, None)
        obj.empty_display_type = "IMAGE"
        obj.data = img
        obj.empty_display_size = size * max(img.size[0], img.size[1]) / max(img.size[1], 1)
        obj.use_empty_image_alpha = opacity < 1.0
        obj.color[3] = opacity
        bpy.context.collection.objects.link(obj)
    obj.rotation_euler = Euler([math.radians(a) for a in rotations[view]])
    if location is not None:
        obj.location = location
    return {"name": obj.name, "mode": mode, "image": img.name, "pixels": list(img.size), "view": view}


register_handler("import_file", import_file)
register_handler("export_file", export_file)
register_handler("save_blend", save_blend)
register_handler("open_blend", open_blend)
register_handler("save_checkpoint", save_checkpoint)
register_handler("list_directory", list_directory)
register_handler("list_blend_contents", list_blend_contents)
register_handler("append_from_blend", append_from_blend)
register_handler("list_asset_libraries", list_asset_libraries)
register_handler("add_reference_image", add_reference_image)
