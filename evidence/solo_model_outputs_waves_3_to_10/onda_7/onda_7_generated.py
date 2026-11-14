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

def build_lod_variant(name, subdiv_cuts, x_offset):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= 2.0
        v.co.y *= 1.2
        v.co.z = (v.co.z + 0.5) * 2.4
    if subdiv_cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=subdiv_cuts, use_grid_fill=True)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    uv = bm.loops.layers.uv.verify()
    for fi, f in enumerate(bm.faces):
        u0, v0 = (fi % 4) * 0.22 + 0.02, ((fi // 4) % 4) * 0.22 + 0.02
        pts = [(u0, v0), (u0 + 0.18, v0), (u0 + 0.18, v0 + 0.18), (u0, v0 + 0.18)]
        for li, lp in enumerate(f.loops):
            lp[uv].uv = pts[li % 4]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = (x_offset, 0.0, 0.0)
    sc.collection.objects.link(ob)

build_lod_variant("Industrial_Tower_LOD0", 3, 0.0)
build_lod_variant("Industrial_Tower_LOD1", 1, 3.0)
build_lod_variant("Industrial_Tower_LOD2", 0, 6.0)
bpy.ops.export_scene.gltf(filepath=str(out_dir / "Onda7_LODs.glb"), export_format='GLB')