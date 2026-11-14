#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seção 5 — Treino Experimental Anti-Esquecimento em Sandbox Isolado (`RTX 5060 8 GB`):
  - Arquitetura: `DoRA` (`use_dora=True`, `r=16`, `alpha=32`) + Subespaço Ortogonal `O-LoRA` (`lambda_orth = 0.10`)
    + `15%` Replay Buffer das amostras ouro do `Motor Humano` `0.15.0` (`Nota 8,57/10`).
  - Vocabulário `Qwen3.5-4B` 100% congelado (`embed_tokens` e `lm_head` intocados).
  - Onda 1 -> `D:\\Beyond Adonai\\Isaque\\laboratorio-kev-01\\pesos\\lab-mh-blender-bridge.safetensors` (+ `.gguf`)
  - Onda 2 -> `D:\\Beyond Adonai\\Isaque\\laboratorio-kev-01\\pesos\\lab-mh-ue5-kev.safetensors` (+ `.gguf` + acumulado)
  - Prova Matemática de Retenção Pós-Onda 2 sobre `Hold-out 0.15.0` e `Hold-out Onda 1` (`meta >= 99,0%`).
"""

import ctypes
import gc
import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

LAB_DIR = Path(r"D:\Beyond Adonai\Isaque\laboratorio-kev-01")
PROVA_DIR = Path(r"D:\Beyond Adonai\Abraao-Windows\Dados\Prova-KEV-01")
PESOS_DIR = LAB_DIR / "pesos"
TEMP_DIR = LAB_DIR / "temp" / "treino_dora_olora"
for _d in (PESOS_DIR, PROVA_DIR, TEMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

os.environ["TEMP"] = str(TEMP_DIR)
os.environ["TMP"] = str(TEMP_DIR)
os.environ["HF_HOME"] = str(TEMP_DIR / "hf")
os.environ["TORCH_HOME"] = str(TEMP_DIR / "torch")
os.environ["CUDA_CACHE_PATH"] = str(TEMP_DIR / "cuda")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import numpy as np
import torch
import torch.nn.functional as F
from peft import LoraConfig, get_peft_model
from safetensors import safe_open
from safetensors.torch import save_file as safetensors_save_file
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(LAB_DIR / "verificadores"))
from verificador_fisico_blender import verificar_script_blender  # noqa: E402

RAIZ_CASA = Path(r"D:\Beyond Adonai\Abraao-Windows")
RAIZ_ISAQUE = Path(r"D:\Beyond Adonai\Isaque")
MODEL_DIR = RAIZ_ISAQUE / "modelos" / "qwen3-4b"
UE5_VERIFIER_EXE = LAB_DIR / "bin" / "verificador_fisico_ue5_cpp.exe"

TARGET_MODULES = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "in_proj_qkv",
    "out_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]

MODULE_MAP_GGUF = {
    "linear_attn.in_proj_qkv": "attn_qkv",
    "linear_attn.out_proj": "ssm_out",
    "mlp.down_proj": "ffn_down",
    "mlp.gate_proj": "ffn_gate",
    "mlp.up_proj": "ffn_up",
    "self_attn.q_proj": "attn_q",
    "self_attn.k_proj": "attn_k",
    "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
}


class Win32GpuMutex:
    def __init__(self, name="Global\\AdonaiIsaqueGpuBurstLock", timeout_ms=240000):
        self.name = name
        self.timeout_ms = timeout_ms
        self.handle = None
        self.k32 = ctypes.windll.kernel32

    def __enter__(self):
        self.handle = self.k32.CreateMutexW(None, False, self.name)
        if not self.handle:
            self.handle = self.k32.CreateMutexW(None, False, "Local\\AdonaiIsaqueGpuBurstLock")
        res = self.k32.WaitForSingleObject(self.handle, self.timeout_ms)
        if res not in (0x00000000, 0x00000080):
            raise TimeoutError(f"Timeout aguardando Mutex GPU: {res}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.handle:
            self.k32.ReleaseMutex(self.handle)
            self.k32.CloseHandle(self.handle)
            self.handle = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def contar_cuda_compute_puro() -> int:
    proc = subprocess.run(
        ["nvidia-smi", "-q", "-d", "PIDS"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    txt = proc.stdout or ""
    # No WDDM Windows, processos puramente CUDA Compute reportam `Type : C`
    # e processos Isaque/llama/python não devem restar ativos pós-pulso.
    pure_c = re.findall(r"^\s*Type\s*:\s*C\s*$", txt, flags=re.M)
    residual_isaque = re.findall(r"(llama-completion|llama-mtmd-cli|isaque-)", txt, flags=re.I)
    return len(pure_c) + len(residual_isaque)


# ============================================================================
# DATASETS CURADOS E VERIFICADOS MECANICAMENTE (0.15.0 + ONDA 1 + ONDA 2)
# ============================================================================

GOLD_BLENDER_MODULAR_PY = """import os
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
bmesh.ops.inset_individual(bm, faces=front_faces, thickness=0.18, depth=-0.04)
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
"""

GOLD_BRIDGE_BLENDER_PY = """import os
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
sock_muzzle.location = (0.50, 0.0, 0.18)
sc.collection.objects.link(sock_muzzle)

sock_grip = bpy.data.objects.new("Socket_Grip", None)
sock_grip.parent = primary_obj
sock_grip.location = (-0.12, 0.0, 0.04)
sc.collection.objects.link(sock_grip)

bpy.ops.export_scene.gltf(filepath=str(out_dir / "ModularBridgePack.glb"), export_format='GLB')
bpy.ops.export_scene.fbx(filepath=str(out_dir / "ModularBridgePack.fbx"), apply_scale_options='FBX_SCALE_ALL')
"""

GOLD_UE5_INVENTORY_H = """#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/SphereComponent.h"
#include "GameFramework/Actor.h"
#include "TimerManager.h"
#include "InteractionInventorySystem.generated.h"

class AInteractableWorldActor;

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnInventoryItemChangedSignature, FName, ItemId, int32, NewQuantity);
DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnWorldActorInteractedSignature, AActor*, Interactor, FName, GrantedItemId);

USTRUCT(BlueprintType)
struct FInventorySlotEntry {
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Inventory")
    FName ItemId = NAME_None;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Inventory")
    int32 Quantity = 0;
};

UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent))
class UInteractionInventoryComponent : public UActorComponent {
    GENERATED_BODY()

public:
    UInteractionInventoryComponent();

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    float MaxInteractionDistanceCm = 250.0f;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Inventory")
    int32 MaxSlots = 16;

    UPROPERTY(BlueprintAssignable, Category="Inventory|Events")
    FOnInventoryItemChangedSignature OnInventoryItemChanged;

    UFUNCTION(BlueprintCallable, Category="Inventory")
    bool AddItem(FName ItemId, int32 Quantity);

    UFUNCTION(BlueprintCallable, Category="Inventory")
    int32 GetItemQuantity(FName ItemId) const;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool TryInteractWithActor(AInteractableWorldActor* TargetActor);

private:
    UPROPERTY(VisibleAnywhere, Category="Inventory")
    TArray<FInventorySlotEntry> Entries;
};

UCLASS()
class AInteractableWorldActor : public AActor {
    GENERATED_BODY()

public:
    AInteractableWorldActor();

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<UStaticMeshComponent> DisplayMesh;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<USphereComponent> InteractionSphere;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    FName RewardItemId = FName("PowerCell_Mk1");

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    int32 RewardQuantity = 1;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Interaction")
    float CooldownSeconds = 1.5f;

    UPROPERTY(BlueprintAssignable, Category="Interaction|Events")
    FOnWorldActorInteractedSignature OnWorldActorInteracted;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool CanInteract() const;

    UFUNCTION(BlueprintCallable, Category="Interaction")
    bool ExecuteInteraction(AActor* Interactor, UInteractionInventoryComponent* InventoryComp);

protected:
    virtual void EndPlay(const EEndPlayReason Reason) override;

private:
    bool bOnCooldown = false;
    FTimerHandle CooldownTimerHandle;
    void ResetInteractionCooldown();
};
"""

GOLD_UE5_INVENTORY_CPP = """#include "InteractionInventorySystem.h"

UInteractionInventoryComponent::UInteractionInventoryComponent() {
    PrimaryComponentTick.bCanEverTick = false;
}

bool UInteractionInventoryComponent::AddItem(FName ItemId, int32 Quantity) {
    if (ItemId.IsNone() || Quantity <= 0) {
        return false;
    }
    for (FInventorySlotEntry& Slot : Entries) {
        if (Slot.ItemId == ItemId) {
            Slot.Quantity += Quantity;
            OnInventoryItemChanged.Broadcast(ItemId, Slot.Quantity);
            return true;
        }
    }
    if (Entries.Num() >= MaxSlots) {
        return false;
    }
    FInventorySlotEntry NewSlot;
    NewSlot.ItemId = ItemId;
    NewSlot.Quantity = Quantity;
    Entries.Add(NewSlot);
    OnInventoryItemChanged.Broadcast(ItemId, Quantity);
    return true;
}

int32 UInteractionInventoryComponent::GetItemQuantity(FName ItemId) const {
    for (const FInventorySlotEntry& Slot : Entries) {
        if (Slot.ItemId == ItemId) {
            return Slot.Quantity;
        }
    }
    return 0;
}

bool UInteractionInventoryComponent::TryInteractWithActor(AInteractableWorldActor* TargetActor) {
    AActor* OwnerActor = GetOwner();
    if (!IsValid(OwnerActor) || !IsValid(TargetActor) || !TargetActor->CanInteract()) {
        return false;
    }
    const double DistCm = FVector::Dist(OwnerActor->GetActorLocation(), TargetActor->GetActorLocation());
    if (DistCm > static_cast<double>(MaxInteractionDistanceCm)) {
        return false;
    }
    return TargetActor->ExecuteInteraction(OwnerActor, this);
}

AInteractableWorldActor::AInteractableWorldActor() {
    PrimaryActorTick.bCanEverTick = false;
    DisplayMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("DisplayMesh"));
    SetRootComponent(DisplayMesh);

    InteractionSphere = CreateDefaultSubobject<USphereComponent>(TEXT("InteractionSphere"));
    InteractionSphere->InitSphereRadius(250.0f);
    InteractionSphere->SetupAttachment(DisplayMesh);
}

bool AInteractableWorldActor::CanInteract() const {
    return !bOnCooldown;
}

bool AInteractableWorldActor::ExecuteInteraction(AActor* Interactor, UInteractionInventoryComponent* InventoryComp) {
    if (bOnCooldown || !IsValid(Interactor) || !IsValid(InventoryComp)) {
        return false;
    }
    if (!InventoryComp->AddItem(RewardItemId, RewardQuantity)) {
        return false;
    }
    bOnCooldown = true;
    OnWorldActorInteracted.Broadcast(Interactor, RewardItemId);
    if (CooldownSeconds > 0.0f) {
        GetWorldTimerManager().SetTimer(
            CooldownTimerHandle,
            this,
            &AInteractableWorldActor::ResetInteractionCooldown,
            CooldownSeconds,
            false
        );
    } else {
        bOnCooldown = false;
    }
    return true;
}

void AInteractableWorldActor::ResetInteractionCooldown() {
    bOnCooldown = false;
    CooldownTimerHandle.Invalidate();
}

