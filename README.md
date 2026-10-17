# <img src="logo.jpg" width="48" align="center"> YABlenderMCP

MCP server that lets an AI agent work in Blender 5.1 on your computer: modeling, materials, lighting, animation, rendering and 3D-print preparation.

- 105 tools and 4 prompts.
- Local only. No API keys, no accounts, no telemetry. The MCP server refuses network connections to any machine except this one.
- Every tool call that changes the scene is one Ctrl+Z step.

## Setup

**1. Python package** (Python 3.10+):

```bash
pip install -r requirements.txt
```

**2. Blender add-on.** Build the zip:

```bash
python build_addon.py
```

In Blender: Edit > Preferences > Add-ons > dropdown (top right) > **Install from Disk...** > pick `addon.zip` > enable **BlenderMCP**.

On Windows, `install_addon.bat` builds the zip on the first run. Once the add-on is installed, running it again copies your source changes into the installed add-on. Restart Blender after syncing.

If another add-on named BlenderMCP is installed, remove it first.

**3. Start the server in Blender:** in the 3D viewport, press N, open the **BlenderMCP** tab and click **Start Server**. To start it automatically, tick **Start server when Blender opens**.

**4. Add it to your MCP client** (any client that runs stdio MCP servers), then restart the client:

```json
{
  "mcpServers": {
    "blender": {
      "command": "python",
      "args": ["C:/path/to/YABlenderMCP/server/main.py"],
      "env": {"PYTHONUTF8": "1"}
    }
  }
}
```

**5. Check it:**

```bash
python server/main.py --check
```

This prints the number of tools and whether the add-on answers.

**Updating:** pull, rebuild/reinstall the add-on (or re-run `install_addon.bat`), restart Blender, then restart the MCP client.

## How it works

```
MCP client  <--stdio-->  server/main.py  <--TCP 127.0.0.1:9001-->  add-on inside Blender
```

`server/` is a normal Python process that speaks MCP. `addon/` runs inside Blender, listens on localhost and runs each command on Blender's main thread. Messages are newline-delimited JSON.

## Configuration

