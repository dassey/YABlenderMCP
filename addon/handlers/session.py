"""Session handlers: Blender info, undo/redo, batches, units, scene cleanup, API lookup."""

import re
import sys

import bpy

from . import get_handler, register_handler
from .code import to_jsonable

# Batches run inside one undo step, so they must not load files or walk the undo stack.
_NOT_IN_BATCH = {"open_blend", "undo", "redo", "execute_batch"}


def ping() -> dict:
    from .. import bl_info
    from ..server import PROTOCOL_VERSION
    return {"pong": True, "blender": bpy.app.version_string, "addon_version": list(bl_info["version"]),
            "protocol": PROTOCOL_VERSION}


def get_blender_info() -> dict:
    """Version, file, units, engine, counts, GPU."""
    scene = bpy.context.scene
    units = scene.unit_settings
    info = {
        "blender_version": bpy.app.version_string,
        "python": sys.version.split()[0],
        "file": bpy.data.filepath or None,
        "unsaved_changes": bpy.data.is_dirty,
        "scene": scene.name,
        "scenes": [s.name for s in bpy.data.scenes],
        "mode": bpy.context.mode,
        "units": {
            "system": units.system,
            "scale_length": units.scale_length,
            "length_unit": units.length_unit,
            "mm_per_blender_unit": round(units.scale_length * 1000.0, 6),
        },
        "render_engine": scene.render.engine,
        "frame_range": [scene.frame_start, scene.frame_end],
        "fps": scene.render.fps,
        "active_camera": scene.camera.name if scene.camera else None,
        "counts": {
            "objects": len(bpy.data.objects),
            "meshes": len(bpy.data.meshes),
            "materials": len(bpy.data.materials),
            "images": len(bpy.data.images),
            "actions": len(bpy.data.actions),
            "node_groups": len(bpy.data.node_groups),
            "collections": len(bpy.data.collections),
        },
        "background_mode": bpy.app.background,
    }
    try:
        import gpu
        info["gpu"] = {
            "backend": gpu.platform.backend_type_get(),
            "renderer": gpu.platform.renderer_get(),
            "version": gpu.platform.version_get(),
        }
    except Exception:
        pass
    cycles = bpy.context.preferences.addons.get("cycles")
    if cycles:
        prefs = cycles.preferences
        info["cycles"] = {
            "compute_device_type": prefs.compute_device_type,
            "devices": [{"name": d.name, "type": d.type, "use": d.use} for d in prefs.devices],
            "scene_device": scene.cycles.device,
        }
    return info


def _step_undo(op_name: str, steps: int) -> int:
    wm = bpy.context.window_manager
    if bpy.app.background or not wm.windows:
        raise RuntimeError("Undo/redo needs Blender's UI (it is not available in background mode)")
    op = getattr(bpy.ops.ed, op_name)
    done = 0
    with bpy.context.temp_override(window=wm.windows[0]):
        for _ in range(max(1, min(int(steps), 100))):
            try:
                if "FINISHED" not in op():
                    break
            except RuntimeError:
                break
            done += 1
    return done


def undo(steps: int = 1) -> dict:
    """Undo the last N steps (each MCP command is one step)."""
    done = _step_undo("undo", steps)
    return {"undone": done, "objects": sorted(o.name for o in bpy.context.scene.objects)[:200]}


def redo(steps: int = 1) -> dict:
    """Redo N undone steps."""
    done = _step_undo("redo", steps)
    return {"redone": done, "objects": sorted(o.name for o in bpy.context.scene.objects)[:200]}