void AInteractableWorldActor::EndPlay(const EEndPlayReason Reason) {
    GetWorldTimerManager().ClearTimer(CooldownTimerHandle);
    Super::EndPlay(Reason);
}
"""

GOLD_UE5_BRIDGE_H = """#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "Components/StaticMeshComponent.h"
#include "GameFramework/Actor.h"
#include "ModularBridgeAssetActor.generated.h"

DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams(FOnBridgeVariantAppliedSignature, FName, VariantId, bool, bSocketsVerified);

USTRUCT(BlueprintType)
struct FModularBridgeVariantRow : public FTableRowBase {
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge")
    FName VariantId = FName("Var_01_Standard");

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge")
    TObjectPtr<UStaticMesh> VariantMesh = nullptr;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge")
    FVector ExpectedDimensionsMeters{1.00, 0.16, 0.28};

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge")
    FName MuzzleSocketName = FName("Socket_Muzzle");

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="Bridge")
    FName GripSocketName = FName("Socket_Grip");
};

UCLASS()
class AModularBridgeAssetActor : public AActor {
    GENERATED_BODY()

public:
    AModularBridgeAssetActor();

    static constexpr double BlenderMeterToUe5Cm = 100.0;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<UStaticMeshComponent> ReceiverMeshComponent;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<UStaticMeshComponent> MuzzleModuleComponent;

    UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category="Components")
    TObjectPtr<UStaticMeshComponent> GripModuleComponent;

    UPROPERTY(EditAnywhere, BlueprintReadOnly, Category="Bridge")
    TObjectPtr<UDataTable> VariantDataTable;

    UPROPERTY(BlueprintAssignable, Category="Bridge|Events")
    FOnBridgeVariantAppliedSignature OnBridgeVariantApplied;

    UFUNCTION(BlueprintCallable, Category="Bridge")
    bool ApplyDataDrivenVariant(FName RowName, float ToleranceRatio = 0.02f);

    UFUNCTION(BlueprintCallable, Category="Bridge")
    bool ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio = 0.02f) const;
};
"""

GOLD_UE5_BRIDGE_CPP = """#include "ModularBridgeAssetActor.h"

AModularBridgeAssetActor::AModularBridgeAssetActor() {
    PrimaryActorTick.bCanEverTick = false;

    ReceiverMeshComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ReceiverMeshComponent"));
    SetRootComponent(ReceiverMeshComponent);

    MuzzleModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("MuzzleModuleComponent"));
    MuzzleModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Muzzle"));

    GripModuleComponent = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("GripModuleComponent"));
    GripModuleComponent->SetupAttachment(ReceiverMeshComponent, FName("Socket_Grip"));
}

bool AModularBridgeAssetActor::ValidateBoundsMetersToCm(const FVector& ExpectedMeters, float ToleranceRatio) const {
    if (!IsValid(ReceiverMeshComponent) || !IsValid(ReceiverMeshComponent->GetStaticMesh())) {
        return false;
    }
    const FBox BoxCm = ReceiverMeshComponent->GetStaticMesh()->GetBoundingBox();
    const FVector MeasuredCm = BoxCm.GetSize();
    const FVector TargetCm = ExpectedMeters * BlenderMeterToUe5Cm;

    const double ErrX = FMath::Abs(MeasuredCm.X - TargetCm.X) / FMath::Max(TargetCm.X, KINDA_SMALL_NUMBER);
    const double ErrY = FMath::Abs(MeasuredCm.Y - TargetCm.Y) / FMath::Max(TargetCm.Y, KINDA_SMALL_NUMBER);
    const double ErrZ = FMath::Abs(MeasuredCm.Z - TargetCm.Z) / FMath::Max(TargetCm.Z, KINDA_SMALL_NUMBER);
    return (ErrX <= ToleranceRatio) && (ErrY <= ToleranceRatio) && (ErrZ <= ToleranceRatio);
}

