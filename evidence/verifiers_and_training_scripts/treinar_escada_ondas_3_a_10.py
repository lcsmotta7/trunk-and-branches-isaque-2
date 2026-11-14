#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
ATO 2 — Escada Científica de Estresse até o Limite de Ruptura (`Ondas 3 a 10` Sem Retreinar o Passado)
Regras Físicas Inegociáveis Cumpridas:
  1. Tronco `Qwen/Qwen3.5-4B` NF4 100% congelado (`embed_tokens` e `lm_head` verificados por SHA-256 antes/depois).
  2. PROIBIDO retreinar `Onda 1` ou `Onda 2` (e ondas `3..7` já homologadas em disco são preservadas intactas com SHA-256!):
     carregadas com `is_trainable=False` e invariância criptográfica SHA-256 comprovada antes e após a Onda 10.
  3. Empilhamento sequencial `Ondas 3..10` via `DoRA` (`r=16, alpha=32, use_dora=True`) + Projeção Ortogonal Acumulada
     contra TODAS as ondas anteriores (`O-LoRA` / `SPACE-LoRA`):
       L_{onda k} = L_{CE} + lambda_orth * sum_{j=1}^{k-1} sum_l || A_l^(k) (A_l^(j))^T ||_F^2
     + Replay Buffer leve (`12.5%` fixo, dentro da faixa `10%-15%`).
  4. Matriz Triangular Completa de Retenção medida para TODAS as Ondas k in {1..10} sobre todos os hold-outs H_0..H_k
     comparando:
       (a) Coluna Única Monolítica Acumulada (`["onda_1", ..., f"onda_{k}"]` simultâneas);
       (b) Particionamento `LD-MoLE` por Cluster de Subdomínio (`<= 4` colunas ativas por subdomínio);
       (c) Roteamento `LD-MoLE` Top-2/Top-3 Cirúrgico (`[âncora, especialista]`).
  5. Teto de Complexidade Combinada no `4B`: fusão progressiva num ÚNICO script Blender completo (`2, 3, 4, 5 e 6` ondas:
     `Onda 1 + 3 + 4 + 5 + 6 + 7`) medindo aprovação física real e latência exata de pulso.
  6. Pulso Efêmero: encerra com `compute_procs_ativos == 0` no `nvidia-smi`.
