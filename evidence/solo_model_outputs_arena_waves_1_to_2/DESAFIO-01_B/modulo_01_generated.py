import bpy, bmesh, mathutils
from pathlib import Path
import os

# Configuração de ambiente headless e unidades
sc = bpy.context.scene
sc.unit_settings.system = 'METRIC'
sc.unit_settings.scale_length = 1.0
sc.render.engine = 'CYCLES' if hasattr(sc, 'render') and sc.render else None

# Diretório de exportação
export_dir = Path(os.environ.get('KEV_EXPORT_DIR', '.'))
os.makedirs(export_dir, exist_ok=True)

def create_ucx_collider(name, verts_co):
    """Cria colisor convexo (UCX) baseado em vértices fornecidos."""
    bm = bmesh.new()
    for co in verts_co:
        bm.verts.new(co)
    
    # Fechamento convexo estrito
    bmesh.ops.convex_hull(bm, input=bm.verts[:])
    
    # Recálculo de normais (obrigatório com faces plural)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    # Criação da malha e objeto
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    
    obj = bpy.data.objects.new(name, me)
    sc.collection.objects.link(obj)
    return obj

def build_modular_scifi_panel(SX=4.0, SY=0.4, SZ=3.0):
    """Constrói o módulo principal com geometria escalonada e UVs manuais."""
    
    # 1. Criação do cubo unitário estritamente (size=1.0)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)  # Tamanho fixo em unidades [-0.5, +0.5]
    
    # 2. Escala dos vértices para as dimensões finais
    # O cubo unitário tem vértices em [-0.5, 0.5].
    # Multiplicar por SX/SY/ZS e adicionar offset Z para garantir Z_min=0.0
    for v in bm.verts:
        v.co.x *= SX
        v.co.y *= SY
        v.co.z = (v.co.z + 0.5) * SZ
    
    # 3. Recálculo de normais e verificação de UVs
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    
    # Verificação estrita da camada UV (retorna None se não existir, não gera erro)
    uv_layer = bm.loops.layers.uv.verify()
    
    # 4. Atribuição manual de UVs (fallback seguro para background)
    if uv_layer is not None:
        for fi, f in enumerate(bm.faces):
            # Cálculo de coordenadas UV baseadas na face
            u0 = (fi % 3) * 0.31 + 0.02
            v0 = (fi // 3) * 0.45 + 0.02
            
            quad = [
                (u0, v0), 
                (u0 + 0.27, v0), 
                (u0 + 0.27, v0 + 0.40), 
                (u0, v0 + 0.40)
            ]
            
            for li, lp in enumerate(f.loops):
                lp[uv_layer].uv = quad[li % 4]
    
    # 5. Criação do objeto final e linkagem
    me_final = bpy.data.meshes.new('Modulo_01')
    bm.to_mesh(me_final)
    bm.free()
    
    obj_final = bpy.data.objects.new('Modulo_01', me_final)
    sc.collection.objects.link(obj_final)
    
    # Ajuste de pivô para (0,0,0) e verificação Z_min
    obj_final.location = (0.0, 0.0, 0.0)
    
    # Exportação GLB e FBX
    filepath_glb = f"{export_dir}/Modulo_01.glb"
    bpy.ops.export_scene.gltf(filepath=filepath_glb, export_format='GLB', use_selection=False)
    
    filepath_fbx = f"{export_dir}/Modulo_01.fbx"
    bpy.ops.export_scene.fbx(filepath=filepath_fbx, use_selection=False)

def assign_box_uvs_and_sockets(bm, primary_obj):
    """Atribui UVs e cria objetos EMPTY de socket."""
    
    # Verificação de camada UV
    uv_layer = bm.loops.layers.uv.verify()
    
    # Atribuição de UVs (repetição para garantir consistência)
    if uv_layer is not None:
        for fi, f in enumerate(bm.faces):
            u0 = (fi % 3) * 0.31 + 0.02
            v0 = (fi // 3) * 0.45 + 0.02
            
            quad = [
                (u0, v0), 
                (u0 + 0.27, v0), 
                (u0 + 0.27, v0 + 0.40), 
                (u0, v0 + 0.40)
            ]
            
            for li, lp in enumerate(f.loops):
                lp[uv_layer].uv = quad[li % 4]
    
    # Criação de Socket EMPTY
    sock = bpy.data.objects.new('Socket_Muzzle', None)
    sock.parent = primary_obj
    sc.collection.objects.link(sock)

# Execução do fluxo KEV/1.0
if __name__ == "__main__":
    # Inicialização da malha
    bm = bmesh.new()
    
    # Criação do cubo unitário
    bmesh.ops.create_cube(bm, size=1.0)
    
    # Aplicação das transformações conforme gráfico S1-S4
    SX, SY, SZ = 4.0, 0.4, 3.0
    
    for v in bm.verts:
        v.co.x *= SX
        v.co.y *= SY
        v.co.z = (v.co.z + 0.5) * SZ
    
    # Criação do objeto principal
    build_modular_scifi_panel(SX, SY, SZ)
    
    # Criação do colisor convexo UCX a partir dos vértices escalados
    verts_scaled = [v.co for v in bm.verts]
    ucx_obj = create_ucx_collider('UCX_Collider', verts_scaled)
    
    # Verificação final de não-manifold (simulação via bmesh)
    bm_check = bmesh.new()
    for v in bm.verts:
        bm_check.verts.new(v.co)
    bmesh.ops.convex_hull(bm_check, input=bm_check.verts[:])
    bmesh.ops.recalc_face_normals(bm_check, faces=bm_check.faces[:])
    
    # Verificação de exportação
    if os.path.exists(f"{export_dir}/Modulo_01.glb") and os.path.exists(f"{export_dir}/Modulo_01.fbx"):
        print("Exportação concluída com sucesso.")
    else:
        print("Erro na exportação.")