def execute_batch(commands: list, stop_on_error: bool = True) -> dict:
    """Run several commands in one round trip and one undo step."""
    results = []
    for i, cmd in enumerate(commands):
        name = cmd.get("type") or cmd.get("command") or cmd.get("tool")
        params = cmd.get("params") or cmd.get("args") or {}
        handler = get_handler(name)
        if handler is None or name in _NOT_IN_BATCH:
            entry = {"index": i, "type": name, "status": "error", "message": f"Command not allowed in a batch: {name}"}
        else:
            try:
                entry = {"index": i, "type": name, "status": "success", "result": handler(**params)}
            except Exception as e:
                entry = {"index": i, "type": name, "status": "error", "message": f"{type(e).__name__}: {e}"}
        results.append(entry)
        if entry["status"] == "error" and stop_on_error:
            break
    return {
        "completed": sum(1 for r in results if r["status"] == "success"),
        "total": len(commands),
        "results": results,
    }


def set_units(system: str = "METRIC", length_unit: str = "", scale_length: float = 0.0,
              preset: str = "") -> dict:
    """Set scene units. preset="mm" makes 1 Blender unit = 1 millimeter (3D printing)."""
    units = bpy.context.scene.unit_settings
    if preset:
        presets = {
            "mm": ("METRIC", "MILLIMETERS", 0.001),
            "cm": ("METRIC", "CENTIMETERS", 0.01),
            "m": ("METRIC", "METERS", 1.0),
            "inch": ("IMPERIAL", "INCHES", 0.0254),
        }
        if preset.lower() not in presets:
            raise ValueError(f"Unknown preset '{preset}'. Valid: {', '.join(presets)}")
        system, length_unit, scale_length = presets[preset.lower()]
    units.system = system.upper()
    if scale_length > 0:
        units.scale_length = scale_length
    if length_unit:
        units.length_unit = length_unit.upper()
    if preset.lower() == "mm":
        # Keep a 300 mm build plate inside the viewport clip range.
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == "VIEW_3D":
                    space = area.spaces.active
                    space.clip_start = min(space.clip_start, 0.1)
                    space.clip_end = max(space.clip_end, 10000.0)
    return {
        "system": units.system,
        "length_unit": units.length_unit,
        "scale_length": units.scale_length,
        "mm_per_blender_unit": round(units.scale_length * 1000.0, 6),
    }


def clear_scene(keep_types: list = None, purge: bool = True) -> dict:
    """Delete all objects in the scene except the given types (e.g. ["CAMERA", "LIGHT"])."""
    keep = {t.upper() for t in (keep_types or [])}
    removed = []
    for obj in list(bpy.context.scene.objects):
        if obj.type not in keep:
            removed.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)
    purged = purge_orphans()["removed"] if purge else 0
    return {"removed": removed, "orphans_purged": purged}


def purge_orphans() -> dict:
    """Remove unused data-blocks (meshes, materials, images... with zero users)."""
    removed = bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    return {"removed": removed}


def _prop_doc(p) -> dict:
    doc = {"name": p.identifier, "type": p.type}
    if p.description:
        doc["description"] = p.description
    if p.subtype and p.subtype != "NONE":
        doc["subtype"] = p.subtype
    if p.is_readonly:
        doc["readonly"] = True
    if p.type == "ENUM":
        doc["items"] = [i.identifier for i in p.enum_items][:60]
        if p.is_enum_flag:
            doc["flag"] = True
    elif p.type in ("POINTER", "COLLECTION") and p.fixed_type:
        doc["fixed_type"] = p.fixed_type.identifier
    else:
        try:
            length = getattr(p, "array_length", 0)
            if length:
                doc["default"] = list(p.default_array)
            elif hasattr(p, "default"):
                doc["default"] = p.default
        except Exception:
            pass
    for attr in ("hard_min", "hard_max"):
        if hasattr(p, attr) and abs(getattr(p, attr)) < 1e30:
            doc[attr.replace("hard_", "")] = getattr(p, attr)
    return doc


def _operator_index():
    index = []
    for mod in dir(bpy.ops):
        if mod.startswith("_"):
            continue
        module = getattr(bpy.ops, mod)
        for name in dir(module):
            if not name.startswith("_"):
                index.append(f"bpy.ops.{mod}.{name}")
    return index


