#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verificadores Físicos Determinísticos de Domínio para as Ondas 3 a 10 + Teste Combinado Multi-Ondas (Ato 2 & Ato 3):
  - Onda 3 (`BLENDER_CURVES`): Tubulações curvas Bezier pressurizadas + flanges/escadas/guarda-corpos manifold + conexão exata nos Sockets.
  - Onda 4 (`BLENDER_PBR_NODES`): Árvores `ShaderNodeTree` puras por código (`Principled BSDF`, `Noise`, `ColorRamp`, `Bump`, `AO`) sem material rosa/ausente.
  - Onda 5 (`BLENDER_GEONODES`): `GeometryNodeTree` parametrizada avaliada no `depsgraph` com `Realize Instances` gerando `faces > 0`.
  - Onda 6 (`BLENDER_STAGE`): Rig de luz 3 pontos (`Key/Fill/Rim` em Watts) fora do interior da malha + Câmera `DOF` + `Track To` + render EEVEE com luminância válida.
  - Onda 7 (`BLENDER_LOD`): Redução estritamente monotônica `tris(LOD0) > tris(LOD1) > tris(LOD2) > 0` preservando UV.
  - Onda 8 (`UE5_NET_CPP`): `GetLifetimeReplicatedProps`, `DOREPLIFETIME`, `UFUNCTION(Server, Reliable)` e `OnRep_` seguro em `clang++ -std=c++20`.
  - Onda 9 (`UE5_HISM_CPP`): `UHierarchicalInstancedStaticMeshComponent` populando transforms em lote via `DataTable` sem `Tick` em `clang++ -std=c++20`.
  - Onda 10 (`BRIDGE_MANIFEST`): Paridade `1:1` exata entre `Material Slots` e `Sockets` do `.glb`/Blender e do struct C++20 `FIndustrialAssetManifest`.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

BLENDER_EXE = Path(r"D:\Blender\blender.exe")
LAB_DIR = Path(r"D:\Beyond Adonai\Isaque\laboratorio-kev-01")
TEMP_ROOT = LAB_DIR / "temp"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

