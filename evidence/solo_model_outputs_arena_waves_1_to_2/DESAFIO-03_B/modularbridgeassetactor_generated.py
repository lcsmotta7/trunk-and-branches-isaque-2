import bpy, bmesh, os, mathutils
from pathlib import Path
from typing import List, Tuple

# Configuração de Exportação
EXPORT_DIR = Path(os.environ.get('KEV_EXPORT_DIR', '.'))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Variáveis de Entrada (Pacote KEV/1.0)
VAR_01_STANDARD = {'x': 1.0, 'y': 0.4, 'z': 3.0}
VAR_02_COMPACT = {'x': 0.8, 'y': 0.35, 'z': 2.5}
VAR_03_HEAVY = {'x': 1.25, 'y': 0.18, 'z': 0.32}

SOCKETS = {
    'Socket_Muzzle': (mathutils.Vector(0.0, 0.0, 1.5), mathutils.Quaternion.identity()),
    'Socket_Grip': (mathutils.Vector(0.0, -0.2, 0.0), mathutils.Quaternion.identity())
}

def create_ucx_collider(name: str, verts_co: List[mathutils.Vector]) -> bpy.types.Object:
    """Cria colisor convexo manifold conforme KEV-BLENDER-01"""
    bm = bmesh.new()
    for co in verts_co:
        bm.verts.new(co)
    
    # Fechamento convexo (UCX_ exige convex_hull fechado)
    bmesh.ops.convex_hull(bm, input=bm.verts[:])
    
    # Recálculo de normais (REQUISITO KEV-BLENDER-01: faces plural)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj

def build_modular_scifi_panel(SX: float, SY: float, SZ: float) -> Tuple[bpy.types.Object, List[mathutils.Vector]]:
    """Construção de painel modular conforme KEV-BLENDER-01 e KEV-BLENDER-02"""
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 1.0
    
    bm = bmesh.new()
    
    # Criação de cubo unitário estrita (KEV-BLENDER-01: size=1.0)
    bmesh.ops.create_cube(bm, size=1.0)
    
    # Escala coordenada para evitar erro quadrático (KEV-BLENDER-02)
    verts_list = []
    for v in bm.verts:
        v.co.x *= SX
        v.co.y *= SY
        # Ajuste Z para garantir Z_min=0.0 exato conforme KEV-BLENDER-02
        v.co.z = (v.co.z + 0.5) * SZ
        verts_list.append(v.co)
    
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    # Verificação UV estrita (KEV-BLENDER-02: verify() não inteiro)
    uv_layer = bm.loops.layers.uv.verify()
    
    me = bpy.data.meshes.new('Modulo_01')
    bm.to_mesh(me)
    bm.free()
    
    obj = bpy.data.objects.new('Modulo_01', me)
    sc.collection.objects.link(obj)
    
    # Exportação GLB/FBX (KEV-BLENDER-02)
    filepath_glb = EXPORT_DIR / 'Modulo_01.glb'
    bpy.ops.export_scene.gltf(filepath=filepath_glb, export_format='GLB')
    
    return obj, verts_list

def build_bridge_variants() -> List[Tuple[str, bpy.types.Object]]:
    """Construção dos 3 variantes conforme @GRAPH"""
    variants = []
    
    # Variante 01: Standard
    verts_01 = [mathutils.Vector(x, y, z) for x, y, z in [
        (0.5, 0.2, 1.5), (-0.5, 0.2, 1.5), (-0.5, -0.2, 1.5), (0.5, -0.2, 1.5),
        (0.5, 0.2, -1.5), (-0.5, 0.2, -1.5), (-0.5, -0.2, -1.5), (0.5, -0.2, -1.5)
    ]]
    obj_01 = create_ucx_collider('UCX_Var_01_Standard_01', verts_01)
    variants.append(('Var_01_Standard', obj_01))
    
    # Variante 02: Compact
    verts_02 = [mathutils.Vector(x, y, z) for x, y, z in [
        (0.4, 0.175, 1.25), (-0.4, 0.175, 1.25), (-0.4, -0.175, 1.25), (0.4, -0.175, 1.25),
        (0.4, 0.175, -1.25), (-0.4, 0.175, -1.25), (-0.4, -0.175, -1.25), (0.4, -0.175, -1.25)
    ]]
    obj_02 = create_ucx_collider('UCX_Var_02_Compact_01', verts_02)
    variants.append(('Var_02_Compact', obj_02))
    
    # Variante 03: Heavy (Dimensões específicas KEV-GUARD)
    verts_03 = [mathutils.Vector(x, y, z) for x, y, z in [
        (0.625, 0.09, 0.16), (-0.625, 0.09, 0.16), (-0.625, -0.09, 0.16), (0.625, -0.09, 0.16),
        (0.625, 0.09, -0.16), (-0.625, 0.09, -0.16), (-0.625, -0.09, -0.16), (0.625, -0.09, -0.16)
    ]]
    obj_03 = create_ucx_collider('UCX_Var_03_Heavy_01', verts_03)
    variants.append(('Var_03_Heavy', obj_03))
    
    return variants

def add_sockets_to_mesh(obj: bpy.types.Object, socket_name: str, pos: mathutils.Vector, rot: mathutils.Quaternion) -> bool:
    """Adiciona sockets virtuais para Unreal Engine 5"""
    if not obj or not obj.data:
        return False
    
    me = obj.data
    bm = bmesh.from_mesh(me)
    
    # Verificar se o loop existe
    try:
        uv_layer = bm.loops.layers.uv.verify()
    except Exception:
        return False
    
    # Adicionar socket (representado por um loop específico ou vértice modificado para Unreal)
    # Implementação simplificada para Unreal Socket: adicionar vértice de referência e marcar como socket
    # Nota: Em Blender, sockets são geralmente adicionados via addon ou modificadores, mas aqui simulamos a estrutura
    
    # Adicionar vértice de socket se não existir (simplificação para o script)
    # Na prática, Unreal espera que os sockets estejam definidos no FBX/glTF
    # Aqui garantimos que a malha tenha os vért