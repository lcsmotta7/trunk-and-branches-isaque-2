import os
import bpy
import bmesh
from pathlib import Path
from mathutils import Vector

out_dir = Path(os.environ.get("KEV_EXPORT_DIR", "."))
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.unit_settings.system = 'METRIC'
sc.unit_settings.scale_length = 1.0

def make_bmesh_solid(name, sx, sy, sz, loc=(0.0, 0.0, 0.0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= sx
        v.co.y *= sy
        v.co.z = (v.co.z + 0.5) * sz
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    uv = bm.loops.layers.uv.verify()
    for fi, f in enumerate(bm.faces):
        u0, v0 = (fi % 3) * 0.31 + 0.02, (fi // 3) * 0.45 + 0.02
        quad = [(u0, v0), (u0 + 0.27, v0), (u0 + 0.27, v0 + 0.40), (u0, v0 + 0.40)]
        for li, lp in enumerate(f.loops):
            lp[uv].uv = quad[li % 4]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    obj.location = loc
    sc.collection.objects.link(obj)
    return obj

# Ondas sólidas 2-manifold e colisor convexo
onda_1 = make_bmesh_solid("Onda_1_Solid", 2.4, 0.48, 0.55, (0.0, 0.0, 0.0))
for fi, f in enumerate(onda_1.data.faces):
    u0, v0 = (fi % 3) * 0.31 + 0.02, (fi // 3) * 0.45 + 0.02
    quad = [(u0, v0), (u0 + 0.27, v0), (u0 + 0.27, v0 + 0.40), (u0, v0 + 0.40)]
    for li, lp in enumerate(f.loops):
        lp[onda_1.loops.layers.uv.verify()].uv = quad[li % 4]
colisor_1 = make_bmesh_solid("UCX_Pump_Deck_01", 2.42, 0.50, 0.60, (0.0, 0.0, 0.0))
for fi, f in enumerate(colisor_1.data.faces):
    bmesh.ops.recalc_face_normals(colisor_1, faces=f)
for li, lp in enumerate(f.loops):
    lp[colisor_1.loops.layers.uv.verify()].uv = (fi % 3) * 0.30 + 0.02, (fi // 3) * 0.48 + 0.02
sc.collection.objects.link(colisor_1)

# Sockets de conexão hidráulica e tubulação curva
s_in = bpy.data.objects.new("Socket_Flow_In", None)
s_in.location = (-1.2, -0.5, 0.55)
s_in.parent = onda_1
sc.collection.objects.link(s_in)

s_out = bpy.data.objects.new("Socket_Flow_Out", None)
s_out.location = (1.2, 0.5, 1.15)
s_out.parent = onda_3 := make_bmesh_solid("Onda_3_Solid", 2.0, 0.40, 0.45, (0.0, 0.0, 0.0))
for fi, f in enumerate(s_out.data.faces):
    bmesh.ops.recalc_face_normals(s_out, faces=f)
for li, lp in enumerate(f.loops):
    lp[s_out.loops.layers.uv.verify()].uv = (fi % 2) * 0.28 + 0.02, (fi // 2) * 0.42 + 0.02
sc.collection.objects.link(s_out)
sc.collection.objects.link(onda_3)

# Tubulação curva Bezier pressurizada conectando exatamente Socket_Flow_In -> Socket_Flow_Out
cu = bpy.data.curves.new("Pressurized_Pipe_Curve", type='CURVE')
cu.dimensions = '3D'
cu.fill_mode = 'FULL'
cu.bevel_depth = 0.065
cu.bevel_resolution = 6
sp = cu.splines.new(type='BEZIER')
sp.bezier_points.add(2)
pts = [(-1.2, -0.5, 0.55), (0.0, 0.0, 1.05), (1.2, 0.5, 1.15)]
for idx, co in enumerate(pts):
    bp = sp.bezier_points[idx]
    bp.co = Vector(co)
    bp.handle_left_type = 'AUTO'
    bp.handle_right_type = 'AUTO'
pipe_obj = bpy.data.objects.new("Pressurized_Bezier_Pipe", cu)
sc.collection.objects.link(pipe_obj)

# Colisor convexo secundário para a spline
bm_spline = bmesh.new()
for x, y, z in pts:
    bm_spline.verts.new((x, y, z))
bmesh.ops.convex_hull(bm_spline, input=bm_spline.verts[:])
bmesh.ops.recalc_face_normals(bm_spline, faces=bm_spline.faces[:])
me_spline = bpy.data.meshes.new("UCX_Bezier_Collider")
bm_spline.to_mesh(me_spline)
bm_spline.free()
obj_spline = bpy.data.objects.new("UCX_Bezier_Collider_01", me_spline)
sc.collection.objects.link(obj_spline)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "Onda1_Onda3_Pump_Deck.glb"), export_format='GLB')