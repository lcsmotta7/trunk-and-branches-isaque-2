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

SX, SY, SZ = 4.0, 0.4, 3.0
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
for v in bm.verts:
    v.co.x *= SX
    v.co.y *= SY
    v.co.z = (v.co.z + 0.5) * SZ

# Detalhes industriais sci-fi recuados mantendo 100% manifold e AABB exata
front_faces = [f for f in bm.faces if abs(f.normal.y) > 0.9]
bmesh.ops.inset_individual(bm, faces=front_faces, thickness=0.18)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])

uv_layer = bm.loops.layers.uv.verify()
n_faces = max(len(bm.faces), 1)
cols = int(n_faces ** 0.5) + 1
cell = 1.0 / cols
pad = cell * 0.08
for idx, f in enumerate(bm.faces):
    gx = (idx % cols) * cell + pad
    gy = (idx // cols) * cell + pad
    span = cell - 2.0 * pad
    pts = [(gx, gy), (gx + span, gy), (gx + span, gy + span), (gx, gy + span)]
    for li, loop in enumerate(f.loops):
        loop[uv_layer].uv = pts[li % len(pts)]

me = bpy.data.meshes.new("Modulo_01")
bm.to_mesh(me)
obj = bpy.data.objects.new("Modulo_01", me)
obj.location = (0.0, 0.0, 0.0)
sc.collection.objects.link(obj)

bm_ucx = bmesh.new()
for x in (-SX * 0.5, SX * 0.5):
    for y in (-SY * 0.5, SY * 0.5):
        for z in (0.0, SZ):
            bm_ucx.verts.new((x, y, z))
bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])
bmesh.ops.recalc_face_normals(bm_ucx, faces=bm_ucx.faces[:])
me_ucx = bpy.data.meshes.new("UCX_Modulo_01")
bm_ucx.to_mesh(me_ucx)
bm.free()
bm_ucx.free()

obj_ucx = bpy.data.objects.new("UCX_Modulo_01", me_ucx)
obj_ucx.location = (0.0, 0.0, 0.0)
sc.collection.objects.link(obj_ucx)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "Modulo_01.glb"), export_format='GLB')
bpy.ops.export_scene.fbx(filepath=str(out_dir / "Modulo_01.fbx"), apply_scale_options='FBX_SCALE_ALL')