"""3D printing handlers: printability checks, repair, orientation, clearances, STL/3MF export, SDF parts.

Everything is measured in millimeters (scene units converted with unit_settings.scale_length).
"""

import math
import os
import zipfile
from xml.sax.saxutils import escape

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import register_handler
from .common import get_object, object_mode, select_only, unit_scale_to_mm, world_bbox

# Build volumes in mm (X, Y, Z). H2C/H2D/H2S values from Bambu Lab specs.
PRINTERS = {
    "H2C": (330, 320, 325),
    "H2D": (350, 320, 325),
    "H2S": (340, 320, 340),
    "X1C": (256, 256, 256),
    "X1E": (256, 256, 256),
    "P1S": (256, 256, 256),
    "P1P": (256, 256, 256),
    "P2S": (256, 256, 256),
    "A1": (256, 256, 256),
    "A1 MINI": (180, 180, 180),
}
_PRINTABLE_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT"}


def _targets(names):
    if names:
        objs = [get_object(n) for n in names]
    else:
        objs = [o for o in bpy.context.selected_objects if o.type in _PRINTABLE_TYPES] or \
               [o for o in bpy.context.scene.objects if o.type in _PRINTABLE_TYPES and o.visible_get()]
    bad = [o.name for o in objs if o.type not in _PRINTABLE_TYPES]
    if bad:
        raise ValueError(f"Not printable geometry: {bad}")
    if not objs:
        raise ValueError("No mesh objects to check")
    return objs


def _build_volume(printer, build_volume_mm):
    if build_volume_mm:
        return tuple(float(v) for v in build_volume_mm)
    if printer:
        key = printer.upper().replace("BAMBU LAB ", "").strip()
        if key not in PRINTERS:
            raise ValueError(f"Unknown printer '{printer}'. Known: {', '.join(PRINTERS)}")
        return PRINTERS[key]
    return None


def _triangles(objs):
    """World-space triangles in mm for the evaluated objects: (verts (V,3), tris (T,3), owner per tri)."""
    dg = bpy.context.evaluated_depsgraph_get()
    scale = unit_scale_to_mm()
    all_v, all_t, owner = [], [], []
    offset = 0
    for i, obj in enumerate(objs):
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            v = np.empty(len(me.vertices) * 3, np.float64)
            me.vertices.foreach_get("co", v)
            t = np.empty(len(me.loop_triangles) * 3, np.int64)
            me.loop_triangles.foreach_get("vertices", t)
        finally:
            ev.to_mesh_clear()
        v = v.reshape(-1, 3)
        t = t.reshape(-1, 3)
        m = np.array(obj.matrix_world, dtype=np.float64)
        v = v @ m[:3, :3].T + m[:3, 3]
        if np.linalg.det(m[:3, :3]) < 0:
            t = t[:, ::-1]  # mirrored object: keep faces pointing outward
        all_v.append(v * scale)
        all_t.append(t + offset)
        owner.append(np.full(len(t), i))
        offset += len(v)
    if not all_v:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64)
    return np.vstack(all_v), np.vstack(all_t), np.concatenate(owner)


def _weld(verts, tolerance=1e-4):
    """Map vertices that share a position (within tolerance, mm) to one id, like slicers do."""
    keys = np.round(verts / tolerance).astype(np.int64)
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    return ids.reshape(-1)


