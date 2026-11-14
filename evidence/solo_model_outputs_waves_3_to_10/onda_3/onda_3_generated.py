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

def make_manifold_box(name, sx, sy, sz, loc=(0.0, 0.0, 0.0)):
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

# Base e passarela industrial com degraus e guarda-corpo sólidos 2-manifold
base_obj = make_manifold_box("Manifold_Pump_Deck", 3.2, 1.8, 0.35, (0.0, 0.0, 0.0))
for step_i in range(4):
    make_manifold_box(
        f"Stair_Step_{step_i:02d}",
        0.55, 0.28, 0.08,
        (-1.85, -0.45 + step_i * 0.28, 0.08 * (step_i + 1)),
    )
for post_i, px in enumerate((-1.5, 0.0, 1.5)):
    make_manifold_box(f"Guardrail_Post_{post_i:02d}", 0.06, 0.06, 1.05, (px, 0.85, 0.35))
make_manifold_box("Guardrail_TopBar", 3.06, 0.06, 0.06, (0.0, 0.85, 1.38))

# Sockets de conexão hidráulica e flanges sólidos
p_in = (-1.20, -0.50, 0.55)
p_out = (1.20, 0.50, 1.15)
s_in = bpy.data.objects.new("Socket_Flow_In", None)
s_in.location = p_in
s_in.parent = base_obj
sc.collection.objects.link(s_in)

s_out = bpy.data.objects.new("Socket_Flow_Out", None)
s_out.location = p_out
s_out.parent = base_obj
sc.collection.objects.link(s_out)

make_manifold_box("Flange_In", 0.24, 0.24, 0.08, (p_in[0], p_in[1], p_in[2] - 0.04))
make_manifold_box("Flange_Out", 0.24, 0.24, 0.08, (p_out[0], p_out[1], p_out[2] - 0.04))

# Tubulação curva Bezier pressurizada conectando exatamente Socket_Flow_In -> Socket_Flow_Out
cu = bpy.data.curves.new("Pressurized_Pipe_Curve", type='CURVE')
cu.dimensions = '3D'
cu.fill_mode = 'FULL'
cu.bevel_depth = 0.065
cu.bevel_resolution = 6
sp = cu.splines.new(type='BEZIER')
sp.bezier_points.add(2)
pts = [p_in, (0.0, -0.10, 1.45), p_out]
for idx, co in enumerate(pts):
    bp = sp.bezier_points[idx]
    bp.co = Vector(co)
    bp.handle_left_type = 'AUTO'
    bp.handle_right_type = 'AUTO'
pipe_obj = bpy.data.objects.new("Pressurized_Bezier_Pipe", cu)
sc.collection.objects.link(pipe_obj)

# Colisor convexo UCX
bm_ucx = bmesh.new()
for x in (-1.9, 1.6):
    for y in (-0.9, 0.9):
        for z in (0.0, 1.55):
            bm_ucx.verts.new((x, y, z))
bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])
bmesh.ops.recalc_face_normals(bm_ucx, faces=bm_ucx.faces[:])
me_ucx = bpy.data.meshes.new("UCX_Pump_Deck_01")
bm_ucx.to_mesh(me_ucx)
bm_ucx.free()
obj_ucx = bpy.data.objects.new("UCX_Pump_Deck_01", me_ucx)
sc.collection.objects.link(obj_ucx)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "Onda3_Curves.glb"), export_format='GLB')