Environment variables for the MCP server (set them in the client config's `env`):

| Variable | Default | Meaning |
|---|---|---|
| `BLENDER_MCP_HOST` | `127.0.0.1` | Where the add-on listens |
| `BLENDER_MCP_PORT` | `9001` | Add-on port; must match the add-on's **Port** |
| `BLENDER_MCP_TIMEOUT` | `180` | Seconds to wait for a command (long tools raise their own limit) |
| `BLENDER_MCP_TOKEN` | empty | Shared secret; must match the add-on's **Token** |
| `BLENDER_MCP_TOOLSETS` | all | Only expose these tool groups (see below) |
| `PYTHONUTF8` | | Set to `1` on Windows |

Add-on preferences (Edit > Preferences > Add-ons > BlenderMCP): **Port**, **Start server when Blender opens**, **Token**.

**Fewer tools.** Some clients work better with fewer tools. List the groups you want; `execute_blender_code` is always included:

```json
"env": {"PYTHONUTF8": "1", "BLENDER_MCP_TOOLSETS": "scene,viewport,materials,print"}
```

Groups: `session`, `scene`, `viewport`, `materials`, `modifiers`, `io`, `animation`, `nodes`, `render`, `mesh`, `lighting`, `print`, `analysis`.

**Token.** Put the same value in the add-on's Token field and in the client config:

```json
"env": {"PYTHONUTF8": "1", "BLENDER_MCP_TOKEN": "pick-a-secret"}
```

**Headless Blender (no window).** After the add-on is installed and enabled once:

```bash
blender -b path/to/scene.blend -c blendermcp
blender -b -c blendermcp --port 9002 --token pick-a-secret
```

Port and token default to the add-on preferences. Ctrl+C stops it. Headless mode has no viewport tools (`get_viewport_screenshot`, `capture_views`, `find_object_at`, `set_view`, shading) and no undo; modeling, print, file and render tools and `compare_silhouette` work.

## Safety

- The add-on listens on 127.0.0.1 only. The optional token is checked on every command.
- A connection that sends anything other than JSON (for example a web page probing the port) is dropped.
- The MCP server process blocks network connections to anything except this computer and `BLENDER_MCP_HOST`.
- `open_blend` loads files with embedded scripts disabled.
- Undo: each scene-changing call, including `execute_blender_code` and `execute_batch`, is exactly one undo step. `undo` / `redo` step back and forward. `save_checkpoint` saves a copy of the scene before risky work.
- Scene-changing calls are refused while a render is running.
- The server tells the model that text inside object names, files and logs is data, not instructions.

## Features and how to use them

Tool arguments are shown as the client sends them (JSON). Lengths are in scene units, except for 3D-print tools, which always use millimeters.

### Seeing the result

| Tool | Use |
|---|---|
| `capture_views` | One labeled grid image from several angles. `views`: `front`, `back`, `left`, `right`, `top`, `bottom`, `iso`, `iso_back`, `camera` or `[x, y, z]`. `shading`: `solid`, `material`, `wireframe`, `wireframe_only`, `xray`, `clay`, `rendered` (EEVEE). `frames: [1, 10, 20]` shows one view at several frames. `objects` frames only those. Does not move your viewport. |
| `get_viewport_screenshot` | What the viewport shows, as an image (`max_size` px). |
| `find_object_at` | `{"x": 0.5, "y": 0.5}`: which object is at that point of the last screenshot (0-1, from top-left). |
| `compare_silhouette` | `{"objects": ["Body"], "reference_image": "C:/ref/side.png", "view": "left"}`: IoU score plus an overlay (gray = both, blue = model only, red = reference only). For matching a 2D drawing. |
| `snapshot_scene` / `diff_scene` | Save the scene state under a name, then list what was added, removed or changed since. |
| `measure_distance` | Gap between two objects' surfaces, plus origin and bounding-box distances. |
| `find_ray_hit` | `{"origin": [0, 0, 10], "direction": [0, 0, -1]}`: first object hit, point, normal, distance. |

### Scene and objects

| Tool | Use |
|---|---|
| `get_scene_info` | Objects with type, location, size and vertex counts. Filter with `query` (name) and `types`; paginate with `limit` / `offset`. `fields`: `ground`, `bbox`, `rotation`, `scale`, `materials`, `modifiers`, `collections`. |
| `get_object_info` | Full details of one object. |
| `create_object` | `type`: cube, sphere, ico_sphere, cylinder, cone, torus, plane, circle, grid, monkey, empty, camera, light, text, bezier_curve, bezier_circle, armature. `params` go to Blender's operator: `{"type": "cylinder", "params": {"radius": 0.5, "depth": 2, "vertices": 6}}`, `{"type": "text", "params": {"body": "Hello"}}`. Returns the bounding box. |
| `place_object` | `{"name": "Lamp", "target": "Table", "position": "on_top"}`. Positions: `on_top`, `below`, `left`, `right`, `front`, `back`, `center`, `on_ground`. Optional `gap`. Uses bounding boxes, so no coordinate guessing. |
| `set_transform` | Location / rotation / scale; `relative: true` adds to the current value, `degrees: true` for rotation in degrees. |
| `duplicate_object`, `delete_objects`, `rename_object`, `select_objects` | As named. `duplicate_object` takes `linked` and `offset`. |
| `parent_objects`, `get_collections`, `move_to_collection` | Hierarchy and collections. |
| `set_visibility` | `hide`, `hide_render`, `hide_select`. |
| `join_objects`, `apply_transforms`, `convert_to_mesh` | Join, bake transforms, convert curves/text/metaballs to meshes. |
| `set_origin` | `bottom_center` (good for print beds and floors), `geometry`, `center_of_mass`, `center_of_volume`, `cursor`, `world_origin`. |

### Session, properties and API lookup

| Tool | Use |
|---|---|
| `get_blender_info` | Version, open file, unsaved changes, units (mm per unit), engine, frame range. |
| `undo` / `redo` | `{"steps": 1}`. |
| `execute_batch` | Several commands in one round trip and one undo step: `{"commands": [{"type": "create_object", "params": {"type": "cube", "name": "A"}}, {"type": "set_transform", "params": {"name": "A", "location": [0, 0, 1]}}]}`. |
| `set_units` | `{"preset": "mm"}` makes 1 unit = 1 mm; also `cm`, `m`, `inch`. |
| `clear_scene` | Delete everything except `keep_types` (e.g. `["CAMERA", "LIGHT"]`); purges unused data. |
| `get_properties` / `set_properties` | Any property by path: `{"target": "Key", "properties": {"data.energy": 800}}`; targets: an object name, `scene`, `world`, `view_layer`, or `kind:Name` (`material:Red`, `light:Key`, `node_group:...`). Wrong names return close matches. |
| `get_operator_history` | Operators you ran by hand in Blender, so the model can see what you just did. |
| `search_api` / `get_api_docs` | Search this Blender's Python API by words; exact parameters of an operator, type or property. |

### Materials

| Tool | Use |
|---|---|
| `create_material` | `{"name": "Red", "color": [0.8, 0.1, 0.1], "preset": "plastic"}`. Presets: plastic, matte, rubber, metal, brushed_metal, gold, copper, glass, frosted_glass, ceramic, emissive. Also `metallic`, `roughness`, `emission_color`, `emission_strength`, `alpha`. |
| `create_pbr_material` | `{"name": "Wood", "folder": "C:/textures/wood", "object_name": "Table"}`. Maps are found by filename (basecolor/albedo/diffuse, roughness, metallic, normal, displacement/height, ao, opacity, emission). Box projection when the object has no UVs. |
| `assign_material`, `set_material_property`, `list_materials`, `get_material_info` | Assign, tweak Principled BSDF inputs, inspect. |

### Modifiers and mesh editing

| Tool | Use |
|---|---|
| `add_modifier` | `{"object_name": "Box", "type": "BEVEL", "settings": {"width": 0.05, "segments": 3}}`. Wrong setting names list the valid ones; extreme values (e.g. subdivision levels above 6) are refused. |
| `set_modifier_property`, `apply_modifier`, `remove_modifier`, `list_modifiers` | Edit, apply, remove, inspect. |
| `boolean_operation` | `{"target": "Plate", "cutter": "Hole", "operation": "DIFFERENCE"}`; solver EXACT, FLOAT or MANIFOLD; the cutter is hidden afterwards by default. |
| `mesh_operation` | Whole-mesh edits without edit mode: merge_by_distance, recalculate_normals, flip_normals, triangulate, quads_from_tris, subdivide, smooth_vertices, shade_smooth, shade_flat, shade_auto_smooth, decimate, remesh_voxel, fill_holes, dissolve_degenerate, delete_loose, separate_loose, separate_by_material, solidify, mirror, bevel, uv_smart_project, convex_hull. Example: `{"name": "Scan", "operation": "decimate", "params": {"ratio": 0.3}}`. |
| `get_mesh_data`, `set_vertex_positions`, `get_vertex_groups`, `set_vertex_group` | Vertex-level read/write. |

### Nodes

| Tool | Use |
|---|---|
| `get_node_tree` | Nodes and links of a material, an object's Geometry Nodes (`"Obj"` or `"Obj/Modifier"`), a node group or the world. |
| `get_node_type_info` | Real sockets and settings of a node type in this Blender version, e.g. `GeometryNodeMeshCube`. Unknown names get suggestions. |
| `add_node`, `connect_nodes`, `set_node_value`, `set_node_property`, `remove_node` | Build trees. Sockets by name, identifier or index; `set_node_property` sets things like Math `operation`. |
| `create_geometry_nodes` | Adds a Geometry Nodes modifier with an empty, wired node group. |

### Lighting, camera and world

| Tool | Use |
|---|---|
| `create_light_rig` | `{"preset": "three_point"}` (also `studio`, `rim`, `outdoor`), sized to the objects. |
| `create_light` | POINT, SUN, SPOT, AREA aimed with `look_at`; power is scaled to the distance when `energy` is omitted. |
| `create_camera`, `set_active_camera`, `point_at` | Camera aimed at an object or point; `point_at` with `use_constraint: true` keeps tracking. |
| `frame_camera` | `{"camera": "Cam", "fill": 0.8}`: moves/zooms until the objects fill that share of the frame; reports clipping. |
| `set_world` | Background colour, or a local `.hdr` / `.exr` with `hdri_path` and `rotation_degrees`. |

### Animation

| Tool | Use |
|---|---|
| `set_keyframe` | `{"object_name": "Ball", "property": "location", "frame": 20, "value": [0, 0, 3], "interpolation": "LINEAR"}`. Nested paths work (`data.energy`). |
| `delete_keyframe`, `clear_animation`, `set_interpolation`, `get_animation_info` | Edit and inspect keys (Blender 5 slotted actions). |
| `set_frame`, `get_timeline_info`, `set_timeline` | Timeline. |
| `add_constraint` / `remove_constraint` | TRACK_TO, DAMPED_TRACK, COPY_*, CHILD_OF, LIMIT_*, FOLLOW_PATH, FLOOR, ... with `settings`. |
| `create_turntable` | Camera orbits the objects once (seamless loop) for 360° previews. |

### Rendering

| Tool | Use |
|---|---|
| `set_render_settings` | `engine` (`CYCLES`, `EEVEE`, `WORKBENCH`), resolution, `samples`, `denoise`, `film_transparent`, `file_format`, `view_transform`, `output_path`. |
| `set_render_device` | `{"device": "AUTO"}` renders Cycles on the GPU: OptiX on NVIDIA RTX cards, then CUDA, HIP, oneAPI, Metal; CPU if none. |
| `render_frame` | Renders and returns the image (`max_size` preview); `output_path` keeps the file. |
| `render_animation` | In the UI it renders in the background and returns at once; poll `get_render_status`. `wait: true` blocks. Use a frame placeholder: `"//render/frame_####"`. |

### Files

| Tool | Use |
|---|---|
| `import_file` | FBX, OBJ, glTF/GLB, STL, PLY, Alembic, USD (usd/usda/usdc/usdz), SVG (as curves), 3MF (geometry, including Bambu Studio projects). `target_size`, `drop_to_ground`, `center` normalise the import. |
| `export_file` | FBX, OBJ, glTF/GLB, STL, PLY, Alembic, USD; whole scene or `objects`. For printing use `export_print`. |
| `save_blend`, `open_blend`, `save_checkpoint` | Save; open (refuses to drop unsaved changes unless `discard_changes: true`); timestamped copy. |
| `list_directory`, `list_blend_contents`, `append_from_blend` | Browse folders, look inside another .blend, append or link from it. |
| `list_asset_libraries` | Your local asset libraries (Preferences > File Paths) and their .blend files. |
| `add_reference_image` | A drawing or photo as an image empty or a textured plane, facing `front`, `back`, `left`, `right` or `top`. |

### 3D printing

Printers: `H2C`, `H2D`, `H2S`, `X1C`, `X1E`, `P1S`, `P1P`, `P2S`, `A1`, `A1 mini`, or `build_volume_mm: [x, y, z]`. Sizes are in millimeters whatever the scene units are.

| Tool | Use |
|---|---|
| `check_printability` | Watertight, flipped normals, self-intersections, zero-area faces, shells, thin walls (`min_wall_mm`), overhang area (`overhang_angle`), bed contact, build-volume fit. Each issue is blocking or advisory; `print_ready` means no blocking issues. `combined: true` checks an assembly. |
| `repair_mesh` | Merge doubles, remove loose and degenerate geometry, fill holes, fix normals. `voxel_remesh_mm` rebuilds a watertight solid as a last resort. |
| `check_clearances` | Gaps between parts for print-in-place joints: reports pairs that intersect, touch or are closer than `min_clearance_mm`. |
| `prepare_for_print` | `orientation`: `keep`, `flat` (largest flat face down) or `min_overhang`; drops to the bed and centres; `as_group` keeps an assembly rigid. |
| `export_print` | `.3mf` (one part per object with its colour, for Bambu Studio, OrcaSlicer or PrusaSlicer) or `.stl` (merged, or `separate_files`). Millimeters, modifiers applied, optional checks. |
| `create_sdf_part` | Solid from signed-distance shapes: always closed, exact clearances, smooth fillets. |

Typical flow:

```
set_units          {"preset": "mm"}
check_printability {"printer": "H2C"}
repair_mesh        {}                                  (only if there are blocking issues)
check_clearances   {"min_clearance_mm": 0.3}           (print-in-place / assemblies)
prepare_for_print  {"orientation": "min_overhang", "printer": "H2C"}
export_print       {"filepath": "C:/prints/part.3mf"}
```

`create_sdf_part` shapes are applied in order. Each one has a `type`, an optional `op` (`union`, `subtract`, `intersect`) and an optional `smooth` fillet in mm:

| Shape | Fields |
|---|---|
| `sphere` | `center`, `radius` |
| `box` | `center`, `size` [x, y, z], `rounding`, `rotation` [deg] |
| `cylinder` | `center` + `height` + `radius` (Z axis), or `start` + `end` + `radius` |
| `capsule` | `start`, `end`, `radius` |
| `cone` | `start`, `end`, `radius_start`, `radius_end` |
| `torus` | `center`, `major_radius`, `minor_radius`, `rotation` |
| `mesh` | `object` (an existing closed mesh), `offset` in mm (+ grows, - shrinks) |

Example: a print-in-place ball joint with 0.3 mm clearance. The pin is a shaft with a ball head. The socket is a rounded block minus the pin grown by 0.3 mm:

```json
{"name": "Pin", "shapes": [
  {"type": "cylinder", "center": [0, 0, 10], "height": 20, "radius": 3},
  {"type": "sphere", "center": [0, 0, 20], "radius": 4, "smooth": 1}
]}
```

```json
{"name": "Socket", "shapes": [
  {"type": "box", "center": [0, 0, 20], "size": [14, 14, 12], "rounding": 1},
  {"type": "mesh", "object": "Pin", "offset": 0.3, "op": "subtract"}
]}
```

`voxel_size_mm` (default 0.2) sets the detail. Smaller is finer but uses more memory.

### Python in Blender

`execute_blender_code` runs any Python inside Blender, for anything without a dedicated tool. Pre-imported: `bpy`, `bmesh`, `mathutils` (`Vector`, `Matrix`, `Euler`, `Quaternion`), `math`, `np`, `C` (context), `D` (data). Assign `result` to return JSON. Code that runs longer than `timeout` seconds (default 170) is stopped. Viewport operators work.

```python
bpy.ops.mesh.primitive_cylinder_add(radius=0.5, depth=2, location=(0, 0, 1))
result = {"name": C.active_object.name, "size": C.active_object.dimensions}
```

## Prompts

Clients that support MCP prompts (often shown as slash commands) list these:

| Prompt | Arguments | What it does |
|---|---|---|
| `print_prep` | `objects`, `printer` (default H2C) | check, repair, clearances, orient, export .3mf |
| `build_scene` | `description` | plan, build in steps, check each step with images |
| `review_scene` | | read-only inspection and report of problems |
| `image_to_model` | `reference_image`, `view` | 2D drawing to 3D model, checked with `compare_silhouette` |

## Testing

```bash
python server/main.py --check            # tools load and the add-on answers
python tests/test_connection.py 9001     # raw TCP smoke test
```

## Troubleshooting

| Message | Fix |
|---|---|
| Could not connect to Blender | Start the server in the BlenderMCP tab; check the port matches `BLENDER_MCP_PORT`. |
| Unknown command ... | The add-on in Blender is older than the MCP server; reinstall it and restart Blender. |
| Invalid or missing token | Set `BLENDER_MCP_TOKEN` to the add-on's Token (or clear both). |
| Port already in use | Another program or a second Blender uses it; change Port in the add-on and `BLENDER_MCP_PORT`. |
| A render is running | Wait until `get_render_status` reports finished. |
| ZIP packaged incorrectly | Build the zip with `python build_addon.py`. |