def _components(n, pairs):
    """Connected-component label per vertex (union-find over edge pairs)."""
    parent = list(range(n))

    def find(i):
        root = i
        while parent[root] != root:
            root = parent[root]
        while parent[i] != root:
            parent[i], i = root, parent[i]
        return root

    for a, b in pairs.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def _analyze(verts, tris, overhang_angle=45.0, min_wall_mm=0.0, self_intersections=True,
             bed_z=None, sample_limit=20000):
    report = {}
    if len(tris) == 0:
        return {"triangles": 0, "issues": [{"severity": "blocking", "issue": "no faces"}]}
    vid = _weld(verts)
    t = vid[tris]
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    cross = np.cross(b - a, c - a)
    area2 = np.linalg.norm(cross, axis=1)
    areas = area2 / 2
    normals = np.divide(cross, area2[:, None], out=np.zeros_like(cross), where=area2[:, None] > 0)
    signed = np.einsum("ij,ij->i", a, np.cross(b, c)) / 6.0

    degenerate = (areas < 1e-6) | (t[:, 0] == t[:, 1]) | (t[:, 1] == t[:, 2]) | (t[:, 0] == t[:, 2])
    valid = ~degenerate
    tv = t[valid]
    directed = np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]])
    undirected = np.sort(directed, axis=1)
    _, edge_counts = np.unique(undirected, axis=0, return_counts=True)
    _, dir_counts = np.unique(directed, axis=0, return_counts=True)
    boundary = int((edge_counts == 1).sum())
    non_manifold = int((edge_counts > 2).sum())
    flipped = int((dir_counts > 1).sum())

    comp_v = _components(int(vid.max()) + 1, np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]]]))
    shell_of_tri = comp_v[tv[:, 0]]
    shells, shell_index = np.unique(shell_of_tri, return_inverse=True)
    shell_volume = np.bincount(shell_index, weights=signed[valid])
    inverted_shells = int((shell_volume < -1e-6).sum())

    lo, hi = verts[np.unique(tris)].min(axis=0), verts[np.unique(tris)].max(axis=0)
    bed = lo[2] if bed_z is None else bed_z
    tri_min_z = np.minimum(np.minimum(a[:, 2], b[:, 2]), c[:, 2])
    on_bed = tri_min_z <= bed + 0.05
    limit = math.sin(math.radians(overhang_angle))
    overhang = (normals[:, 2] < -limit) & ~on_bed & valid
    contact = (normals[:, 2] < -0.99) & (np.maximum(np.maximum(a[:, 2], b[:, 2]), c[:, 2]) <= bed + 0.05)

    watertight = boundary == 0 and non_manifold == 0
    report.update({
        "triangles": int(len(tris)),
        "dimensions_mm": [round(float(x), 3) for x in (hi - lo)],
        "bbox_min_mm": [round(float(x), 3) for x in lo],
        "volume_cm3": round(float(signed[valid].sum()) / 1000.0, 4) if watertight else None,
        "surface_area_cm2": round(float(areas.sum()) / 100.0, 3),
        "watertight": watertight,
        "boundary_edges": boundary,
        "non_manifold_edges": non_manifold,
        "inconsistent_normal_edges": flipped,
        "degenerate_faces": int(degenerate.sum()),
        "shells": int(len(shells)),
        "inverted_shells": inverted_shells,
        "overhang_area_mm2": round(float(areas[overhang].sum()), 2),
        "overhang_faces": int(overhang.sum()),
        "bed_contact_area_mm2": round(float(areas[contact].sum()), 2),
        "min_z_mm": round(float(lo[2]), 4),
    })

    bvh = None
    if self_intersections and len(tris) <= 400000:
        bvh = BVHTree.FromPolygons(verts.tolist(), tris.tolist(), all_triangles=True, epsilon=0.0)
        pairs = bvh.overlap(bvh)
        hits = 0
        for i, j in pairs:
            if i < j and not (set(t[i]) & set(t[j])) and valid[i] and valid[j]:
                hits += 1
        report["self_intersections"] = hits
    elif self_intersections:
        report["self_intersections"] = "skipped (over 400k triangles)"

    if min_wall_mm > 0:
        if bvh is None:
            bvh = BVHTree.FromPolygons(verts.tolist(), tris.tolist(), all_triangles=True, epsilon=0.0)
        candidates = np.nonzero(valid)[0]
        step = max(1, len(candidates) // sample_limit)
        sample = candidates[::step]
        centers = (a + b + c) / 3
        thin_area, thin_count, thinnest = 0.0, 0, None
        for i in sample:
            n = Vector(normals[i])
            origin = Vector(centers[i]) - n * 1e-4
            loc, _, idx, dist = bvh.ray_cast(origin, -n, min_wall_mm)
            if loc is not None and idx != i and dist > 1e-4:
                thin_count += 1
                thin_area += float(areas[i])
                thinnest = dist if thinnest is None else min(thinnest, dist)
        report["thin_wall"] = {
            "min_wall_mm": min_wall_mm,
            "faces_sampled": int(len(sample)),
            "thin_faces": thin_count,
            "thin_area_mm2_estimate": round(thin_area * step, 2),
            "thinnest_mm": round(thinnest, 3) if thinnest is not None else None,
        }
    return report


def _issues(report, volume, on_bed_required=True):
    issues = []
    if report.get("boundary_edges"):
        issues.append({"severity": "blocking", "issue": f"{report['boundary_edges']} open (boundary) edges: mesh has holes"})
    if report.get("non_manifold_edges"):
        issues.append({"severity": "blocking", "issue": f"{report['non_manifold_edges']} non-manifold edges (shared by 3+ faces)"})
    if report.get("inconsistent_normal_edges"):
        issues.append({"severity": "blocking", "issue": f"{report['inconsistent_normal_edges']} edges with flipped neighbouring faces"})
    if report.get("inverted_shells"):
        issues.append({"severity": "blocking", "issue": f"{report['inverted_shells']} shell(s) inside-out (normals point inward)"})
    if isinstance(report.get("self_intersections"), int) and report["self_intersections"]:
        issues.append({"severity": "blocking", "issue": f"{report['self_intersections']} self-intersecting face pairs"})
    if report.get("degenerate_faces"):
        issues.append({"severity": "advisory", "issue": f"{report['degenerate_faces']} zero-area faces"})
    if report.get("shells", 1) > 1:
        issues.append({"severity": "advisory", "issue": f"{report['shells']} separate shells (fine for print-in-place parts)"})
    if volume:
        dims = report["dimensions_mm"]
        if any(d > v for d, v in zip(dims, volume)):
            fits_rotated = sorted(dims[:2]) <= sorted(volume[:2]) and dims[2] <= volume[2]
            issues.append({"severity": "blocking",
                           "issue": f"{dims} mm exceeds build volume {list(volume)} mm"
                                    + (" (fits if rotated 90° on the bed)" if fits_rotated else "")})
    if on_bed_required and abs(report.get("min_z_mm", 0)) > 0.05:
        issues.append({"severity": "advisory", "issue": f"lowest point is at z={report['min_z_mm']} mm, not on the bed (z=0)"})
    thin = report.get("thin_wall")
    if thin and thin["thin_faces"]:
        issues.append({"severity": "advisory",
                       "issue": f"thin walls under {thin['min_wall_mm']} mm (thinnest {thin['thinnest_mm']} mm)"})
    if report.get("overhang_area_mm2", 0) > 1.0:
        issues.append({"severity": "advisory", "issue": f"{report['overhang_area_mm2']} mm² of overhangs need support"})
    if report.get("bed_contact_area_mm2", 1) < 1.0:
        issues.append({"severity": "advisory", "issue": "almost no flat bed contact (adhesion risk)"})
    return issues


def check_printability(objects: list = None, printer: str = "", build_volume_mm=None,
                       min_wall_mm: float = 0.8, overhang_angle: float = 45.0,
                       self_intersections: bool = True, combined: bool = False) -> dict:
    """Check meshes for 3D printing: watertight, manifold, normals, self-intersections, thin walls,
    overhangs, bed contact and build volume. Uses the evaluated mesh (modifiers applied), in mm."""
    objs = _targets(objects)
    volume = _build_volume(printer, build_volume_mm)
    results = []
    groups = [objs] if combined else [[o] for o in objs]
    for group in groups:
        verts, tris, _ = _triangles(group)
        report = _analyze(verts, tris, overhang_angle, min_wall_mm, self_intersections)
        report["issues"] = _issues(report, volume)
        report["print_ready"] = not any(i["severity"] == "blocking" for i in report["issues"])
        report["objects" if combined else "object"] = [o.name for o in group] if combined else group[0].name
        results.append(report)
    return {
        "printer": printer.upper() or None,
        "build_volume_mm": list(volume) if volume else None,
        "results": results,
        "all_print_ready": all(r["print_ready"] for r in results),
    }


def repair_mesh(objects: list = None, merge_distance_mm: float = 0.01, fill_holes: bool = True,
                recalc_normals: bool = True, delete_loose: bool = True, dissolve_degenerate: bool = True,
                voxel_remesh_mm: float = 0.0, apply_modifiers: bool = False) -> dict:
    """Fix common print problems in place: merge duplicates, remove loose/degenerate geometry,
    fill holes, make normals consistent; optional voxel remesh to force a watertight solid."""
    objs = [o for o in _targets(objects) if o.type == "MESH"]
    object_mode()
    to_bu = 1.0 / unit_scale_to_mm()
    out = []
    for obj in objs:
        before = _analyze(*_triangles([obj])[:2], self_intersections=False)
        if apply_modifiers and obj.modifiers:
            select_only([obj])
            for mod in list(obj.modifiers):
                bpy.ops.object.modifier_apply(modifier=mod.name)
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        sx = max(abs(s) for s in obj.matrix_world.to_scale()) or 1.0
        dist = merge_distance_mm * to_bu / sx
        steps = {}
        n = len(bm.verts)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=dist)
        steps["merged_vertices"] = n - len(bm.verts)
        if dissolve_degenerate:
            bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=bm.edges)
        if delete_loose:
            loose_e = [e for e in bm.edges if not e.link_faces]
            loose_v = [v for v in bm.verts if not v.link_edges]
            bmesh.ops.delete(bm, geom=loose_e, context="EDGES")
            loose_v += [v for v in bm.verts if not v.link_edges]
            bmesh.ops.delete(bm, geom=list(set(loose_v)), context="VERTS")
            steps["removed_loose"] = len(loose_e) + len(loose_v)
        if fill_holes:
            boundary = [e for e in bm.edges if e.is_boundary]
            if boundary:
                res = bmesh.ops.holes_fill(bm, edges=boundary, sides=0)
                steps["holes_filled"] = len(res["faces"])
        if recalc_normals:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.validate()
        obj.data.update()
        if voxel_remesh_mm > 0:
            lo, hi = world_bbox([obj])
            cells = math.prod(max((h - l) * unit_scale_to_mm() / voxel_remesh_mm, 1) for l, h in zip(lo, hi))
            if cells > 40_000_000:
                raise ValueError(f"voxel_remesh_mm={voxel_remesh_mm} would need {cells:.0f} cells; use a larger size "
                                 f"(at least {voxel_remesh_mm * (cells / 40_000_000) ** (1 / 3):.3f})")
            mod = obj.modifiers.new("MCP Remesh", "REMESH")
            mod.mode = "VOXEL"
            mod.voxel_size = voxel_remesh_mm * to_bu / sx
            select_only([obj])
            bpy.ops.object.modifier_apply(modifier=mod.name)
            steps["voxel_remesh_mm"] = voxel_remesh_mm
        after = _analyze(*_triangles([obj])[:2], self_intersections=False)
        keys = ("watertight", "boundary_edges", "non_manifold_edges", "inconsistent_normal_edges",
                "inverted_shells", "shells", "triangles")
        out.append({"object": obj.name, "steps": steps,
                    "before": {k: before.get(k) for k in keys}, "after": {k: after.get(k) for k in keys}})
    return {"results": out}


