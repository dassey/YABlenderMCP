"""3D printing MCP tools (all measurements in millimeters)."""

from typing import Any, Optional

from ..compat import DESTRUCTIVE, EDIT, READ, FastMCP
from ..connection import params_of, send


def register(mcp: FastMCP):
    @mcp.tool(annotations=READ)
    def check_printability(objects: Optional[list[str]] = None, printer: str = "",
                           build_volume_mm: Optional[list[float]] = None, min_wall_mm: float = 0.8,
                           overhang_angle: float = 45.0, self_intersections: bool = True,
                           combined: bool = False) -> str:
        """Check meshes for 3D printing (modifiers applied, sizes in mm):

        watertight (open/non-manifold edges), flipped or inside-out normals,
        self-intersections, zero-area faces, separate shells, volume, thin walls under
        min_wall_mm (0 skips), overhang area beyond overhang_angle from vertical, bed
        contact, and fit in the build volume. printer: H2C, H2D, H2S, X1C, X1E, P1S,
        P1P, P2S, A1, "A1 mini" - or build_volume_mm [x, y, z]. combined checks the
        objects as one assembly. Default objects: selection, else all visible meshes.
        Each issue is "blocking" or "advisory"; print_ready = no blocking issues.
        """
        return send("check_printability", params_of(objects=objects, printer=printer,
                                                    build_volume_mm=build_volume_mm, min_wall_mm=min_wall_mm,
                                                    overhang_angle=overhang_angle,
                                                    self_intersections=self_intersections, combined=combined),
                    timeout=600)

    @mcp.tool(annotations=DESTRUCTIVE)
    def repair_mesh(objects: Optional[list[str]] = None, merge_distance_mm: float = 0.01, fill_holes: bool = True,
                    recalc_normals: bool = True, delete_loose: bool = True, dissolve_degenerate: bool = True,
                    voxel_remesh_mm: float = 0.0, apply_modifiers: bool = False) -> str:
        """Fix common print problems in place: merge duplicate vertices, remove loose and zero-area
        geometry, fill holes, make normals consistent and outward. voxel_remesh_mm > 0 rebuilds the
        mesh as a watertight solid at that resolution (loses sharp detail below it).
        Returns health before/after."""
        return send("repair_mesh", params_of(objects=objects, merge_distance_mm=merge_distance_mm,
                                             fill_holes=fill_holes, recalc_normals=recalc_normals,
                                             delete_loose=delete_loose, dissolve_degenerate=dissolve_degenerate,
                                             voxel_remesh_mm=voxel_remesh_mm, apply_modifiers=apply_modifiers),
                    timeout=600)

    @mcp.tool(annotations=EDIT)
    def prepare_for_print(objects: Optional[list[str]] = None, orientation: str = "keep",
                          place_on_bed: bool = True, center: bool = True, as_group: bool = True,
                          overhang_angle: float = 45.0, printer: str = "") -> str:
        """Get objects ready to slice: orientation keep, flat (largest flat face down) or
        min_overhang (least support area, from convex-hull resting faces); drop to z=0;
        centre on the origin. as_group keeps an assembly rigid (print-in-place parts).
        Returns overhang/contact area and dimensions in mm."""
        return send("prepare_for_print", params_of(objects=objects, orientation=orientation,
                                                   place_on_bed=place_on_bed, center=center, as_group=as_group,
                                                   overhang_angle=overhang_angle, printer=printer), timeout=600)

    @mcp.tool(annotations=READ)
    def check_clearances(objects: Optional[list[str]] = None, min_clearance_mm: float = 0.3,
                         split_shells: bool = False) -> str:
        """Check gaps between parts for print-in-place joints and assemblies: reports pairs that
        intersect (would fuse), touch, or are closer than min_clearance_mm, with the measured
        clearance. split_shells=True compares the separate shells inside each object."""
        return send("check_clearances", params_of(objects=objects, min_clearance_mm=min_clearance_mm,
                                                  split_shells=split_shells), timeout=600)

    @mcp.tool(annotations=EDIT)
    def export_print(filepath: str, objects: Optional[list[str]] = None, check: bool = True,
                     separate_files: bool = False, printer: str = "") -> str:
        """Export for the slicer in millimeters with modifiers applied.

        .3mf: one file, each object a separate part with its material colour (opens in
        Bambu Studio, Orca, Prusa). .stl: merged, or one per object (separate_files).
        check=True reports blocking print issues per object.
        """
        return send("export_print", params_of(filepath=filepath, objects=objects, check=check,
                                              separate_files=separate_files, printer=printer), timeout=600)

    @mcp.tool(annotations=EDIT)
    def create_sdf_part(name: str, shapes: list[dict[str, Any]], voxel_size_mm: float = 0.2) -> str:
        """Model a solid from signed-distance shapes (millimeters) - always closed and manifold,
        with exact clearances and smooth fillets. Ideal for pins, sockets, ball joints, hinges.

        shapes (applied in order): {"type": ..., "op": "union"|"subtract"|"intersect",
        "smooth": fillet_mm, ...}. sphere: center, radius. box: center, size [x,y,z],
        rounding, rotation [deg]. cylinder: center + height + radius (Z axis) or start/end
        + radius. capsule: start, end, radius. cone: start, end, radius_start, radius_end.
        torus: center, major_radius, minor_radius, rotation. mesh: object (existing closed
        mesh), offset (mm; +grows) - e.g. subtract a pin's mesh with offset 0.3 to cut a
        socket with 0.3 mm clearance. Smaller voxel_size_mm = finer detail, more memory.
        """
        return send("create_sdf_part", {"name": name, "shapes": shapes, "voxel_size_mm": voxel_size_mm},
                    timeout=600)
