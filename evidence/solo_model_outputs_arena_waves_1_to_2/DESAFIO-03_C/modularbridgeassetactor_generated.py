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

variants = [
    ("Var_01_Standard", 1.00, 0.16, 0.28, 0.0),
    ("Var_02_Compact", 0.80, 0.16, 0.28, 0.65),
    ("Var_03_Heavy", 1.25, 0.18, 0.32, -0.65),
]

primary_obj = None
for vname, sx, sy, sz, y_off in variants:
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy
        v.co.z = (v.co.z + 0.5) * sz
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    uv_layer = bm.loops.layers.uv.verify()
    for fi, f in enumerate(bm.faces):
        u0 = (fi % 3) * 0.31 + 0.02
        v0 = (fi // 3) * 0.45 + 0.02
        quad = [(u0, v0), (u0 + 0.27, v0), (u0 + 0.27, v0 + 0.40), (u0, v0 + 0.40)]
        for li, lp in enumerate(f.loops):
            lp[uv_layer].uv = quad[li % 4]
    me = bpy.data.meshes.new(vname)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(vname, me)
    obj.location = (0.0, y_off, 0.0)
    sc.collection.objects.link(obj)
    if primary_obj is None:
        primary_obj = obj

# Colisor convexo 100% manifold para a peça primária
bm_ucx = bmesh.new()
for x in (-0.50, 0.50):
    for y in (-0.08, 0.08):
        for z in (0.0, 0.28):
            bm_ucx.verts.new((x, y, z))
bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])
bmesh.ops.recalc_face_normals(bm_ucx, faces=bm_ucx.faces[:])
me_ucx = bpy.data.meshes.new("UCX_Var_01_Standard_01")
bm_ucx.to_mesh(me_ucx)
bm_ucx.free()
obj_ucx = bpy.data.objects.new("UCX_Var_01_Standard_01", me_ucx)
obj_ucx.location = (0.0, 0.0, 0.0)
sc.collection.objects.link(obj_ucx)

# Sockets EMPTY coordenados (1.0m = 100.0cm UE5)
sock_muzzle = bpy.data.objects.new("Socket_Muzzle", None)
sock_muzzle.parent = primary_obj
sock_muzzle.location = (0.50, 0.0, 0.14)
sc.collection.objects.link(sock_muzzle)

sock_grip = bpy.data.objects.new("Socket_Grip", None)
sock_grip.parent = primary_obj
sock_grip.location = (-0.12, 0.0, 0.04)
sc.collection.objects.link(sock_grip)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "ModularBridgePack.glb"), export_format='GLB')
bpy.ops.export_scene.fbx(filepath=str(out_dir / "ModularBridgePack.fbx"), apply_scale_options='FBX_SCALE_ALL')