def _hull_candidates(verts, max_candidates=12):
    """Face-normal groups of the convex hull, largest area first (stable resting faces)."""
    bm = bmesh.new()
    for v in verts[::max(1, len(verts) // 50000)]:
        bm.verts.new(v)
    if len(bm.verts) < 4:
        bm.free()
        return []
    bmesh.ops.convex_hull(bm, input=bm.verts)
    faces = [f for f in bm.faces if f.is_valid]
    normals = np.array([f.normal for f in faces], dtype=np.float64)
    areas = np.array([f.calc_area() for f in faces], dtype=np.float64)
    bm.free()
    order = np.argsort(-areas)
    assigned = np.zeros(len(faces), bool)
    groups = []
    cos_tol = math.cos(math.radians(1.0))
    for i in order:
        if assigned[i]:
            continue
        mask = (~assigned) & (normals @ normals[i] > cos_tol)
        assigned |= mask
        groups.append((float(areas[mask].sum()), normals[i]))
        if len(groups) >= 200:
            break
    groups.sort(key=lambda g: -g[0])
    return [Vector(n) for _, n in groups[:max_candidates]]


def _rotation_down(n):
    return Vector(n).rotation_difference(Vector((0, 0, -1))).to_matrix()


def prepare_for_print(objects: list = None, orientation: str = "keep", place_on_bed: bool = True,
                      center: bool = True, as_group: bool = True, overhang_angle: float = 45.0,
                      printer: str = "") -> dict:
    """Get objects ready to slice: orient (keep, flat = largest flat face down, min_overhang),
    drop to z=0, centre on the origin, origin at the bottom centre. as_group keeps an
    assembly (e.g. print-in-place parts) rigid."""
    objs = _targets(objects)
    object_mode()
    groups = [objs] if as_group else [[o] for o in objs]
    limit = math.sin(math.radians(overhang_angle))
    report = []
    for group in groups:
        verts, tris, _ = _triangles(group)
        chosen = Matrix.Identity(3)
        info = {"objects": [o.name for o in group], "orientation": orientation}
        if orientation in ("flat", "min_overhang") and len(tris):
            a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
            cross = np.cross(b - a, c - a)
            areas = np.linalg.norm(cross, axis=1) / 2
            normals = np.divide(cross, (2 * areas)[:, None], out=np.zeros_like(cross), where=areas[:, None] > 0)
            candidates = _hull_candidates(verts)
            if orientation == "min_overhang":
                candidates += [Vector(d) for d in ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]

            def score(n):
                r = np.array(_rotation_down(n))
                rn = normals @ r.T
                z = np.stack([a @ r.T, b @ r.T, c @ r.T])[:, :, 2]
                bed = z.min()
                on_bed = z.min(axis=0) <= bed + 0.05
                over = float(areas[(rn[:, 2] < -limit) & ~on_bed].sum())
                contact = float(areas[(rn[:, 2] < -0.99) & (z.max(axis=0) <= bed + 0.05)].sum())
                return over, contact

            if candidates:
                if orientation == "flat":
                    best = candidates[0]
                    over, contact = score(best)
                else:
                    scored = [(score(n), n) for n in candidates]
                    (over, contact), best = min(scored, key=lambda s: (round(s[0][0], 1), -s[0][1]))
                chosen = _rotation_down(best)
                info.update(overhang_area_mm2=round(over, 2), bed_contact_area_mm2=round(contact, 2))
        if chosen != Matrix.Identity(3):
            lo, hi = world_bbox(group)
            pivot = (lo + hi) / 2
            m = Matrix.Translation(pivot) @ chosen.to_4x4() @ Matrix.Translation(-pivot)
            for o in group:
                if o.parent is None or o.parent not in group:
                    o.matrix_world = m @ o.matrix_world
        bpy.context.view_layer.update()
        verts, tris, _ = _triangles(group)
        to_bu = 1.0 / unit_scale_to_mm()
        lo, hi = verts.min(axis=0) * to_bu, verts.max(axis=0) * to_bu
        shift = Vector((0, 0, 0))
        if place_on_bed:
            shift.z = -lo[2]
        if center:
            shift.x, shift.y = -(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2
        for o in group:
            if o.parent is None or o.parent not in group:
                o.matrix_world.translation += shift
        bpy.context.view_layer.update()
        verts, _, _ = _triangles(group)
        dims = verts.max(axis=0) - verts.min(axis=0)
        info["dimensions_mm"] = [round(float(x), 3) for x in dims]
        volume = _build_volume(printer, None)
        if volume:
            info["fits_build_volume"] = all(d <= v for d, v in zip(dims, volume))
        report.append(info)
    return {"results": report}


def _bvh(verts, tris):
    return BVHTree.FromPolygons(verts.tolist(), tris.tolist(), all_triangles=True, epsilon=0.0)


def _min_distance(src_verts, bvh, cap=20000):
    step = max(1, len(src_verts) // cap)
    best = None
    for v in src_verts[::step]:
        hit = bvh.find_nearest(Vector(v))
        if hit[0] is not None and (best is None or hit[3] < best):
            best = hit[3]
    return best


def check_clearances(objects: list = None, min_clearance_mm: float = 0.3, split_shells: bool = False) -> dict:
    """Find parts that touch, intersect (fused) or sit closer than min_clearance_mm.

    Checks every pair of objects, or every pair of separate shells inside one object
    (split_shells=True), which is how print-in-place joints are usually modeled.
    """
    objs = _targets(objects)
    parts = []
    if split_shells:
        for obj in objs:
            verts, tris, _ = _triangles([obj])
            vid = _weld(verts)
            comp = _components(int(vid.max()) + 1, np.concatenate([vid[tris][:, [0, 1]], vid[tris][:, [1, 2]]]))
            shell = comp[vid[tris[:, 0]]]
            for k, sid in enumerate(np.unique(shell)):
                st = tris[shell == sid]
                parts.append((f"{obj.name}#shell{k}", verts, st))
    else:
        for obj in objs:
            verts, tris, _ = _triangles([obj])
            parts.append((obj.name, verts, tris))
    if len(parts) < 2:
        raise ValueError("Need at least two parts (objects, or shells with split_shells=True)")
    if len(parts) > 60:
        raise ValueError(f"{len(parts)} parts is too many to compare pairwise (max 60)")

    data = []
    for name, verts, tris in parts:
        used = np.unique(tris)
        pv = verts[used]
        data.append((name, pv, pv.min(axis=0), pv.max(axis=0), _bvh(verts, tris)))
    pairs = []
    for i in range(len(data)):
        for j in range(i + 1, len(data)):
            na, va, loa, hia, ba = data[i]
            nb, vb, lob, hib, bb = data[j]
            gap = np.maximum(np.maximum(lob - hia, loa - hib), 0)
            box_gap = float(np.linalg.norm(gap))
            if box_gap > min_clearance_mm * 3:
                continue
            if ba.overlap(bb):
                pairs.append({"a": na, "b": nb, "status": "intersecting", "clearance_mm": 0.0})
                continue
            d = min(x for x in (_min_distance(va, bb), _min_distance(vb, ba)) if x is not None)
            status = "touching" if d < 1e-3 else ("too_close" if d < min_clearance_mm else "ok")
            pairs.append({"a": na, "b": nb, "status": status, "clearance_mm": round(d, 4)})
    problems = [p for p in pairs if p["status"] != "ok"]
    return {"parts": [p[0] for p in parts], "min_clearance_mm": min_clearance_mm,
            "close_pairs": pairs, "problems": len(problems), "ok": not problems}


def _object_color(obj):
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        if mat.node_tree:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED" and not node.inputs["Base Color"].is_linked:
                    return tuple(node.inputs["Base Color"].default_value[:3])
        return tuple(mat.diffuse_color[:3])
    return None


def _write_3mf(filepath, objs):
    scale = unit_scale_to_mm()
    dg = bpy.context.evaluated_depsgraph_get()
    colors, objects_xml, items = [], [], []
    stats = []
    for index, obj in enumerate(objs, start=1):
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        try:
            me.calc_loop_triangles()
            v = np.empty(len(me.vertices) * 3, np.float64)
            me.vertices.foreach_get("co", v)
            t = np.empty(len(me.loop_triangles) * 3, np.int64)
            me.loop_triangles.foreach_get("vertices", t)
        finally:
            ev.to_mesh_clear()
        m = np.array(obj.matrix_world, dtype=np.float64)
        v = (v.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]) * scale
        t = t.reshape(-1, 3)
        if np.linalg.det(m[:3, :3]) < 0:
            t = t[:, ::-1]
        color = _object_color(obj)
        pid = ""
        if color is not None:
            colors.append(color)
            pid = f' pid="1" pindex="{len(colors) - 1}"'
        vertices = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
        triangles = "".join(f'<triangle v1="{i}" v2="{j}" v3="{k}"/>' for i, j, k in t)
        objects_xml.append(f'<object id="{index + 1}" type="model" name="{escape(obj.name, {chr(34): "&quot;"})}"{pid}>'
                           f"<mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh></object>")
        items.append(f'<item objectid="{index + 1}"/>')
        stats.append({"object": obj.name, "triangles": int(len(t)),
                      "dimensions_mm": [round(float(x), 3) for x in (v.max(axis=0) - v.min(axis=0))]})
    materials = ""
    if colors:
        bases = "".join(
            f'<base name="color{i}" displaycolor="#{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}FF"/>'
            for i, (r, g, b) in enumerate(colors))
        materials = f'<basematerials id="1">{bases}</basematerials>'
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Application">YABlenderMCP</metadata>'
             f"<resources>{materials}{''.join(objects_xml)}</resources>"
             f"<build>{''.join(items)}</build></model>")
    content_types = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                     '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
                     "</Types>")
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(filepath, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model)
    return stats


def export_print(filepath: str, objects: list = None, check: bool = True, separate_files: bool = False,
                 printer: str = "") -> dict:
    """Export objects for slicing in millimeters: .3mf (one file, objects kept separate, colours kept)
    or .stl (merged, or one file per object with separate_files). Modifiers are applied."""
    objs = _targets(objects)
    ext = os.path.splitext(filepath)[1].lower()
    if ext not in (".stl", ".3mf"):
        raise ValueError("filepath must end in .stl or .3mf")
    directory = os.path.dirname(os.path.abspath(filepath))
    if not os.path.isdir(directory):
        raise ValueError(f"Directory does not exist: {directory}")
    object_mode()
    result = {"filepath": filepath, "format": ext[1:], "objects": [o.name for o in objs]}
    if ext == ".3mf":
        result["parts"] = _write_3mf(filepath, objs)
    else:
        meshable = [o for o in objs]
        select_only(meshable)
        bpy.ops.wm.stl_export(filepath=filepath, export_selected_objects=True, apply_modifiers=True,
                              global_scale=unit_scale_to_mm(), use_scene_unit=False, use_batch=separate_files,
                              ascii_format=False)
        if separate_files:
            result["note"] = "One STL per object, named after the objects, next to filepath"
    if os.path.isfile(filepath):
        result["size_bytes"] = os.path.getsize(filepath)
    if check:
        checked = check_printability([o.name for o in objs], printer=printer, min_wall_mm=0.0,
                                     self_intersections=False)
        result["checks"] = [{"object": r["object"], "print_ready": r["print_ready"],
                             "issues": [i["issue"] for i in r["issues"] if i["severity"] == "blocking"]}
                            for r in checked["results"]]
    return result


# --- SDF modeling -----------------------------------------------------------

def _rot(deg):
    from mathutils import Euler
    return np.array(Euler([math.radians(d) for d in deg]).to_matrix(), dtype=np.float32)


def _local(X, Y, Z, center, rotation):
    px, py, pz = X - center[0], Y - center[1], Z - center[2]
    if rotation and any(rotation):
        r = _rot(rotation).T  # world -> local
        px, py, pz = (r[0, 0] * px + r[0, 1] * py + r[0, 2] * pz,
                      r[1, 0] * px + r[1, 1] * py + r[1, 2] * pz,
                      r[2, 0] * px + r[2, 1] * py + r[2, 2] * pz)
    return px, py, pz


def _segment_sdf(X, Y, Z, p0, p1):
    """Distance to segment p0-p1 and the clamped parameter along it."""
    p0, p1 = np.asarray(p0, np.float32), np.asarray(p1, np.float32)
    ba = p1 - p0
    length2 = float(ba @ ba) or 1e-12
    px, py, pz = X - p0[0], Y - p0[1], Z - p0[2]
    h = np.clip((px * ba[0] + py * ba[1] + pz * ba[2]) / length2, 0.0, 1.0)
    dx, dy, dz = px - ba[0] * h, py - ba[1] * h, pz - ba[2] * h
    return np.sqrt(dx * dx + dy * dy + dz * dz), h


def _shape_sdf(shape, X, Y, Z, origin, vox):
    kind = shape["type"].lower()
    center = shape.get("center", [0, 0, 0])
    rotation = shape.get("rotation", [0, 0, 0])
    if kind == "sphere":
        px, py, pz = _local(X, Y, Z, center, None)
        return np.sqrt(px * px + py * py + pz * pz) - shape["radius"]
    if kind == "box":
        px, py, pz = _local(X, Y, Z, center, rotation)
        half = np.asarray(shape["size"], np.float32) / 2
        r = shape.get("rounding", 0.0)
        qx, qy, qz = np.abs(px) - half[0] + r, np.abs(py) - half[1] + r, np.abs(pz) - half[2] + r
        outside = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2 + np.maximum(qz, 0) ** 2)
        return outside + np.minimum(np.maximum(qx, np.maximum(qy, qz)), 0) - r
    if kind == "cylinder":
        if "start" in shape:
            p0, p1 = np.asarray(shape["start"], np.float32), np.asarray(shape["end"], np.float32)
        else:
            h = shape["height"] / 2
            p0, p1 = np.array([center[0], center[1], center[2] - h]), np.array([center[0], center[1], center[2] + h])
        axis = p1 - p0
        length = float(np.linalg.norm(axis))
        axis = axis / length
        px, py, pz = X - (p0[0] + p1[0]) / 2, Y - (p0[1] + p1[1]) / 2, Z - (p0[2] + p1[2]) / 2
        along = px * axis[0] + py * axis[1] + pz * axis[2]
        radial = np.sqrt(np.maximum(px * px + py * py + pz * pz - along * along, 0))
        dx, dy = radial - shape["radius"], np.abs(along) - length / 2
        return np.minimum(np.maximum(dx, dy), 0) + np.sqrt(np.maximum(dx, 0) ** 2 + np.maximum(dy, 0) ** 2)
    if kind == "capsule":
        d, _ = _segment_sdf(X, Y, Z, shape["start"], shape["end"])
        return d - shape["radius"]
    if kind == "cone":
        d, h = _segment_sdf(X, Y, Z, shape["start"], shape["end"])
        return d - (shape["radius_start"] * (1 - h) + shape["radius_end"] * h)
    if kind == "torus":
        px, py, pz = _local(X, Y, Z, center, rotation)
        q = np.sqrt(px * px + py * py) - shape["major_radius"]
        return np.sqrt(q * q + pz * pz) - shape["minor_radius"]
    if kind == "mesh":
        return _mesh_sdf(shape, X.shape, origin, vox)
    raise ValueError(f"Unknown SDF shape '{kind}'. Valid: sphere, box, cylinder, capsule, cone, torus, mesh")