"""

import gc
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from pathlib import Path

CUR_DIR = Path(__file__).resolve().parent
LAB_DIR = CUR_DIR.parent
PESOS_BASE_DIR = LAB_DIR / "pesos"
PESOS_W3_10_DIR = CUR_DIR / "pesos"
PROVA02_DIR = Path(r"D:\Beyond Adonai\Abraao-Windows\Dados\Prova-Limite-KEV-02")
TEMP_DIR = LAB_DIR / "temp" / "escada_ondas_3_10"
for _d in (PESOS_W3_10_DIR, PROVA02_DIR, TEMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["TEMP"] = str(TEMP_DIR)
os.environ["TMP"] = str(TEMP_DIR)
os.environ["HF_HOME"] = str(TEMP_DIR / "hf")
os.environ["TORCH_HOME"] = str(TEMP_DIR / "torch")
os.environ["CUDA_CACHE_PATH"] = str(TEMP_DIR / "cuda")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import numpy as np
import torch
from peft import LoraConfig, PeftModel
from safetensors import safe_open
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(LAB_DIR / "scripts"))
sys.path.insert(0, str(CUR_DIR))

from treinar_ondas_dora_olora_kev import (  # noqa: E402
    MODEL_DIR,
    TARGET_MODULES,
    Win32GpuMutex,
    avaliar_holdout,
    contar_cuda_compute_puro,
    forward_chunked_ce,
    montar_splits_treino_e_holdout,
    salvar_dora_safetensors_oficial,
    sha256_file,
    tokenizar_pares,
)
from catalogo_ondas_3_a_10 import SYS_KEV, construir_ondas_3_a_10  # noqa: E402
from verificadores_ondas_3_a_10 import auditar_script_blender_multidominio, auditar_ue5_onda8_9_10  # noqa: E402

V2_EXE = CUR_DIR / "bin" / "verificador_fisico_ue5_cpp_v2.exe"


def hash_adapter_parameters(peft_model, adapter_name: str) -> str:
    h = hashlib.sha256()
    matched = 0
    for name, param in sorted(peft_model.named_parameters(), key=lambda kv: kv[0]):
        if f".{adapter_name}." in name:
            h.update(name.encode("utf-8"))
            h.update(param.detach().to(torch.float32).cpu().numpy().tobytes())
            matched += 1
    assert matched > 0, f"Nenhum parâmetro encontrado para {adapter_name}"
    return h.hexdigest()


def coletar_matrizes_a_cpu(peft_model, adapter_name: str) -> dict[str, torch.Tensor]:
    """Armazena as matrizes A congeladas em RAM CPU (float32) para custo 0 MB de VRAM residente."""
    out = {}
    for name, param in peft_model.named_parameters():
        if f".lora_A.{adapter_name}.weight" in name:
            key_mod = name.split(f".lora_A.{adapter_name}.weight")[0]
            out[key_mod] = param.detach().to(torch.float32).cpu().contiguous()
    return out


def carregar_matrizes_a_safetensors_cpu(st_path: Path) -> dict[str, torch.Tensor]:
    """Lê as matrizes A de uma onda já salva em `.safetensors` diretamente em RAM CPU (0 MB VRAM)."""
    out = {}
    with safe_open(str(st_path), framework="pt", device="cpu") as sf:
        for k in sf.keys():
            if k.endswith(".lora_A.weight"):
                key_mod = k.split(".lora_A.weight")[0]
                out[key_mod] = sf.get_tensor(k).to(torch.float32).contiguous()
    return out


def calcular_orth_frob_cpu(
    a_cur_cpu: dict[str, torch.Tensor],
    bank_a_anteriores_cpu: dict[str, dict[str, torch.Tensor]],
) -> float:
    prev_names = list(bank_a_anteriores_cpu.keys())
    total_sq = 0.0
    for key_mod, ak in a_cur_cpu.items():
        mats = [bank_a_anteriores_cpu[pn][key_mod] for pn in prev_names if key_mod in bank_a_anteriores_cpu[pn]]
        if not mats:
            continue
        stacked = torch.cat(mats, dim=0)
        prod = torch.matmul(ak, stacked.transpose(0, 1))
        total_sq += float(torch.sum(prod * prod).item())
    return total_sq


def projetar_nova_onda_ortogonal_acumulada(
    peft_model,
    bank_a_anteriores_cpu: dict[str, dict[str, torch.Tensor]],
    nova_onda: str,
):
    """
    Projeta inicialmente `A_l^(k)` no complemento ortogonal do subespaço gerado por
    TODAS as ondas anteriores `bigcup_{j=1}^{k-1} rowspace(A_l^(j))` via decomposição QR reduzida.
    """
    prev_names = sorted(bank_a_anteriores_cpu.keys(), key=lambda s: int(s.split("_")[1]))
    with torch.no_grad():
        for name, param in peft_model.named_parameters():
            if f".lora_A.{nova_onda}.weight" in name:
                key_mod = name.split(f".lora_A.{nova_onda}.weight")[0]
                mats = [bank_a_anteriores_cpu[pn][key_mod] for pn in prev_names if key_mod in bank_a_anteriores_cpu[pn]]
                if not mats:
                    continue
                stacked_gpu = torch.cat(mats, dim=0).to(device=param.device, dtype=torch.float32)
                q_basis, _ = torch.linalg.qr(stacked_gpu.T, mode="reduced")
                ak = param.data.to(torch.float32)
                proj = (ak @ q_basis) @ q_basis.T
                ak_orth = ak - proj
                param.data.copy_(ak_orth.to(param.dtype))
                del stacked_gpu, q_basis, proj, ak_orth


def calcular_loss_ortogonal_acumulada(
    peft_model,
    bank_a_anteriores_cpu: dict[str, dict[str, torch.Tensor]],
    nova_onda: str,
) -> torch.Tensor:
    """
    Calcula exatamente:
      sum_{j=1}^{k-1} sum_l || A_l^(k) (A_l^(j))^T ||_F^2
    transferindo camada a camada (< 1.5 MB temporário) a partir do banco CPU.
    """
    prev_names = list(bank_a_anteriores_cpu.keys())
    orth_sum = None
    for name, param in peft_model.named_parameters():
        if f".lora_A.{nova_onda}.weight" in name:
            key_mod = name.split(f".lora_A.{nova_onda}.weight")[0]
            mats = [bank_a_anteriores_cpu[pn][key_mod] for pn in prev_names if key_mod in bank_a_anteriores_cpu[pn]]
            if not mats:
                continue
            stacked_gpu = torch.cat(mats, dim=0).to(device=param.device, dtype=torch.float32)
            ak = param.float()
            prod = torch.matmul(ak, stacked_gpu.transpose(0, 1))
            frob_sq = torch.sum(prod * prod)
            orth_sum = frob_sq if orth_sum is None else (orth_sum + frob_sq)
    if orth_sum is None:
        return torch.tensor(0.0, device="cuda:0")
    return orth_sum


def montar_batches_onda_com_replay_12_5pct(
    primary_tok: list[tuple[torch.Tensor, torch.Tensor]],
    replay_tok: list[tuple[torch.Tensor, torch.Tensor]],
    total_batches: int = 28,
    batch_size: int = 2,
) -> list[list[tuple[torch.Tensor, torch.Tensor]]]:
    """87.5% amostras da nova onda + 12.5% Replay Buffer leve (dentro da janela permitida 10%-15%)."""
    total_items = total_batches * batch_size
    n_replay = max(1, int(round(total_items * 0.125)))
    replay_positions = set(np.linspace(3, total_items - 1, num=n_replay, dtype=int).tolist())
    seq = []
    p_i, r_i = 0, 0
    for pos in range(total_items):
        if pos in replay_positions:
            seq.append(replay_tok[r_i % len(replay_tok)])
            r_i += 1
        else:
            seq.append(primary_tok[p_i % len(primary_tok)])
            p_i += 1
    return [seq[i : i + batch_size] for i in range(0, total_items, batch_size)]


def adaptadores_ancora_treino(wave_k: int) -> list[str]:
    """Subdomínio base sobre o qual a nova coluna ortogonal `onda_k` se acopla sem retreinar ondas passadas."""
    if wave_k in (3, 4, 5, 6, 7):
        return ["onda_1", f"onda_{wave_k}"]
    # Ondas 8, 9 e 10 operam sobre a base homologada UE5/Bridge (`["onda_1", "onda_2"]`)
    return ["onda_1", "onda_2", f"onda_{wave_k}"]


def rotear_cluster_ld_mole(holdout_idx_j: int, max_wave_k: int) -> list[str]:
    """
    Particionamento `LD-MoLE` (`arXiv:2509.25684`) em 4 clusters funcionais de colunas corticais (`<= 4` adaptadores):
      - `BLENDER_GEOM`: ondas {1, 3, 5, 7} (máx 4 adaptadores simultâneos)
      - `BLENDER_LOOKDEV`: ondas {1, 4, 6} (máx 3 adaptadores simultâneos)
      - `UE5_SYSTEMS`: ondas {1, 2, 8, 9} (máx 4 adaptadores simultâneos, preservando a base Onda 1 sob Onda 2)
      - `BRIDGE_SYNC`: ondas {1, 2, 10} (máx 3 adaptadores simultâneos)
    """
    if holdout_idx_j in (0, 1, 3, 5, 7):
        cand = [1, 3, 5, 7]
    elif holdout_idx_j in (4, 6):
        cand = [1, 4, 6]
    elif holdout_idx_j in (2, 8, 9):
        cand = [1, 2, 8, 9]
    else:
        cand = [1, 2, 10]
    ativos = [f"onda_{w}" for w in cand if w <= max_wave_k]
    return ativos if ativos else ["onda_1"]


def rotear_top2_cirurgico_ld_mole(holdout_idx_j: int, max_wave_k: int) -> list[str]:
    """Roteamento esparso cirúrgico (`[âncora, especialista]`) do `LD-MoLE`."""
    if holdout_idx_j in (0, 1):
        return ["onda_1"]
    if holdout_idx_j == 2:
        return ["onda_1", "onda_2"] if max_wave_k >= 2 else ["onda_1"]
    if holdout_idx_j <= max_wave_k:
        return adaptadores_ancora_treino(holdout_idx_j)
    return ["onda_1"]


def extrair_blocos_codigo(txt: str) -> list[str]:
    blocks = re.findall(r"```(?:python|cpp|h|c\+\+)?\s*\n(.*?)```", txt, flags=re.S | re.I)
    if blocks:
        return [b.strip() for b in blocks if b.strip()]
    return [txt.strip()]


@torch.no_grad()
def gerar_resposta_modelo(peft_model, base_model, tokenizer, sys_msg: str, usr_msg: str, max_new_tokens: int = 1536) -> dict:
    base_model.gradient_checkpointing_disable()
    base_model.config.use_cache = True
    peft_model.eval()
    msgs = [{"role": "system", "content": sys_msg}, {"role": "user", "content": usr_msg}]
    prompt_txt = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    enc = tokenizer(prompt_txt, return_tensors="pt", add_special_tokens=False).to("cuda:0")
    in_len = enc["input_ids"].shape[1]
    t0 = time.perf_counter()
    out_ids = peft_model.generate(
        **enc,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
        use_cache=True,
    )
    torch.cuda.synchronize()
    dt = round(time.perf_counter() - t0, 3)
    gen_ids = out_ids[0, in_len:]
    texto = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
    return {
        "texto": texto,
        "tokens_gerados": int(gen_ids.numel()),
        "pulso_geracao_s": dt,
    }


def construir_degraus_fusao_combinada_4b() -> list[dict]:
    """
    5 degraus progressivos para responder com precisão empírica à Pergunta 2 do Ato 2:
    'Quantas ondas simultâneas (Onda 1 + 3 + 4 + 5 + 6 + 7) o Qwen3.5-4B consegue fundir
     num único script Blender completo mantendo 100% de aprovação física, e qual o tempo exato de pulso?'
    """
    return [
        {
            "id": "FUSAO_2_ONDAS_1_3",
            "ondas_fundidas": [1, 3],
            "num_ondas": 2,
            "dominios_verificados": ["ONDA_1", "ONDA_3"],
            "adaptadores_ld_mole": ["onda_1", "onda_3"],
            "prompt": (
                "Gere UM ÚNICO script Python completo para Blender 5.2 headless (`--background --factory-startup`) "
                "fundindo simultaneamente `ONDA_1` (`bmesh` sólido 2-manifold + UV `bm.loops.layers.uv.verify()` + colisor convexo `UCX_Pump_Deck_01`) "
                "e `ONDA_3` (`Socket_Flow_In` em `(-1.2, -0.5, 0.55)`, `Socket_Flow_Out` em `(1.2, 0.5, 1.15)` e tubulação curva `BEZIER` com `bevel_depth=0.065`, `fill_mode='FULL'` conectando exatamente nos dois sockets). "
                "Responda APENAS com um bloco ```python ... ```."
            ),
        },
        {
            "id": "FUSAO_3_ONDAS_1_3_4",
            "ondas_fundidas": [1, 3, 4],
            "num_ondas": 3,
            "dominios_verificados": ["ONDA_1", "ONDA_3", "ONDA_4"],
            "adaptadores_ld_mole": ["onda_1", "onda_3", "onda_4"],
            "prompt": (
                "Gere UM ÚNICO script Python completo para Blender 5.2 headless fundindo simultaneamente **3 Ondas** (`Onda 1 + 3 + 4`):\n"
                "1. `ONDA_1`: Base industrial sólida 2-manifold com UV via `bm.loops.layers.uv.verify()` + colisor convexo `UCX_Station_01` (`bmesh.ops.convex_hull`).\n"
                "2. `ONDA_3`: `EMPTY` `Socket_Flow_In` em `(-1.2, -0.5, 0.55)` e `Socket_Flow_Out` em `(1.2, 0.5, 1.15)` + curva `BEZIER` 3D (`bevel_depth=0.065`, `fill_mode='FULL'`) iniciando em `Socket_Flow_In` e terminando em `Socket_Flow_Out`.\n"
                "3. `ONDA_4`: Criar por código 4 materiais PBR procedurais (`M_Industrial_Concrete`, `M_Brushed_Steel`, `M_Pressurized_Copper`, `M_Tech_Glass`) usando `ShaderNodeBsdfPrincipled`, `ShaderNodeTexNoise`, `ShaderNodeValToRGB` e `ShaderNodeBump` conectados a `ShaderNodeOutputMaterial.inputs['Surface']`.\n"
                "Responda APENAS com um único bloco ```python ... ``` sem truncar."
            ),
        },
        {
            "id": "FUSAO_4_ONDAS_1_3_4_5",
            "ondas_fundidas": [1, 3, 4, 5],
            "num_ondas": 4,
            "dominios_verificados": ["ONDA_1", "ONDA_3", "ONDA_4", "ONDA_5"],
            "adaptadores_ld_mole": ["onda_1", "onda_3", "onda_4", "onda_5"],
            "prompt": (
                "Gere UM ÚNICO script Python completo para Blender 5.2 headless fundindo simultaneamente **4 Ondas** (`Onda 1 + 3 + 4 + 5`):\n"
                "1. `ONDA_1`: Plataforma sólida 2-manifold (`bmesh.ops.create_cube`, UV via `bm.loops.layers.uv.verify()`) + colisor convexo `UCX_Station_01`.\n"
                "2. `ONDA_3`: `Socket_Flow_In` em `(-1.2, -0.5, 0.55)` e `Socket_Flow_Out` em `(1.2, 0.5, 1.15)` + tubulação `BEZIER` (`bevel_depth=0.065`, `fill_mode='FULL'`) conectando exatamente nos dois sockets.\n"
                "3. `ONDA_4`: 4 materiais PBR procedurais (`M_Industrial_Concrete`, `M_Brushed_Steel`, `M_Pressurized_Copper`, `M_Tech_Glass`) com `ShaderNodeBsdfPrincipled`, `ShaderNodeTexNoise`, `ShaderNodeValToRGB`, `ShaderNodeBump` ligados a `Surface`.\n"
                "4. `ONDA_5`: Objeto `GN_Walkway_Grate` com modificador `NODES` (`GeometryNodeTree` usando `ng.interface.new_socket` `NodeSocketGeometry`, `GeometryNodeMeshGrid` -> `GeometryNodeInstanceOnPoints` com `GeometryNodeMeshCube` -> `GeometryNodeRealizeInstances` -> `NodeGroupOutput`).\n"
                "Responda APENAS com um único bloco ```python ... ``` completo."
            ),
        },
        {
            "id": "FUSAO_5_ONDAS_1_3_4_5_6",
            "ondas_fundidas": [1, 3, 4, 5, 6],
            "num_ondas": 5,
            "dominios_verificados": ["ONDA_1", "ONDA_3", "ONDA_4", "ONDA_5", "ONDA_6"],
            "adaptadores_ld_mole": ["onda_1", "onda_3", "onda_4", "onda_5", "onda_6"],
            "prompt": (
                "Gere UM ÚNICO script Python completo para Blender 5.2 headless fundindo simultaneamente **5 Ondas** (`Onda 1 + 3 + 4 + 5 + 6`):\n"
                "1. `ONDA_1`: Plataforma sólida 2-manifold (`2.4m x 1.6m x 1.2m`, `Z_min=0`, UV válida) + colisor convexo `UCX_Station_01` (`non_manifold_edges == 0`).\n"
                "2. `ONDA_3`: `Socket_Flow_In` `(-1.0, -0.5, 0.6)` e `Socket_Flow_Out` `(1.0, 0.5, 1.1)` + curva `BEZIER` (`bevel_depth=0.065`, `fill_mode='FULL'`) ligando exatamente os dois sockets.\n"
                "3. `ONDA_4`: 4 materiais PBR procedurais (`M_Industrial_Concrete`, `M_Brushed_Steel`, `M_Pressurized_Copper`, `M_Tech_Glass`) com `ShaderNodeBsdfPrincipled` + `ShaderNodeTexNoise` + `ShaderNodeValToRGB` + `ShaderNodeBump` ligados a `Surface` e aplicados nas malhas.\n"
                "4. `ONDA_5`: Objeto `GN_Grid_Carrier` (nome contendo `GEONODE` ou `GRID`) com modificador `NODES` (`GeometryNodeTree`, `ng.interface.new_socket` `NodeSocketGeometry`, `GeometryNodeMeshGrid` + `GeometryNodeMeshCube` + `GeometryNodeInstanceOnPoints` + `GeometryNodeRealizeInstances`).\n"
                "5. `ONDA_6`: `EMPTY` `Stage_Aim` em `(0,0,0.8)`, 3 luzes (`Key` 850W em `(-4.5,-4.5,4.8)`, `Fill` 380W em `(4.5,-3.5,3.2)`, `Rim` 620W em `(0.5,4.8,4.4)` — todas fora da AABB!) e câmera ativa `sc.camera` com `dof.use_dof = True` e constraint `TRACK_TO` (`TRACK_NEGATIVE_Z`, `UP_Y`) apontando para `Stage_Aim`.\n"
                "Responda APENAS com um único bloco ```python ... ``` completo."
            ),
        },
        {
            "id": "FUSAO_6_ONDAS_1_3_4_5_6_7",
            "ondas_fundidas": [1, 3, 4, 5, 6, 7],
            "num_ondas": 6,
            "dominios_verificados": ["ONDA_1", "ONDA_3", "ONDA_4", "ONDA_5", "ONDA_6", "ONDA_7"],
            "adaptadores_ld_mole": ["onda_1", "onda_3", "onda_4", "onda_5", "onda_6", "onda_7"],
            "prompt": (
                "Gere UM ÚNICO script Python completo para Blender 5.2 headless fundindo simultaneamente **TODAS AS 6 ONDAS BLENDER** (`Onda 1 + 3 + 4 + 5 + 6 + 7`):\n"
                "1. `ONDA_1` + `ONDA_7`: Construir 3 malhas 2-manifold com UV válida (`bm.loops.layers.uv.verify()`): `Station_Core_LOD0` (`bmesh.ops.subdivide_edges` `cuts=3`), `Station_Core_LOD1` (`cuts=1`, pos `(3.2,0,0)`) e `Station_Core_LOD2` (`cuts=0`, pos `(6.4,0,0)`), garantindo `tris(LOD0) > tris(LOD1) > tris(LOD2) > 0`, mais colisor convexo `UCX_Station_Core_01`.\n"
                "2. `ONDA_3`: `Socket_Flow_In` `(-1.0, -0.5, 0.6)` e `Socket_Flow_Out` `(1.0, 0.5, 1.1)` + curva `BEZIER` (`bevel_depth=0.065`, `fill_mode='FULL'`) conectando exatamente `Socket_Flow_In` a `Socket_Flow_Out`.\n"
                "3. `ONDA_4`: 4 materiais PBR procedurais (`M_Industrial_Concrete`, `M_Brushed_Steel`, `M_Pressurized_Copper`, `M_Tech_Glass`) com `ShaderNodeBsdfPrincipled`, `ShaderNodeTexNoise`, `ShaderNodeValToRGB`, `ShaderNodeBump` ligados a `Surface` e atribuídos às malhas.\n"
                "4. `ONDA_5`: Objeto `GEONODE_Walkway_Grid` com modificador `NODES` (`GeometryNodeTree` via `ng.interface.new_socket`, `GeometryNodeMeshGrid` + `GeometryNodeMeshCube` + `GeometryNodeInstanceOnPoints` + `GeometryNodeRealizeInstances`).\n"
                "5. `ONDA_6`: `EMPTY` `Stage_Aim` em `(0,0,0.8)`, 3 luzes (`Key` 900W em `(-5.5,-5.5,5.5)`, `Fill` 420W em `(9.5,-4.5,4.0)`, `Rim` 650W em `(2.0,5.5,5.0)` — estritamente fora da AABB global!) e câmera ativa `sc.camera` em `(4.8,-6.2,3.8)` com `dof.use_dof = True` e constraint `TRACK_TO` (`TRACK_NEGATIVE_Z`, `UP_Y`) para `Stage_Aim`.\n"
                "Responda APENAS com um único bloco ```python ... ``` completo."
            ),
        },
    ]


def main():
    t_start = time.perf_counter()
    print(">> [ATO 2] Preparando datasets H_0..H_10 e Replay Buffer leve (12.5%)...", flush=True)

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), trust_remote_code=True)
    vocab_len_initial = len(tokenizer)

    splits_base = montar_splits_treino_e_holdout()
    ondas_3_10 = construir_ondas_3_a_10()

    # Tokenizar todos os Hold-outs H_0 .. H_10 (nunca vistos no treino!)
    holdouts_tok: dict[int, list] = {
        0: tokenizar_pares(splits_base["holdout_0150"], tokenizer, seq_len=2048),
        1: tokenizar_pares(splits_base["holdout_onda1"], tokenizer, seq_len=2048),
        2: tokenizar_pares(splits_base["holdout_onda2"], tokenizer, seq_len=2048),
    }
    holdouts_labels: dict[int, str] = {
        0: "H0_MotorHumano_0150",
        1: "H1_Onda1_BlenderBridge",
        2: "H2_Onda2_UE5_Core",
    }
    for w in ondas_3_10:
        wk = w["wave"]
        holdouts_tok[wk] = tokenizar_pares(w["holdout_pairs"], tokenizer, seq_len=2048)
        holdouts_labels[wk] = f"H{wk}_Onda{wk}_{w['domain']}"

    # Replay Buffer leve fixo (12.5%): amostras de treino 0.15.0 + 2 amostras Onda 1 + 2 amostras Onda 2
    replay_pairs_fixed = (
        splits_base["replay_0150"][:4]
        + splits_base["train_onda1"][:2]
        + splits_base["train_onda2"][:2]
    )
    replay_tok_fixed = tokenizar_pares(replay_pairs_fixed, tokenizer, seq_len=2048)

    dora_cfg = LoraConfig(
        r=16,
        lora_alpha=32,
        use_dora=True,
        lora_dropout=0.0,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=TARGET_MODULES,
    )

    matriz_triangular_monolitica: dict[str, dict] = {}
    matriz_triangular_ld_mole_cluster: dict[str, dict] = {}
    matriz_triangular_ld_mole_top2: dict[str, dict] = {}
    baselines_referencia: dict[int, dict] = {}
    telemetria_ondas: list[dict] = []
    resultados_fusao_4b: list[dict] = []

    with Win32GpuMutex(timeout_ms=600000):
        print(">> [PULSO GPU ATO 2] Carregando tronco congelado Qwen3.5-4B NF4 + Ondas 1 e 2 CONGELADAS...", flush=True)
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

        emb_sha_before = hashlib.sha256(
            base_model.get_input_embeddings().weight.detach().to(torch.float16).cpu().numpy().tobytes()
        ).hexdigest()

        # Carregar Onda 1 e Onda 2 estritamente congeladas (PROIBIDO retreinar!)
        peft_model = PeftModel.from_pretrained(
            base_model,
            str(PESOS_BASE_DIR / "peft_onda_1" / "onda_1"),
            adapter_name="onda_1",
            is_trainable=False,
        )
        peft_model.load_adapter(
            str(PESOS_BASE_DIR / "peft_onda_2" / "onda_2"),
            adapter_name="onda_2",
            is_trainable=False,
        )

        sha_o1_before = hash_adapter_parameters(peft_model, "onda_1")
        sha_o2_before = hash_adapter_parameters(peft_model, "onda_2")
        print(f"   [CONGELAMENTO VERIFICADO] onda_1={sha_o1_before[:16]}... | onda_2={sha_o2_before[:16]}...", flush=True)

        # Banco acumulado de matrizes A congeladas em RAM CPU (0 MB de VRAM permanente!)
        bank_a_cpu: dict[str, dict[str, torch.Tensor]] = {
            "onda_1": coletar_matrizes_a_cpu(peft_model, "onda_1"),
            "onda_2": coletar_matrizes_a_cpu(peft_model, "onda_2"),
        }

        # =====================================================================
        # FASE A — TREINO SEQUENCIAL DE SUBESPAÇO ORTOGONAL COM ORÇAMENTO LIMPO DE VRAM
        # (Reaproveita Ondas 3..7 já homologadas em disco sem retreinar; treina Ondas faltantes
        #  com apenas [onda_1, onda_2, onda_k] residentes na GPU!)
        # =====================================================================
        lambda_orth = 0.10
        meta_treino_ondas: dict[int, dict] = {}
        sha_ondas_preexistentes_antes: dict[str, str] = {}

        for w in ondas_3_10:
            wk = w["wave"]
            wname = w["id"]
            st_path = PESOS_W3_10_DIR / f"lab-mh-onda-{wk:02d}-{w['domain'].lower()}.safetensors"
            peft_dir_wk = PESOS_W3_10_DIR / f"peft_{wname}" / wname

            if st_path.is_file() and (peft_dir_wk / "adapter_model.safetensors").is_file():
                t_w = time.perf_counter()
                sha_existing = sha256_file(st_path)
                sha_ondas_preexistentes_antes[wname] = sha_existing
                a_wk_cpu = carregar_matrizes_a_safetensors_cpu(st_path)
                orth_final_val = calcular_orth_frob_cpu(a_wk_cpu, bank_a_cpu)
                bank_a_cpu[wname] = a_wk_cpu
                print(
                    f">> [ONDA {wk}/10 — {w['domain']}] Checkpoint congelado existente em disco "
                    f"(SHA={sha_existing[:12]}... | orth_sum_1..{wk-1}={orth_final_val:.6f}, zero retreino!)",
                    flush=True,
                )
                meta_treino_ondas[wk] = {
                    "modo_treino": "checkpoint_congelado_existente_sem_retreinar",
                    "safetensors_path": str(st_path),
                    "safetensors_sha256": sha_existing,
                    "orth_frob_sq_init": 0.0,
                    "orth_frob_sq_final": round(orth_final_val, 8),
                    "tempo_treino_s": round(time.perf_counter() - t_w, 3),
                    "historico_loss_resumo": [],
                }
                continue

            t_w = time.perf_counter()
            print(
                f"\n>> [ONDA {wk}/10 — {w['domain']}] Treinando subespaço ortogonal contra Ondas 1..{wk-1} "
                f"(VRAM enxuta: apenas âncoras + {wname})...",
                flush=True,
            )

            peft_model.add_adapter(wname, dora_cfg)
            projetar_nova_onda_ortogonal_acumulada(peft_model, bank_a_cpu, wname)

            train_active = adaptadores_ancora_treino(wk)
            peft_model.base_model.set_adapter(train_active)

            params_a, params_b, params_m = [], [], []
            for n, p in peft_model.named_parameters():
                if f".{wname}." in n:
                    p.requires_grad = True
                    if "lora_A" in n:
                        params_a.append(p)
                    elif "lora_B" in n:
                        params_b.append(p)
                    else:
                        params_m.append(p)
                else:
                    p.requires_grad = False

            orth_init_val = float(calcular_loss_ortogonal_acumulada(peft_model, bank_a_cpu, wname).detach().cpu().item())

            tok_primary = tokenizar_pares(w["train_pairs"], tokenizer, seq_len=2048)
            batches_wk = montar_batches_onda_com_replay_12_5pct(
                tok_primary, replay_tok_fixed, total_batches=28, batch_size=2
            )

            opt_wk = torch.optim.AdamW(
                [
                    {"params": params_a, "lr": 1.8e-4, "weight_decay": 0.01},
                    {"params": params_b, "lr": 5.5e-4, "weight_decay": 0.01},
                    {"params": params_m, "lr": 1.4e-4, "weight_decay": 0.0},
                ]
            )

            base_model.config.use_cache = False
            base_model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
            hist_wk = []
            for step, batch in enumerate(batches_wk, start=1):
                peft_model.train()
                opt_wk.zero_grad(set_to_none=True)
                l_ce = 0.0
                for bx, by in batch:
                    xb = bx.unsqueeze(0).to("cuda:0")
                    yb = by.unsqueeze(0).to("cuda:0")
                    loss_item = forward_chunked_ce(peft_model, xb, yb, chunk_size=64) / float(len(batch))
                    loss_item.backward()
                    l_ce += float(loss_item.detach().cpu().item())
                loss_orth = calcular_loss_ortogonal_acumulada(peft_model, bank_a_cpu, wname)
                (lambda_orth * loss_orth).backward()
                torch.nn.utils.clip_grad_norm_(params_a + params_b + params_m, max_norm=1.0)
                opt_wk.step()

                l_or = float(loss_orth.detach().cpu().item())
                hist_wk.append({"step": step, "ce_loss": round(l_ce, 6), "orth_frob_sq": round(l_or, 8)})
                if step in (1, 14, len(batches_wk)):
                    print(
                        f"   [{wname} | Passo {step:02d}/{len(batches_wk)}] ce={l_ce:.4f} | orth_sum_1..{wk-1}={l_or:.6f}",
                        flush=True,
                    )

            orth_final_val = float(calcular_loss_ortogonal_acumulada(peft_model, bank_a_cpu, wname).detach().cpu().item())

            for n, p in peft_model.named_parameters():
                if f".{wname}." in n:
                    p.requires_grad = False
            del opt_wk

            sha_wk = salvar_dora_safetensors_oficial(
                peft_model,
                wname,
                st_path,
                {
                    "wave": str(wk),
                    "domain": w["domain"],
                    "use_dora": "True",
                    "r": "16",
                    "alpha": "32",
                    "lambda_orth": str(lambda_orth),
                },
            )
            peft_model.save_pretrained(str(PESOS_W3_10_DIR / f"peft_{wname}"), selected_adapters=[wname])
            bank_a_cpu[wname] = coletar_matrizes_a_cpu(peft_model, wname)

            # Descarregar adaptador recém-salvo da VRAM durante a Fase A para manter pico < 5.5 GiB!
            peft_model.base_model.set_adapter(["onda_1", "onda_2"])
            peft_model.delete_adapter(wname)
            gc.collect()
            torch.cuda.empty_cache()

            meta_treino_ondas[wk] = {
                "modo_treino": "treinado_novo_subespaco_ortogonal",
                "safetensors_path": str(st_path),
                "safetensors_sha256": sha_wk,
                "orth_frob_sq_init": round(orth_init_val, 8),
                "orth_frob_sq_final": round(orth_final_val, 8),
                "tempo_treino_s": round(time.perf_counter() - t_w, 3),
                "historico_loss_resumo": [hist_wk[0], hist_wk[len(hist_wk) // 2], hist_wk[-1]],
            }

        # =====================================================================
        # FASE B — AVALIAÇÃO CIENTÍFICA INTEGRAL EM `torch.no_grad()` (`Ondas 1..10` CONGELADAS)
        # =====================================================================
        print(
            "\n>> [FASE B — AVALIAÇÃO INTEGRAL] Carregando todas as 10 colunas corticais congeladas em modo inferência (`no_grad`)...",
            flush=True,
        )
        base_model.gradient_checkpointing_disable()
        base_model.config.use_cache = True
        for w in ondas_3_10:
            wname = w["id"]
            peft_model.load_adapter(
                str(PESOS_W3_10_DIR / f"peft_{wname}" / wname),
                adapter_name=wname,
                is_trainable=False,
            )
        peft_model.eval()

        def _medir_celula_retencao(ev: dict, j_idx: int) -> dict:
            base_ev = baselines_referencia[j_idx]
            ret_acc = round(100.0 * (ev["token_acc"] / max(base_ev["token_acc"], 1e-6)), 3)
            ret_prob = round(100.0 * math.exp(base_ev["loss"] - ev["loss"]), 3)
            return {
                "loss": ev["loss"],
                "token_acc": ev["token_acc"],
                "retencao_token_acc_pct": ret_acc,
                "retencao_verossimilhanca_pct": ret_prob,
            }

        # --- Linha k=1 (Referência Pós-Onda 1) ---
        peft_model.base_model.set_adapter(["onda_1"])
        ev_k1_h0 = avaliar_holdout(peft_model, holdouts_tok[0])
        ev_k1_h1 = avaliar_holdout(peft_model, holdouts_tok[1])
        baselines_referencia[0] = ev_k1_h0
        baselines_referencia[1] = ev_k1_h1
        row_k1 = {
            holdouts_labels[0]: _medir_celula_retencao(ev_k1_h0, 0),
            holdouts_labels[1]: _medir_celula_retencao(ev_k1_h1, 1),
        }
        matriz_triangular_monolitica["onda_1"] = row_k1
        matriz_triangular_ld_mole_cluster["onda_1"] = row_k1
        matriz_triangular_ld_mole_top2["onda_1"] = row_k1
        print(f"   [LINHA k=1] H0_acc={ev_k1_h0['token_acc']:.4f} | H1_acc={ev_k1_h1['token_acc']:.4f}", flush=True)

        # --- Linha k=2 (Referência Pós-Onda 2, sem retreinar!) ---
        peft_model.base_model.set_adapter(["onda_1", "onda_2"])
        ev_k2_h0 = avaliar_holdout(peft_model, holdouts_tok[0])
        ev_k2_h1 = avaliar_holdout(peft_model, holdouts_tok[1])
        ev_k2_h2 = avaliar_holdout(peft_model, holdouts_tok[2])
        baselines_referencia[2] = ev_k2_h2
        row_k2_mono = {
            holdouts_labels[0]: _medir_celula_retencao(ev_k2_h0, 0),
            holdouts_labels[1]: _medir_celula_retencao(ev_k2_h1, 1),
            holdouts_labels[2]: _medir_celula_retencao(ev_k2_h2, 2),
        }
        matriz_triangular_monolitica["onda_2"] = row_k2_mono

        row_k2_cluster = {}
        row_k2_top2 = {}
        for j in (0, 1, 2):
            peft_model.base_model.set_adapter(rotear_cluster_ld_mole(j, 2))
            row_k2_cluster[holdouts_labels[j]] = _medir_celula_retencao(avaliar_holdout(peft_model, holdouts_tok[j]), j)
            peft_model.base_model.set_adapter(rotear_top2_cirurgico_ld_mole(j, 2))
            row_k2_top2[holdouts_labels[j]] = _medir_celula_retencao(avaliar_holdout(peft_model, holdouts_tok[j]), j)
        matriz_triangular_ld_mole_cluster["onda_2"] = row_k2_cluster
        matriz_triangular_ld_mole_top2["onda_2"] = row_k2_top2
        print(
            f"   [LINHA k=2] Mono H1_ret={row_k2_mono[holdouts_labels[1]]['retencao_token_acc_pct']:.2f}% | "
            f"H2_acc={ev_k2_h2['token_acc']:.4f}",
            flush=True,
        )

        # --- Linhas k=3 .. 10: Verificador Físico de Domínio + Matriz Triangular Completa ---
        tmp_verify_root = Path(tempfile.mkdtemp(prefix="ato2_gen_verify_", dir=str(TEMP_DIR)))
        for w in ondas_3_10:
            wk = w["wave"]
            wname = w["id"]
            t_ev = time.perf_counter()

            train_active = adaptadores_ancora_treino(wk)
            peft_model.base_model.set_adapter(train_active)
            baselines_referencia[wk] = avaliar_holdout(peft_model, holdouts_tok[wk])

            w_dir = tmp_verify_root / wname
            w_dir.mkdir(parents=True, exist_ok=True)
            if wk in (3, 4, 5, 6, 7):
                gen_out = gerar_resposta_modelo(
                    peft_model, base_model, tokenizer, w["train_pairs"][0][0], w["train_pairs"][0][1], max_new_tokens=1400
                )
                py_code = extrair_blocos_codigo(gen_out["texto"])[0]
                py_file = w_dir / f"{wname}_generated.py"
                py_file.write_text(py_code, encoding="utf-8")
                doms = ["ONDA_1", "ONDA_3"] if wk == 3 else [f"ONDA_{wk}"]
                v_rep = auditar_script_blender_multidominio(py_file, doms, export_dir=w_dir / "exports")
                verif_dominio = {
                    "aprovado_fisico": v_rep["aprovado_fisico"],
                    "violacoes": v_rep["violacoes"],
                    "pulso_geracao_s": gen_out["pulso_geracao_s"],
                    "tokens_gerados": gen_out["tokens_gerados"],
                }
            elif wk in (8, 9):
                g_h = gerar_resposta_modelo(
                    peft_model, base_model, tokenizer, w["train_pairs"][0][0], w["train_pairs"][0][1], max_new_tokens=1024
                )
                g_cpp = gerar_resposta_modelo(
                    peft_model, base_model, tokenizer, w["train_pairs"][1][0], w["train_pairs"][1][1], max_new_tokens=1024
                )
                stem = "ReplicatedPressureValveActor" if wk == 8 else "IndustrialCatwalkHismBuilder"
                hf = w_dir / f"{stem}.h"
                cf = w_dir / f"{stem}.cpp"
                hf.write_text(extrair_blocos_codigo(g_h["texto"])[0], encoding="utf-8")
                cf.write_text(extrair_blocos_codigo(g_cpp["texto"])[0], encoding="utf-8")
                u_rep = auditar_ue5_onda8_9_10(hf, cf, f"ONDA_{wk}", ue5_verifier_exe=V2_EXE)
                verif_dominio = {
                    "aprovado_fisico": u_rep["aprovado_fisico"],
                    "violacoes": u_rep["violacoes"],
                    "pulso_geracao_s": round(g_h["pulso_geracao_s"] + g_cpp["pulso_geracao_s"], 3),
                }
            else:
                g_cpp_both = gerar_resposta_modelo(
                    peft_model, base_model, tokenizer, w["train_pairs"][0][0], w["train_pairs"][0][1], max_new_tokens=1400
                )
                g_bl = gerar_resposta_modelo(
                    peft_model, base_model, tokenizer, w["train_pairs"][1][0], w["train_pairs"][1][1], max_new_tokens=1400
                )
                c_blocks = extrair_blocos_codigo(g_cpp_both["texto"])
                py_f = w_dir / "manifest_blender.py"
                py_f.write_text(extrair_blocos_codigo(g_bl["texto"])[0], encoding="utf-8")
                bl_m = auditar_script_blender_multidominio(py_f, ["ONDA_4", "ONDA_7"], export_dir=w_dir / "exports")
                hf = w_dir / "IndustrialAssetManifestActor.h"
                cf = w_dir / "IndustrialAssetManifestActor.cpp"
                hf.write_text(c_blocks[0], encoding="utf-8")
                cf.write_text(c_blocks[1] if len(c_blocks) > 1 else "", encoding="utf-8")
                u_rep = auditar_ue5_onda8_9_10(hf, cf, "ONDA_10", blender_manifest_audit=bl_m, ue5_verifier_exe=V2_EXE)
                verif_dominio = {
                    "aprovado_fisico": bl_m["aprovado_fisico"] and u_rep["aprovado_fisico"],
                    "violacoes_blender": bl_m["violacoes"],
                    "violacoes_ue5": u_rep["violacoes"],
                    "pulso_geracao_s": round(g_cpp_both["pulso_geracao_s"] + g_bl["pulso_geracao_s"], 3),
                }

            mono_stack = [f"onda_{i}" for i in range(1, wk + 1)]
            peft_model.base_model.set_adapter(mono_stack)
            row_mono = {}
            for j in range(0, wk + 1):
                row_mono[holdouts_labels[j]] = _medir_celula_retencao(avaliar_holdout(peft_model, holdouts_tok[j]), j)

            row_cluster = {}
            for j in range(0, wk + 1):
                peft_model.base_model.set_adapter(rotear_cluster_ld_mole(j, wk))
                row_cluster[holdouts_labels[j]] = _medir_celula_retencao(avaliar_holdout(peft_model, holdouts_tok[j]), j)

            row_top2 = {}
            for j in range(0, wk + 1):
                peft_model.base_model.set_adapter(rotear_top2_cirurgico_ld_mole(j, wk))
                row_top2[holdouts_labels[j]] = _medir_celula_retencao(avaliar_holdout(peft_model, holdouts_tok[j]), j)

            matriz_triangular_monolitica[wname] = row_mono
            matriz_triangular_ld_mole_cluster[wname] = row_cluster
            matriz_triangular_ld_mole_top2[wname] = row_top2

            min_mono_prev = min(
                row_mono[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, wk)
            )
            min_cluster_prev = min(
                row_cluster[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, wk)
            )
            min_top2_prev = min(
                row_top2[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, wk)
            )
            print(
                f"   [LINHA k={wk:02d} | {w['domain']}] Verif={verif_dominio['aprovado_fisico']} | "
                f"MinRet(H1..H{wk-1}): Monolítica[1..{wk}]={min_mono_prev:.2f}% | "
                f"LD-MoLE(Cluster)={min_cluster_prev:.2f}% | LD-MoLE(Top2)={min_top2_prev:.2f}%",
                flush=True,
            )

            mt = meta_treino_ondas[wk]
            telemetria_ondas.append({
                "wave": wk,
                "id": wname,
                "domain": w["domain"],
                "modo_treino": mt["modo_treino"],
                "safetensors_path": mt["safetensors_path"],
                "safetensors_sha256": mt["safetensors_sha256"],
                "orth_frob_sq_init": mt["orth_frob_sq_init"],
                "orth_frob_sq_final": mt["orth_frob_sq_final"],
                "tempo_onda_s": round(mt["tempo_treino_s"] + (time.perf_counter() - t_ev), 3),
                "verificador_fisico_dominio": verif_dominio,
                "min_retencao_ondas_anteriores_acc_pct": {
                    "coluna_monolitica_1_ate_k": min_mono_prev,
                    "ld_mole_cluster_subdominio": min_cluster_prev,
                    "ld_mole_top2_cirurgico": min_top2_prev,
                },
                "historico_loss_resumo": mt["historico_loss_resumo"],
            })

        # =====================================================================
        # PERGUNTA 2 DO ATO 2: TETO DE COMPLEXIDADE COMBINADA NO `Qwen3.5-4B`
        # (`Onda 1 + 3 + 4 + 5 + 6 + 7` num ÚNICO script Blender completo!)
        # =====================================================================
        print("\n>> [FRONTEIRA PERGUNTA 2] Testando Teto de Complexidade Combinada no Qwen3.5-4B (2 a 6 Ondas num único script)...", flush=True)
        fusao_dir = PROVA02_DIR / "scripts_fusao_4b"
        fusao_dir.mkdir(parents=True, exist_ok=True)

        for deg in construir_degraus_fusao_combinada_4b():
            peft_model.base_model.set_adapter(deg["adaptadores_ld_mole"])
            gen_p1 = gerar_resposta_modelo(peft_model, base_model, tokenizer, SYS_KEV, deg["prompt"], max_new_tokens=2304)
            code_p1 = extrair_blocos_codigo(gen_p1["texto"])[0]
            py_p1 = fusao_dir / f"{deg['id']}_pass1.py"
            py_p1.write_text(code_p1, encoding="utf-8")
            aud_p1 = auditar_script_blender_multidominio(py_p1, deg["dominios_verificados"], export_dir=fusao_dir / f"exp_{deg['id']}_p1")

            pass_loop = aud_p1["aprovado_fisico"]
            viol_final = aud_p1["violacoes"]
            pulso_loop_s = 0.0
            if not pass_loop:
                repair_prompt = (
                    f"{deg['prompt']}\n\n"
                    f"CORREÇÃO MECÂNICA OBRIGATÓRIA — O verificador físico Blender 5.2 apontou estas violações no código anterior:\n"
                    f"{json.dumps(aud_p1['violacoes'], ensure_ascii=False)}\n\n"
                    f"CÓDIGO ANTERIOR:\n```python\n{code_p1[:3500]}\n```\n\n"
                    "Reescreva o script Python COMPLETO corrigindo 100% das violações acima."
                )
                gen_p2 = gerar_resposta_modelo(peft_model, base_model, tokenizer, SYS_KEV, repair_prompt, max_new_tokens=2304)
                pulso_loop_s = gen_p2["pulso_geracao_s"]
                code_p2 = extrair_blocos_codigo(gen_p2["texto"])[0]
                py_p2 = fusao_dir / f"{deg['id']}_pass2.py"
                py_p2.write_text(code_p2, encoding="utf-8")
                aud_p2 = auditar_script_blender_multidominio(py_p2, deg["dominios_verificados"], export_dir=fusao_dir / f"exp_{deg['id']}_p2")
                pass_loop = aud_p2["aprovado_fisico"]
                viol_final = aud_p2["violacoes"]

            print(
                f"   [{deg['id']} ({deg['num_ondas']} ondas)] Pass@1={aud_p1['aprovado_fisico']} "
                f"(pulso={gen_p1['pulso_geracao_s']}s, toks={gen_p1['tokens_gerados']}) | "
                f"Pass@Loop={pass_loop} | viol={viol_final[:2]}",
                flush=True,
            )
            resultados_fusao_4b.append({
                "id": deg["id"],
                "ondas_fundidas": deg["ondas_fundidas"],
                "num_ondas_simultaneas": deg["num_ondas"],
                "dominios_verificados": deg["dominios_verificados"],
                "pass_at_1_fisico": aud_p1["aprovado_fisico"],
                "pass_at_loop_fisico": pass_loop,
                "pulso_geracao_pass1_s": gen_p1["pulso_geracao_s"],
                "pulso_reparo_s": pulso_loop_s,
                "pulso_verificador_blender_s": aud_p1["latencia_s"],
                "tokens_gerados_pass1": gen_p1["tokens_gerados"],
                "violacoes_pass1": aud_p1["violacoes"],
                "violacoes_finais": viol_final,
                "script_pass1_path": str(py_p1),
            })

        # Verificações finais de invariância estrita (Vocabulário + Onda 1 + Onda 2 + Ondas pré-existentes jamais tocados!)
        emb_sha_after = hashlib.sha256(
            base_model.get_input_embeddings().weight.detach().to(torch.float16).cpu().numpy().tobytes()
        ).hexdigest()
        sha_o1_after = hash_adapter_parameters(peft_model, "onda_1")
        sha_o2_after = hash_adapter_parameters(peft_model, "onda_2")
        ondas_pre_invariantes = all(
            sha256_file(Path(meta_treino_ondas[int(wn.split("_")[1])]["safetensors_path"])) == sh0
            for wn, sh0 in sha_ondas_preexistentes_antes.items()
        )
        vram_peak_mib = int(round(torch.cuda.max_memory_allocated() / (1024 * 1024)))

        del bank_a_cpu
        del peft_model
        del base_model
        gc.collect()
        torch.cuda.empty_cache()

    time.sleep(0.6)
    compute_procs_pos = contar_cuda_compute_puro()

    # Síntese analítica automática das Perguntas 1 e 2 da Fronteira
    curva_saturacao = []
    for k in range(2, 11):
        wn = f"onda_{k}"
        rm = matriz_triangular_monolitica[wn]
        rc = matriz_triangular_ld_mole_cluster[wn]
        rt = matriz_triangular_ld_mole_top2[wn]
        min_m_acc = min(rm[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, k))
        min_m_prob = min(rm[holdouts_labels[j]]["retencao_verossimilhanca_pct"] for j in range(1, k))
        min_c_acc = min(rc[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, k))
        min_c_prob = min(rc[holdouts_labels[j]]["retencao_verossimilhanca_pct"] for j in range(1, k))
        min_t_acc = min(rt[holdouts_labels[j]]["retencao_token_acc_pct"] for j in range(1, k))
        curva_saturacao.append({
            "onda_k": k,
            "monolitica_min_acc_pct": min_m_acc,
            "monolitica_min_verossimilhanca_pct": min_m_prob,
            "ld_mole_cluster_min_acc_pct": min_c_acc,
            "ld_mole_cluster_min_verossimilhanca_pct": min_c_prob,
            "ld_mole_top2_min_acc_pct": min_t_acc,
            "ld_mole_vence_monolitica": (min_c_acc > min_m_acc) or (min_c_prob > min_m_prob + 0.25),
        })

    teto_pass1 = max([r["num_ondas_simultaneas"] for r in resultados_fusao_4b if r["pass_at_1_fisico"]], default=0)
    teto_loop = max([r["num_ondas_simultaneas"] for r in resultados_fusao_4b if r["pass_at_loop_fisico"]], default=0)

    recibo_ato2 = {
        "schema": "abraao.isaque.ato2_escada_ruptura_ondas_1_a_10/1.0",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "invariantes_congelamento": {
            "vocabulario_congelado_intacto": (emb_sha_before == emb_sha_after) and (len(tokenizer) == vocab_len_initial),
            "embed_tokens_sha256": emb_sha_before,
            "onda_1_jamais_retreinada_sha256_invariante": (sha_o1_before == sha_o1_after),
            "onda_1_params_sha256": sha_o1_before,
            "onda_2_jamais_retreinada_sha256_invariante": (sha_o2_before == sha_o2_after),
            "onda_2_params_sha256": sha_o2_before,
            "ondas_3_a_7_preexistentes_sha256_invariantes": ondas_pre_invariantes,
            "replay_buffer_pct": 12.5,
            "lambda_orth_acumulado": lambda_orth,
        },
        "baselines_referencia_h0_a_h10": {holdouts_labels[k]: v for k, v in baselines_referencia.items()},
        "matriz_triangular_coluna_monolitica_1_ate_k": matriz_triangular_monolitica,
        "matriz_triangular_ld_mole_cluster_subdominio": matriz_triangular_ld_mole_cluster,
        "matriz_triangular_ld_mole_top2_cirurgico": matriz_triangular_ld_mole_top2,
        "curva_comparativa_saturacao_monolitica_vs_ld_mole": curva_saturacao,
        "telemetria_por_onda_3_a_10": telemetria_ondas,
        "teto_complexidade_combinada_4b_unico_script": {
            "max_ondas_simultaneas_pass_at_1": teto_pass1,
            "max_ondas_simultaneas_pass_at_loop": teto_loop,
            "degraus_testados": resultados_fusao_4b,
        },
        "telemetria_gpu": {
            "vram_pico_mib": vram_peak_mib,
            "compute_procs_ativos_pos_ato2": compute_procs_pos,
            "tempo_total_ato2_s": round(time.perf_counter() - t_start, 3),
        },
    }

    out_json = PROVA02_DIR / "ato2_escada_ondas_3_a_10.json"
    out_json.write_text(json.dumps(recibo_ato2, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"\n>> [ATO 2 CONCLUÍDO] Salvo em {out_json} | VRAM pico={vram_peak_mib} MiB | "
        f"compute_procs={compute_procs_pos} | tempo={recibo_ato2['telemetria_gpu']['tempo_total_ato2_s']}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
