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

bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
for v in bm.verts:
    v.co.x *= 2.4
    v.co.y *= 1.6
    v.co.z = (v.co.z + 0.5) * 1.8
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
me = bpy.data.meshes.new("Hero_Industrial_Core")
bm.to_mesh(me)
bm.free()

mat = bpy.data.materials.new("M_Stage_Steel")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs["Base Color"].default_value = (0.55, 0.58, 0.62, 1.0)
    bsdf.inputs["Metallic"].default_value = 0.65
    bsdf.inputs["Roughness"].default_value = 0.35
me.materials.append(mat)

hero = bpy.data.objects.new("Hero_Industrial_Core", me)
sc.collection.objects.link(hero)

target_empty = bpy.data.objects.new("Stage_Aim_Center", None)
target_empty.location = (0.0, 0.0, 0.9)
sc.collection.objects.link(target_empty)

rig_specs = [
    ("Key_Light_Main", 'AREA', 850.0, (-4.2, -4.0, 4.6), (1.0, 0.96, 0.90)),
    ("Fill_Light_Soft", 'AREA', 360.0, (4.5, -3.2, 3.0), (0.82, 0.90, 1.0)),
    ("Rim_Light_Back", 'SPOT', 620.0, (0.4, 4.8, 4.2), (1.0, 0.88, 0.74)),
]
for lname, ltype, watts, loc, col in rig_specs:
    ld = bpy.data.lights.new(name=lname, type=ltype)
    ld.energy = watts
    ld.color = col
    lo = bpy.data.objects.new(name=lname, object_data=ld)
    lo.location = loc
    tr = lo.constraints.new(type='TRACK_TO')
    tr.target = target_empty
    tr.track_axis = 'TRACK_NEGATIVE_Z'
    tr.up_axis = 'UP_Y'
    sc.collection.objects.link(lo)

cam_d = bpy.data.cameras.new("Cine_Cam_DOF")
cam_d.lens = 42.0
cam_d.dof.use_dof = True
cam_d.dof.focus_object = target_empty
cam_d.dof.aperture_fstop = 4.0
cam_o = bpy.data.objects.new("Cine_Cam_DOF", cam_d)
cam_o.location = (5.4, -5.8, 3.4)
ct = cam_o.constraints.new(type='TRACK_TO')
ct.target = target_empty
ct.track_axis = 'TRACK_NEGATIVE_Z'
ct.up_axis = 'UP_Y'
sc.collection.objects.link(cam_o)
sc.camera = cam_o