def _mesh_sdf(shape, dims, origin, vox):
    """Signed distance to an existing closed mesh object (via OpenVDB level set), plus offset."""
    import openvdb
    obj = get_object(shape["object"])
    verts, tris, _ = _triangles([obj])
    index_pts = ((verts - origin) / vox).astype(np.float32)
    band = max(3.0, (abs(shape.get("offset", 0.0)) + 2 * vox) / vox + 2)
    grid = openvdb.FloatGrid.createLevelSetFromPolygons(index_pts, triangles=tris.astype(np.uint32),
                                                        halfWidth=band)
    dense = np.full(dims, band, dtype=np.float32)
    grid.copyToArray(dense, ijk=(0, 0, 0))
    return dense * vox - shape.get("offset", 0.0)


def _combine(acc, d, op, k):
    if acc is None:
        return d
    if op == "union":
        if k > 0:
            h = np.clip(0.5 + 0.5 * (d - acc) / k, 0, 1)
            return d + (acc - d) * h - k * h * (1 - h)
        return np.minimum(acc, d)
    if op == "subtract":
        if k > 0:
            h = np.clip(0.5 - 0.5 * (acc + d) / k, 0, 1)
            return acc + (-d - acc) * h + k * h * (1 - h)
        return np.maximum(acc, -d)
    if op == "intersect":
        return np.maximum(acc, d)
    raise ValueError("op must be union, subtract or intersect")