BLENDER_MULTI_DOMAIN_AUDIT_INNER = r'''
import json
import math
import os
import runpy
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

argv = sys.argv
sep = argv.index("--")
target_script = Path(argv[sep + 1])
cfg_path = Path(argv[sep + 2])
out_path = Path(argv[sep + 3])

cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
export_dir = Path(cfg.get("export_dir", str(target_script.parent)))
export_dir.mkdir(parents=True, exist_ok=True)
os.environ["KEV_EXPORT_DIR"] = str(export_dir)

ok_exec = True
tb_str = ""
exit_code = 0
try:
    sys.argv = [str(target_script), "--", str(export_dir)]
    runpy.run_path(str(target_script), run_name="__main__")
except SystemExit as se:
    c = se.code if isinstance(se.code, int) else (0 if se.code is None else 1)
    exit_code = c
    if c != 0:
        ok_exec = False
        tb_str = f"SystemExit({c})"
except Exception:
    ok_exec = False
    exit_code = 1
    tb_str = traceback.format_exc()

sc = bpy.context.scene
deps = bpy.context.evaluated_depsgraph_get()

# 1. Auditoria de malhas sólidas, curvas e sockets (Onda 1 + Onda 3)
meshes_solid = []
curves_info = []
sockets_map = {}

for obj in sc.objects:
    if obj.type == "EMPTY" and obj.name.startswith("Socket_"):
        sockets_map[obj.name] = [round(float(c), 4) for c in obj.matrix_world.translation]
    elif obj.type == "CURVE":
        cv = obj.data
        splines_pts = []
        for sp in cv.splines:
            if sp.type == 'BEZIER' and len(sp.bezier_points) >= 2:
                p0 = obj.matrix_world @ sp.bezier_points[0].co
                p1 = obj.matrix_world @ sp.bezier_points[-1].co
                splines_pts.append(([round(float(x), 4) for x in p0], [round(float(x), 4) for x in p1]))
            elif len(sp.points) >= 2:
                p0 = obj.matrix_world @ Vector(sp.points[0].co[:3])
                p1 = obj.matrix_world @ Vector(sp.points[-1].co[:3])
                splines_pts.append(([round(float(x), 4) for x in p0], [round(float(x), 4) for x in p1]))
        ev = obj.evaluated_get(deps)
        me_cv = ev.to_mesh()
        n_poly = len(me_cv.polygons) if me_cv else 0
        if me_cv:
            ev.to_mesh_clear()
        curves_info.append({
            "name": obj.name,
            "bevel_depth": round(float(getattr(cv, "bevel_depth", 0.0)), 5),
            "evaluated_faces": n_poly,
            "endpoints": splines_pts,
        })
    elif obj.type == "MESH":
        ev = obj.evaluated_get(deps)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.transform(obj.matrix_world)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
        zero_area = sum(1 for f in bm.faces if f.calc_area() <= 1e-8)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        tris = len(bm.faces)
        xs = [v.co.x for v in bm.verts] or [0.0]
        ys = [v.co.y for v in bm.verts] or [0.0]
        zs = [v.co.z for v in bm.verts] or [0.0]
        uv_count = len(me.uv_layers)
        mat_names = [m.name for m in obj.data.materials if m is not None]
        bm.free()
        ev.to_mesh_clear()
        meshes_solid.append({
            "name": obj.name,
            "tris": tris,
            "non_manifold_edges": non_manifold,
            "zero_area_faces": zero_area,
            "uv_layers": uv_count,
            "bbox_min": [round(min(xs), 4), round(min(ys), 4), round(min(zs), 4)],
            "bbox_max": [round(max(xs), 4), round(max(ys), 4), round(max(zs), 4)],
            "materials": mat_names,
        })

# 2. Auditoria de Materiais PBR Procedurais (Onda 4)
pbr_materials = []
for mat in bpy.data.materials:
    if mat.name == "Dots Stroke":
        continue
    use_n = bool(mat.use_nodes and mat.node_tree is not None)
    node_types = []
    linked_to_surface = False
    metallic_val = None
    roughness_val = None
    transmission_val = None
    if use_n:
        nt = mat.node_tree
        node_types = [n.bl_idname for n in nt.nodes]
        out_nodes = [n for n in nt.nodes if n.bl_idname == "ShaderNodeOutputMaterial"]
        for on in out_nodes:
            surf_in = on.inputs.get("Surface")
            if surf_in and surf_in.is_linked:
                linked_to_surface = True
        bsdfs = [n for n in nt.nodes if n.bl_idname == "ShaderNodeBsdfPrincipled"]
        if bsdfs:
            b0 = bsdfs[0]
            if "Metallic" in b0.inputs:
                metallic_val = round(float(b0.inputs["Metallic"].default_value), 4)
            if "Roughness" in b0.inputs:
                roughness_val = round(float(b0.inputs["Roughness"].default_value), 4)
            for tkey in ("Transmission Weight", "Transmission"):
                if tkey in b0.inputs:
                    transmission_val = round(float(b0.inputs[tkey].default_value), 4)
                    break
    pbr_materials.append({
        "name": mat.name,
        "use_nodes": use_n,
        "linked_to_surface": linked_to_surface,
        "node_types": node_types,
        "metallic": metallic_val,
        "roughness": roughness_val,
        "transmission": transmission_val,
    })

# 3. Auditoria de Geometry Nodes (Onda 5)
geonodes_info = []
for obj in sc.objects:
    for mod in obj.modifiers:
        if mod.type == "NODES" and getattr(mod, "node_group", None) is not None:
            ng = mod.node_group
            ev = obj.evaluated_get(deps)
            me_ev = ev.to_mesh()
            ev_faces = len(me_ev.polygons) if me_ev else 0
            if me_ev:
                ev.to_mesh_clear()
            geonodes_info.append({
                "object": obj.name,
                "node_group": ng.name,
                "node_types": [n.bl_idname for n in ng.nodes],
                "evaluated_faces": ev_faces,
            })

# 4. Auditoria de Palco Cinematográfico: Câmera DOF + TrackTo + Luz 3 Pontos + Luminância EEVEE (Onda 6)
lights_info = []
scene_min = [min([m["bbox_min"][i] for m in meshes_solid], default=-1.0) for i in range(3)]
scene_max = [max([m["bbox_max"][i] for m in meshes_solid], default=1.0) for i in range(3)]

for obj in sc.objects:
    if obj.type == "LIGHT":
        loc = obj.matrix_world.translation
        inside_aabb = (
            (scene_min[0] + 0.05) < loc.x < (scene_max[0] - 0.05)
            and (scene_min[1] + 0.05) < loc.y < (scene_max[1] - 0.05)
            and (scene_min[2] + 0.05) < loc.z < (scene_max[2] - 0.05)
        )
        lights_info.append({
            "name": obj.name,
            "light_type": obj.data.type,
            "energy_watts": round(float(obj.data.energy), 2),
            "location": [round(float(c), 3) for c in loc],
            "outside_mesh_interior": not inside_aabb,
        })

cam_info = {"has_active_camera": sc.camera is not None, "use_dof": False, "has_track_to": False}
if sc.camera is not None:
    cam_obj = sc.camera
    cam_info["name"] = cam_obj.name
    cam_info["use_dof"] = bool(getattr(cam_obj.data, "dof", None) and cam_obj.data.dof.use_dof)
    cam_info["has_track_to"] = any(c.type in ("TRACK_TO", "DAMPED_TRACK") for c in cam_obj.constraints)

eevee_luma = None
if cfg.get("render_eevee_check", False) and sc.camera is not None:
    rnd_path = export_dir / "eevee_stage_audit.png"
    avail_engines = {e.identifier for e in sc.render.bl_rna.properties["engine"].enum_items}
    if "BLENDER_EEVEE_NEXT" in avail_engines:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in avail_engines:
        sc.render.engine = "BLENDER_EEVEE"
    else:
        sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = 320
    sc.render.resolution_y = 180
    sc.render.filepath = str(rnd_path)
    try:
        bpy.ops.render.render(write_still=True)
        if rnd_path.is_file():
            img = bpy.data.images.load(str(rnd_path))
            px = list(img.pixels[:])
            n_px = max(len(px) // 4, 1)
            luma_acc = 0.0
            for i in range(0, len(px), 4):
                luma_acc += 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2]
            eevee_luma = round(luma_acc / n_px, 5)
            bpy.data.images.remove(img)
    except Exception:
        eevee_luma = None

# 5. Auditoria de LODs (Onda 7)
lods_map = {}
for m in meshes_solid:
    nm_up = m["name"].upper()
    if "LOD0" in nm_up:
        lods_map["LOD0"] = m
    elif "LOD1" in nm_up:
        lods_map["LOD1"] = m
    elif "LOD2" in nm_up:
        lods_map["LOD2"] = m

# 6. Arquivos exportados (.glb/.fbx)
glb_files = [str(p) for p in export_dir.glob("*.glb") if p.stat().st_size > 120]

report = {
    "ok_exec": ok_exec,
    "exit_code": exit_code,
    "traceback": tb_str[-1500:],
    "unit_system": str(sc.unit_settings.system),
    "unit_scale": round(float(sc.unit_settings.scale_length), 4),
    "meshes_solid": meshes_solid,
    "curves_info": curves_info,
    "sockets_map": sockets_map,
    "pbr_materials": pbr_materials,
    "geonodes_info": geonodes_info,
    "lights_info": lights_info,
    "camera_info": cam_info,
    "eevee_mean_luminance": eevee_luma,
    "lods_map": lods_map,
    "glb_files": glb_files,
}
out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
'''


