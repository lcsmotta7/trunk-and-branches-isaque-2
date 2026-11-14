import os
import bpy
import bmesh
from pathlib import Path

out_dir = Path(os.environ.get("KEV_EXPORT_DIR", "."))
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = 'METRIC'
sc.unit_settings.scale_length = 1.0

slot_specs = [
    ("M_Industrial_Concrete", (0.35, 0.36, 0.38, 1.0), 0.0, 0.85),
    ("M_Brushed_Steel", (0.62, 0.65, 0.69, 1.0), 0.92, 0.28),
    ("M_Pressurized_Copper", (0.78, 0.44, 0.24, 1.0), 0.95, 0.22),
    ("M_Tech_Glass", (0.76, 0.88, 0.95, 1.0), 0.05, 0.08),
]
mats = []
for mname, rgba, met, rough in slot_specs:
    m = bpy.data.materials.new(mname)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Metallic"].default_value = met
    bsdf.inputs["Roughness"].default_value = rough
    nt.links.new(noise.outputs["Fac"], bsdf.inputs["Roughness"])
    nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])
    mats.append(m)

primary = None
for lod_name, cuts, x_off in [("PumpingUnit_LOD0", 3, 0.0), ("PumpingUnit_LOD1", 1, 4.0), ("PumpingUnit_LOD2", 0, 8.0)]:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= 3.0
        v.co.y *= 1.8
        v.co.z = (v.co.z + 0.5) * 2.5
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    uv = bm.loops.layers.uv.verify()
    for lp in [l for f in bm.faces for l in f.loops]:
        lp[uv].uv = (0.5, 0.5)
    me = bpy.data.meshes.new(lod_name)
    bm.to_mesh(me)
    bm.free()
    for m in mats:
        me.materials.append(m)
    ob = bpy.data.objects.new(lod_name, me)
    ob.location = (x_off, 0.0, 0.0)
    sc.collection.objects.link(ob)
    if primary is None:
        primary = ob

for sname, sloc in [("Socket_Flow_In", (-1.5, 0.0, 0.8)), ("Socket_Flow_Out", (1.5, 0.0, 1.6)), ("Socket_Walkway_Link", (0.0, 0.9, 2.5))]:
    so = bpy.data.objects.new(sname, None)
    so.location = sloc
    so.parent = primary
    sc.collection.objects.link(so)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "PumpingUnit_Manifest.glb"), export_format='GLB')