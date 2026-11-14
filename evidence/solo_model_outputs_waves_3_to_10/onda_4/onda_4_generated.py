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

def build_procedural_pbr(name, base_rgba, metallic, roughness, noise_scale=12.0, bump_strength=0.18, transmission=0.0):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out_n = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    bump = nt.nodes.new("ShaderNodeBump")
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion")

    noise.inputs["Scale"].default_value = noise_scale
    noise.inputs["Detail"].default_value = 6.0
    ramp.color_ramp.elements[0].color = (base_rgba[0] * 0.78, base_rgba[1] * 0.78, base_rgba[2] * 0.78, 1.0)
    ramp.color_ramp.elements[1].color = base_rgba

    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    for tk in ("Transmission Weight", "Transmission"):
        if tk in bsdf.inputs:
            bsdf.inputs[tk].default_value = transmission
            break

    bump.inputs["Strength"].default_value = bump_strength
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    nt.links.new(bsdf.outputs["BSDF"], out_n.inputs["Surface"])
    return mat

m_concrete = build_procedural_pbr("M_Industrial_Concrete", (0.34, 0.35, 0.37, 1.0), 0.0, 0.86, 18.0, 0.25, 0.0)
m_steel = build_procedural_pbr("M_Brushed_Steel", (0.62, 0.65, 0.69, 1.0), 0.92, 0.28, 42.0, 0.08, 0.0)
m_copper = build_procedural_pbr("M_Pressurized_Copper", (0.78, 0.44, 0.24, 1.0), 0.95, 0.22, 24.0, 0.06, 0.0)
m_glass = build_procedural_pbr("M_Tech_Glass", (0.76, 0.88, 0.95, 1.0), 0.05, 0.06, 8.0, 0.01, 0.88)

for idx, (m_ref, x_pos) in enumerate([(m_concrete, -1.5), (m_steel, -0.5), (m_copper, 0.5), (m_glass, 1.5)]):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=0.75)
    for v in bm.verts:
        v.co.z += 0.375
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    uv = bm.loops.layers.uv.verify()
    for lp in [l for f in bm.faces for l in f.loops]:
        lp[uv].uv = (0.5, 0.5)
    me = bpy.data.meshes.new(f"Swatch_{idx:02d}")
    bm.to_mesh(me)
    bm.free()
    me.materials.append(m_ref)
    ob = bpy.data.objects.new(f"Swatch_{idx:02d}", me)
    ob.location = (x_pos, 0.0, 0.0)
    sc.collection.objects.link(ob)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "Onda4_PBR.glb"), export_format='GLB')