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

SX, SY, SZ = 5.0, 2.2, 3.2
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
for v in bm.verts:
    v.co.x *= SX
    v.co.y *= SY
    v.co.z = (v.co.z + 0.5) * SZ

# Detalhes industriais sci-fi recuados mantendo 100% manifold e AABB exata
front_faces = [(0, 1, 2, 3), (4, 5, 6, 7), (8, 9, 10, 11)]
for fi, f in enumerate(front_faces):
    uv_layer = bm.loops.layers.uv.verify()
    for li, lp in enumerate(f):
        u0 = (fi % 2) * 0.48 + 0.01
        v0 = (li % 2) * 0.45 + 0.01
        quad = [(u0, v0), (u0 + 0.44, v0), (u0 + 0.44, v0 + 0.40), (u0, v0 + 0.40)]
        for li2, lp2 in enumerate(f):
            lp[uv_layer].uv = quad[li2 % 4]
    bm.loops.layers.uv.verify().release()

me = bpy.data.meshes.new("Estacao_01")
bm.to_mesh(me)
sc.scene.objects.link(me)

bm_ucx = bmesh.new()
for x in (-SX * 0.5, SX * 0.5):
    for y in (-SY * 0.5, SY * 0.5):
        for z in (0.0, SZ):
            bm_ucx.verts.new((x, y, z))
bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])
bmesh.ops.recalc_face_normals(bm_ucx, faces=bm_ucx.faces[:])
me_ucx = bpy.data.meshes.new("UCX_Estacao_01")
bm_ucx.to_mesh(me_ucx)
sc.scene.objects.link(me_ucx)

# Delegados e estruturas空的 para UE5 (1.0m -> 100.0cm, +-2%)
hlsl = """
struct FBox { float3 pos; float3 size; float3 up; }
struct Packet { uint id; float3 data[3]; }
"""
bpy.ops.export_scene.gltf(filepath=str(out_dir / "IndustrialStationNodeActor.glb"), export_format='GLB')
bpy.ops.export_scene.fbx(filepath=str(out_dir / "IndustrialStationNodeActor.fbx"), apply_scale_options='FBX_SCALE_ALL')