def _shape_bounds(shape):
    kind = shape["type"].lower()
    if kind == "mesh":
        lo, hi = world_bbox([get_object(shape["object"])])
        s = unit_scale_to_mm()
        off = abs(shape.get("offset", 0.0))
        return np.array(lo) * s - off, np.array(hi) * s + off
    center = np.asarray(shape.get("center", [0, 0, 0]), dtype=np.float64)
    unrotated = not any(shape.get("rotation", [0, 0, 0]))
    if kind == "box":
        half = np.asarray(shape["size"], dtype=np.float64) / 2
        if not unrotated:
            half = np.full(3, np.linalg.norm(half))
        return center - half, center + half
    if kind == "sphere":
        return center - shape["radius"], center + shape["radius"]
    if kind == "torus":
        outer, minor = shape["major_radius"] + shape["minor_radius"], shape["minor_radius"]
        ext = np.array([outer, outer, minor]) if unrotated else np.full(3, outer)
        return center - ext, center + ext
    if kind == "cylinder" and "start" not in shape:
        ext = np.array([shape["radius"], shape["radius"], shape["height"] / 2])
        return center - ext, center + ext
    # capsule, cone, cylinder by start/end: the end points grown by the largest radius
    pts = np.array([shape[k] for k in ("start", "end") if k in shape] or [center], dtype=np.float64)
    reach = max(shape.get(k, 0.0) for k in ("radius", "radius_start", "radius_end"))
    return pts.min(axis=0) - reach, pts.max(axis=0) + reach


