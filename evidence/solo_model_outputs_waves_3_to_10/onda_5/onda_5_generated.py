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
bmesh.ops.create_cube(bm, size=0.2)
me_seed = bpy.data.meshes.new("Seed_Carrier")
bm.to_mesh(me_seed)
bm.free()
carrier = bpy.data.objects.new("GN_Industrial_Walkway_Grate", me_seed)
sc.collection.objects.link(carrier)

ng = bpy.data.node_groups.new("GN_Modular_Grate_Array", "GeometryNodeTree")
ng.interface.new_socket(name="Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
ng.interface.new_socket(name="Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')

n_in = ng.nodes.new("NodeGroupInput")
n_out = ng.nodes.new("NodeGroupOutput")
n_grid = ng.nodes.new("GeometryNodeMeshGrid")
n_cube = ng.nodes.new("GeometryNodeMeshCube")
n_inst = ng.nodes.new("GeometryNodeInstanceOnPoints")
n_real = ng.nodes.new("GeometryNodeRealizeInstances")

n_grid.inputs["Size X"].default_value = 3.6
n_grid.inputs["Size Y"].default_value = 1.6
n_grid.inputs["Vertices X"].default_value = 7
n_grid.inputs["Vertices Y"].default_value = 4
n_cube.inputs["Size"].default_value = (0.48, 0.36, 0.06)

ng.links.new(n_grid.outputs["Mesh"], n_inst.inputs["Points"])
ng.links.new(n_cube.outputs["Mesh"], n_inst.inputs["Instance"])
ng.links.new(n_inst.outputs["Instances"], n_real.inputs["Geometry"])
ng.links.new(n_real.outputs["Geometry"], n_out.inputs["Geometry"])

mod = carrier.modifiers.new(name="ModularGrateGN", type='NODES')
mod.node_group = ng