def search_api(query: str, limit: int = 40) -> dict:
    """Find bpy operators and types whose names or descriptions match all query words."""
    words = [w.lower() for w in query.split() if w]
    if not words:
        raise ValueError("Empty query")
    hits = []
    for path in _operator_index():
        _, _, mod, name = path.split(".")
        haystack = path.lower()
        if not all(w in haystack for w in words):
            try:
                rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
                haystack += " " + (rna.name + " " + rna.description).lower()
            except Exception:
                continue
            if not all(w in haystack for w in words):
                continue
            hits.append({"path": path, "description": rna.description[:160]})
        else:
            try:
                rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
                hits.append({"path": path, "description": rna.description[:160]})
            except Exception:
                hits.append({"path": path})
        if len(hits) >= limit:
            break
    for name in dir(bpy.types):
        if len(hits) >= limit * 2:
            break
        if all(w in name.lower() for w in words):
            hits.append({"path": f"bpy.types.{name}"})
    return {"query": query, "results": hits[: limit * 2]}


def get_api_docs(path: str) -> dict:
    """Describe an operator, type, property, or Python module member from the running Blender."""
    path = path.strip()
    if path.startswith("bpy.ops."):
        _, _, mod, name = path.split(".", 3)
        rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
        return {
            "path": path,
            "name": rna.name,
            "description": rna.description,
            "parameters": [_prop_doc(p) for p in rna.properties if p.identifier != "rna_type"],
        }
    short = path[len("bpy.types."):] if path.startswith("bpy.types.") else path
    type_name, _, member = short.partition(".")
    if hasattr(bpy.types, type_name):
        rna = getattr(bpy.types, type_name).bl_rna
        if member:
            if member in rna.properties:
                return {"path": path, **_prop_doc(rna.properties[member])}
            if member in rna.functions:
                fn = rna.functions[member]
                return {"path": path, "description": fn.description,
                        "parameters": [_prop_doc(p) for p in fn.parameters]}
            raise ValueError(f"'{member}' is not a property or function of {type_name}")
        return {
            "path": f"bpy.types.{type_name}",
            "description": rna.description,
            "base": rna.base.identifier if rna.base else None,
            "properties": [_prop_doc(p) for p in rna.properties if p.identifier != "rna_type"],
            "functions": [
                {"name": f.identifier, "description": f.description,
                 "parameters": [p.identifier for p in f.parameters]}
                for f in rna.functions
            ],
        }
    # Plain Python modules (bmesh.ops.*, mathutils.*, gpu.*, bpy.utils.* ...)
    import importlib
    parts = path.split(".")
    obj = importlib.import_module(parts[0])
    for part in parts[1:]:
        obj = getattr(obj, part)
    doc = {"path": path, "doc": (obj.__doc__ or "").strip()[:4000]}
    if not callable(obj):
        doc["members"] = [m for m in dir(obj) if not m.startswith("_")][:200]
    return doc


_ROOT_KINDS = {
    "object": "objects", "mesh": "meshes", "material": "materials", "light": "lights",
    "camera": "cameras", "collection": "collections", "node_group": "node_groups", "image": "images",
    "curve": "curves", "world": "worlds", "action": "actions", "scene": "scenes", "armature": "armatures",
    "text": "texts",
}


def _resolve_root(target):
    if not target or target == "scene":
        return bpy.context.scene
    if target == "world":
        return bpy.context.scene.world
    if target == "view_layer":
        return bpy.context.view_layer
    if ":" in target:
        kind, name = target.split(":", 1)
        if kind not in _ROOT_KINDS:
            raise ValueError(f"Unknown data kind '{kind}'. Valid: {', '.join(_ROOT_KINDS)}")
        block = getattr(bpy.data, _ROOT_KINDS[kind]).get(name)
        if block is None:
            raise ValueError(f"{kind} '{name}' not found")
        return block
    obj = bpy.data.objects.get(target)
    if obj is None:
        raise ValueError(f"'{target}' is not an object name. Use scene, world, view_layer or kind:Name "
                         f"({', '.join(_ROOT_KINDS)})")
    return obj