bool AModularBridgeAssetActor::ApplyDataDrivenVariant(FName RowName, float ToleranceRatio) {
    if (!IsValid(VariantDataTable) || !IsValid(ReceiverMeshComponent)) {
        return false;
    }
    const FModularBridgeVariantRow* Row = VariantDataTable->FindRow<FModularBridgeVariantRow>(RowName, TEXT("BridgeLookup"));
    if (!Row || !IsValid(Row->VariantMesh.Get())) {
        return false;
    }
    ReceiverMeshComponent->SetStaticMesh(Row->VariantMesh.Get());

    const bool bHasMuzzle = ReceiverMeshComponent->DoesSocketExist(Row->MuzzleSocketName);
    const bool bHasGrip = ReceiverMeshComponent->DoesSocketExist(Row->GripSocketName);
    if (!bHasMuzzle || !bHasGrip) {
        OnBridgeVariantApplied.Broadcast(Row->VariantId, false);
        return false;
    }

    MuzzleModuleComponent->AttachToComponent(
        ReceiverMeshComponent,
        FAttachmentTransformRules::SnapToTargetNotIncludingScale,
        Row->MuzzleSocketName
    );
    GripModuleComponent->AttachToComponent(
        ReceiverMeshComponent,
        FAttachmentTransformRules::SnapToTargetNotIncludingScale,
        Row->GripSocketName
    );

    const bool bBoundsValid = ValidateBoundsMetersToCm(Row->ExpectedDimensionsMeters, ToleranceRatio);
    OnBridgeVariantApplied.Broadcast(Row->VariantId, bBoundsValid);
    return bBoundsValid;
}
"""


def verificar_gabaritos_fisicos_pre_treino() -> dict:
    """Garante R-VERDADE-OU-AJUDA: 100% dos alvos sintéticos de treino passam nos verificadores físicos reais!"""
    gdir = TEMP_DIR / "gold_pre_verify"
    gdir.mkdir(parents=True, exist_ok=True)

    p_b1 = gdir / "gold_mod01.py"
    p_b1.write_text(GOLD_BLENDER_MODULAR_PY, encoding="utf-8")
    r_b1 = verificar_script_blender(p_b1, expected_bbox_m=[4.0, 0.4, 3.0], try_headless_render=False)

    p_b2 = gdir / "gold_bridge.py"
    p_b2.write_text(GOLD_BRIDGE_BLENDER_PY, encoding="utf-8")
    r_b2 = verificar_script_blender(
        p_b2,
        expected_bbox_m=[1.0, 0.16, 0.28],
        min_visual_meshes=3,
        primary_prefix="Var_01_Standard",
        required_sockets=["Socket_Muzzle", "Socket_Grip"],
        try_headless_render=False,
    )

    h1, c1 = gdir / "InteractionInventorySystem.h", gdir / "InteractionInventorySystem.cpp"
    h1.write_text(GOLD_UE5_INVENTORY_H, encoding="utf-8")
    c1.write_text(GOLD_UE5_INVENTORY_CPP, encoding="utf-8")
    p_u1 = subprocess.run([str(UE5_VERIFIER_EXE), "--header", str(h1), "--source", str(c1)], capture_output=True, text=True, encoding="utf-8")
    r_u1 = json.loads(p_u1.stdout)

    h2, c2 = gdir / "ModularBridgeAssetActor.h", gdir / "ModularBridgeAssetActor.cpp"
    h2.write_text(GOLD_UE5_BRIDGE_H, encoding="utf-8")
    c2.write_text(GOLD_UE5_BRIDGE_CPP, encoding="utf-8")
    p_u2 = subprocess.run([str(UE5_VERIFIER_EXE), "--header", str(h2), "--source", str(c2)], capture_output=True, text=True, encoding="utf-8")
    r_u2 = json.loads(p_u2.stdout)

    checks = {
        "gold_blender_mod01_pass": bool(r_b1.get("aprovado_mecanico")),
        "gold_blender_bridge_pass": bool(r_b2.get("aprovado_mecanico")),
        "gold_ue5_inventory_pass": bool(r_u1.get("aprovado_mecanico")),
        "gold_ue5_bridge_pass": bool(r_u2.get("aprovado_mecanico")),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Falha na pré-verificação mecânica dos gabaritos de treino: {checks}\nB1={r_b1.get('violacoes')}\nB2={r_b2.get('violacoes')}\nU1={r_u1.get('violacoes')}\nU2={r_u2.get('violacoes')}")
    return checks


def montar_splits_treino_e_holdout() -> dict:
    sys_kev = (
        "Você é o Motor Humano KEV-1.0 do Isaque 2.0 Soberano. "
        "Opere sem bloco de pensamento prolixo e emita pacotes KEV/1.0 determinísticos ou código mecânico 100% verificado."
    )
    sys_0150 = (
        "Você opera com as Colunas Corticais MH-01 (VICOP) e MH-02 (Condutor Compacto) do Isaque 2.0 Soberano (0.15.0)."
    )

    # --- 0.15.0 Amostras Ouro (Replay Buffer 15% DISJUNTO do Hold-out 0.15.0!) ---
    gold_0150_all = []
    temas_0150 = [
        ("Painel Executivo Escuro Adon", "oklch(0.16 0.015 255)", "oklch(0.78 0.14 82)", "APCA Lc >= 75, tabular-nums, 1 CTA primario"),
        ("Ícone Gota 3D Vidro e Ouro", "oklch(0.14 0.012 250)", "oklch(0.80 0.15 84)", "IOR=1.52, Roughness=0.08 vidro, rim light dourada"),
        ("Acampamento Escritório Vivo", "oklch(0.20 0.018 255)", "oklch(0.75 0.13 80)", "Escala 1:1 INSUNITS=6m, LineArt GreasePencil"),
        ("Locomotiva B1-v1 PBR Lateral", "oklch(0.22 0.020 245)", "oklch(0.72 0.12 78)", "Metallic=0.85, Roughness=0.32, zero non-manifold"),
        ("Prancha Urbanística Arterial 32m", "oklch(0.18 0.015 255)", "oklch(0.77 0.14 82)", "Arterial 32m, Coletora 24m, Local 16m, 0 conflitos"),
        ("Card Telemetria BAVAR Conformal", "oklch(0.15 0.014 255)", "oklch(0.79 0.14 85)", "Grid 12-col gap-16px, badge status desacoplado"),
        ("Auditoria Base + Máscara Cadeia", "oklch(0.17 0.016 252)", "oklch(0.76 0.13 81)", "Preservar 100% pixels fora da mascara aprovada"),
        ("Vitrine 3D WebGPU Iluminação", "oklch(0.13 0.012 258)", "oklch(0.81 0.15 83)", "Key/Fill/Rim 3 pontos, exposicao equilibrada"),
        ("Tipografia Hierárquica Dashboard", "oklch(0.16 0.014 255)", "oklch(0.78 0.14 82)", "12/14/18/24px, tracking 0, contraste APCA >= 90 KPIs"),
        ("Maquete Industrial Pavimento Único", "oklch(0.19 0.017 250)", "oklch(0.74 0.12 79)", "Componentes pavimento=1, afastamento >= 2.33km"),
        ("Modal Confirmação Soberana Portão", "oklch(0.15 0.015 255)", "oklch(0.78 0.15 30)", "Hierarquia clara, foco teclado visivel 2px"),
        (" Textura Pedra Fosca e Metal Escovado", "oklch(0.24 0.015 250)", "oklch(0.76 0.13 82)", "Pedra Roughness 0.84, Metal Roughness 0.28"),
    ]
    for idx, (titulo, bg, acc, spec) in enumerate(temas_0150):
        q = f"Sintetize o pacote compacto VICOP-YHWH (0.15.0) para: {titulo}."
        a = (
            f"[VICOP-SPEC] Superfície base {bg}, acento {acc}; {spec}.\n"
            f"[VETOR-ANCORA-EN] spatial hierarchy, PBR roughness, APCA contrast, watertight mesh, mask preservation, metric scale 1:1.\n"
            f"[PARAMETROS-EXATOS] grid=12-col gap=16px pad=24px; bavar_gate=0.92; escala_m=1.0.\n"
            f"[NAO-FAZER] Proibido alterar pixels fora da máscara aprovada; proibido eleger preferência estética pelo Lucas."
        )
        gold_0150_all.append((sys_0150, q, a))

    replay_0150 = gold_0150_all[:6]   # 6 amostras para replay buffer (15%)
    holdout_0150 = gold_0150_all[6:]  # 6 amostras estritamente retidas para prova matemática H_0!

    # Carregar trechos reais de ruído documental do acervo Motor Humano (~1.100 tokens) para treinar
    # extração KEV de longo alcance imune a dossiês densos (>= 6.000 tokens na Arena)
    acervo_noise_chunks = []
    mh_root = Path(r"D:\Beyond Adonai\Abraao-Windows\Conhecimento\Motor humano")
    for p_md in sorted(mh_root.rglob("*.md"))[:12]:
        txt_md = p_md.read_text(encoding="utf-8", errors="ignore").strip()
        if len(txt_md) > 200:
            acervo_noise_chunks.append(f"[ACERVO MOTOR HUMANO :: {p_md.name}]\n{txt_md[:1100]}")
    while len(acervo_noise_chunks) < 6:
        acervo_noise_chunks.append("[ACERVO MOTOR HUMANO :: nota_tecnica.md]\nReferência de escala métrica 1:1 e topologia limpa.")

    def _montar_prefixo_ruido(seed_i: int) -> str:
        c1 = acervo_noise_chunks[seed_i % len(acervo_noise_chunks)]
        c2 = acervo_noise_chunks[(seed_i + 3) % len(acervo_noise_chunks)]
        return (
            f"--- TRANSCRIÇÃO TÉCNICA E REFERÊNCIA DE DOMÍNIO MULTIMODAL #01 ---\n{c1}\n\n"
            f"--- TRANSCRIÇÃO TÉCNICA E REFERÊNCIA DE DOMÍNIO MULTIMODAL #02 ---\n{c2}\n\n"
            f"=== ESPECIFICAÇÃO MANDATÓRIA DO ALVO ATUAL (PARÂMETROS OFICIAIS) ===\n"
        )

    # --- ONDA 1: Blender 5.2 BMesh Headless + UCX_ + Bridge 3D -> KEV-1.0 ---
    onda1_specs = [
        ("Modulo_01", 4.0, 0.4, 3.0, "UCX_Modulo_01", 3),
        ("Bulkhead_SciFi_02", 4.0, 0.5, 3.2, "UCX_Bulkhead_02", 4),
        ("Catwalk_Deck_03", 4.0, 1.6, 1.1, "UCX_Catwalk_03", 2),
        ("Reactor_Wall_04", 3.6, 0.6, 3.0, "UCX_Reactor_04", 3),
        ("Airlock_Portal_05", 3.0, 0.5, 3.2, "UCX_Airlock_05", 2),
        ("Cargo_Bunker_06", 2.4, 1.2, 1.6, "UCX_Bunker_06", 2),
        ("Pillar_Support_07", 0.8, 0.8, 3.0, "UCX_Pillar_07", 4),
        ("Hangar_Panel_08", 5.0, 0.4, 3.5, "UCX_Hangar_08", 3),
        ("Corridor_Arch_09", 4.0, 0.45, 3.0, "UCX_Arch_09", 3),
        ("Conduit_Frame_10", 2.5, 0.4, 2.4, "UCX_Conduit_10", 2),
    ]
    onda1_all = []
    for idx_b, (name, sx, sy, sz, ucx, ribs) in enumerate(onda1_specs):
        if idx_b < 4:
            q_kev = (
                f"Emita estritamente o pacote KEV/1.0 conciso (domain=BLENDER_BPY, target={name}) comprimindo fielmente todos os invariantes "
                f"físicos, nomes e dimensões da especificação oficial abaixo "
                f"(Guarda V_err Arena Tripla: Em modo --background, bpy.context.area é None; proibido usar bpy.ops.uv.smart_project dependente de VIEW_3D):\n"
                + _montar_prefixo_ruido(idx_b)
                + f"ESPECIFICAÇÃO OFICIAL — DESAFIO (BLENDER 5.2 HEADLESS -> ASSET MODULAR `{name}` PRONTO PARA UE5)\n"
                f"1. Sistema de Unidades: `METRIC`, `scale_length = 1.0`, orientação `Z-up`.\n"
                f"2. Dimensões Exatas da AABB (`@SPACE`): Largura `X = {sx}m`, Espessura `Y = {sy}m`, Altura `Z = {sz}m`, tolerância `±2%`.\n"
                f"3. Pivô e Base: Origem do objeto `{name}` cravada em `(0.0, 0.0, 0.0)` com `Z_min = 0.0`.\n"
                f"4. Geometria e UV: `bmesh.ops.inset_individual` ({ribs} nervuras, `2-manifold`, `non_manifold_edges == 0`, `zero_area_faces == 0`) e UV em `bm.loops.layers.uv.verify()`.\n"
                f"5. Colisor Físico Unreal e Exportação: `{ucx}` via `bmesh.ops.convex_hull` (`Z_min = 0.0`, `100% manifold`) e exportação `{name}.glb` / `{name}.fbx`."
            )
        else:
            q_kev = (
                f"Emita estritamente o pacote KEV/1.0 (domain=BLENDER_BPY) para construir em Blender 5.2 --background "
                f"o asset modular {name} ({sx}m x {sy}m x {sz}m), pivô (0,0,0) com Z_min=0.0, UV sem overlap, "
                f"colisor convexo manifold {ucx} e exportação GLB/FBX."
            )
        a_kev = (
            f"KEV/1.0 domain=BLENDER_BPY target={name}\n"
            f"@SPACE{{unit=METRIC;scale=1.0;up=Z;size_x={sx};size_y={sy};size_z={sz};pivot_z_min=0.0;collider={ucx}}}\n"
            f"@GRAPH[\n"
            f"  S1:BMESH.init_metric_scene(scale=1.0,empty=true) -> S2\n"
            f"  S2:BMESH.create_cube_and_inset(sx={sx},sy={sy},sz={sz},z_min=0.0,ribs={ribs}) -> S3\n"
            f"  S3:BMESH.loops_uv_verify_grid(outward=true,overlap=0) -> S4\n"
            f"  S4:BMESH.convex_hull_collider(name={ucx},manifold=true) -> S5\n"
            f"  S5:IO.export_assets(glb=\"{name}.glb\",fbx=\"{name}.fbx\")\n"
            f"]\n"
            f"@GUARD[\n"
            f"  !NO-VIEW3D-OPS: Construir geometria e UVs exclusivamente via bmesh e bm.loops.layers.uv.verify sem depender de janela 3D ativa\n"
            f"  !MANIFOLD-UCX: Garantir non_manifold_edges==0 e recalc_face_normals no colisor {ucx}\n"
            f"  !PIVOT-ORIGIN-Z0: Manter origin em (0,0,0) e base apoiada em Z_min=0.0 dentro de +-2% da AABB\n"
            f"]\n"
            f"@VERIFY[\n"
            f"  ?non_manifold_edges==0\n"
            f"  ?zero_area_faces==0\n"
            f"  ?unit_scale==1.0\n"
            f"  ?bbox_tol_pct<=2.0\n"
            f"]\n"
        )
        onda1_all.append((sys_kev, q_kev, a_kev))

    kev_bridge_3d = (
        'KEV/1.0 domain=BRIDGE_3D target=ModularBridgeAssetActor\n'
        '@SPACE{blender_unit=METRIC;ue5_unit=CM;meter_to_cm=100.0;up=Z;variations=3;sx=1.0;sy=0.16;sz=0.28;socket_a=Socket_Muzzle;socket_b=Socket_Grip;collider=UCX_Var_01_Standard_01}\n'
        '@GRAPH[\n'
        '  S1:BLENDER.build_3_variations_bmesh(v1_x=1.0,v2_x=0.8,v3_x=1.25,sy=0.16,sz=0.28,z_min=0.0) -> S2\n'
        '  S2:BLENDER.attach_sockets_and_ucx(muzzle=Socket_Muzzle,grip=Socket_Grip,ucx=UCX_Var_01_Standard_01) -> S3\n'
        '  S3:BLENDER.export_glb_fbx(glb="ModularBridgePack.glb",fbx="ModularBridgePack.fbx") -> S4\n'
        '  S4:UE5.ustruct_datatable_row(name=FModularBridgeVariantRow,meter_to_cm=100.0) -> S5\n'
        '  S5:UE5.actor_socket_validator(actor=AModularBridgeAssetActor,rule=SnapToTargetNotIncludingScale)\n'
        ']\n'
        '@GUARD[\n'
        '  !SCALE-1M-100CM: Multiplicar dimensoes em metros do Blender por 100.0 para validar FBox em centimetros no UE5\n'
        '  !SOCKET-EXACT-NAMES: Preservar literalmente Socket_Muzzle e Socket_Grip no Blender e no DoesSocketExist do C++\n'
        ']\n'
        '@VERIFY[\n'
        '  ?variations==3\n'
        '  ?non_manifold_edges==0\n'
        '  ?meter_to_cm==100.0\n'
        '  ?clang_cpp20_errors==0\n'
        ']\n'
    )

    kev_mod01_variant = (
        'KEV/1.0 domain=BLENDER_BPY target=Modulo_01\n'
        '@SPACE{unit=METRIC;scale=1.0;up=Z;size_x=4.0;size_y=0.4;size_z=3.0;pivot_z_min=0.0;collider=UCX_Modulo_01}\n'
        '@GRAPH[\n'
        '  S1:BMESH.init_metric_scene(scale=1.0,empty=true) -> S2\n'
        '  S2:BMESH.create_aabb_and_inset(sx=4.0,sy=0.4,sz=3.0,z_min=0.0,ribs=2) -> S3\n'
        '  S3:BMESH.recalc_normals_and_uv(faces=bm.faces,overlap=0) -> S4\n'
        '  S4:BMESH.convex_hull_collider(name=UCX_Modulo_01,mesh=Modulo_01) -> S5\n'
        '  S5:IO.export_assets(glb="Modulo_01.glb",fbx="Modulo_01.fbx")\n'
        ']\n'
        '@GUARD[\n'
        '  !NO-VIEW3D-OPS: Construir geometria e UVs exclusivamente via bmesh sem depender de janela 3D ativa\n'
        '  !MANIFOLD-0: Garantir non_manifold_edges==0 e zero_area_faces==0 no colisor convexo\n'
        ']\n'
        '@VERIFY[\n'
        '  ?non_manifold_edges==0\n'
        '  ?unit_scale==1.0\n'
        ']\n'
    )

    kev_bridge_3d_variant = (
        'KEV/1.0 domain=BRIDGE_3D target=ModularBridgeAssetActor\n'
        '@SPACE{unit=METRIC;scale=1.0;up=Z;variations=3;sx=1.0;sy=0.16;sz=0.28;socket_a=Socket_Muzzle;socket_b=Socket_Grip}\n'
        '@GRAPH[\n'
        '  S1:BLENDER.build_3_variations_bmesh(v1_x=1.0,v2_x=0.8,v3_x=1.25,sy=0.16,sz=0.28,z_min=0.0) -> S2\n'
        '  S2:BLENDER.attach_sockets_and_ucx(parent=Var_01_Standard,socket_a=Socket_Muzzle,socket_b=Socket_Grip,ucx=UCX_Var_01_Standard_01) -> S3\n'
        '  S3:BLENDER.export_glb_fbx(glb="ModularBridgePack.glb",fbx="ModularBridgePack.fbx") -> S4\n'
        '  S4:UE5.ustruct_datatable_row(name=FModularBridgeVariantRow,base=FTableRowBase,mesh=TObjectPtr_UStaticMesh,dims=ExpectedDimensionsMeters) -> S5\n'
        '  S5:UE5.actor_socket_validator_and_attacher(name=AModularBridgeAssetActor,base=AActor,tick=false,rule=SnapToTargetNotIncludingScale)\n'
        ']\n'
        '@GUARD[\n'
        '  !SCALE-1M-100CM: Multiplicar dimensoes em metros do Blender por 100.0 para validar FBox em centimetros no UE5\n'
        '  !SOCKET-EXACT-NAMES: Preservar literalmente Socket_Muzzle e Socket_Grip no Blender e no DoesSocketExist do C++\n'
        ']\n'
        '@VERIFY[\n'
        '  ?variations==3\n'
        '  ?non_manifold_edges==0\n'
        '  ?bbox_tol_pct<=2.0\n'
        ']\n'
    )

    def _gerar_py_modular_parametrico(tname: str, sx: float, sy: float, sz: float, ucx: str) -> str:
        return (
            GOLD_BLENDER_MODULAR_PY
            .replace("SX, SY, SZ = 4.0, 0.4, 3.0", f"SX, SY, SZ = {sx}, {sy}, {sz}")
            .replace('"UCX_Modulo_01"', f'"{ucx}"')
            .replace('"Modulo_01"', f'"{tname}"')
            .replace("Modulo_01.glb", f"{tname}.glb")
            .replace("Modulo_01.fbx", f"{tname}.fbx")
        )

    broken_mod01_py = GOLD_BLENDER_MODULAR_PY.replace(
        "uv_layer = bm.loops.layers.uv.verify()",
        'bmesh.ops.unwrap_atlas_uv(bm, faces=front_faces, padding=0.12)\nuv_layer = bm.loops.layers.uv.verify()',
    )
    broken_bridge_py = (
        "import os, bpy, bmesh\nfrom pathlib import Path\n"
        "bm = bmesh.new()\nbmesh.ops.scale_object(bm, size=1.0, origin='CENTER')\n"
        "sock_a = bpy.data.sockets.new(name='Socket_Muzzle')\n"
    )

    # Pares explícitos Estágio 1 (KEV/1.0 longo e curto), Estágio 2 (canônico + variante) e Reparo Físico Fechado na Onda 1
    onda1_code_pairs = [
        (
            sys_kev,
            (
                "Converta o pacote condutor abaixo (alvo `Modulo_01`) em um script Python completo para "
                "Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                "sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                "`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python.\n\n"
                f"PACOTE RECEBIDO:\n{onda1_all[0][2]}"
            ),
            GOLD_BLENDER_MODULAR_PY,
        ),
        (
            sys_kev,
            (
                "Converta o pacote condutor abaixo (alvo `Modulo_01`) em um script Python completo para "
                "Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                "sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                "`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python.\n\n"
                f"PACOTE RECEBIDO:\n{kev_mod01_variant}"
            ),
            GOLD_BLENDER_MODULAR_PY,
        ),
        (
            sys_kev,
            (
                "Corrija o script Python Blender 5.2 headless abaixo eliminando 100% das violações "
                "reportadas pelo verificador físico. Responda APENAS com código Python completo.\n\n"
                "[GUARDAS V_ERR ARENA TRIPLA]:\n- [KEV-BLENDER-01] GUARDA_ANTI_ERRO: Operar exclusivamente em bmesh e bm.loops.layers.uv.verify() sem operadores inexistentes.\n\n"
                f"PACOTE RECEBIDO:\n{kev_mod01_variant}\n\n"
                'DIAGNÓSTICO DO VERIFICADOR BLENDER 5.2:\n{"exit_code": 1, "violacoes": ["AttributeError: BMeshOpsModule: operator unwrap_atlas_uv doesnt exist"]}\n\n'
                f"CÓDIGO ANTERIOR:\n{broken_mod01_py[:1800]}"
            ),
            GOLD_BLENDER_MODULAR_PY,
        ),
        (
            sys_kev,
            (
                "Converta o pacote condutor abaixo (alvo `Bulkhead_SciFi_02`) em um script Python completo para "
                "Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                "sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                "`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python.\n\n"
                f"PACOTE RECEBIDO:\n{onda1_all[1][2]}"
            ),
            _gerar_py_modular_parametrico("Bulkhead_SciFi_02", 4.0, 0.5, 3.2, "UCX_Bulkhead_02"),
        ),
        (
            sys_kev,
            (
                "Emita estritamente o pacote KEV/1.0 conciso (domain=BRIDGE_3D, target=ModularBridgeAssetActor) comprimindo fielmente todos os invariantes "
                "físicos, nomes e dimensões da especificação oficial abaixo "
                "(Guarda V_err Arena Tripla: Converter metros do Blender para centímetros no UE5 multiplicando por 100.0 e usar SnapToTargetNotIncludingScale):\n"
                + _montar_prefixo_ruido(4)
                + "ESPECIFICAÇÃO OFICIAL — DESAFIO-03 (VARIAÇÃO EXTREMA CRUZADA: PONTE COMPLETA BLENDER 5.2 -> C++ UE5 DATA-DRIVEN)\n"
                "Parte A — Blender 5.2 Headless (`bmesh` puro):\n"
                "1. Escala `METRIC` (`scale_length = 1.0`, `Z-up`), 3 variações paramétricas (`2-manifold`, UV válida): "
                "`Var_01_Standard` (`1.00m x 0.16m x 0.28m`, `Z_min = 0.0`), `Var_02_Compact` (`0.80m x 0.16m x 0.28m`), `Var_03_Heavy` (`1.25m x 0.18m x 0.32m`).\n"
                "2. Sockets EMPTY `Socket_Muzzle` e `Socket_Grip` parentados à peça primária e colisor convexo `UCX_Var_01_Standard_01`, exportando `.glb` e `.fbx`.\n"
                "Parte B — Unreal Engine 5 C++20 Data-Driven (`ModularBridgeAssetActor.h` / `.cpp`):\n"
                "1. `USTRUCT(BlueprintType) struct FModularBridgeVariantRow : public FTableRowBase` (`ExpectedDimensionsMeters`, `Socket_Muzzle`, `Socket_Grip`).\n"
                "2. `UCLASS() class AModularBridgeAssetActor : public AActor` (`ExpectedMeters * 100.0`, `DoesSocketExist`, `SnapToTargetNotIncludingScale`)."
            ),
            kev_bridge_3d,
        ),
        (
            sys_kev,
            "Emita estritamente o pacote KEV/1.0 (domain=BRIDGE_3D, target=ModularBridgeAssetActor) comprimindo 3 variações paramétricas com Socket_Muzzle, Socket_Grip e UCX_ coordenados entre Blender 5.2 (1.0m) e UE5 C++ (100.0cm).",
            kev_bridge_3d,
        ),
        (
            sys_kev,
            (
                "Converta o pacote condutor abaixo (alvo `ModularBridgeAssetActor`) em um script Python completo para "
                "Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                "sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                "`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python.\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d}"
            ),
            GOLD_BRIDGE_BLENDER_PY,
        ),
        (
            sys_kev,
            (
                "Converta o pacote condutor abaixo (alvo `ModularBridgeAssetActor`) em um script Python completo para "
                "Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                "sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                "`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python.\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d_variant}"
            ),
            GOLD_BRIDGE_BLENDER_PY,
        ),
        (
            sys_kev,
            (
                "Corrija o script Python Blender 5.2 headless abaixo eliminando 100% das violações "
                "reportadas pelo verificador físico. Responda APENAS com código Python completo.\n\n"
                "[GUARDAS V_ERR ARENA TRIPLA]:\n- [KEV-BRIDGE-01] GUARDA_ANTI_ERRO: Escalar vertices diretamente em bm.verts e criar sockets via bpy.data.objects.new('Socket_Muzzle', None).\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d_variant}\n\n"
                'DIAGNÓSTICO DO VERIFICADOR BLENDER 5.2:\n{"exit_code": 1, "violacoes": ["AttributeError: BMeshOpsModule: operator scale_object doesnt exist", "SOCKETS_AUSENTES: Socket_Muzzle, Socket_Grip"]}\n\n'
                f"CÓDIGO ANTERIOR:\n{broken_bridge_py}"
            ),
            GOLD_BRIDGE_BLENDER_PY,
        ),
    ]
    train_onda1 = onda1_all[:7] + onda1_code_pairs * 2
    holdout_onda1 = onda1_all[7:]  # 3 exemplos BLENDER_BPY inéditos nunca vistos no treino!

    # --- ONDA 2: UE5 C++20 UHT/GC Safe + Compilação KEV-1.0 ---
    ue5_specs = [
        ("InteractionInventorySystem", "UInteractionInventoryComponent", "AInteractableWorldActor", 250.0, 1.5),
        ("TacticalSecuritySystem", "USecurityAccessComponent", "ASecurityTerminalActor", 200.0, 2.0),
        ("ReactorTelemetrySystem", "UCoolantControlComponent", "AReactorValveActor", 300.0, 1.0),
        ("CargoExtractionSystem", "ULootTransferComponent", "ACargoPodWorldActor", 220.0, 2.5),
        ("MedbayTriageSystem", "UBioScannerComponent", "AMedStationWorldActor", 180.0, 3.0),
        ("PowerGridRelaySystem", "UCircuitBreakerComponent", "APowerNodeWorldActor", 260.0, 1.2),
        ("CommsUplinkSystem", "USignalDecoderComponent", "AUplinkBeaconActor", 350.0, 4.0),
        ("ArmoryLoadoutSystem", "UWeaponRackComponent", "AArmoryLockerActor", 200.0, 1.5),
        ("AirlockCycleSystem", "UPressureSealComponent", "AAirlockControlActor", 240.0, 2.0),
        ("DroneDockingSystem", "UDroneTelemetryComponent", "ADockingCradleActor", 280.0, 1.8),
    ]
    onda2_all = []
    for idx_u, (sys_name, comp_cls, act_cls, dist_cm, cd_s) in enumerate(ue5_specs):
        if idx_u < 4:
            q_u = (
                f"Emita estritamente o pacote KEV/1.0 conciso (domain=UE5_CPP, target={sys_name}) comprimindo fielmente todos os invariantes "
                f"físicos, nomes e dimensões da especificação oficial abaixo "
                f"(Guarda V_err Arena Tripla: O UHT exige {sys_name}.generated.h estritamente como o último #include e proíbe ponteiro UObject cru sem UPROPERTY/TObjectPtr):\n"
                + _montar_prefixo_ruido(idx_u + 1)
                + f"ESPECIFICAÇÃO OFICIAL — DESAFIO (SISTEMA GAMEPLAY C++ UE5 COMPLETO `{sys_name}` SEM VIOLAÇÃO UHT/GC)\n"
                f"Objetivo: Implementar o par completo `{sys_name}.h` e `{sys_name}.cpp` em C++20 para Unreal Engine 5.\n"
                f"1. Header Guard e Ordem UHT: `#pragma once` e `#include \"{sys_name}.generated.h\"` ESTRITAMENTE como o ÚLTIMO `#include`.\n"
                f"2. Classes Refletidas: `UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent)) class {comp_cls} : public UActorComponent` e `UCLASS() class {act_cls} : public AActor`.\n"
                f"3. Prevenção GC: `TObjectPtr<UStaticMeshComponent>` e `TObjectPtr<USphereComponent>` com `UPROPERTY`, zero `new` bruto (`CreateDefaultSubobject`).\n"
                f"4. API e Ciclo de Vida: `DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams`, `UFUNCTION(BlueprintCallable)`, distância `{dist_cm}cm`, cooldown `{cd_s}s` via `FTimerHandle` sem Tick (`bCanEverTick = false`)."
            )
        else:
            q_u = (
                f"Emita estritamente o pacote KEV/1.0 (domain=UE5_CPP) para o sistema Unreal Engine 5 {sys_name} "
                f"contendo {comp_cls} e {act_cls} com TObjectPtr UPROPERTY seguro contra GC, UFUNCTION(BlueprintCallable), "
                f"DECLARE_DYNAMIC_MULTICAST_DELEGATE, distância {dist_cm}cm e cooldown de {cd_s}s via FTimerHandle sem Tick."
            )
        a_u = (
            f"KEV/1.0 domain=UE5_CPP target={sys_name}\n"
            f"@SPACE{{unit=CM;scale=100.0;up=Z;max_dist_cm={dist_cm};cooldown_s={cd_s};tick_enabled=false}}\n"
            f"@GRAPH[\n"
            f"  S1:UHT.header_order(pragma_once=true,last_include=\"{sys_name}.generated.h\") -> S2\n"
            f"  S2:UHT.delegates_and_struct(multicast=true,blueprint_assignable=true) -> S3\n"
            f"  S3:UCLASS.component(name={comp_cls},base=UActorComponent,tick=false) -> S4\n"
            f"  S4:UCLASS.actor(name={act_cls},base=AActor,mesh=TObjectPtr_UStaticMeshComponent,timer=FTimerHandle)\n"
            f"]\n"
            f"@GUARD[\n"
            f"  !UHT-LAST-INCLUDE: Incluir {sys_name}.generated.h estritamente por ultimo no header\n"
            f"  !GC-SAFE-TOBJECTPTR: Declarar todo membro UObject/AActor/UActorComponent com UPROPERTY() e TObjectPtr<T>\n"
            f"  !NO-RAW-NEW-UOBJECT: Instanciar componentes via CreateDefaultSubobject no construtor sem new bruto\n"
            f"  !TIMER-NO-TICK: Desativar bCanEverTick e limpar FTimerHandle em EndPlay\n"
            f"]\n"
            f"@VERIFY[\n"
            f"  ?generated_h_last==1\n"
            f"  ?raw_uobject_ptrs==0\n"
            f"  ?raw_new_uobject==0\n"
            f"  ?clang_cpp20_errors==0\n"
            f"]\n"
        )
        onda2_all.append((sys_kev, q_u, a_u))

    kev_ue5_inv_variant = (
        'KEV/1.0 domain=UE5_CPP target=InteractionInventorySystem\n'
        '@SPACE{unit=METRIC;scale=1.0;up=Z;max_dist_cm=250.0;cooldown_s=1.5}\n'
        '@GRAPH[\n'
        '  S1:UHT.header_order(pragma_once=true,last_include="InteractionInventorySystem.generated.h") -> S2\n'
        '  S2:UHT.delegates_and_struct(multicast=true,blueprint_assignable=true) -> S3\n'
        '  S3:UCLASS.component(name=UInteractionInventoryComponent,base=UActorComponent,display=DisplayMesh) -> S4\n'
        '  S4:UCLASS.actor(name=AInteractableWorldActor,base=AActor,mesh=TObjectPtr_UStaticMeshComponent,timer=FTimerHandle)\n'
        ']\n'
        '@GUARD[\n'
        '  !UHT-LAST-INCLUDE: Incluir InteractionInventorySystem.generated.h ESTRITAMENTE por ultimo no header\n'
        '  !GC-SAFE-TOBJECTPTR: Declarar todo membro UObject/AActor/UActorComponent com UPROPERTY() e TObjectPtr<T>\n'
        ']\n'
        '@VERIFY[\n'
        '  ?generated_h_last==1\n'
        '  ?raw_uobject_ptrs==0\n'
        ']\n'
    )

    onda2_code_pairs = [
        (
            sys_kev,
            (
                "Gere APENAS o header `InteractionInventorySystem.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                "todas as structs, classes, propriedades, funções, delegados e invariantes UHT/GC do pacote abaixo.\n\n"
                f"PACOTE RECEBIDO:\n{onda2_all[0][2]}"
            ),
            GOLD_UE5_INVENTORY_H,
        ),
        (
            sys_kev,
            (
                "Gere APENAS o header `InteractionInventorySystem.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                "todas as structs, classes, propriedades, funções, delegados e invariantes UHT/GC do pacote abaixo.\n\n"
                f"PACOTE RECEBIDO:\n{kev_ue5_inv_variant}"
            ),
            GOLD_UE5_INVENTORY_H,
        ),
        (
            sys_kev,
            (
                "Gere APENAS a implementação `InteractionInventorySystem.cpp` completa em C++20 Unreal Engine 5 "
                "correspondente estritamente ao pacote abaixo e ao header `InteractionInventorySystem.h`:\n\n"
                f"PACOTE:\n{onda2_all[0][2]}\n\nHEADER `InteractionInventorySystem.h`:\n{GOLD_UE5_INVENTORY_H}"
            ),
            GOLD_UE5_INVENTORY_CPP,
        ),
        (
            sys_kev,
            (
                "Gere APENAS a implementação `InteractionInventorySystem.cpp` completa em C++20 Unreal Engine 5 "
                "correspondente estritamente ao pacote abaixo e ao header `InteractionInventorySystem.h`:\n\n"
                f"PACOTE:\n{kev_ue5_inv_variant}\n\nHEADER `InteractionInventorySystem.h`:\n{GOLD_UE5_INVENTORY_H}"
            ),
            GOLD_UE5_INVENTORY_CPP,
        ),
        (
            sys_kev,
            (
                "Gere APENAS o header `ModularBridgeAssetActor.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                "todas as structs, classes, propriedades, funções, delegados e invariantes UHT/GC do pacote abaixo.\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d}"
            ),
            GOLD_UE5_BRIDGE_H,
        ),
        (
            sys_kev,
            (
                "Gere APENAS o header `ModularBridgeAssetActor.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                "todas as structs, classes, propriedades, funções, delegados e invariantes UHT/GC do pacote abaixo.\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d_variant}"
            ),
            GOLD_UE5_BRIDGE_H,
        ),
        (
            sys_kev,
            (
                "Gere APENAS a implementação `ModularBridgeAssetActor.cpp` completa em C++20 Unreal Engine 5 "
                "correspondente estritamente ao pacote abaixo e ao header `ModularBridgeAssetActor.h`:\n\n"
                f"PACOTE:\n{kev_bridge_3d}\n\nHEADER `ModularBridgeAssetActor.h`:\n{GOLD_UE5_BRIDGE_H}"
            ),
            GOLD_UE5_BRIDGE_CPP,
        ),
        (
            sys_kev,
            (
                "Gere APENAS a implementação `ModularBridgeAssetActor.cpp` completa em C++20 Unreal Engine 5 "
                "correspondente estritamente ao pacote abaixo e ao header `ModularBridgeAssetActor.h`:\n\n"
                f"PACOTE:\n{kev_bridge_3d_variant}\n\nHEADER `ModularBridgeAssetActor.h`:\n{GOLD_UE5_BRIDGE_H}"
            ),
            GOLD_UE5_BRIDGE_CPP,
        ),
        (
            sys_kev,
            (
                "Corrija o header `InteractionInventorySystem.h` em C++20 Unreal Engine 5 eliminando todas as violações "
                "UHT/GC/Clang++20 listadas abaixo. Responda APENAS com o código completo de `InteractionInventorySystem.h`.\n\n"
                "[GUARDAS V_ERR ARENA TRIPLA]:\n- [KEV-UE5-01] GUARDA_ANTI_ERRO: Componentes herdam de UActorComponent (prefixo U) e atores herdam de AActor (prefixo A).\n\n"
                f"PACOTE RECEBIDO:\n{kev_ue5_inv_variant}\n\n"
                'DIAGNÓSTICO:\n{"violacoes": ["error: unknown class name AActorComponent; did you mean UActorComponent?"]}\n\n'
                "HEADER ANTERIOR:\n#pragma once\n#include \"CoreMinimal.h\"\n#include \"InteractionInventorySystem.generated.h\"\nclass AInteractionInventoryComponent : public AActorComponent { GENERATED_BODY() };\n"
            ),
            GOLD_UE5_INVENTORY_H,
        ),
        (
            sys_kev,
            (
                "Reescreva `ModularBridgeAssetActor.cpp` em C++20 Unreal Engine 5 para compilar com zero erros Clang++20 "
                "contra o header `ModularBridgeAssetActor.h` corrigido abaixo (use exatamente os tipos, nomes de membros e assinaturas declarados em `ModularBridgeAssetActor.h`). "
                "Responda APENAS com o código completo de `ModularBridgeAssetActor.cpp`.\n\n"
                "[GUARDAS V_ERR ARENA TRIPLA]:\n- [KEV-BRIDGE-02] GUARDA_ANTI_ERRO: Multiplicar ExpectedMeters por 100.0 e usar RowName no Broadcast sem acessar membros inexistentes.\n\n"
                f"PACOTE RECEBIDO:\n{kev_bridge_3d_variant}\n\n"
                'DIAGNÓSTICO ANTERIOR:\n{"violacoes": ["error: use of undeclared identifier Row", "error: no member named VariantId in FModularBridgeVariantRow"]}\n\n'
                f"HEADER `ModularBridgeAssetActor.h` ATUAL:\n{GOLD_UE5_BRIDGE_H}\n\n"
                "CPP ANTERIOR:\n#include \"ModularBridgeAssetActor.h\"\nAModularBridgeAssetActor::AModularBridgeAssetActor() { MuzzleModuleMesh->SetupAttachment(ReceiverMesh, Row->MuzzleSocketName); }\n"
            ),
            GOLD_UE5_BRIDGE_CPP,
        ),
    ]
    train_onda2 = onda2_all[:7] + onda2_code_pairs * 2
    holdout_onda2 = onda2_all[7:]  # 3 exemplos UE5_CPP inéditos nunca vistos no treino!

    return {
        "replay_0150": replay_0150,
        "holdout_0150": holdout_0150,
        "train_onda1": train_onda1,
        "holdout_onda1": holdout_onda1,
        "train_onda2": train_onda2,
        "holdout_onda2": holdout_onda2,
    }


def tokenizar_pares(pares: list[tuple[str, str, str]], tokenizer, seq_len: int = 2432) -> list[tuple[torch.Tensor, torch.Tensor]]:
    out = []
    for sys_msg, user_msg, asst_msg in pares:
        mp = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        mf = mp + [{"role": "assistant", "content": asst_msg}]
        ptxt = tokenizer.apply_chat_template(mp, tokenize=False, add_generation_prompt=True, enable_thinking=False)
        ftxt = tokenizer.apply_chat_template(mf, tokenize=False, add_generation_prompt=False, enable_thinking=False)
        p_ids = tokenizer.encode(ptxt, add_special_tokens=False)
        f_ids = tokenizer.encode(ftxt, add_special_tokens=False)[:seq_len]
        cut = min(len(p_ids), len(f_ids))
        labels = [-100] * cut + f_ids[cut:]
        out.append((torch.tensor(f_ids, dtype=torch.long), torch.tensor(labels, dtype=torch.long)))
    return out


def mezclar_com_replay_15pct(
    primary_tok: list[tuple[torch.Tensor, torch.Tensor]],
    replay_tok: list[tuple[torch.Tensor, torch.Tensor]],
    total_batches: int,
    batch_size: int = 2,
) -> list[list[tuple[torch.Tensor, torch.Tensor]]]:
    """Monta exatamente 85% amostras da onda atual + 15% Replay Buffer das amostras ouro 0.15.0."""
    total_items = total_batches * batch_size
    n_replay = max(1, int(round(total_items * 0.15)))
    n_primary = total_items - n_replay

    seq = []
    p_idx, r_idx = 0, 0
    # Distribuir uniformemente os itens de replay ao longo dos passos
    replay_positions = set(np.linspace(2, total_items - 1, num=n_replay, dtype=int).tolist())
    for pos in range(total_items):
        if pos in replay_positions:
            seq.append(replay_tok[r_idx % len(replay_tok)])
            r_idx += 1
        else:
            seq.append(primary_tok[p_idx % len(primary_tok)])
            p_idx += 1

    batches = [seq[i : i + batch_size] for i in range(0, total_items, batch_size)]
    return batches


def obter_backbone_e_lm_head(model):
    causal = model.base_model.model if (hasattr(model, "base_model") and hasattr(model.base_model, "model")) else model
    return causal.model, causal.lm_head


def _chunk_ce_fn(h_chunk: torch.Tensor, y_chunk: torch.Tensor, lm_head_weight: torch.Tensor, total_toks: float) -> torch.Tensor:
    logits_chunk = F.linear(h_chunk, lm_head_weight).float()
    return F.cross_entropy(logits_chunk, y_chunk, reduction="sum") / total_toks


def forward_chunked_ce(model, input_ids: torch.Tensor, labels: torch.Tensor, chunk_size: int = 64) -> torch.Tensor:
    backbone, lm_head = obter_backbone_e_lm_head(model)
    outputs = backbone(input_ids=input_ids, use_cache=False)
    hidden = outputs.last_hidden_state

    shift_h = hidden[:, :-1, :].contiguous().view(-1, hidden.size(-1))
    shift_y = labels[:, 1:].contiguous().view(-1)
    valid_idx = torch.nonzero(shift_y != -100, as_tuple=False).squeeze(-1)
    if valid_idx.numel() == 0:
        return hidden.sum() * 0.0

    sh = shift_h.index_select(0, valid_idx)
    sy = shift_y.index_select(0, valid_idx)
    total_toks = float(sy.size(0))
    w_head = lm_head.weight
    loss_total = None
    for s in range(0, int(total_toks), chunk_size):
        e = min(s + chunk_size, int(total_toks))
        hc, yc = sh[s:e], sy[s:e]
        if torch.is_grad_enabled() and hc.requires_grad:
            lc = torch.utils.checkpoint.checkpoint(_chunk_ce_fn, hc, yc, w_head, total_toks, use_reentrant=False)
        else:
            lc = _chunk_ce_fn(hc, yc, w_head, total_toks)
        loss_total = lc if loss_total is None else (loss_total + lc)
    return loss_total


@torch.no_grad()
def avaliar_holdout(model, tok_pairs: list[tuple[torch.Tensor, torch.Tensor]]) -> dict:
    model.eval()
    backbone, lm_head = obter_backbone_e_lm_head(model)
    w_head = lm_head.weight
    nll_sum = 0.0
    tok_count = 0
    correct_top1 = 0

    for x_cpu, y_cpu in tok_pairs:
        xb = x_cpu.unsqueeze(0).to("cuda:0")
        yb = y_cpu.unsqueeze(0).to("cuda:0")
        hidden = backbone(input_ids=xb, use_cache=False).last_hidden_state
        sh = hidden[:, :-1, :].contiguous().view(-1, hidden.size(-1))
        sy = yb[:, 1:].contiguous().view(-1)
        valid_idx = torch.nonzero(sy != -100, as_tuple=False).squeeze(-1)
        if valid_idx.numel() == 0:
            continue
        sh_v = sh.index_select(0, valid_idx)
        sy_v = sy.index_select(0, valid_idx)
        for s in range(0, sh_v.size(0), 64):
            e = min(s + 64, sh_v.size(0))
            logits = F.linear(sh_v[s:e], w_head).float()
            nll_sum += float(F.cross_entropy(logits, sy_v[s:e], reduction="sum").cpu().item())
            preds = logits.argmax(dim=-1)
            correct_top1 += int((preds == sy_v[s:e]).sum().cpu().item())
        tok_count += int(sy_v.size(0))

    avg_loss = nll_sum / max(tok_count, 1)
    acc = correct_top1 / max(tok_count, 1)
    ppl = math.exp(min(avg_loss, 15.0))
    return {
        "loss": round(avg_loss, 6),
        "perplexity": round(ppl, 4),
        "token_acc": round(acc, 6),
        "eval_tokens": tok_count,
    }


def coletar_matrizes_a_congeladas(peft_model, adapter_name: str) -> dict[str, torch.Tensor]:
    out = {}
    for name, param in peft_model.named_parameters():
        if f".lora_A.{adapter_name}.weight" in name:
            key_mod = name.split(f".lora_A.{adapter_name}.weight")[0]
            out[key_mod] = param.detach().to(torch.float32).clone()
    return out


def projetar_onda2_no_complemento_ortogonal_inicial(peft_model, a_onda1: dict[str, torch.Tensor], adapter_onda2: str = "onda_2"):
    """Inicialização O-LoRA exata: projeta as linhas iniciais de A^(2) no subespaço ortogonal a A^(1)."""
    with torch.no_grad():
        for name, param in peft_model.named_parameters():
            if f".lora_A.{adapter_onda2}.weight" in name:
                key_mod = name.split(f".lora_A.{adapter_onda2}.weight")[0]
                if key_mod in a_onda1:
                    a1 = a_onda1[key_mod]  # [r, d_in]
                    a2 = param.data.to(torch.float32)  # [r, d_in]
                    # Base ortonormal das linhas de A1 via QR
                    q1, _ = torch.linalg.qr(a1.T)  # [d_in, r]
                    proj = (a2 @ q1) @ q1.T
                    a2_orth = a2 - proj
                    param.data.copy_(a2_orth.to(param.dtype))


def calcular_loss_ortogonal_olora(peft_model, a_onda1: dict[str, torch.Tensor], adapter_onda2: str = "onda_2") -> torch.Tensor:
    """
    Penalidade exata O-LoRA (Seção 5.1):
      sum_l || A_l^(onda 2) (A_l^(onda 1))^T ||_F^2
    """
    orth_sum = None
    for name, param in peft_model.named_parameters():
        if f".lora_A.{adapter_onda2}.weight" in name:
            key_mod = name.split(f".lora_A.{adapter_onda2}.weight")[0]
            if key_mod in a_onda1:
                a2 = param.float()
                a1 = a_onda1[key_mod]
                prod = torch.matmul(a2, a1.transpose(0, 1))
                frob_sq = torch.sum(prod * prod)
                orth_sum = frob_sq if orth_sum is None else (orth_sum + frob_sq)
    if orth_sum is None:
        return torch.tensor(0.0, device="cuda:0")
    return orth_sum


def salvar_dora_safetensors_oficial(peft_model, adapter_name: str, out_path: Path, metadata: dict) -> str:
    state = {}
    for name, param in peft_model.named_parameters():
        if f".{adapter_name}." in name:
            clean_key = name.replace(f".{adapter_name}.", ".")
            state[clean_key] = param.detach().to(torch.float32).cpu().contiguous()
    str_meta = {k: str(v) for k, v in metadata.items()}
    safetensors_save_file(state, str(out_path), metadata=str_meta)
    return sha256_file(out_path)


# ============================================================================
# EXPORTAÇÃO EXATA DoRA (BF16 + Magnitude + Direção) -> GGUF v3 LoRA (SVD r=16)
# ============================================================================

def _align32(off: int) -> int:
    r = off % 32
    return off if r == 0 else off + (32 - r)


def _pack_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<Q", len(b)) + b


def _pack_kv_str(k: str, v: str) -> bytes:
    return _pack_str(k) + struct.pack("<I", 8) + _pack_str(v)


def _pack_kv_f32(k: str, v: float) -> bytes:
    return _pack_str(k) + struct.pack("<If", 6, float(v))


def exportar_dora_para_gguf_svd(
    dora_safetensors_paths: list[Path],
    out_gguf: Path,
    adapter_label: str,
    dora_rank_r: int = 16,
    dora_alpha: float = 32.0,
    svd_export_rank: int = 64,
    svd_device: str = "cuda:0",
) -> dict:
    """
    Reconstrói o delta efetivo exato do DoRA sobre os pesos BF16 originais `W_0`:
      W_dora = (m / ||W_0 + (alpha/r) B A||_row) * (W_0 + (alpha/r) B A)
      DeltaW = W_dora - W_0
    Fatora (1 / scale) * DeltaW via SVD truncada em GPU (`svd_export_rank=64`) ajustando
    `adapter.lora.alpha = scale * svd_export_rank` para preservar `alpha_gguf / r_gguf == scale`
    com alta fidelidade tanto da direção low-rank quanto do vetor de magnitude DoRA!
    """
    idx_doc = json.loads((MODEL_DIR / "model.safetensors.index.json").read_text(encoding="utf-8"))
    wmap = idx_doc["weight_map"]
    scale = dora_alpha / float(dora_rank_r)
    gguf_alpha = scale * float(svd_export_rank)

    loaded_adapters = []
    for st_p in dora_safetensors_paths:
        d = {}
        with safe_open(str(st_p), framework="pt", device="cpu") as sf:
            for k in sf.keys():
                d[k] = sf.get_tensor(k).to(torch.float32)
        loaded_adapters.append(d)

    shard_handles = {}
    for shard_name in set(wmap.values()):
        sp = MODEL_DIR / shard_name
        if sp.is_file():
            shard_handles[shard_name] = safe_open(str(sp), framework="pt", device="cpu")

    tensors_gguf = []
    rel_recon_errors = []

    with torch.no_grad():
        for blk_idx in range(32):
            for mod_hf, mod_gguf in MODULE_MAP_GGUF.items():
                key_a = f"base_model.model.model.layers.{blk_idx}.{mod_hf}.lora_A.weight"
                key_b = f"base_model.model.model.layers.{blk_idx}.{mod_hf}.lora_B.weight"
                key_m = f"base_model.model.model.layers.{blk_idx}.{mod_hf}.lora_magnitude_vector.weight"
                if key_a not in loaded_adapters[0]:
                    continue

                base_key = f"model.language_model.layers.{blk_idx}.{mod_hf}.weight"
                if base_key not in wmap:
                    base_key = f"model.layers.{blk_idx}.{mod_hf}.weight"
                shard_f = shard_handles[wmap[base_key]]
                W0 = shard_f.get_tensor(base_key).to(device=svd_device, dtype=torch.float32)

                total_delta = torch.zeros_like(W0)
                for ad in loaded_adapters:
                    A = ad[key_a].to(svd_device)
                    B = ad[key_b].to(svd_device)
                    ba = torch.matmul(B, A)
                    if key_m in ad:
                        m_vec = ad[key_m].to(svd_device).view(-1, 1)
                        W_prime = W0 + scale * ba
                        row_norm = torch.linalg.norm(W_prime, dim=1, keepdim=True).clamp_min(1e-8)
                        W_dora = (m_vec / row_norm) * W_prime
                        delta = W_dora - W0
                    else:
                        delta = scale * ba
                    total_delta = total_delta + delta

                target_mat = total_delta / scale
                d_norm = float(torch.linalg.norm(target_mat).item())
                if d_norm < 1e-10:
                    B_g = torch.zeros((W0.shape[0], svd_export_rank), dtype=torch.float32)
                    A_g = torch.zeros((svd_export_rank, W0.shape[1]), dtype=torch.float32)
                else:
                    U, S, Vh = torch.linalg.svd(target_mat, full_matrices=False)
                    U_r = U[:, :svd_export_rank]
                    S_r = S[:svd_export_rank]
                    Vh_r = Vh[:svd_export_rank, :]
                    sqrt_S = torch.sqrt(S_r)
                    B_g_gpu = U_r * sqrt_S.unsqueeze(0)
                    A_g_gpu = sqrt_S.unsqueeze(1) * Vh_r
                    approx = torch.matmul(B_g_gpu, A_g_gpu)
                    err = float(torch.linalg.norm(target_mat - approx).item()) / max(d_norm, 1e-8)
                    rel_recon_errors.append(err)
                    B_g = B_g_gpu.cpu().contiguous()
                    A_g = A_g_gpu.cpu().contiguous()

                del W0, total_delta, target_mat

                for suffix, mat in (("lora_a", A_g), ("lora_b", B_g)):
                    arr = mat.numpy()
                    rows, cols = arr.shape
                    ne = [cols, rows]
                    gname = f"blk.{blk_idx}.{mod_gguf}.weight.{suffix}"
                    tensors_gguf.append((gname, ne, 0, arr.tobytes()))

    if svd_device.startswith("cuda"):
        torch.cuda.empty_cache()

    kvs = [
        _pack_kv_str("general.type", "adapter"),
        _pack_kv_str("general.architecture", "qwen35"),
        _pack_kv_str("general.name", adapter_label),
        _pack_kv_str("adapter.type", "lora"),
        _pack_kv_f32("adapter.lora.alpha", gguf_alpha),
    ]
    header = bytearray(b"GGUF")
    header += struct.pack("<IQQ", 3, len(tensors_gguf), len(kvs))
    for kv in kvs:
        header += kv

    t_infos = bytearray()
    cur_off = 0
    for gname, ne, gtype, raw in tensors_gguf:
        cur_off = _align32(cur_off)
        t_infos += _pack_str(gname)
        t_infos += struct.pack("<I", len(ne))
        for d in ne:
            t_infos += struct.pack("<Q", int(d))
        t_infos += struct.pack("<IQ", gtype, cur_off)
        cur_off += len(raw)

    meta_blob = header + t_infos
    meta_blob += b"\x00" * (_align32(len(meta_blob)) - len(meta_blob))

    out_gguf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_gguf, "wb") as f:
        f.write(meta_blob)
        written = 0
        for _, _, _, raw in tensors_gguf:
            al = _align32(written)
            if al > written:
                f.write(b"\x00" * (al - written))
                written = al
            f.write(raw)
            written += len(raw)

    mean_err = sum(rel_recon_errors) / max(len(rel_recon_errors), 1)
    return {
        "gguf_path": str(out_gguf),
        "size_bytes": out_gguf.stat().st_size,
        "sha256": sha256_file(out_gguf),
        "tensors_count": len(tensors_gguf),
        "dora_train_rank": dora_rank_r,
        "svd_export_rank": svd_export_rank,
        "svd_mean_rel_error": round(mean_err, 6),
        "svd_fidelity_pct": round((1.0 - mean_err) * 100.0, 4),
    }


def main():
    t_global = time.perf_counter()
    print(">> [PASSO 0] Verificando mecanicamente 100% dos gabaritos físicos (Blender 5.2 + UE5 C++20)...", flush=True)
    checks_gold = verificar_gabaritos_fisicos_pre_treino()
    print(f"   Gabaritos pré-verificados: {checks_gold}", flush=True)

    splits = montar_splits_treino_e_holdout()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    vocab_len_antes = len(tokenizer)

    tok_replay_0150 = tokenizar_pares(splits["replay_0150"], tokenizer, seq_len=2432)
    tok_holdout_0150 = tokenizar_pares(splits["holdout_0150"], tokenizer, seq_len=512)
    tok_train_o1 = tokenizar_pares(splits["train_onda1"], tokenizer, seq_len=2432)
    tok_holdout_o1 = tokenizar_pares(splits["holdout_onda1"], tokenizer, seq_len=512)
    tok_train_o2 = tokenizar_pares(splits["train_onda2"], tokenizer, seq_len=2432)
    tok_holdout_o2 = tokenizar_pares(splits["holdout_onda2"], tokenizer, seq_len=512)

    batches_o1 = mezclar_com_replay_15pct(tok_train_o1, tok_replay_0150, total_batches=52, batch_size=2)
    # Na Onda 2, 15% replay buffer (16 itens em 104) cobre 10 amostras de 0.15.0 + 6 âncoras KEV/Código da Onda 1 + O-LoRA lambda_orth=0.10
    replay_pool_o2 = tok_replay_0150 + tok_replay_0150[:4] + [
        tok_train_o1[0],
        tok_train_o1[1],
        tok_train_o1[4],
        tok_train_o1[7],
        tok_train_o1[11],
        tok_train_o1[13],
    ]
    batches_o2 = mezclar_com_replay_15pct(tok_train_o2, replay_pool_o2, total_batches=52, batch_size=2)

    st_o1_path = PESOS_DIR / "lab-mh-blender-bridge.safetensors"
    st_o2_path = PESOS_DIR / "lab-mh-ue5-kev.safetensors"

    with Win32GpuMutex():
        print(">> [PULSO GPU] Carregando Qwen3.5-4B NF4 com embed_tokens e lm_head 100% congelados...", flush=True)
        bnb_cfg = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        base_model = AutoModelForCausalLM.from_pretrained(
            str(MODEL_DIR),
            quantization_config=bnb_cfg,
            device_map={"": 0},
            dtype=torch.bfloat16,
        )
        base_model.config.use_cache = False
        base_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        base_model.enable_input_require_grads()

        # Verificar congelamento estrito de embed_tokens e lm_head
        emb_w_sha_before = hashlib.sha256(
            base_model.model.embed_tokens.weight.detach().to(torch.float16).cpu().numpy().tobytes()
        ).hexdigest()

        dora_cfg = LoraConfig(
            r=16,
            lora_alpha=32,
            use_dora=True,
            lora_dropout=0.0,
            bias="none",
            task_type="CAUSAL_LM",
            target_modules=TARGET_MODULES,
        )
        peft_model = get_peft_model(base_model, dora_cfg, adapter_name="onda_1")

        # Avaliação inicial pré-Onda 1 (Base)
        eval_base_h0 = avaliar_holdout(peft_model, tok_holdout_0150)
        eval_base_h1 = avaliar_holdout(peft_model, tok_holdout_o1)
        eval_base_h2 = avaliar_holdout(peft_model, tok_holdout_o2)
        print(f"   [BASE] H0_loss={eval_base_h0['loss']:.4f} | H1_loss={eval_base_h1['loss']:.4f} | H2_loss={eval_base_h2['loss']:.4f}", flush=True)

        # ---------------- ONDA 1: DoRA + 15% Replay ----------------
        print(">> [ONDA 1] Treinando `lab-mh-blender-bridge.safetensors` (DoRA r=16, alpha=32 + 15% Replay 0.15.0)...", flush=True)
        peft_model.base_model.set_adapter(["onda_1"])
        params_o1_a, params_o1_b, params_o1_m = [], [], []
        for n, p in peft_model.named_parameters():
            if ".onda_1." in n:
                p.requires_grad = True
                if "lora_A" in n:
                    params_o1_a.append(p)
                elif "lora_B" in n:
                    params_o1_b.append(p)
                else:
                    params_o1_m.append(p)
            else:
                p.requires_grad = False

        opt_o1 = torch.optim.AdamW(
            [
                {"params": params_o1_a, "lr": 1.8e-4, "weight_decay": 0.01},
                {"params": params_o1_b, "lr": 5.5e-4, "weight_decay": 0.01},
                {"params": params_o1_m, "lr": 1.4e-4, "weight_decay": 0.0},
            ]
        )

        t_o1 = time.perf_counter()
        hist_o1 = []
        for step, batch in enumerate(batches_o1, start=1):
            peft_model.train()
            opt_o1.zero_grad(set_to_none=True)
            lv_acc = 0.0
            for bx, by in batch:
                xb = bx.unsqueeze(0).to("cuda:0")
                yb = by.unsqueeze(0).to("cuda:0")
                loss_item = forward_chunked_ce(peft_model, xb, yb, chunk_size=64) / float(len(batch))
                loss_item.backward()
                lv_acc += float(loss_item.detach().cpu().item())
            torch.nn.utils.clip_grad_norm_(params_o1_a + params_o1_b + params_o1_m, max_norm=1.0)
            opt_o1.step()
            hist_o1.append({"step": step, "ce_loss": round(lv_acc, 6)})
            if step in (1, 12, 24, len(batches_o1)):
                print(f"   [Onda 1 | Passo {step:02d}/{len(batches_o1)}] ce_loss={lv_acc:.4f}", flush=True)
        dt_o1 = round(time.perf_counter() - t_o1, 3)

        eval_post_o1_h0 = avaliar_holdout(peft_model, tok_holdout_0150)
        eval_post_o1_h1 = avaliar_holdout(peft_model, tok_holdout_o1)
        eval_post_o1_h2 = avaliar_holdout(peft_model, tok_holdout_o2)
        print(
            f"   [PÓS-ONDA 1] H0_loss={eval_post_o1_h0['loss']:.4f} | H1_loss={eval_post_o1_h1['loss']:.4f} "
            f"(acc={eval_post_o1_h1['token_acc']:.4f}) | H2_loss={eval_post_o1_h2['loss']:.4f}",
            flush=True,
        )

        peft_model.save_pretrained(str(PESOS_DIR / "peft_onda_1"), selected_adapters=["onda_1"])
        sha_st_o1 = salvar_dora_safetensors_oficial(
            peft_model,
            "onda_1",
            st_o1_path,
            {"wave": "1", "name": "lab-mh-blender-bridge", "use_dora": "True", "r": "16", "alpha": "32"},
        )
        a_onda1_frozen = coletar_matrizes_a_congeladas(peft_model, "onda_1")

        # ---------------- ONDA 2: DoRA + O-LoRA Ortogonal (lambda_orth=0.10) + 15% Replay ----------------
        print(">> [ONDA 2] Treinando `lab-mh-ue5-kev.safetensors` em Subespaço Ortogonal O-LoRA (lambda_orth=0.10)...", flush=True)
        peft_model.add_adapter("onda_2", dora_cfg)
        projetar_onda2_no_complemento_ortogonal_inicial(peft_model, a_onda1_frozen, adapter_onda2="onda_2")
        # Ativar AMBAS as ondas simultaneamente para acumulação contínua real!
        peft_model.base_model.set_adapter(["onda_1", "onda_2"])

        params_o2_a, params_o2_b, params_o2_m = [], [], []
        for n, p in peft_model.named_parameters():
            if ".onda_2." in n:
                p.requires_grad = True
                if "lora_A" in n:
                    params_o2_a.append(p)
                elif "lora_B" in n:
                    params_o2_b.append(p)
                else:
                    params_o2_m.append(p)
            else:
                p.requires_grad = False

        orth_init = float(calcular_loss_ortogonal_olora(peft_model, a_onda1_frozen, "onda_2").detach().cpu().item())
        opt_o2 = torch.optim.AdamW(
            [
                {"params": params_o2_a, "lr": 1.6e-4, "weight_decay": 0.01},
                {"params": params_o2_b, "lr": 5.0e-4, "weight_decay": 0.01},
                {"params": params_o2_m, "lr": 1.2e-4, "weight_decay": 0.0},
            ]
        )

        lambda_orth = 0.10
        t_o2 = time.perf_counter()
        hist_o2 = []
        for step, batch in enumerate(batches_o2, start=1):
            peft_model.train()
            opt_o2.zero_grad(set_to_none=True)
            l_ce = 0.0
            for bx, by in batch:
                xb = bx.unsqueeze(0).to("cuda:0")
                yb = by.unsqueeze(0).to("cuda:0")
                loss_item = forward_chunked_ce(peft_model, xb, yb, chunk_size=64) / float(len(batch))
                loss_item.backward()
                l_ce += float(loss_item.detach().cpu().item())
            loss_orth = calcular_loss_ortogonal_olora(peft_model, a_onda1_frozen, "onda_2")
            (lambda_orth * loss_orth).backward()
            torch.nn.utils.clip_grad_norm_(params_o2_a + params_o2_b + params_o2_m, max_norm=1.0)
            opt_o2.step()

            l_or = float(loss_orth.detach().cpu().item())
            l_tot = l_ce + lambda_orth * l_or
            hist_o2.append({"step": step, "total_loss": round(l_tot, 6), "ce_loss": round(l_ce, 6), "orth_frob_sq": round(l_or, 8)})
            if step in (1, 12, 24, len(batches_o2)):
                print(
                    f"   [Onda 2 | Passo {step:02d}/{len(batches_o2)}] total={l_tot:.4f} | ce={l_ce:.4f} | orth_frob_sq={l_or:.6f}",
                    flush=True,
                )
        dt_o2 = round(time.perf_counter() - t_o2, 3)

        orth_final = float(calcular_loss_ortogonal_olora(peft_model, a_onda1_frozen, "onda_2").detach().cpu().item())

        # Prova Matemática de Retenção Pós-Onda 2 com AMBAS as ondas (`["onda_1", "onda_2"]`) ativas!
        eval_post_o2_h0 = avaliar_holdout(peft_model, tok_holdout_0150)
        eval_post_o2_h1 = avaliar_holdout(peft_model, tok_holdout_o1)
        eval_post_o2_h2 = avaliar_holdout(peft_model, tok_holdout_o2)
        print(
            f"   [PÓS-ONDA 2 ACUMULADO] H0_loss={eval_post_o2_h0['loss']:.4f} | "
            f"H1_loss={eval_post_o2_h1['loss']:.4f} (acc={eval_post_o2_h1['token_acc']:.4f}) | "
            f"H2_loss={eval_post_o2_h2['loss']:.4f} (acc={eval_post_o2_h2['token_acc']:.4f})",
            flush=True,
        )

        peft_model.save_pretrained(str(PESOS_DIR / "peft_onda_2"), selected_adapters=["onda_2"])
        sha_st_o2 = salvar_dora_safetensors_oficial(
            peft_model,
            "onda_2",
            st_o2_path,
            {"wave": "2", "name": "lab-mh-ue5-kev", "use_dora": "True", "r": "16", "alpha": "32", "lambda_orth": "0.10"},
        )

        emb_w_sha_after = hashlib.sha256(
            base_model.model.embed_tokens.weight.detach().to(torch.float16).cpu().numpy().tobytes()
        ).hexdigest()
        vocab_frozen_intact = (emb_w_sha_before == emb_w_sha_after) and (len(tokenizer) == vocab_len_antes)
        vram_pico_mib = int(round(torch.cuda.max_memory_allocated() / (1024 * 1024)))

        del a_onda1_frozen
        del opt_o1
        del opt_o2
        del peft_model
        del base_model
        gc.collect()
        torch.cuda.empty_cache()

        print(">> [EXPORT GGUF GPU] Decompondo DoRA exato sobre W_nf4 via `reexportar_dora_nf4_exato_gguf.py`...", flush=True)
    # Executa re-exportação exata NF4 sob Win32GpuMutex após liberar memória de otimizadores
    from reexportar_dora_nf4_exato_gguf import main as _reexport_main
    _reexport_main()
    gguf_o1 = {"gguf_path": str(PESOS_DIR / "lab-mh-blender-bridge.gguf"), "sha256": sha256_file(PESOS_DIR / "lab-mh-blender-bridge.gguf")}
    gguf_o2 = {"gguf_path": str(PESOS_DIR / "lab-mh-ue5-kev.gguf"), "sha256": sha256_file(PESOS_DIR / "lab-mh-ue5-kev.gguf")}
    gguf_acum = {"gguf_path": str(PESOS_DIR / "lab-mh-kev-acumulado-o1-o2.gguf"), "sha256": sha256_file(PESOS_DIR / "lab-mh-kev-acumulado-o1-o2.gguf")}

    # Cálculo transparente das métricas matemáticas de retenção Pós-Onda 2 vs Pré-Onda 2
    # Razão de acurácia de tokens e razão de verossimilhança por token exp(-(L_pos - L_pre))
    ret_h0_prob_pct = round(100.0 * math.exp(eval_post_o1_h0["loss"] - eval_post_o2_h0["loss"]), 3)
    ret_h0_acc_pct = round(100.0 * (eval_post_o2_h0["token_acc"] / max(eval_post_o1_h0["token_acc"], 1e-6)), 3)
    ret_h1_prob_pct = round(100.0 * math.exp(eval_post_o1_h1["loss"] - eval_post_o2_h1["loss"]), 3)
    ret_h1_acc_pct = round(100.0 * (eval_post_o2_h1["token_acc"] / max(eval_post_o1_h1["token_acc"], 1e-6)), 3)
    ganho_h2_pct = round(100.0 * (eval_post_o1_h2["loss"] - eval_post_o2_h2["loss"]) / max(eval_post_o1_h2["loss"], 1e-6), 2)

    relatorio = {
        "schema": "isaque.kev01.treino_dora_olora_2_ondas/1.0",
        "vocabulario_congelado_intacto": vocab_frozen_intact,
        "embed_tokens_sha256_invariante": emb_w_sha_before,
        "arquitetura_adaptador": {
            "use_dora": True,
            "r": 16,
            "lora_alpha": 32,
            "lambda_orth": 0.10,
            "replay_buffer_pct": 15.0,
            "target_modules": TARGET_MODULES,
        },
        "pre_verificacao_mecanica_gabaritos": checks_gold,
        "onda_1_blender_bridge": {
            "safetensors_path": str(st_o1_path),
            "safetensors_bytes": st_o1_path.stat().st_size,
            "safetensors_sha256": sha_st_o1,
            "gguf_export": gguf_o1,
            "tempo_treino_s": dt_o1,
            "passos": len(batches_o1),
            "historico_loss": hist_o1,
        },
        "onda_2_ue5_kev_ortogonal": {
            "safetensors_path": str(st_o2_path),
            "safetensors_bytes": st_o2_path.stat().st_size,
            "safetensors_sha256": sha_st_o2,
            "gguf_export": gguf_o2,
            "gguf_acumulado_o1_o2": gguf_acum,
            "tempo_treino_s": dt_o2,
            "passos": len(batches_o2),
            "orth_frob_sq_inicial": round(orth_init, 8),
            "orth_frob_sq_final": round(orth_final, 8),
            "historico_loss": hist_o2,
        },
        "prova_matematica_retencao_anti_esquecimento": {
            "holdout_0150_motor_humano": {
                "base": eval_base_h0,
                "pos_onda_1": eval_post_o1_h0,
                "pos_onda_2_acumulado": eval_post_o2_h0,
                "retencao_verossimilhanca_pct": ret_h0_prob_pct,
                "retencao_token_acc_pct": ret_h0_acc_pct,
            },
            "holdout_onda_1_blender_kev": {
                "base": eval_base_h1,
                "pos_onda_1": eval_post_o1_h1,
                "pos_onda_2_acumulado": eval_post_o2_h1,
                "retencao_verossimilhanca_pct": ret_h1_prob_pct,
                "retencao_token_acc_pct": ret_h1_acc_pct,
            },
            "holdout_onda_2_ue5_kev": {
                "base": eval_base_h2,
                "pre_onda_2": eval_post_o1_h2,
                "pos_onda_2_acumulado": eval_post_o2_h2,
                "queda_eval_loss_pct": ganho_h2_pct,
            },
            "meta_99pct_atingida": (
                min(ret_h0_acc_pct, ret_h1_acc_pct) >= 99.0
                and min(ret_h0_prob_pct, ret_h1_prob_pct) >= 99.0
            ),
        },
        "telemetria_gpu": {
            "vram_pico_mib": vram_pico_mib,
            "tempo_total_ciclo_s": round(time.perf_counter() - t_global, 3),
        },
    }

    out_json = PROVA_DIR / "prova_treino_dora_olora_kev01.json"
    out_json.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f">> [CONCLUIDO] Prova salva em {out_json}", flush=True)


if __name__ == "__main__":
    main()
