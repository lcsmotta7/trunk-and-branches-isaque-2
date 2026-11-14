import bpy
import bmesh
import os
from pathlib import Path
import mathutils
import math

# --- CONFIGURAÇÃO METRICA E VARIACOES ---
METRIC_SCALE = 1.0
UNIT = "meters"
EXPORT_DIR = Path(os.environ.get('KEV_EXPORT_DIR', '.'))
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

VARIATIONS = [
    {
        "name": "Var_01_Standard",
        "dimensions": (1.00, 0.16, 0.28), # L, W, H
        "position": (0.0, 0.0, 0.0),
        "z_min": 0.0,
    },
    {
        "name": "Var_02_Compact",
        "dimensions": (0.80, 0.16, 0.28),
        "position": (0.0, 0.65, 0.0),
        "z_min": 0.0,
    },
    {
        "name": "Var_03_Heavy",
        "dimensions": (1.25, 0.18, 0.32),
        "position": (0.0, -0.65, 0.0),
        "z_min": 0.0,
    },
]

# --- FUNÇÕES AUXILIARES ---
def get_bmesh_from_object(obj):
    """Converte objeto Blender em bmesh."""
    if obj.type == 'MESH':
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        return bm
    else:
        mesh_data = bpy.data.meshes.new(f"Temp_Mesh_{obj.name}")
        mesh_data.from_shape_key(bpy.data.shape_keys.active) if hasattr(bpy.data.shape_keys, 'active') and bpy.data.shape_keys.active else None
        bm = bmesh.new()
        bm.from_mesh(mesh_data)
        return bm

def create_empty_with_socket(name, location, rotation=(0, 0, 0), scale=(1, 1, 1)):
    """Cria objeto EMPTY com sockets."""
    obj = bpy.data.objects.new(name, None)
    obj.location = location
    obj.rotation_mode = 'QUATERNION'
    obj.rotation_euler = rotation
    obj.scale = scale
    
    # Criar sockets
    socket_data = bpy.data.sockets.new()
    socket_data.name = name
    socket_data.location = (0, 0, 0)
    socket_data.rotation_mode = 'QUATERNION'
    socket_data.rotation_euler = rotation
    socket_data.scale = scale
    
    obj.sockets.append(socket_data)
    return obj

def verify_uv_layer(bm):
    """Verifica e cria camada UV se não existir."""
    if bm.loops.layers.uv.is_none:
        bm.loops.layers.add('UV')
    return bm.loops.layers.uv.verify()

def create_convex_hull_bmesh(bm_input, name):
    """Cria bmesh convex hull para colisor."""
    bm_ucx = bmesh.new()
    bm_ucx.verts.clear()
    bm_ucx.verts.extend(bm_input.verts)
    
    # Convex Hull
    bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])
    
    return bm_ucx

def export_scene_to_formats(scene, glb_path, fbx_path):
    """Exporta GLB e FBX."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.context.view_layer.objects.active = None
    
    # Exportar GLB
    bpy.ops.export_scene.gltf(filepath=str(glb_path), use_selection=True)
    
    # Exportar FBX
    bpy.ops.export_scene.fbx(filepath=str(fbx_path), use_selection=True)

# --- PARTE A: Blender 5.2 Headless ---
def generate_blender_variations():
    """Gera as 3 variações paramétricas."""
    print(f"[VICOP] Iniciando geração de variações para {len(VARIATIONS)} objetos...")
    
    for var in VARIATIONS:
        name = var["name"]
        dims = var["dimensions"]
        pos = var["position"]
        
        print(f"[VICOP] Gerando {name}: {dims}m @ {pos}")
        
        # 1. Criar Mesh Base (Cubo)
        mesh_data = bpy.data.meshes.new(f"Bridge_{name}")
        bpy.ops.object.mesh_new(type='BOX')
        obj = bpy.context.active_object
        
        # Ajustar escala e posição
        obj.scale = mathutils.Vector(dims)
        obj.location = pos
        
        # 2. Gerar BMesh e Convex Hull
        bm = get_bmesh_from_object(obj)
        
        # Verificar UVs
        verify_uv_layer(bm)
        
        # 3. Limpar e preparar para exportação
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.transform_apply(scale=True)
        bpy.ops.object.transform_apply(location=True)
        bpy.ops.object.transform_apply(rotation=True)
        
        # 4. Verificar BBox e Z_min
        bbox = obj.bound_box
        z_min = min(v[2] for v in bbox)
        if abs(z_min - var["z_min"]) > 0.001:
            print(f"[VICOP] ALERTA: {name} tem Z_min={z_min}, esperado {var['z_min']}")
        
        # 5. Verificar escala e dimensões
        scale = obj.scale
        if abs(scale.x - dims[0]) > 0.01 or abs(scale.y - dims[1]) > 0.01 or abs(scale.z - dims[2]) > 0.01:
            print(f"[VICOP] ALERTA: {name} escala={scale}, esperado {dims}")
        
        # 6. Exportar GLB e FBX
        glb_path = EXPORT_DIR / f"{name}.glb"
        fbx_path = EXPORT_DIR / f"{name}.fbx"
        export_scene_to_formats(bpy.context.scene, str(glb_path), str(fbx_path))
        
        # 7. Limpar cena para próxima iteração
        bpy.ops.object.select_all(action='SELECT')
        bpy.ops.object.delete()
        bpy.ops.object.mode_set(mode='OBJECT')

# --- PARTE B: Unreal Engine 5 C++20 Data-Driven ---
def generate_unreal_cpp_code():
    """Gera código C++20 para Unreal Engine 5."""
    code = '''// ==========================================
// ModularBridgeAssetActor.h
// Unreal Engine 5 - C++20 Data-Driven
// ==========================================

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Components/StaticMeshComponent.h"
#include "ModularBridgeAssetActor.generated.h"

// Forward Declarations
class UStaticMesh;
class USocketComponent;

// ==========================================
// USTRUCT: FModularBridgeVariantRow
// ==========================================
USTRUCT(BlueprintType)
struct FModularBridgeVariantRow : public FTableRowBase
{
    GENERATED_BODY()

public:
    // Pointer à malha estática
    TObjectPtr<UStaticMesh> VariantMesh;

    // Dimensões esperadas em metros (L, W, H)
    FVector ExpectedDimensionsMeters{1.00f, 0.16f, 0.28f};

    // Nomes dos sockets de conexão
    FName MuzzleSocketName = FName("Socket_Muzzle");
    FName GripSocketName = FName("Socket_Grip");

    // Construtor padrão
    FModularBridgeVariantRow() {}

    // Construtor com dados completos
    FModularBridgeVariantRow(
        const TObjectPtr<UStaticMesh>& Mesh,
        const FVector& Dimensions,
        const FName& MuzzleName,
        const FName& GripName
    ) : VariantMesh(Mesh),
      ExpectedDimensionsMeters(Dimensions),
      MuzzleSocketName(MuzzleName),
      GripSocketName(GripName)
    {}

    // Verificação de toler