def auditar_script_blender_multidominio(script_path: Path, dominios_ativos: list[str], export_dir: Path | None = None) -> dict:
    """
    Executa `script_path` no Blender 5.2 Headless e valida fisicamente todos os domínios solicitados
    (`ONDA_1`, `ONDA_3`, `ONDA_4`, `ONDA_5`, `ONDA_6`, `ONDA_7`, `ONDA_10`).
    """
    t0 = time.perf_counter()
    work_tmp = Path(tempfile.mkdtemp(prefix="kev_w3_10_", dir=str(TEMP_ROOT)))
    exp_d = export_dir or (work_tmp / "exports")
    exp_d.mkdir(parents=True, exist_ok=True)

    inner_py = work_tmp / "_audit_inner.py"
    cfg_json = work_tmp / "_cfg.json"
    out_json = work_tmp / "_out.json"

    inner_py.write_text(BLENDER_MULTI_DOMAIN_AUDIT_INNER, encoding="utf-8")
    cfg_json.write_text(
        json.dumps(
            {
                "export_dir": str(exp_d),
                "render_eevee_check": ("ONDA_6" in dominios_ativos),
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            str(BLENDER_EXE),
            "--background",
            "--factory-startup",
            "--python",
            str(inner_py),
            "--",
            str(script_path),
            str(cfg_json),
            str(out_json),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    dt = round(time.perf_counter() - t0, 3)

    if not out_json.is_file():
        return {
            "aprovado_fisico": False,
            "violacoes": [f"Blender CLI falhou rc={proc.returncode}: {(proc.stderr or '')[-500:]}"],
            "latencia_s": dt,
        }

    rep = json.loads(out_json.read_text(encoding="utf-8"))
    violacoes = []
    if not rep["ok_exec"] or rep["exit_code"] != 0:
        violacoes.append(f"EXEC_ERROR: exit={rep['exit_code']} tb={rep['traceback'][-400:]}")

    meshes = rep["meshes_solid"]
    # Onda 1: sólidos fechados manifold + UCX_
    if "ONDA_1" in dominios_ativos:
        ucx_list = [m for m in meshes if m["name"].upper().startswith("UCX_")]
        vis_list = [m for m in meshes if not m["name"].upper().startswith("UCX_")]
        if not vis_list:
            violacoes.append("ONDA_1: nenhuma malha visual sólida encontrada.")
        if not ucx_list:
            violacoes.append("ONDA_1: colisor UCX_ ausente.")
        for m in ucx_list:
            if m["non_manifold_edges"] > 0:
                violacoes.append(f"ONDA_1: UCX {m['name']} possui {m['non_manifold_edges']} arestas non-manifold.")

    # Onda 3: Curvas Bezier com bevel/geometria + conexão nos Sockets + sólidos manifold
    if "ONDA_3" in dominios_ativos:
        curves = rep["curves_info"]
        socks = rep["sockets_map"]
        if not curves:
            violacoes.append("ONDA_3: nenhum objeto CURVE (tubulação Bezier) encontrado.")
        else:
            has_valid_pipe = any(c["bevel_depth"] > 0.001 and c["evaluated_faces"] > 0 for c in curves)
            if not has_valid_pipe:
                violacoes.append("ONDA_3: curva sem bevel_depth > 0 ou sem faces avaliadas.")
            if socks:
                connected_socks = 0
                for sname, spos in socks.items():
                    for c in curves:
                        for p0, p1 in c["endpoints"]:
                            d0 = sum((spos[i] - p0[i]) ** 2 for i in range(3)) ** 0.5
                            d1 = sum((spos[i] - p1[i]) ** 2 for i in range(3)) ** 0.5
                            if min(d0, d1) <= 0.15:
                                connected_socks += 1
                                break
                if connected_socks < 1:
                    violacoes.append(f"ONDA_3: extremidades dos tubos não conectam nos Sockets ({socks}).")
        solid_closed = [
            m for m in meshes
            if not any(k in m["name"].upper() for k in ("GRID", "FLOOR", "PLANE", "GEONODE"))
        ]
        for m in solid_closed:
            if m["non_manifold_edges"] > 0:
                violacoes.append(f"ONDA_3: sólido {m['name']} tem non_manifold_edges={m['non_manifold_edges']}.")

    # Onda 4: Materiais PBR Procedurais
    if "ONDA_4" in dominios_ativos:
        mats = rep["pbr_materials"]
        if len(mats) < 3:
            violacoes.append(f"ONDA_4: esperados >= 3 materiais PBR procedurais, encontrados {len(mats)}.")
        for m in mats:
            if not m["use_nodes"] or not m["linked_to_surface"]:
                violacoes.append(f"ONDA_4: material {m['name']} sem ShaderNodeTree ativo ou desconectado de Surface.")
            if "ShaderNodeBsdfPrincipled" not in m["node_types"]:
                violacoes.append(f"ONDA_4: material {m['name']} sem Principled BSDF.")
        has_proc_tex = any(
            any(t in m["node_types"] for t in ("ShaderNodeTexNoise", "ShaderNodeValToRGB", "ShaderNodeBump", "ShaderNodeAmbientOcclusion"))
            for m in mats
        )
        if not has_proc_tex:
            violacoes.append("ONDA_4: nenhum nó procedural (Noise/ColorRamp/Bump/AO) encontrado nas árvores PBR.")

    # Onda 5: Geometry Nodes avaliados no depsgraph
    if "ONDA_5" in dominios_ativos:
        gns = rep["geonodes_info"]
        if not gns:
            violacoes.append("ONDA_5: nenhum modificador GeometryNodes encontrado.")
        elif not any(g["evaluated_faces"] > 0 for g in gns):
            violacoes.append("ONDA_5: árvore GeometryNodes gerou 0 faces avaliadas no depsgraph.")

    # Onda 6: Câmera DOF + TrackTo + >= 3 Luzes fora da malha + Luminância EEVEE válida
    if "ONDA_6" in dominios_ativos:
        ci = rep["camera_info"]
        li = rep["lights_info"]
        luma = rep["eevee_mean_luminance"]
        if not ci["has_active_camera"] or not ci["use_dof"] or not ci["has_track_to"]:
            violacoes.append(f"ONDA_6: câmera inválida ({ci}).")
        valid_lights = [l for l in li if l["energy_watts"] > 1.0 and l["outside_mesh_interior"]]
        if len(valid_lights) < 3:
            violacoes.append(f"ONDA_6: esperadas >= 3 luzes externas calibradas em Watts, encontradas {len(valid_lights)}.")
        if luma is None or not (0.02 <= luma <= 0.96):
            violacoes.append(f"ONDA_6: luminância média do render EEVEE fora da faixa alvo ({luma}).")

    # Onda 7: LOD0 > LOD1 > LOD2 > 0
    if "ONDA_7" in dominios_ativos:
        lm = rep["lods_map"]
        if not all(k in lm for k in ("LOD0", "LOD1", "LOD2")):
            violacoes.append(f"ONDA_7: LOD0/LOD1/LOD2 incompletos (encontrados: {list(lm.keys())}).")
        else:
            t0_l, t1_l, t2_l = lm["LOD0"]["tris"], lm["LOD1"]["tris"], lm["LOD2"]["tris"]
            if not (t0_l > t1_l > t2_l > 0):
                violacoes.append(f"ONDA_7: violação de redução monotônica tris ({t0_l} > {t1_l} > {t2_l} > 0 falso).")
            if any(lm[k]["uv_layers"] < 1 for k in ("LOD0", "LOD1", "LOD2")):
                violacoes.append("ONDA_7: perda de camada UV em um dos LODs.")

    rep["aprovado_fisico"] = len(violacoes) == 0
    rep["violacoes"] = violacoes
    rep["latencia_s"] = dt
    return rep


def auditar_ue5_onda8_9_10(
    header_path: Path,
    source_path: Path,
    modo_onda: str,
    blender_manifest_audit: dict | None = None,
    ue5_verifier_exe: Path = LAB_DIR / "bin" / "verificador_fisico_ue5_cpp.exe",
) -> dict:
    """
    Valida fisicamente `header_path` + `source_path` via `verificador_fisico_ue5_cpp.exe` (`8/8` UHT + `clang++ -std=c++20`)
    mais as invariantes específicas da Onda 8 (`UE5_NET_CPP`), Onda 9 (`UE5_HISM_CPP`) ou Onda 10 (`BRIDGE_MANIFEST` 1:1).
    """
    import re

    proc = subprocess.run(
        [str(ue5_verifier_exe), "--header", str(header_path), "--source", str(source_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    base_rec = json.loads(proc.stdout)
    violacoes = list(base_rec.get("violacoes", []))
    h_txt = header_path.read_text(encoding="utf-8", errors="ignore")
    cpp_txt = source_path.read_text(encoding="utf-8", errors="ignore")

    if modo_onda == "ONDA_8":
        if "GetLifetimeReplicatedProps" not in h_txt or "GetLifetimeReplicatedProps" not in cpp_txt:
            violacoes.append("ONDA_8: `GetLifetimeReplicatedProps` ausente em `.h` ou `.cpp`.")
        if "DOREPLIFETIME" not in cpp_txt:
            violacoes.append("ONDA_8: macro `DOREPLIFETIME` ausente em `.cpp`.")
        if not re.search(r"UFUNCTION\s*\([^)]*Server[^)]*Reliable", h_txt, re.I):
            violacoes.append("ONDA_8: `UFUNCTION(Server, Reliable)` ausente no `.h`.")
        if not re.search(r"ReplicatedUsing\s*=\s*OnRep_", h_txt):
            violacoes.append("ONDA_8: `UPROPERTY(ReplicatedUsing=OnRep_...)` ausente no `.h`.")

    elif modo_onda == "ONDA_9":
        if "UHierarchicalInstancedStaticMeshComponent" not in h_txt:
            violacoes.append("ONDA_9: `UHierarchicalInstancedStaticMeshComponent` ausente no `.h`.")
        if "FTableRowBase" not in h_txt and "UDataTable" not in h_txt:
            violacoes.append("ONDA_9: `UDataTable` / `FTableRowBase` ausente no `.h`.")
        if "AddInstance" not in cpp_txt and "AddInstances" not in cpp_txt:
            violacoes.append("ONDA_9: população em lote `AddInstance`/`AddInstances` ausente no `.cpp`.")
        if "bCanEverTick = true" in cpp_txt:
            violacoes.append("ONDA_9: `bCanEverTick = true` proibido em HISM Data-Driven.")

    elif modo_onda == "ONDA_10":
        if "FIndustrialAssetManifest" not in h_txt:
            violacoes.append("ONDA_10: struct `FIndustrialAssetManifest` ausente no `.h`.")
        if blender_manifest_audit is not None:
            bl_mats = sorted({m["name"] for m in blender_manifest_audit.get("pbr_materials", [])})
            bl_socks = sorted(blender_manifest_audit.get("sockets_map", {}).keys())
            bl_lods = sorted(blender_manifest_audit.get("lods_map", {}).keys())
            combined_cpp = h_txt + "\n" + cpp_txt
            missing_mats = [mn for mn in bl_mats if f'"{mn}"' not in combined_cpp]
            missing_socks = [sn for sn in bl_socks if f'"{sn}"' not in combined_cpp]
            if missing_mats:
                violacoes.append(f"ONDA_10: Material Slots do Blender ausentes no C++20: {missing_mats}")
            if missing_socks:
                violacoes.append(f"ONDA_10: Sockets do Blender ausentes no C++20: {missing_socks}")
            if len(bl_lods) < 3:
                violacoes.append(f"ONDA_10: Esperados LOD0..LOD2 no Blender, encontrados: {bl_lods}")

    base_rec["modo_onda"] = modo_onda
    base_rec["violacoes"] = violacoes
    base_rec["aprovado_fisico"] = bool(base_rec.get("aprovado_mecanico")) and len(violacoes) == 0
    return base_rec