def _split_path(path):
    """'data.energy' -> ('data', 'energy', None); 'location[2]' -> ('', 'location', 2)."""
    index = None
    m = re.match(r"^(.*)\[(\d+)\]$", path)
    if m:
        path, index = m.group(1), int(m.group(2))
    depth, cut = 0, -1
    for i, ch in enumerate(path):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "." and depth == 0:
            cut = i
    if cut < 0:
        return "", path, index
    return path[:cut], path[cut + 1:], index


def get_properties(target: str = "scene", paths: list = None) -> dict:
    """Read RNA properties by data path, e.g. target="Light", paths=["data.energy", "location"]."""
    root = _resolve_root(target)
    if not paths:
        values = {}
        for prop in root.bl_rna.properties:
            if prop.identifier == "rna_type" or prop.type == "COLLECTION":
                continue
            try:
                values[prop.identifier] = to_jsonable(getattr(root, prop.identifier))
            except Exception:
                pass
        return {"target": target, "values": values}
    values = {}
    for path in paths:
        try:
            values[path] = to_jsonable(root.path_resolve(path))
        except Exception as e:
            values[path] = f"<error: {e}>"
    return {"target": target, "values": values}


def set_properties(target: str, properties: dict) -> dict:
    """Set RNA properties by data path, e.g. {"data.energy": 800, "modifiers[\"Bevel\"].width": 0.02}."""
    root = _resolve_root(target)
    done, errors = {}, {}
    for path, value in properties.items():
        try:
            owner_path, attr, index = _split_path(path)
            owner = root.path_resolve(owner_path) if owner_path else root
            if index is not None:
                getattr(owner, attr)[index] = value
            else:
                prop = owner.bl_rna.properties.get(attr)
                if prop is not None and prop.type == "ENUM" and prop.is_enum_flag and isinstance(value, list):
                    value = set(value)
                setattr(owner, attr, value)
            done[path] = to_jsonable(root.path_resolve(path))
        except Exception as e:
            hint = ""
            try:
                owner_path, attr, _ = _split_path(path)
                owner = root.path_resolve(owner_path) if owner_path else root
                if attr not in owner.bl_rna.properties:
                    close = [p.identifier for p in owner.bl_rna.properties if attr.lower() in p.identifier.lower()]
                    hint = f" (did you mean: {', '.join(close[:8])})" if close else ""
            except Exception:
                pass
            errors[path] = f"{type(e).__name__}: {e}{hint}"
    result = {"target": target, "set": done}
    if errors:
        result["errors"] = errors
    return result


def get_operator_history(limit: int = 20) -> dict:
    """Operators recently run in this Blender session (includes what the user did by hand)."""
    ops = [op for op in bpy.context.window_manager.operators if not op.bl_idname.startswith("BLENDERMCP_OT")]
    history = []
    for op in ops[-max(1, min(limit, 64)):]:
        entry = {"id": op.bl_idname, "name": op.name}
        props = {}
        for p in op.properties.bl_rna.properties:
            if p.identifier == "rna_type" or p.type in ("POINTER", "COLLECTION"):
                continue
            if p.subtype in ("FILE_PATH", "DIR_PATH", "FILE_NAME"):
                continue
            try:
                props[p.identifier] = to_jsonable(getattr(op.properties, p.identifier))
            except Exception:
                pass
        if props:
            entry["properties"] = props
        history.append(entry)
    return {"operators": history}


register_handler("ping", ping)
register_handler("get_properties", get_properties)
register_handler("set_properties", set_properties)
register_handler("get_operator_history", get_operator_history)
register_handler("get_blender_info", get_blender_info)
register_handler("undo", undo)
register_handler("redo", redo)
register_handler("execute_batch", execute_batch)
register_handler("set_units", set_units)
register_handler("clear_scene", clear_scene)
register_handler("purge_orphans", purge_orphans)
register_handler("search_api", search_api)
register_handler("get_api_docs", get_api_docs)