def create_sdf_part(name: str, shapes: list, voxel_size_mm: float = 0.2, max_cells: int = 20_000_000) -> dict:
    """Model a solid from signed-distance shapes in millimeters and mesh it (always closed/manifold).

    shapes: ordered list; each is {"type": sphere|box|cylinder|capsule|cone|torus|mesh,
    "op": union|subtract|intersect (default union), "smooth": fillet radius mm, ...}.
    sphere: center, radius. box: center, size [x,y,z], rounding, rotation [deg]. cylinder: center +
    height + radius (Z axis) or start/end + radius. capsule: start, end, radius. cone: start, end,
    radius_start, radius_end. torus: center, major_radius, minor_radius, rotation.
    mesh: object (existing closed mesh), offset (mm, + grows / - shrinks) - e.g. subtract a pin's
    mesh with offset 0.3 to cut a socket with 0.3 mm clearance.
    """
    import openvdb
    if not shapes:
        raise ValueError("shapes is empty")
    vox = float(voxel_size_mm)
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for s in shapes:
        if s.get("op", "union") != "subtract":
            slo, shi = _shape_bounds(s)
            lo, hi = np.minimum(lo, slo), np.maximum(hi, shi)
    if not np.all(np.isfinite(lo)):
        raise ValueError("Need at least one union/intersect shape")
    pad = 3 * vox + max(s.get("smooth", 0.0) for s in shapes)
    # The small offset keeps grid points off round coordinates, where flat faces would
    # land exactly on the lattice and mesh into zero-area faces.
    lo, hi = lo - pad - vox * np.array([0.137, 0.271, 0.193]), hi + pad
    dims = np.ceil((hi - lo) / vox).astype(int) + 1
    cells = int(np.prod(dims))
    if cells > max_cells:
        suggest = vox * (cells / max_cells) ** (1 / 3)
        raise ValueError(f"Grid of {cells:,} cells is too big; use voxel_size_mm >= {suggest:.3f}")
    ax = [lo[i] + np.arange(dims[i], dtype=np.float32) * vox for i in range(3)]
    X, Y, Z = ax[0][:, None, None], ax[1][None, :, None], ax[2][None, None, :]
    X, Y, Z = np.broadcast_arrays(X, Y, Z)
    acc = None
    for s in shapes:
        d = _shape_sdf(s, X, Y, Z, lo, vox).astype(np.float32)
        acc = _combine(acc, d, s.get("op", "union").lower(), float(s.get("smooth", 0.0)))
    acc = np.ascontiguousarray(acc, dtype=np.float32)
    background = float(acc.max())
    grid = openvdb.FloatGrid(background)
    grid.copyFromArray(acc)
    points, quads = grid.convertToQuads(0.0)
    points = np.asarray(points, dtype=np.float64) * vox + lo
    quads = np.asarray(quads, dtype=np.int64)
    if len(quads) == 0:
        raise ValueError("The shapes produced an empty solid")
    to_bu = 1.0 / unit_scale_to_mm()
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata((points * to_bu).tolist(), [], quads.tolist())
    mesh.validate()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-4 * vox * to_bu, edges=bm.edges)
    if bm.calc_volume(signed=True) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    bpy.context.view_layer.update()
    select_only([obj])
    verts, tris, _ = _triangles([obj])
    stats = _analyze(verts, tris, self_intersections=False)
    return {"name": obj.name, "voxels": [int(x) for x in dims], "faces": len(mesh.polygons),
            "dimensions_mm": stats["dimensions_mm"], "watertight": stats["watertight"],
            "volume_cm3": stats["volume_cm3"], "shells": stats["shells"]}


register_handler("check_printability", check_printability)
register_handler("repair_mesh", repair_mesh)
register_handler("prepare_for_print", prepare_for_print)
register_handler("check_clearances", check_clearances)
register_handler("export_print", export_print)
register_handler("create_sdf_part", create_sdf_part)
