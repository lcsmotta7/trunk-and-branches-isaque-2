#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seção 6 e Seção 7 — Arena Tripla de Fogo Real (`3 Desafios Extremos` x `3 Competidores` Auditados pelo `Juiz 35B-A3B`):
  - Competidor A: Baseline Campeão 0.15.0 (`Isaque 2.0` atual em produção: `mh-01-vicop` + `mh-02-condutor`, JEV/AtomSD)
  - Competidor B: KEV-1.0 + Vetor Triplo Zero-Shot (`arena-kev-triplo.mmap` + `kev_v1.gbnf` `/no_think`, sem pesos DoRA/O-LoRA)
  - Competidor C: KEV-1.0 + Vetor Triplo + DoRA/O-LoRA Pós-Treino (Ondas 1 e 2 acumuladas + `arena-kev-triplo.mmap` + `kev_v1.gbnf` `/no_think`)

Cada desafio parte de especificação técnica/multimodal longa (`>= 6.000` tokens Qwen3.5 reais), emite o pacote
compacto do competidor, sintetiza o código final A PARTIR APENAS DO PACOTE EMITIDO, submete aos Verificadores Físicos
Determinísticos (`Blender 5.2 Headless BMesh` e/ou `UE5 C++20 Tree-Sitter + Clang++ 22`) e por fim passa pela
Avaliação Cega Contraditória do `Juiz Qwen3.5-35B-A3B` (`autor_session != revisor_session`).
"""

import ctypes
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

LAB_DIR = Path(r"D:\Beyond Adonai\Isaque\laboratorio-kev-01")
PROVA_DIR = Path(r"D:\Beyond Adonai\Abraao-Windows\Dados\Prova-KEV-01")
DESAFIOS_DIR = LAB_DIR / "desafios"
SAIDAS_DIR = DESAFIOS_DIR / "saidas_arena"
TEMP_DIR = LAB_DIR / "temp" / "arena_tripla"
for _d in (PROVA_DIR, DESAFIOS_DIR, SAIDAS_DIR, TEMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

os.environ["TEMP"] = str(TEMP_DIR)
os.environ["TMP"] = str(TEMP_DIR)

sys.path.insert(0, str(LAB_DIR / "scripts"))
sys.path.insert(0, str(LAB_DIR / "verificadores"))
from construir_arena_kev_triplo import ConsultorArenaKevTriplo  # noqa: E402
from verificador_fisico_blender import verificar_script_blender  # noqa: E402

from tokenizers import Tokenizer  # noqa: E402

RAIZ_CASA = Path(r"D:\Beyond Adonai\Abraao-Windows")
RAIZ_ISAQUE = Path(r"D:\Beyond Adonai\Isaque")
LLAMA_COMP_EXE = RAIZ_ISAQUE / "bin" / "llama-completion.exe"
MODELO_4B_GGUF = RAIZ_ISAQUE / "modelos" / "qwen3-4b" / "isaque-qwen3.5-4b-q4-k-m-rust-v3-01a1273b.gguf"
MODELO_35B_GGUF = RAIZ_ISAQUE / "modelos" / "qwen3.5-35b-a3b" / "Qwen3.5-35B-A3B-Q4_K_M.gguf"
TOKENIZER_PATH = RAIZ_ISAQUE / "modelos" / "qwen3-4b" / "tokenizer.json"

LORA_0150_VICOP_REL = "modelos/colunas_corticais/mh-01-vicop-lora.gguf"
LORA_0150_CONDUTOR_REL = "modelos/colunas_corticais/mh-02-condutor-lora.gguf"

LORA_KEV_O1_REL = "laboratorio-kev-01/pesos/lab-mh-blender-bridge.gguf"
LORA_KEV_O2_REL = "laboratorio-kev-01/pesos/lab-mh-ue5-kev.gguf"
LORA_KEV_ACUM_REL = "laboratorio-kev-01/pesos/lab-mh-kev-acumulado-o1-o2.gguf"

KEV_GBNF = LAB_DIR / "grammars" / "kev_v1.gbnf"
UE5_VERIFIER_EXE = LAB_DIR / "bin" / "verificador_fisico_ue5_cpp.exe"

AUTOR_SESSION = "ce5dabcc-19e6-405b-b251-9c8ceacf1937"
REVISOR_SESSION = "juiz-35b-contraditorio-kev01-9f4a2e11"


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


def ler_vram_usada_mib() -> int:
    try:
        p = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        return int(p.stdout.strip().splitlines()[0].strip())
    except Exception:
        return 0


def contar_cuda_compute_ativos() -> int:
    p = subprocess.run(
        ["nvidia-smi", "-q", "-d", "PIDS"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    txt = p.stdout or ""
    pure_c = re.findall(r"^\s*Type\s*:\s*C\s*$", txt, flags=re.M)
    res_isaque = re.findall(r"(llama-completion|llama-mtmd-cli|isaque-)", txt, flags=re.I)
    return len(pure_c) + len(res_isaque)


def qwen35_no_think_prompt(sys_msg: str, usr_msg: str) -> str:
    return (
        f"<|im_start|>system\n{sys_msg}<|im_end|>\n"
        f"<|im_start|>user\n{usr_msg}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def rodar_llama_sob_pulso(
    prompt_text: str,
    model_gguf: Path,
    max_tokens: int = 320,
    temp: float = 0.1,
    ctx_size: int = 8192,
    lora_scaled: str | None = None,
    grammar_file: Path | None = None,
    reasoning_off: bool = False,
    cpu_moe: bool = False,
    repeat_penalty: float = 1.10,
    repeat_last_n: int = 64,
    timeout_s: int = 180,
) -> dict:
    pfile = TEMP_DIR / f"prompt_{int(time.time()*1000)}_{random.randint(100,999)}.txt"
    pfile.write_text(prompt_text, encoding="utf-8")

    cmd = [
        str(LLAMA_COMP_EXE),
        "-m", str(model_gguf),
        "-ngl", "99",
        "-c", str(ctx_size),
        "-n", str(max_tokens),
        "-s", "42",
        "--temp", str(temp),
        "--repeat-penalty", str(repeat_penalty),
        "--repeat-last-n", str(repeat_last_n),
        "--no-display-prompt",
        "-no-cnv",
        "-f", str(pfile),
    ]
    if cpu_moe:
        cmd.extend(["--cpu-moe", "-ctk", "q8_0", "-ctv", "q8_0", "-b", "512", "-ub", "512"])
    elif ctx_size >= 8192:
        cmd.extend(["-ctk", "q8_0", "-ctv", "q8_0"])
    if reasoning_off:
        cmd.extend(["--reasoning", "off", "--reasoning-budget", "0"])
    if lora_scaled:
        cmd.extend(["--lora-scaled", lora_scaled])
    if grammar_file:
        cmd.extend(["--grammar-file", str(grammar_file)])

    peak_vram = [ler_vram_usada_mib()]
    stop_flag = [False]

    def _poll_vram():
        while not stop_flag[0]:
            v = ler_vram_usada_mib()
            if v > peak_vram[0]:
                peak_vram[0] = v
            time.sleep(0.20)

    t0 = time.perf_counter()
    with Win32GpuMutex():
        th = threading.Thread(target=_poll_vram, daemon=True)
        th.start()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(RAIZ_ISAQUE),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
            )
        finally:
            stop_flag[0] = True
            th.join(timeout=1.0)
    dt = round(time.perf_counter() - t0, 3)
    try:
        pfile.unlink(missing_ok=True)
    except Exception:
        pass

    out = (proc.stdout or "").replace("[end of text]", "").strip()
    return {
        "ok": proc.returncode == 0 and len(out) > 10,
        "returncode": proc.returncode,
        "texto": out,
        "stderr_tail": (proc.stderr or "")[-400:],
        "latencia_s": dt,
        "vram_pico_mib": peak_vram[0],
    }


def construir_especificacoes_6000_tokens(tok: Tokenizer) -> list[dict]:
    """
    Constrói e grava em disco os 3 dossiês técnicos longos (`>= 6.000` tokens Qwen3.5 reais cada)
    combinando especificações paramétricas, transcrições de tutoriais técnicos e regras de engenharia.
    """
    # Carregar trechos reais do acervo Motor Humano para compor contexto técnico denso e realista
    acervo_mh = []
    for p in sorted((RAIZ_CASA / "Conhecimento" / "Motor humano").rglob("*.md"))[:25]:
        t = p.read_text(encoding="utf-8", errors="ignore").strip()
        if len(t) > 120:
            acervo_mh.append(f"[ACERVO MOTOR HUMANO :: {p.name}]\n{t[:1500]}")
    bloco_acervo = "\n\n".join(acervo_mh)

    def expandir_ate_min_tokens(nucleo: str, apendice_tecnico: str, min_toks: int = 6250) -> tuple[str, int]:
        corpo_ref = apendice_tecnico
        sec_idx = 1
        while len(tok.encode(corpo_ref + "\n\n" + nucleo).ids) < min_toks:
            fatia = bloco_acervo[(sec_idx * 900) % max(len(bloco_acervo) - 1800, 1) : ((sec_idx * 900) % max(len(bloco_acervo) - 1800, 1)) + 1800]
            corpo_ref += (
                f"\n\n--- TRANSCRIÇÃO TÉCNICA E REFERÊNCIA DE DOMÍNIO MULTIMODAL #{sec_idx:02d} ---\n"
                f"{apendice_tecnico[:1200]}\n{fatia}"
            )
            sec_idx += 1
        doc = corpo_ref + "\n\n=== ESPECIFICAÇÃO MANDATÓRIA DO ALVO ATUAL (PARÂMETROS OFICIAIS) ===\n" + nucleo
        n_toks = len(tok.encode(doc).ids)
        return doc, n_toks

    # --- DESAFIO 01 ---
    d1_core = (
        "ESPECIFICAÇÃO OFICIAL — DESAFIO-01 (BLENDER 5.2 HEADLESS -> ASSET MODULAR SCI-FI/INDUSTRIAL PRONTO PARA UE5)\n"
        "Objetivo: Construir via script Python `bpy`/`bmesh` em modo estritamente `--background --factory-startup` "
        "(zero viewport 3D aberta) o módulo arquitetônico industrial sci-fi `Modulo_01` pronto para Unreal Engine 5.\n"
        "Requisitos Físicos Inegociáveis:\n"
        "1. Sistema de Unidades: `METRIC`, `scale_length = 1.0`, orientação `Z-up`.\n"
        "2. Dimensões Exatas da AABB (`@SPACE`): Largura `X = 4.0m` (`[-2.0, +2.0]`), Espessura `Y = 0.4m` (`[-0.2, +0.2]`), "
        "Altura `Z = 3.0m` (`[0.0, +3.0]`), tolerância máxima `±2%`.\n"
        "3. Pivô e Base: Origem do objeto `Modulo_01` cravada em `(0.0, 0.0, 0.0)` com `Z_min = 0.0` perfeitamente alinhado ao piso.\n"
        "4. Geometria e Normais: Detalhe sci-fi industrial recuado (`bmesh.ops.inset_individual` nas faces frontais/traseiras mantendo "
        "100% 2-manifold fechado, `non_manifold_edges == 0`, `zero_area_faces == 0`, `recalc_face_normals` com volume assinado > 0).\n"
        "5. Mapeamento UV Determinístico: Camada UV ativa sem overlap crítico calculada em `bmesh` (`bm.loops.layers.uv.verify()`) "
        "para nunca falhar por `bpy.ops.uv.smart_project.poll()` sem janela 3D.\n"
        "6. Colisor Físico Unreal: Objeto separado `UCX_Modulo_01` gerado por `bmesh.ops.convex_hull` cobrindo `[4.0, 0.4, 3.0]` "
        "com `Z_min = 0.0` e `100% manifold` (`non_manifold_edges == 0`).\n"
        "7. Exportação Real em Disco: Exportar `Modulo_01.glb` (`export_scene.gltf`) e `Modulo_01.fbx` (`export_scene.fbx`) "
        "no diretório `os.environ.get('KEV_EXPORT_DIR', '.')`."
    )
    d1_apendice = (
        "Notas de Tutorial Headless Blender 5.2 LTS & Pipeline FBX/glTF UE5:\n"
        "- Em execução `--background`, `bpy.context.area` e `bpy.context.region` são `None`. Operadores `bpy.ops.mesh.*` ou "
        "`bpy.ops.uv.*` que exigem contexto `VIEW_3D` disparam `RuntimeError: Operator poll() failed, context is incorrect`.\n"
        "- A construção geométrica industrial determinística deve instanciar `bm = bmesh.new()`, escalar vértices do cubo unitário "
        "para `[-SX/2, SX/2] x [-SY/2, SY/2] x [0, SZ]`, aplicar `bmesh.ops.inset_individual` com profundidade negativa controlada, "
        "recalcular normais externas com `bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])` e empacotar ilhas UV em grade unitária `[0,1]^2`.\n"
        "- Para o colisor Chaos/PhysX da Unreal Engine 5, a nomenclatura `UCX_<MeshName>` exige casca estritamente convexa e fechada."
    )
    d1_full, d1_toks = expandir_ate_min_tokens(d1_core, d1_apendice, 6250)
    (DESAFIOS_DIR / "desafio_01_blender_modular_6k.txt").write_text(d1_full, encoding="utf-8")

    # --- DESAFIO 02 ---
    d2_core = (
        "ESPECIFICAÇÃO OFICIAL — DESAFIO-02 (SISTEMA GAMEPLAY C++ UE5 COMPLETO SEM VIOLAÇÃO UHT/GC)\n"
        "Objetivo: Implementar o par completo `InteractionInventorySystem.h` e `InteractionInventorySystem.cpp` em C++20 para Unreal Engine 5.\n"
        "Requisitos Arquiteturais e Invariantes UHT/GC Obrigatórias:\n"
        "1. Header Guard e Ordem UHT: `#pragma once` no topo e `#include \"InteractionInventorySystem.generated.h\"` ESTRITAMENTE como o ÚLTIMO `#include` do `.h`.\n"
        "2. Classes e Structs Refletidas:\n"
        "   - `USTRUCT(BlueprintType) struct FInventorySlotEntry` (`GENERATED_BODY()`, `FName ItemId`, `int32 Quantity`);\n"
        "   - `UCLASS(ClassGroup=(Custom), meta=(BlueprintSpawnableComponent)) class UInteractionInventoryComponent : public UActorComponent` (`GENERATED_BODY()`);\n"
        "   - `UCLASS() class AInteractableWorldActor : public AActor` (`GENERATED_BODY()`).\n"
        "3. Prevenção Absoluta de Dangling Pointer sob Garbage Collector (`GC`):\n"
        "   - ZERO ponteiros crus `UObject*`/`AActor*`/`UStaticMeshComponent*` como membros de classe sem `UPROPERTY(...)`.\n"
        "   - Usar `UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category=\"Components\") TObjectPtr<UStaticMeshComponent> DisplayMesh;` "
        "e `TObjectPtr<USphereComponent> InteractionSphere;`.\n"
        "   - ZERO uso de `new` bruto em classes `UObject` (instanciar com `CreateDefaultSubobject<T>` no construtor).\n"
        "4. Delegados e Blueprint API:\n"
        "   - `DECLARE_DYNAMIC_MULTICAST_DELEGATE_TwoParams` para atualização de inventário e evento de interação (`UPROPERTY(BlueprintAssignable)`);\n"
        "   - `UFUNCTION(BlueprintCallable)` para `AddItem`, `GetItemQuantity`, `TryInteractWithActor` (validando distância `<= 250.0cm`), `CanInteract` e `ExecuteInteraction`.\n"
        "5. Ciclo de Vida Sem Tick Inútil:\n"
        "   - `PrimaryComponentTick.bCanEverTick = false;` e `PrimaryActorTick.bCanEverTick = false;`;\n"
        "   - Cooldown assíncrono (`1.5s`) gerenciado via `FTimerHandle` e `GetWorldTimerManager().SetTimer(...)` com limpeza obrigatória `ClearTimer` no `EndPlay`."
    )
    d2_apendice = (
        "Documentação Técnica do Sistema de Reflexão Unreal Header Tool (UHT) e Coleta de Lixo UObject:\n"
        "- O UHT pré-processa cabeçalhos `.h` antes do compilador C++20 e exige que `<HeaderName>.generated.h` seja o último `#include` "
        "para injetar as macros `CURRENT_FILE_ID_<Line>_GENERATED_BODY` com os typedefs `Super` e `ThisClass`.\n"
        "- Qualquer membro ponteiro para derivado de `UObject` não marcado com `UPROPERTY()` permanece invisível ao grafo de alcançabilidade "
        "do Garbage Collector da Unreal, podendo ser coletado prematuramente ou deixar ponteiro pendente fatal.\n"
        "- Componentes de ator devem desabilitar `bCanEverTick` quando operam por eventos ou temporizadores `FTimerManager`."
    )
    d2_full, d2_toks = expandir_ate_min_tokens(d2_core, d2_apendice, 6250)
    (DESAFIOS_DIR / "desafio_02_ue5_cpp_gameplay_6k.txt").write_text(d2_full, encoding="utf-8")

    # --- DESAFIO 03 ---
    d3_core = (
        "ESPECIFICAÇÃO OFICIAL — DESAFIO-03 (VARIAÇÃO EXTREMA CRUZADA: PONTE COMPLETA BLENDER 5.2 -> C++ UE5 DATA-DRIVEN)\n"
        "Objetivo: Gerar em cadeia coordenada (`BRIDGE_3D`) TANTO o pacote de 3 variações paramétricas no Blender 5.2 headless "
        "QUANTO a arquitetura C++20 Data-Driven correspondente na Unreal Engine 5 (`ModularBridgeAssetActor.h` e `.cpp`).\n"
        "Parte A — Blender 5.2 Headless (`bmesh` puro):\n"
        "1. Escala `METRIC` (`scale_length = 1.0`, `Z-up`), gerando 3 variações paramétricas fechadas (`2-manifold`, UV válida):\n"
        "   - `Var_01_Standard`: `1.00m x 0.16m x 0.28m` posicionada na origem `(0.0, 0.0, 0.0)` com `Z_min = 0.0`;\n"
        "   - `Var_02_Compact`: `0.80m x 0.16m x 0.28m` posicionada em `(0.0, 0.65, 0.0)` com `Z_min = 0.0`;\n"
        "   - `Var_03_Heavy`: `1.25m x 0.18m x 0.32m` posicionada em `(0.0, -0.65, 0.0)` com `Z_min = 0.0`.\n"
        "2. Sockets e Colisor Físico: Criar objetos `EMPTY` `Socket_Muzzle` e `Socket_Grip` parentados à peça primária, "
        "além do colisor convexo `UCX_Var_01_Standard_01` (`100% manifold`), exportando `.glb` e `.fbx` reais.\n"
        "Parte B — Unreal Engine 5 C++20 Data-Driven (`ModularBridgeAssetActor.h` / `.cpp`):\n"
        "1. Definir `USTRUCT(BlueprintType) struct FModularBridgeVariantRow : public FTableRowBase` com `TObjectPtr<UStaticMesh> VariantMesh`, "
        "`FVector ExpectedDimensionsMeters{1.00, 0.16, 0.28}`, `FName MuzzleSocketName = FName(\"Socket_Muzzle\")` e `GripSocketName = FName(\"Socket_Grip\")`.\n"
        "2. Definir `UCLASS() class AModularBridgeAssetActor : public AActor` com `TObjectPtr<UStaticMeshComponent>` protegidos por `UPROPERTY`, "
        "`PrimaryActorTick.bCanEverTick = false`, validação cruzada de escala `ExpectedMeters * 100.0` (`1.0m Blender == 100.0cm UE5`, tolerância `±2%`), "
        "verificação `DoesSocketExist` para `Socket_Muzzle` e `Socket_Grip` e acoplamento via `FAttachmentTransformRules::SnapToTargetNotIncludingScale`."
    )
    d3_apendice = (
        "Regras de Engenharia de Ponte Cruzada DCC (Blender 5.2 Metros) <-> Runtime (Unreal Engine 5 Centímetros):\n"
        "- O erro mais frequente em pipelines 3D industriais é comparar dimensões em metros diretamente com `GetBoundingBox().GetSize()` "
        "da Unreal Engine (que opera em centímetros: `1.0m = 100.0cm`), causando rejeição de escala por fator `100x`.\n"
        "- Acoplamentos modulares em sockets (`Socket_Muzzle`, `Socket_Grip`) devem usar `SnapToTargetNotIncludingScale` para evitar "
        "herança acidental de escala não uniforme do socket exportado via FBX/glTF."
    )
    d3_full, d3_toks = expandir_ate_min_tokens(d3_core, d3_apendice, 6250)
    (DESAFIOS_DIR / "desafio_03_bridge_3d_cruzado_6k.txt").write_text(d3_full, encoding="utf-8")

    return [
        {
            "id": "DESAFIO-01",
            "domain": "BLENDER_BPY",
            "target": "Modulo_01",
            "titulo": "Blender 5.2 Headless -> Asset Modular Sci-Fi/Industrial Pronto para UE5 (4.0m x 0.4m x 3.0m)",
            "spec_completa": d1_full,
            "spec_resumo_prompt": d1_core,
            "tokens_entrada_bruta": d1_toks,
            "queries_arena": (
                "Blender 5.2 METRIC 1.0 modular sci-fi panel 4.0m x 0.4m x 3.0m pivot (0,0,0) Z_min=0 UCX_Modulo_01 manifold GLB FBX",
                "bmesh create_cube inset_individual uv_layer convex_hull export_scene.gltf",
                "bpy.ops.uv.smart_project poll failed VIEW_3D non_manifold_edges scale_length",
            ),
            "blender_spec": {
                "expected_bbox_m": [4.0, 0.4, 3.0],
                "min_visual_meshes": 1,
                "primary_prefix": "",
                "required_sockets": [],
            },
            "ue5_stem": None,
        },
        {
            "id": "DESAFIO-02",
            "domain": "UE5_CPP",
            "target": "InteractionInventorySystem",
            "titulo": "Sistema Gameplay C++ UE5 Completo sem Violação UHT/GC (UInteractionInventoryComponent + AInteractableWorldActor)",
            "spec_completa": d2_full,
            "spec_resumo_prompt": d2_core,
            "tokens_entrada_bruta": d2_toks,
            "queries_arena": (
                "UE5 interaction distance 250cm Actor Component inventory cooldown 1.5s timer without Tick",
                "UCLASS USTRUCT GENERATED_BODY UInteractionInventoryComponent AInteractableWorldActor TObjectPtr UPROPERTY UFUNCTION DECLARE_DYNAMIC_MULTICAST_DELEGATE FTimerHandle",
                "generated.h last include raw UObject pointer dangling GC crash new UObject wasteful bCanEverTick",
            ),
            "blender_spec": None,
            "ue5_stem": "InteractionInventorySystem",
        },
        {
            "id": "DESAFIO-03",
            "domain": "BRIDGE_3D",
            "target": "ModularBridgeAssetActor",
            "titulo": "Variação Extrema Cruzada: Ponte Completa Blender 5.2 (3 Variações + Sockets) -> C++ UE5 Data-Driven (1m -> 100cm)",
            "spec_completa": d3_full,
            "spec_resumo_prompt": d3_core,
            "tokens_entrada_bruta": d3_toks,
            "queries_arena": (
                "3 parametric mesh variations 1.0m 0.8m 1.25m Blender METRIC to 100cm UE5 Socket_Muzzle Socket_Grip UCX_ Z_min=0",
                "bmesh Socket_Muzzle Socket_Grip FTableRowBase AModularBridgeAssetActor DoesSocketExist AttachToComponent",
                "1m to 100cm scale mismatch SnapToTargetIncludingScale socket name mismatch generated.h last include",
            ),
            "blender_spec": {
                "expected_bbox_m": [1.0, 0.16, 0.28],
                "min_visual_meshes": 3,
                "primary_prefix": "Var_01",
                "required_sockets": ["Socket_Muzzle", "Socket_Grip"],
            },
            "ue5_stem": "ModularBridgeAssetActor",
        },
    ]


def extrair_bloco_codigo(raw_txt: str, lang_hint: str = "") -> str:
    txt = raw_txt.replace("[end of text]", "")
    txt = re.sub(r"<think>.*?</think>", "", txt, flags=re.S).replace("<think>", "").replace("</think>", "").strip()
    m = re.search(r"```(?:python|cpp|c\+\+|h|hpp|c)?\s*\n(.*?)```", txt, flags=re.S | re.I)
    if m:
        return m.group(1).replace("[end of text]", "").strip()
    # Caso tenha começado com ``` sem fechar ou texto puro de código
    txt = re.sub(r"^```[a-zA-Z0-9_+]*\s*\n?", "", txt)
    txt = re.sub(r"\n?```\s*$", "", txt)
    return txt.strip()


def emitir_pacote_competidor(comp_id: str, desafio: dict, consultor: ConsultorArenaKevTriplo) -> dict:
    """
    Estágio 1: Emissão do Pacote Condutor comprimindo integralmente o dossiê de `>= 6.000` tokens:
      - A: Baseline 0.15.0 (`mh-01-vicop:0.28,mh-02-condutor:0.22`, formato 4 blocos JEV/AtomSD)
      - B: KEV-1.0 + Vetor Triplo Zero-Shot (`arena-kev-triplo.mmap` + `kev_v1.gbnf` `/no_think`, sem DoRA/O-LoRA)
      - C: KEV-1.0 + Vetor Triplo + DoRA/O-LoRA Pós-Treino (`arena-kev-triplo.mmap` + `kev_v1.gbnf` `/no_think` + Ondas 1&2 acumuladas)
    """
    trecho_dossie = desafio["spec_completa"]

    if comp_id == "A":
        sys_a = (
            "Você opera com as Colunas Corticais MH-01 (Extrator Perceptual VICOP) e MH-02 (Condutor Compacto YHWH) "
            "do Isaque 2.0 Soberano (0.15.0). Comprima a especificação longa abaixo nos 4 blocos:\n"
            "[VICOP-SPEC]\n[VETOR-ANCORA-EN]\n[PARAMETROS-EXATOS]\n[NAO-FAZER]"
        )
        usr_a = (
            f"TAREFA: {desafio['titulo']}\n"
            f"Comprima fielmente nos 4 blocos oficiais todos os parâmetros exatos, classes, structs, objetos, sockets e restrições da especificação oficial no final do dossiê abaixo:\n\n"
            f"{trecho_dossie}"
        )
        prompt = qwen35_no_think_prompt(sys_a, usr_a)
        lora_str = f"{LORA_0150_VICOP_REL}:0.28,{LORA_0150_CONDUTOR_REL}:0.22"
        res = rodar_llama_sob_pulso(
            prompt_text=prompt,
            model_gguf=MODELO_4B_GGUF,
            max_tokens=560,
            temp=0.15,
            ctx_size=10240,
            lora_scaled=lora_str,
            grammar_file=None,
            repeat_penalty=1.10,
        )
        res["mmap_lookup_ms"] = None
        res["arena_top_hit"] = None
        return res

    # Competidores B e C consultam a Arena Vetorial Tripla 384d em `< 1 ms`
    gq, aq, eq = desafio["queries_arena"]
    qg, qa, qe = consultor.codificar_query_tripla(gq, aq, eq)
    hits, mmap_ms = consultor.buscar_vetores_mmap(qg, qa, qe, desafio["domain"], top_k=12)
    canon_hits = [h for h in hits if re.match(r"^KEV-(?:BLENDER|UE5|BRIDGE)-0[1-9]$", h["id"])]
    top_hit = canon_hits[0] if canon_hits else hits[0]

    if comp_id == "B":
        # Zero-Shot sobre Qwen3.5-4B base + Arena Tripla + GBNF /no_think (sem pesos DoRA/O-LoRA!)
        sys_b = (
            "Emita estritamente um pacote determinístico e conciso KEV/1.0 seguindo a gramática:\n"
            "KEV/1.0 domain=<DOM> target=<ALVO>\n"
            "@SPACE{k1=v1;k2=v2}\n"
            "@GRAPH[\n  S1:MOD.op(p1=v1) -> S2\n]\n"
            "@GUARD[\n  !RULE-01: texto objetivo\n]\n"
            "@VERIFY[\n  ?campo==valor\n]\n"
            f"Guarda anti-erro recuperada da Arena Tripla ({top_hit['id']}, score={top_hit['score_fused']}): {top_hit['err_guard'][:280]}"
        )
        usr_b = (
            f"Emita estritamente o pacote KEV/1.0 conciso (domain={desafio['domain']}, target={desafio['target']}, "
            f"4 a 5 passos S1..S5 em @GRAPH, 3 a 4 regras em @GUARD e 4 asserts em @VERIFY) "
            f"preservando literalmente todos os nomes de classes, structs, objetos, sockets e dimensões da especificação oficial no final do dossiê abaixo:\n\n"
            f"{trecho_dossie}"
        )
        prompt = qwen35_no_think_prompt(sys_b, usr_b)
        res = rodar_llama_sob_pulso(
            prompt_text=prompt,
            model_gguf=MODELO_4B_GGUF,
            max_tokens=560,
            temp=0.10,
            ctx_size=10240,
            lora_scaled=None,
            grammar_file=KEV_GBNF,
            repeat_penalty=1.10,
        )
        res["mmap_lookup_ms"] = mmap_ms
        res["arena_top_hit"] = top_hit
        return res

    # Competidor C: KEV-1.0 + Vetor Triplo + Colunas DoRA/O-LoRA Pós-Treino (Ondas 1 e 2 ortogonais acumuladas)
    sys_c = (
        "Você é o Motor Humano KEV-1.0 do Isaque 2.0 Soberano. "
        "Opere sem bloco de pensamento prolixo e emita pacotes KEV/1.0 determinísticos ou código mecânico 100% verificado."
    )
    usr_c = (
        f"Emita estritamente o pacote KEV/1.0 conciso (domain={desafio['domain']}, target={desafio['target']}) "
        f"comprimindo fielmente todos os invariantes físicos, nomes exatos das classes UCLASS/USTRUCT/meshes/sockets e dimensões da especificação oficial abaixo "
        f"(Guarda V_err Arena Tripla: {top_hit['err_guard'][:180]}):\n"
        f"{trecho_dossie}"
    )
    prompt_c = qwen35_no_think_prompt(sys_c, usr_c)
    lora_c = f"{LORA_KEV_ACUM_REL}:1.00"
    res_c = rodar_llama_sob_pulso(
        prompt_text=prompt_c,
        model_gguf=MODELO_4B_GGUF,
        max_tokens=560,
        temp=0.0,
        ctx_size=10240,
        lora_scaled=lora_c,
        grammar_file=KEV_GBNF,
        repeat_penalty=1.10,
    )
    res_c["mmap_lookup_ms"] = mmap_ms
    res_c["arena_top_hit"] = top_hit
    return res_c


def hidratar_ast_guardas_do_pacote_kev(
    pacote_emitido: str,
    primary_domain: str,
    consultor: ConsultorArenaKevTriplo,
    extra_domain: str | None = None,
    include_ast: bool = True,
) -> str:
    """
    Recupera em `< 0,1 ms` a partir ESTRITAMENTE do pacote `KEV/1.0` emitido (`@SPACE`, `@GRAPH`, `@GUARD`)
    as assinaturas AST canônicas (`V_ast`) e guardas determinísticas de Negative Knowledge (`V_err`)
    de `arena-kev-triplo.mmap`, filtrando apenas padrões canônicos (`KEV-BLENDER/UE5/BRIDGE-01..09`).
    """
    m_sp = re.search(r"@SPACE\{([^}]*)\}", pacote_emitido)
    m_gr = re.search(r"@GRAPH\[(.*?)\]", pacote_emitido, re.S)
    m_gu = re.search(r"@GUARD\[(.*?)\]", pacote_emitido, re.S)
    s_txt = m_sp.group(1) if m_sp else pacote_emitido[:240]
    g_txt = m_gr.group(1) if m_gr else pacote_emitido[:240]
    u_txt = m_gu.group(1) if m_gu else pacote_emitido[:240]

    qg, qa, qe = consultor.codificar_query_tripla(s_txt, g_txt, u_txt)
    hits, _ = consultor.buscar_vetores_mmap(qg, qa, qe, primary_domain, top_k=24)
    hits = [
        h for h in hits
        if h["domain"] == primary_domain and re.match(r"^KEV-(?:BLENDER|UE5|BRIDGE)-0[1-9]$", h["id"])
    ]
    if extra_domain:
        hits_extra, _ = consultor.buscar_vetores_mmap(qg, qa, qe, extra_domain, top_k=16)
        hits_extra = [
            h for h in hits_extra
            if h["domain"] == extra_domain and re.match(r"^KEV-(?:BLENDER|UE5|BRIDGE)-0[1-9]$", h["id"])
        ]
        hits = hits[:2] + hits_extra[:1]

    blocos = []
    seen_ids = set()
    for h in hits[:3]:
        if h["id"] in seen_ids:
            continue
        seen_ids.add(h["id"])
        ast_snip = h.get("code_ast", "").strip()
        err_clean = h.get("err_guard", "").strip()
        if include_ast:
            blocos.append(
                f"[{h['id']} | score={h['score_fused']}]\n"
                f"  V_AST_CANON:\n{ast_snip[:2900]}\n"
                f"  V_ERR_GUARD: {err_clean[:680]}"
            )
        else:
            blocos.append(f"- [{h['id']}] GUARDA_ANTI_ERRO: {err_clean[:680]}")
    return "\n".join(blocos)


def sintetizar_e_verificar_fisicamente(
    comp_id: str,
    desafio: dict,
    pacote_emitido: str,
    consultor: ConsultorArenaKevTriplo | None = None,
) -> dict:
    """
    Estágio 2: O Executor recebe ESTRITAMENTE o pacote emitido pelo competidor (`pacote_emitido`)
    sem acesso ao dossiê original de 6.000 tokens, gera os artefatos reais (`.py` e/ou `.h` + `.cpp`)
    e submete imediatamente aos Verificadores Físicos Determinísticos no Loop (`BlenderLLM arXiv:2412.14203`,
    até `max_tentativas = 3` simétricas para A, B e C, registrando `Pass@1` e `Pass@Loop`).
    """
    out_sub = SAIDAS_DIR / f"{desafio['id']}_{comp_id}"
    out_sub.mkdir(parents=True, exist_ok=True)

    if comp_id == "A":
        exec_lora_py = f"{LORA_0150_VICOP_REL}:0.28,{LORA_0150_CONDUTOR_REL}:0.22"
        exec_lora_cpp = exec_lora_py
        exec_temp = 0.05
        exec_rp = 1.05
        sys_exec = (
            "Você opera com as Colunas Corticais MH-01 (VICOP) e MH-02 (Condutor Compacto) do Isaque 2.0 Soberano (0.15.0). "
            "Traduza estritamente o pacote recebido em código completo e verificável sem explicações."
        )
    elif comp_id == "B":
        exec_lora_py = None
        exec_lora_cpp = None
        exec_temp = 0.05
        exec_rp = 1.05
        sys_exec = (
            "Você é um Executor de Engenharia 3D (Blender 5.2 Python) e Gameplay C++20 (Unreal Engine 5). "
            "Traduza estritamente o pacote KEV/1.0 recebido em código completo sem explicações."
        )
    else:
        # Roteamento por Coluna Cortical DoRA/O-LoRA: Onda 1 (`lab-mh-blender-bridge`) p/ Blender 5.2 e Ondas 1+2 acumuladas p/ UE5 C++20
        exec_lora_py = f"{LORA_KEV_O1_REL}:1.00"
        exec_lora_cpp = f"{LORA_KEV_ACUM_REL}:1.00"
        exec_temp = 0.0
        exec_rp = 1.0
        sys_exec = (
            "Você é o Motor Humano KEV-1.0 do Isaque 2.0 Soberano. "
            "Opere sem bloco de pensamento prolixo e emita pacotes KEV/1.0 determinísticos ou código mecânico 100% verificado."
        )

    checks_pass1 = []
    checks_executados = []
    vram_max_exec = 0
    lat_exec_s = 0.0
    max_tentativas = 3

    # --- Parte Blender Headless no Loop (DESAFIO-01 e DESAFIO-03) ---
    blender_recibo = None
    blender_tentativas = 0
    if desafio["blender_spec"] is not None:
        bspec = desafio["blender_spec"]
        arena_ctx_py = ""
        repair_ctx_py = ""
        extra_dom_py = "BRIDGE_3D" if desafio["domain"] == "BRIDGE_3D" else None
        if comp_id == "B" and consultor is not None:
            hid_py = hidratar_ast_guardas_do_pacote_kev(
                pacote_emitido, "BLENDER_BPY", consultor, extra_dom_py, include_ast=True
            )
            arena_ctx_py = f"\n\n[ARENA TRIPLA 384D (V_AST + V_ERR)]:\n{hid_py}" if hid_py else ""
            repair_ctx_py = arena_ctx_py
        elif comp_id == "C" and consultor is not None:
            # Pass@1 usa puramente as colunas DoRA/O-LoRA pós-treino; o loop de reparo injeta V_ast + V_err da Arena Tripla
            hid_g_py = hidratar_ast_guardas_do_pacote_kev(
                pacote_emitido, "BLENDER_BPY", consultor, extra_dom_py, include_ast=True
            )
            repair_ctx_py = f"\n\n[ARENA TRIPLA 384D (V_AST + V_ERR)]:\n{hid_g_py}" if hid_g_py else ""

        if comp_id == "C":
            task_instr = (
                f"Converta o pacote condutor abaixo (alvo `{desafio['target']}`) em um script Python completo para "
                f"Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria, UVs, "
                f"sockets/colisores especificados no pacote e exportando `.glb` e `.fbx` em "
                f"`Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python."
            )
        else:
            task_instr = (
                f"Converta o pacote condutor abaixo (alvo `{desafio['target']}`) em um script Python completo para "
                f"Blender 5.2 headless (`blender --background --factory-startup`), construindo toda a geometria em `bmesh`, "
                f"UVs (`bm.loops.layers.uv.verify()`), objetos EMPTY de sockets (`bpy.data.objects.new(nome, None)`) e "
                f"colisor convexo manifold (`UCX_*` via `bmesh.ops.convex_hull(bm_ucx, input=bm_ucx.verts[:])`), exportando "
                f"`.glb` e `.fbx` em `Path(os.environ.get('KEV_EXPORT_DIR', '.'))`. Responda APENAS com código Python."
            )

        p_py = qwen35_no_think_prompt(
            sys_exec,
            f"{task_instr}{arena_ctx_py}\n\nPACOTE RECEBIDO:\n{pacote_emitido}",
        )
        gen_py = rodar_llama_sob_pulso(
            prompt_text=p_py,
            model_gguf=MODELO_4B_GGUF,
            max_tokens=1850,
            temp=exec_temp,
            ctx_size=6144,
            lora_scaled=exec_lora_py,
            repeat_penalty=exec_rp,
        )
        vram_max_exec = max(vram_max_exec, gen_py["vram_pico_mib"])
        lat_exec_s += gen_py["latencia_s"]
        blender_tentativas = 1

        code_py = extrair_bloco_codigo(gen_py["texto"], "python")
        script_file = out_sub / f"{desafio['target'].lower()}_generated.py"
        script_file.write_text(code_py, encoding="utf-8")

        blender_recibo = verificar_script_blender(
            script_path=script_file,
            expected_bbox_m=bspec["expected_bbox_m"],
            min_visual_meshes=bspec["expected_min_visual_meshes"] if "expected_min_visual_meshes" in bspec else bspec["min_visual_meshes"],
            primary_prefix=bspec["primary_prefix"],
            required_sockets=bspec["required_sockets"],
            export_dir=out_sub / "exports",
            try_headless_render=True,
        )
        pass1_b = bool(blender_recibo.get("aprovado_mecanico"))
        checks_pass1.append(pass1_b)

        while not bool(blender_recibo.get("aprovado_mecanico")) and blender_tentativas < max_tentativas:
            blender_tentativas += 1
            diag_b = json.dumps(
                {
                    "exit_code": blender_recibo.get("exit_code"),
                    "violacoes": [str(v)[-650:] for v in blender_recibo.get("violacoes", [])],
                    "stderr_tail": str(blender_recibo.get("stderr_tail", ""))[-600:],
                },
                ensure_ascii=False,
            )
            p_py_fix = qwen35_no_think_prompt(
                sys_exec,
                (
                    f"Corrija o script Python Blender 5.2 headless abaixo eliminando 100% das violações "
                    f"reportadas pelo verificador físico e alinhando a construção BMesh com `V_AST_CANON` "
                    f"(`bmesh.ops.create_cube(bm, size=1.0)` unitário antes de escalar `v.co`, `Z_min=0.0` e `uv_layer = bm.loops.layers.uv.verify()`). "
                    f"Responda APENAS com código Python completo.\n\n"
                    f"PACOTE RECEBIDO:\n{pacote_emitido}\n\n"
                    f"CÓDIGO ANTERIOR (COM ERROS):\n{code_py[:3600]}\n\n"
                    f"DIAGNÓSTICO DO VERIFICADOR BLENDER 5.2:\n{diag_b}{repair_ctx_py}"
                ),
            )
            gen_py_next = rodar_llama_sob_pulso(
                prompt_text=p_py_fix,
                model_gguf=MODELO_4B_GGUF,
                max_tokens=1850,
                temp=0.03 if comp_id == "C" else max(exec_temp, 0.05),
                ctx_size=8192,
                lora_scaled=exec_lora_py,
                repeat_penalty=1.05 if comp_id == "C" else exec_rp,
            )
            vram_max_exec = max(vram_max_exec, gen_py_next["vram_pico_mib"])
            lat_exec_s += gen_py_next["latencia_s"]
            cand_py = extrair_bloco_codigo(gen_py_next["texto"], "python")
            if len(cand_py) > 40:
                code_py = cand_py
                script_file.write_text(code_py, encoding="utf-8")
                blender_recibo = verificar_script_blender(
                    script_path=script_file,
                    expected_bbox_m=bspec["expected_bbox_m"],
                    min_visual_meshes=bspec["min_visual_meshes"],
                    primary_prefix=bspec["primary_prefix"],
                    required_sockets=bspec["required_sockets"],
                    export_dir=out_sub / "exports",
                    try_headless_render=True,
                )

        blender_recibo["tentativas_loop"] = blender_tentativas
        blender_recibo["aprovado_pass_1"] = pass1_b
        checks_executados.append(bool(blender_recibo.get("aprovado_mecanico")))

    # --- Parte Unreal Engine 5 C++20 no Loop (DESAFIO-02 e DESAFIO-03) ---
    ue5_recibo = None
    ue5_tentativas = 0
    if desafio["ue5_stem"] is not None:
        stem = desafio["ue5_stem"]
        exec_rp_cpp = 1.10 if comp_id == "C" else exec_rp
        exec_rln_cpp = 256 if comp_id == "C" else 64
        arena_ctx_cpp = ""
        repair_ctx_cpp = ""
        dom_cpp_q = "BRIDGE_3D" if desafio["domain"] == "BRIDGE_3D" else "UE5_CPP"
        if comp_id in ("B", "C") and consultor is not None:
            hid_cpp = hidratar_ast_guardas_do_pacote_kev(
                pacote_emitido, dom_cpp_q, consultor, None, include_ast=True
            )
            arena_ctx_cpp = f"\n\n[ARENA TRIPLA 384D (V_AST + V_ERR)]:\n{hid_cpp}" if hid_cpp else ""
            repair_ctx_cpp = arena_ctx_cpp

        if comp_id == "C":
            h_instr = (
                f"Gere APENAS o header `{stem}.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                f"todas as structs, classes, propriedades, funções, delegados e invariantes UHT/GC do pacote abaixo."
            )
        else:
            h_instr = (
                f"Gere APENAS o header `{stem}.h` completo em C++20 Unreal Engine 5 implementando estritamente "
                f"todas as structs, classes, propriedades (`UPROPERTY` + `TObjectPtr<T>` apenas em membros UObject/Component e `T*` em argumentos de métodos), "
                f"funções (`UFUNCTION`), delegados e `#include \"{stem}.generated.h\"` como último include."
            )

        p_h = qwen35_no_think_prompt(
            sys_exec,
            f"{h_instr}\n\nPACOTE RECEBIDO:\n{pacote_emitido}{arena_ctx_cpp}",
        )
        gen_h = rodar_llama_sob_pulso(
            prompt_text=p_h,
            model_gguf=MODELO_4B_GGUF,
            max_tokens=1500,
            temp=exec_temp,
            ctx_size=6144,
            lora_scaled=exec_lora_cpp,
            repeat_penalty=exec_rp_cpp,
            repeat_last_n=exec_rln_cpp,
        )
        vram_max_exec = max(vram_max_exec, gen_h["vram_pico_mib"])
        lat_exec_s += gen_h["latencia_s"]
        code_h = extrair_bloco_codigo(gen_h["texto"], "cpp")

        if comp_id == "C":
            cpp_usr = (
                f"Gere APENAS a implementação `{stem}.cpp` completa em C++20 Unreal Engine 5 "
                f"correspondente estritamente ao pacote abaixo e ao header `{stem}.h`:\n\n"
                f"PACOTE:\n{pacote_emitido}{arena_ctx_cpp}\n\nHEADER `{stem}.h`:\n{code_h}"
            )
        else:
            cpp_usr = (
                f"Gere APENAS a implementação `{stem}.cpp` completa em C++20 Unreal Engine 5 "
                f"implementando estritamente apenas os métodos e membros declarados no header `{stem}.h` abaixo:\n\n"
                f"PACOTE:\n{pacote_emitido}{arena_ctx_cpp}\n\nHEADER `{stem}.h`:\n{code_h}"
            )
        p_cpp = qwen35_no_think_prompt(sys_exec, cpp_usr)
        gen_cpp = rodar_llama_sob_pulso(
            prompt_text=p_cpp,
            model_gguf=MODELO_4B_GGUF,
            max_tokens=1850,
            temp=exec_temp,
            ctx_size=6144,
            lora_scaled=exec_lora_cpp,
            repeat_penalty=exec_rp_cpp,
            repeat_last_n=exec_rln_cpp,
        )
        vram_max_exec = max(vram_max_exec, gen_cpp["vram_pico_mib"])
        lat_exec_s += gen_cpp["latencia_s"]
        code_cpp = extrair_bloco_codigo(gen_cpp["texto"], "cpp")
        ue5_tentativas = 1

        h_file = out_sub / f"{stem}.h"
        cpp_file = out_sub / f"{stem}.cpp"
        h_file.write_text(code_h, encoding="utf-8")
        cpp_file.write_text(code_cpp, encoding="utf-8")

        proc_u = subprocess.run(
            [str(UE5_VERIFIER_EXE), "--header", str(h_file), "--source", str(cpp_file)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        ue5_recibo = json.loads(proc_u.stdout)
        pass1_u = bool(ue5_recibo.get("aprovado_mecanico"))
        checks_pass1.append(pass1_u)

        while not bool(ue5_recibo.get("aprovado_mecanico")) and ue5_tentativas < max_tentativas:
            ue5_tentativas += 1
            raw_viols = [str(v) for v in ue5_recibo.get("violacoes", [])]
            compact_viols = []
            for rv in raw_viols:
                if rv.startswith("INV-08:"):
                    kept_lines = []
                    for ln in rv.splitlines():
                        if ": note:" in ln or "In file included from" in ln:
                            continue
                        if ": error:" in ln or "|" in ln or ln.startswith("INV-08:"):
                            kept_lines.append(ln.split("; did you mean")[0])
                    compact_viols.append("\n".join(kept_lines)[:1800])
                else:
                    compact_viols.append(rv[:500])
            diag_u = json.dumps({"violacoes": compact_viols}, ensure_ascii=False)

            invs_map = ue5_recibo.get("invariantes_8_de_8", {})
            uht_ok = all(
                bool(val)
                for k, val in invs_map.items()
                if k != "inv_08_clang_cpp20_fsyntax_only_zero_erros"
            )
            joined_err = "\n".join(compact_viols)
            header_needs_fix = (
                (not uht_ok)
                or (f"{stem}.h:" in joined_err)
                or ("undeclared identifier" in joined_err)
                or ("no member named" in joined_err)
            )

            if header_needs_fix:
                p_h_fix = qwen35_no_think_prompt(
                    sys_exec,
                    (
                        f"Corrija o header `{stem}.h` em C++20 Unreal Engine 5 eliminando 100% das violações "
                        f"UHT/GC/Clang++20 abaixo e alinhando todas as structs, classes, membros e forward declarations "
                        f"com `V_AST_CANON`. Responda APENAS com o código completo de `{stem}.h`.\n\n"
                        f"PACOTE RECEBIDO:\n{pacote_emitido}\n\n"
                        f"HEADER ANTERIOR (COM ERROS):\n{code_h[:3800]}\n\n"
                        f"DIAGNÓSTICO CLANG++20 / UHT:\n{diag_u}{repair_ctx_cpp}"
                    ),
                )
                gen_h_next = rodar_llama_sob_pulso(
                    prompt_text=p_h_fix,
                    model_gguf=MODELO_4B_GGUF,
                    max_tokens=1500,
                    temp=0.0 if comp_id == "C" else max(exec_temp, 0.05),
                    ctx_size=8192,
                    lora_scaled=exec_lora_cpp,
                    repeat_penalty=exec_rp_cpp,
                    repeat_last_n=exec_rln_cpp,
                )
                vram_max_exec = max(vram_max_exec, gen_h_next["vram_pico_mib"])
                lat_exec_s += gen_h_next["latencia_s"]
                code_h = extrair_bloco_codigo(gen_h_next["texto"], "cpp") or code_h

            p_cpp_fix = qwen35_no_think_prompt(
                sys_exec,
                (
                    f"Reescreva `{stem}.cpp` em C++20 Unreal Engine 5 para compilar com zero erros Clang++20 "
                    f"contra o header `{stem}.h` corrigido abaixo (use estritamente os tipos, membros e assinaturas declarados em `{stem}.h`). "
                    f"Responda APENAS com o código completo de `{stem}.cpp`.\n\n"
                    f"PACOTE RECEBIDO:\n{pacote_emitido}\n\n"
                    f"CPP ANTERIOR (COM ERROS):\n{code_cpp[:3800]}\n\n"
                    f"DIAGNÓSTICO ANTERIOR:\n{diag_u}{repair_ctx_cpp}\n\n"
                    f"HEADER `{stem}.h` ATUAL (OFICIAL):\n{code_h[:3800]}"
                ),
            )
            gen_cpp_next = rodar_llama_sob_pulso(
                prompt_text=p_cpp_fix,
                model_gguf=MODELO_4B_GGUF,
                max_tokens=1850,
                temp=0.0 if comp_id == "C" else max(exec_temp, 0.05),
                ctx_size=8192,
                lora_scaled=exec_lora_cpp,
                repeat_penalty=exec_rp_cpp,
                repeat_last_n=exec_rln_cpp,
            )
            vram_max_exec = max(vram_max_exec, gen_cpp_next["vram_pico_mib"])
            lat_exec_s += gen_cpp_next["latencia_s"]
            code_cpp = extrair_bloco_codigo(gen_cpp_next["texto"], "cpp") or code_cpp

            h_file.write_text(code_h, encoding="utf-8")
            cpp_file.write_text(code_cpp, encoding="utf-8")
            proc_u2 = subprocess.run(
                [str(UE5_VERIFIER_EXE), "--header", str(h_file), "--source", str(cpp_file)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            ue5_recibo = json.loads(proc_u2.stdout)

        ue5_recibo["tentativas_loop"] = ue5_tentativas
        ue5_recibo["aprovado_pass_1"] = pass1_u
        checks_executados.append(bool(ue5_recibo.get("aprovado_mecanico")))

    aprovado_pass1_desafio = len(checks_pass1) > 0 and all(checks_pass1)
    aprovado_desafio = len(checks_executados) > 0 and all(checks_executados)
    return {
        "aprovado_pass_1_desafio": aprovado_pass1_desafio,
        "aprovado_mecanico_desafio": aprovado_desafio,
        "verificadores_acionados": len(checks_executados),
        "verificadores_aprovados_pass_1": sum(1 for c in checks_pass1 if c),
        "verificadores_aprovados": sum(1 for c in checks_executados if c),
        "latencia_sintese_executor_s": round(lat_exec_s, 3),
        "vram_pico_executor_mib": vram_max_exec,
        "recibo_blender": blender_recibo,
        "recibo_ue5_cpp": ue5_recibo,
    }


def resumir_verificacao_para_juiz(exec_res: dict) -> str:
    partes = [
        f"aprovado_mecanico_total={exec_res['aprovado_mecanico_desafio']} "
        f"({exec_res['verificadores_aprovados']}/{exec_res['verificadores_acionados']} verificadores fisicos aprovados)"
    ]
    if exec_res.get("recibo_blender"):
        rb = exec_res["recibo_blender"]
        viol_b = [str(v)[:200] for v in rb.get("violacoes", [])[:3]]
        partes.append(
            f"[BLENDER 5.2 HEADLESS] pass={rb.get('aprovado_mecanico')} | exit={rb.get('exit_code')} | "
            f"non_manifold={rb.get('non_manifold_edges')} | zero_area={rb.get('zero_area_faces')} | "
            f"bbox={rb.get('bounding_box_m')} (2pct_ok={rb.get('bbox_within_2pct')}) | "
            f"pivot_z0={rb.get('pivot_z_min_aligned')} | violacoes={viol_b}"
        )
    if exec_res.get("recibo_ue5_cpp"):
        ru = exec_res["recibo_ue5_cpp"]
        viol_u = [str(v)[:200] for v in ru.get("violacoes", [])[:3]]
        partes.append(
            f"[UE5 C++20 AST+CLANG++] pass={ru.get('aprovado_mecanico')} | "
            f"clang_exit={ru.get('clang_cpp20', {}).get('exit_code')} | "
            f"invariantes={json.dumps(ru.get('invariantes_8_de_8', {}))} | "
            f"violacoes={viol_u}"
        )
    return "\n".join(partes)


def julgar_cego_contraditorio_35b(desafios: list[dict], resultados: dict) -> dict:
    """
    Avaliação Cega Contraditória pelo `Juiz Qwen3.5-35B-A3B` (`--cpu-moe`, `autor_session != revisor_session`):
    Os rótulos A, B e C são embaralhados por desafio em `PACOTE_1`, `PACOTE_2`, `PACOTE_3`.
    O Juiz vê apenas o pacote anônimo + o laudo mecânico determinístico real dos verificadores físicos!
    """
    assert AUTOR_SESSION != REVISOR_SESSION
    notas = {"A": [], "B": [], "C": []}
    pareceres = []
    vram_pico_juiz = 0

    for i, d in enumerate(desafios):
        did = d["id"]
        cands = []
        for cid in ("A", "B", "C"):
            item = resultados[cid][i]
            cands.append((cid, item))

        rng = random.Random(20261111 + i * 17)
        rng.shuffle(cands)
        mapa_cego = {f"PACOTE_{idx + 1}": cid for idx, (cid, _) in enumerate(cands)}

        blocos_txt = []
        for idx, (_, item) in enumerate(cands):
            pk = f"PACOTE_{idx + 1}"
            laudo_fis = resumir_verificacao_para_juiz(item["execucao_fisica"])
            blocos_txt.append(
                f"=== {pk} (tokens_pacote={item['tokens_pacote_entregue']}) ===\n"
                f"[PACOTE EMITIDO AO EXECUTOR]:\n{item['pacote_texto'][:780]}\n\n"
                f"[LAUDO MECÂNICO DOS VERIFICADORES FÍSICOS DETERMINÍSTICOS]:\n{laudo_fis}"
            )

        sys_juiz = (
            "Você é o Juiz Sênior Contraditório de Engenharia 3D e Gameplay C++ (Sessão Revisora Independente). "
            "Avalie às cegas PACOTE_1, PACOTE_2 e PACOTE_3 atribuindo a NOTA FINAL TOTAL de 0.0 a 10.0 "
            "(SOMA dos 3 eixos abaixo):\n"
            "- Eixo 1 (0.0 a 5.0 pts): Aprovação Mecânica Real nos Verificadores Físicos Blender 5.2 / UE5 AST+Clang++20;\n"
            "- Eixo 2 (0.0 a 3.0 pts): Densidade Paramétrica, Escala Física Exata e Guardas Anti-Erro UHT/GC/BMesh no Pacote;\n"
            "- Eixo 3 (0.0 a 2.0 pts): Condutividade Estrutural Enxuta sem Gordura Conversacional.\n"
            "Faixas obrigatórias da NOTA FINAL TOTAL (escala 0.0 a 10.0 = Eixo1 + Eixo2 + Eixo3):\n"
            "- Pacote com `aprovado_mecanico_total=True` (100% dos verificadores físicos aprovados) e alta densidade/concisão: nota final entre 8.8 e 9.8;\n"
            "- Pacote com aprovação mecânica parcial (ex.: 1/2 verificadores aprovados): nota final entre 5.5 e 7.5;\n"
            "- Pacote com `aprovado_mecanico_total=False` (0 verificadores aprovados): Eixo 1 = 0.0..1.0, somando apenas Eixos 2 e 3 conforme a qualidade do pacote (nota final entre 1.5 e 4.6).\n"
            "Responda ESTRITAMENTE em uma única linha JSON válida (até 210 caracteres em justificativa sem aspas internas):\n"
            "{\"justificativa\": \"...\", \"PACOTE_1\": 0.0, \"PACOTE_2\": 0.0, \"PACOTE_3\": 0.0}"
        )
        usr_juiz = f"DESAFIO: {d['titulo']}\n\n" + "\n\n".join(blocos_txt)
        prompt_juiz = qwen35_no_think_prompt(sys_juiz, usr_juiz)

        parsed = None
        res_j = None
        for attempt_j in range(1, 4):
            time.sleep(2.0 * attempt_j)
            res_j = rodar_llama_sob_pulso(
                prompt_text=prompt_juiz,
                model_gguf=MODELO_35B_GGUF,
                max_tokens=320,
                temp=0.10,
                ctx_size=4096,
                grammar_file=(LAB_DIR / "grammars" / "juiz_35b_veredito.gbnf") if attempt_j <= 2 else None,
                cpu_moe=True,
                repeat_penalty=1.05,
                timeout_s=360,
            )
            vram_pico_juiz = max(vram_pico_juiz, res_j["vram_pico_mib"])
            raw_j = res_j["texto"]
            if "</think>" in raw_j:
                raw_j = raw_j.split("</think>")[-1].strip()
            m = re.search(r"\{[^{}]*\"PACOTE_1\"[^{}]*\}", raw_j, re.S)
            if m:
                try:
                    parsed = json.loads(m.group(0))
                    if all(k in parsed for k in ("PACOTE_1", "PACOTE_2", "PACOTE_3")):
                        break
                except Exception:
                    parsed = None
            print(
                f"   [WARN JUIZ 35B tentativa={attempt_j} em {did}] rc={res_j['returncode']} stderr={res_j['stderr_tail'][-180:]} raw={raw_j[-120:]}",
                flush=True,
            )

        if not parsed:
            raise RuntimeError(
                f"R-VERDADE-OU-AJUDA: Juiz 35B-A3B não retornou JSON válido em {did} (rc={res_j['returncode']}, stderr={res_j['stderr_tail'][-250:]}): {raw_j[-300:]}"
            )

        for pk, cid in mapa_cego.items():
            nota_v = round(float(parsed[pk]), 2)
            notas[cid].append(nota_v)

        pareceres.append({
            "desafio_id": did,
            "autor_session": AUTOR_SESSION,
            "revisor_session": REVISOR_SESSION,
            "contraditorio_valido": AUTOR_SESSION != REVISOR_SESSION,
            "mapa_cego": mapa_cego,
            "veredito_juiz_35b": parsed,
            "latencia_juiz_s": res_j["latencia_s"],
        })

    return {
        "notas_por_competidor": notas,
        "pareceres_cegos": pareceres,
        "vram_pico_juiz_35b_mib": vram_pico_juiz,
    }


def calcular_icc(nota_media: float, tokens_medio: float, latencia_media_s: float) -> float:
    if nota_media <= 0.0 or tokens_medio <= 0.0 or latencia_media_s <= 0.0:
        return 0.0
    return round(nota_media / ((tokens_medio / 1000.0) * latencia_media_s), 4)


def _sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def auditar_invariancia_sha256_producao() -> dict:
    snap_path = PROVA_DIR / "snapshot_producao_antes.json"
    snap = json.loads(snap_path.read_text(encoding="utf-8-sig"))
    bin_dir = Path(r"D:\Abraao-Bin")
    col_dir = RAIZ_ISAQUE / "modelos" / "colunas_corticais"

    diffs_bin = []
    for item in snap["abraao_bin"]:
        fp = bin_dir / item["name"]
        if not fp.is_file() or _sha256_arquivo(fp).lower() != item["sha256"].lower():
            diffs_bin.append(item["name"])

    diffs_col = []
    for item in snap["colunas_isaque"]:
        fp = col_dir / item["name"]
        if not fp.is_file() or _sha256_arquivo(fp).lower() != item["sha256"].lower():
            diffs_col.append(item["name"])

    return {
        "abraao_bin_arquivos_verificados": len(snap["abraao_bin"]),
        "abraao_bin_divergencias_sha256": len(diffs_bin),
        "colunas_isaque_arquivos_verificados": len(snap["colunas_isaque"]),
        "colunas_isaque_divergencias_sha256": len(diffs_col),
        "isolamento_100pct_integro": (len(diffs_bin) == 0 and len(diffs_col) == 0),
    }


def main():
    t_inicio = time.perf_counter()
    tok = Tokenizer.from_file(str(TOKENIZER_PATH))
    desafios = construir_especificacoes_6000_tokens(tok)
    for d in desafios:
        print(f">> [{d['id']}] Especificação gerada: {d['tokens_entrada_bruta']} tokens Qwen3.5 (>= 6.000)", flush=True)

    consultor = ConsultorArenaKevTriplo()
    resultados = {"A": [], "B": [], "C": []}

    for d in desafios:
        for cid, cname in (
            ("A", "Baseline_Campeao_0150"),
            ("B", "KEV_1_0_Vetor_Triplo_ZeroShot"),
            ("C", "KEV_1_0_Vetor_Triplo_DoRA_OLoRA"),
        ):
            print(f">> [{d['id']} | Competidor {cid} ({cname})] Emitindo pacote condutor...", flush=True)
            em = emitir_pacote_competidor(cid, d, consultor)
            pkt_txt = em["texto"]
            pkt_toks = len(tok.encode(pkt_txt).ids)
            comp_pct = round(100.0 * (1.0 - pkt_toks / max(d["tokens_entrada_bruta"], 1)), 2)

            print(
                f"   Pacote {cid}: {pkt_toks} toks (compressao={comp_pct}%, pulso={em['latencia_s']}s) -> Rodando sintese & verificadores fisicos...",
                flush=True,
            )
            ex = sintetizar_e_verificar_fisicamente(cid, d, pkt_txt, consultor)
            print(
                f"   Verificacao Fisica {cid} em {d['id']}: aprovado={ex['aprovado_mecanico_desafio']} "
                f"({ex['verificadores_aprovados']}/{ex['verificadores_acionados']})",
                flush=True,
            )
            resultados[cid].append({
                "desafio_id": d["id"],
                "domain": d["domain"],
                "tokens_entrada_bruta": d["tokens_entrada_bruta"],
                "pacote_texto": pkt_txt,
                "tokens_pacote_entregue": pkt_toks,
                "compressao_pct": comp_pct,
                "latencia_pulso_emissao_s": em["latencia_s"],
                "mmap_lookup_ms": em["mmap_lookup_ms"],
                "vram_pico_emissao_mib": em["vram_pico_mib"],
                "execucao_fisica": ex,
            })

    consultor.close()

    print(">> [JUIZ 35B-A3B] Executando Avaliacao Cega Contraditoria nos 3 Desafios...", flush=True)
    julgamento = julgar_cego_contraditorio_35b(desafios, resultados)

    # Carregar recibos de PRE-01 e Treino DoRA+O-LoRA para consolidar no recibo soberano final
    pre01_doc = json.loads((PROVA_DIR / "pre01_semble_prewarm.json").read_text(encoding="utf-8"))
    treino_doc = json.loads((PROVA_DIR / "prova_treino_dora_olora_kev01.json").read_text(encoding="utf-8"))
    arena_bench_doc = json.loads((PROVA_DIR / "arena_kev_triplo_bench.json").read_text(encoding="utf-8"))

    time.sleep(0.5)
    compute_procs_finais = contar_cuda_compute_ativos()

    resumo_competidores = {}
    nomes_oficiais = {
        "A": "A_Baseline_Campeao_0150_JEV_AtomSD",
        "B": "B_KEV_1_0_Vetor_Triplo_ZeroShot",
        "C": "C_KEV_1_0_Vetor_Triplo_DoRA_OLoRA_PosTreino",
    }
    for cid, chave_oficial in nomes_oficiais.items():
        itens = resultados[cid]
        toks_in = [x["tokens_entrada_bruta"] for x in itens]
        toks_out = [x["tokens_pacote_entregue"] for x in itens]
        lats = [x["latencia_pulso_emissao_s"] for x in itens]
        ver_tot = sum(x["execucao_fisica"]["verificadores_acionados"] for x in itens)
        ver_ok_p1 = sum(x["execucao_fisica"]["verificadores_aprovados_pass_1"] for x in itens)
        ver_ok = sum(x["execucao_fisica"]["verificadores_aprovados"] for x in itens)
        desafios_ok_p1 = sum(1 for x in itens if x["execucao_fisica"]["aprovado_pass_1_desafio"])
        desafios_ok = sum(1 for x in itens if x["execucao_fisica"]["aprovado_mecanico_desafio"])
        notas_c = julgamento["notas_por_competidor"][cid]

        tok_med = round(sum(toks_out) / len(toks_out), 1)
        lat_med = round(sum(lats) / len(lats), 3)
        nota_med = round(sum(notas_c) / len(notas_c), 2)
        comp_med = round(100.0 * (1.0 - sum(toks_out) / sum(toks_in)), 2)
        taxa_pass1_pct = round(100.0 * ver_ok_p1 / max(ver_tot, 1), 2)
        taxa_mecanica_pct = round(100.0 * ver_ok / max(ver_tot, 1), 2)
        icc = calcular_icc(nota_med, tok_med, lat_med)
        vram_pico_c = max(
            max(x["vram_pico_emissao_mib"] for x in itens),
            max(x["execucao_fisica"]["vram_pico_executor_mib"] for x in itens),
        )

        resumo_competidores[chave_oficial] = {
            "tokens_entrada_bruta_por_desafio": toks_in,
            "tokens_entregues_por_desafio": toks_out,
            "tokens_entregues_total": sum(toks_out),
            "tokens_entregues_medio": tok_med,
            "compressao_frente_entrada_bruta_pct": comp_med,
            "desafios_100pct_aprovados_pass_1": f"{desafios_ok_p1}/{len(itens)}",
            "desafios_100pct_aprovados": f"{desafios_ok}/{len(itens)}",
            "verificadores_fisicos_aprovados_pass_1": f"{ver_ok_p1}/{ver_tot}",
            "taxa_aprovacao_pass1_pct": taxa_pass1_pct,
            "verificadores_fisicos_aprovados": f"{ver_ok}/{ver_tot}",
            "taxa_aprovacao_mecanica_real_pct": taxa_mecanica_pct,
            "notas_cegas_juiz_35b_por_desafio": notas_c,
            "nota_cega_media_juiz_35b_0_10": nota_med,
            "latencia_pulso_emissao_por_desafio_s": lats,
            "latencia_pulso_media_s": lat_med,
            "icc_indice_condutividade_cognitiva": icc,
            "comparacao_recorde_0150_icc_2_7828": f"{round(icc / 2.7828, 2)}x",
            "vram_pico_mib": vram_pico_c,
            "detalhes_desafios": itens,
        }

    ret_info = treino_doc["prova_matematica_retencao_anti_esquecimento"]
    vram_global_pico = max(
        treino_doc["telemetria_gpu"]["vram_pico_mib"],
        julgamento["vram_pico_juiz_35b_mib"],
        max(v["vram_pico_mib"] for v in resumo_competidores.values()),
    )

    auditoria_sha = auditar_invariancia_sha256_producao()
    recibo_final = {
        "schema": "abraao.isaque.prova_arena_kev_motor_humano/1.0",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modo_execucao": "SANDBOX_LABORATORIO_100PCT_ISOLADO",
        "autoridade_exclusiva": "lucas",
        "co_arquiteto": "gemini-4-argon",
        "autor_session": AUTOR_SESSION,
        "revisor_contraditorio_session": REVISOR_SESSION,
        "leis_inegociaveis": {
            "producao_0151_intocada": auditoria_sha["abraao_bin_divergencias_sha256"] == 0,
            "pesos_producao_isaque_0150_intocados": auditoria_sha["colunas_isaque_divergencias_sha256"] == 0,
            "auditoria_sha256_isolamento_producao": auditoria_sha,
            "vocabulario_base_congelado_embed_lm_head": treino_doc["vocabulario_congelado_intacto"],
            "anti_leak_gbnf_no_think_20345": True,
            "compute_procs_ativos_finais_nvidia_smi": compute_procs_finais,
        },
        "pre_01_semble_async_prewarm": {
            "cold_ms": pre01_doc["cold_without_prewarm"]["mcp_roundtrip_total_ms"],
            "warm_mcp_gated_ms": pre01_doc["mcp_gated_roundtrip_ms"],
            "warm_semble_ram_ms": pre01_doc["semble_first_call_ms"],
            "aprovado_menor_150ms": pre01_doc["criterio_aceite_menor_150ms"],
        },
        "arena_vetorial_tripla_384d": arena_bench_doc,
        "treino_anti_esquecimento_dora_olora": {
            "onda_1_safetensors": treino_doc["onda_1_blender_bridge"]["safetensors_path"],
            "onda_2_safetensors": treino_doc["onda_2_ue5_kev_ortogonal"]["safetensors_path"],
            "lambda_orth": 0.10,
            "replay_buffer_pct": 15.0,
            "orth_frob_sq_inicial": treino_doc["onda_2_ue5_kev_ortogonal"]["orth_frob_sq_inicial"],
            "orth_frob_sq_final": treino_doc["onda_2_ue5_kev_ortogonal"]["orth_frob_sq_final"],
            "retencao_holdout_0150_token_acc_pct": ret_info["holdout_0150_motor_humano"]["retencao_token_acc_pct"],
            "retencao_holdout_0150_verossimilhanca_pct": ret_info["holdout_0150_motor_humano"]["retencao_verossimilhanca_pct"],
            "retencao_holdout_onda1_token_acc_pct": ret_info["holdout_onda_1_blender_kev"]["retencao_token_acc_pct"],
            "retencao_holdout_onda1_ganho_loss_pct": round(
                100.0
                * (ret_info["holdout_onda_1_blender_kev"]["base"]["loss"] - ret_info["holdout_onda_1_blender_kev"]["pos_onda_2_acumulado"]["loss"])
                / max(ret_info["holdout_onda_1_blender_kev"]["base"]["loss"] - ret_info["holdout_onda_1_blender_kev"]["pos_onda_1"]["loss"], 1e-6),
                3,
            ),
            "retencao_holdout_onda1_verossimilhanca_pct": ret_info["holdout_onda_1_blender_kev"]["retencao_verossimilhanca_pct"],
            "queda_loss_onda2_ue5_pct": ret_info["holdout_onda_2_ue5_kev"]["queda_eval_loss_pct"],
            "meta_retencao_token_acc_99pct_cumprida": (
                min(
                    ret_info["holdout_0150_motor_humano"]["retencao_token_acc_pct"],
                    ret_info["holdout_onda_1_blender_kev"]["retencao_token_acc_pct"],
                )
                >= 99.0
            ),
            "vram_pico_treino_mib": treino_doc["telemetria_gpu"]["vram_pico_mib"],
        },
        "recorde_referencia_producao_0150": {
            "nota_media_0_10": 8.57,
            "icc": 2.7828,
        },
        "competidores_arena_3x3": resumo_competidores,
        "julgamento_cego_contraditorio_35b": julgamento["pareceres_cegos"],
        "telemetria_hardware_final": {
            "gpu": "NVIDIA GeForce RTX 5060 (8151 MiB)",
            "vram_pico_global_bateria_mib": vram_global_pico,
            "compute_procs_ativos_pos_arena": compute_procs_finais,
            "tempo_total_arena_s": round(time.perf_counter() - t_inicio, 3),
        },
    }

    out_final = PROVA_DIR / "PROVA_ARENA_KEV_MOTOR_HUMANO_01.json"
    out_final.write_text(json.dumps(recibo_final, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f">> [SUCESSO SOBERANO] Recibo final gravado em {out_final}", flush=True)


if __name__ == "__main__":
    main()
