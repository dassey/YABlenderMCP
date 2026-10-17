"""MCP prompts: ready-made workflows the client can offer (e.g. as slash commands)."""

from .compat import FastMCP


def register(mcp: FastMCP):
    @mcp.prompt()
    def print_prep(objects: str = "", printer: str = "H2C") -> str:
        """Get a model ready for 3D printing and export it."""
        target = f"the objects {objects}" if objects else "the selected objects (or all visible meshes)"
        return f"""Prepare {target} for printing on a Bambu Lab {printer}.
1. get_blender_info: note the units. All print tools report millimeters.
2. check_printability(printer="{printer}") and read every blocking issue.
3. Fix blocking issues: repair_mesh (voxel_remesh_mm only if holes/self-intersections remain),
   or boolean/convert_to_mesh for curves and text. Re-run check_printability until print_ready.
4. Multi-part or print-in-place: check_clearances(min_clearance_mm=0.3); fused or too-close
   pairs must be fixed (move parts, or subtract with create_sdf_part mesh offset).
5. prepare_for_print(orientation="min_overhang", printer="{printer}") unless the user chose an
   orientation; then capture_views(shading="xray") to confirm.
6. export_print to a .3mf next to the .blend (or a path the user gives) and report the file,
   dimensions, overhang area and any advisory issues."""

    @mcp.prompt()
    def build_scene(description: str) -> str:
        """Plan, build and visually verify a scene in steps."""
        return f"""Build this in Blender: {description}
1. Inspect: get_scene_info. Don't modify existing objects unless asked; use a new collection.
2. Plan 3-8 groups of work. For each group write what the check image must show.
3. For each group: build with the structured tools (create_object with params, place_object,
   set_transform, materials, modifiers; execute_blender_code only when nothing fits), then
   capture_views and compare with the group's goal. Fix gaps before moving on (at most 2
   retries per group; ask the user if still wrong).
4. Finish with a lighting rig/camera if the user wants renders (create_light_rig, frame_camera)
   and one final capture_views. Summarize what was built and anything left open."""

    @mcp.prompt()
    def review_scene() -> str:
        """Inspect the scene without changing anything and report problems."""
        return """Review the current Blender scene WITHOUT modifying it (read-only tools only).
1. get_blender_info and get_scene_info(fields=["ground", "materials", "modifiers"]).
2. capture_views of the whole scene.
3. For meshes: check_printability (also useful outside printing: holes, flipped normals,
   self-intersections). Note objects floating above or sunk below the ground.
4. Report: what the scene contains, problems found (with object names), and suggested fixes.
   Do not apply any fix until the user says so."""

    @mcp.prompt()
    def image_to_model(reference_image: str, view: str = "front") -> str:
        """Turn a 2D drawing or photo into a 3D model and check it against the drawing."""
        return f"""Create a 3D model that matches the 2D reference {reference_image} (seen from the {view}).
1. add_reference_image("{reference_image}", view="{view}") and capture_views to see it.
2. Block out the main shapes (create_object / create_sdf_part for printable parts, or
   import_file for an .svg outline then extrude the curves and convert_to_mesh).
3. compare_silhouette(objects, "{reference_image}", view="{view}"): blue = model too big there,
   red = model missing there. Adjust and repeat until IoU >= 0.9 (or explain why not).
4. Check side and top views with capture_views for plausible depth.
5. If it will be printed, follow the print_prep workflow."""
