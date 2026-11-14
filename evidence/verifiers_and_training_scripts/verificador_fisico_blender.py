#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verificador Físico Determinístico Blender 5.2 Headless + BMesh Audit (`Zero Achismo` — Seção 4.1)
Executa scripts `.py` gerados em `D:\\Blender\\blender.exe --background --factory-startup`
e audita via `bmesh`:
  1. exit_code == 0 e zero Traceback;
  2. non_manifold_edges == 0 nos colisores `UCX_*` e nas peças sólidas fechadas;
  3. zero_area_faces == 0 e normais externas consistentes (volume assinado > 0);
  4. unit_scale == 1.0 (METRIC), pivot_z_min_aligned == true e bounding_box_m dentro de +-2% de @SPACE;
  5. UV layer presente sem degenerescência crítica, sockets (`Socket_*`) auditados (m -> cm UE5),
     exportação real `.glb` / `.fbx` validada em disco + render ortográfico rápido Workbench headless.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_BLENDER_EXE = Path(r"D:\Blender\blender.exe")
LAB_TEMP_DIR = Path(r"D:\Beyond Adonai\Isaque\laboratorio-kev-01\temp")

BLENDER_INNER_AUDIT_CODE = r'''
import json
import math
import os
import runpy
import sys
import traceback
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector, Matrix

argv = sys.argv
sep = argv.index("--")
target_script = Path(argv[sep + 1])
spec_json_path = Path(argv[sep + 2])
out_json_path = Path(argv[sep + 3])

spec = json.loads(spec_json_path.read_text(encoding="utf-8"))
export_dir = Path(spec.get("export_dir", str(target_script.parent)))
export_dir.mkdir(parents=True, exist_ok=True)
os.environ["KEV_EXPORT_DIR"] = str(export_dir)

script_ok = True
script_traceback = ""
script_exit_code = 0

try:
    # Limpar cena inicial padrão antes de rodar se necessário? Não: factory-startup já inicia limpo
    # e scripts bem formados limpam o cubo default; rodamos exatamente o script gerado.
    sys.argv = [str(target_script), "--", str(export_dir)]
    runpy.run_path(str(target_script), run_name="__main__")
except SystemExit as se:
    code = se.code if isinstance(se.code, int) else (0 if se.code is None else 1)
    script_exit_code = code
    if code != 0:
        script_ok = False
        script_traceback = f"SystemExit({code})"
except Exception:
    script_ok = False
    script_exit_code = 1
    script_traceback = traceback.format_exc()

scene = bpy.context.scene
depsgraph = bpy.context.evaluated_depsgraph_get()

unit_system = str(scene.unit_settings.system)
unit_scale = round(float(scene.unit_settings.scale_length), 6)

mesh_objects = [o for o in scene.objects if o.type == "MESH"]
empty_objects = [o for o in scene.objects if o.type == "EMPTY"]

visual_meshes = [o for o in mesh_objects if not o.name.upper().startswith("UCX_")]
ucx_meshes = [o for o in mesh_objects if o.name.upper().startswith("UCX_")]

def calc_signed_volume_and_audit(obj):
    eval_obj = obj.evaluated_get(depsgraph)
    me = eval_obj.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(obj.matrix_world)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    non_manifold = sum(1 for e in bm.edges if not e.is_manifold)
    zero_area = sum(1 for f in bm.faces if f.calc_area() <= 1e-8)
    zero_normals = sum(1 for f in bm.faces if f.normal.length <= 1e-6)

    signed_vol = 0.0
    for f in bm.faces:
        if len(f.verts) == 3:
            p1, p2, p3 = f.verts[0].co, f.verts[1].co, f.verts[2].co
            signed_vol += p1.dot(p2.cross(p3)) / 6.0

    xs = [v.co.x for v in bm.verts]
    ys = [v.co.y for v in bm.verts]
    zs = [v.co.z for v in bm.verts]
    bbox_min = [min(xs), min(ys), min(zs)] if xs else [0.0, 0.0, 0.0]
    bbox_max = [max(xs), max(ys), max(zs)] if xs else [0.0, 0.0, 0.0]
    dims = [bbox_max[0] - bbox_min[0], bbox_max[1] - bbox_min[1], bbox_max[2] - bbox_min[2]]

    uv_layers_count = len(me.uv_layers)
    uv_area_total = 0.0
    if uv_layers_count > 0 and bm.loops.layers.uv.active is not None:
        uv_layer = bm.loops.layers.uv.active
        for f in bm.faces:
            if len(f.loops) == 3:
                u0 = f.loops[0][uv_layer].uv
                u1 = f.loops[1][uv_layer].uv
                u2 = f.loops[2][uv_layer].uv
                uv_area_total += abs((u1.x - u0.x) * (u2.y - u0.y) - (u2.x - u0.x) * (u1.y - u0.y)) * 0.5

    n_verts = len(bm.verts)
    n_faces = len(bm.faces)
    bm.free()
    eval_obj.to_mesh_clear()

    loc = obj.matrix_world.translation
    return {
        "name": obj.name,
        "is_ucx": obj.name.upper().startswith("UCX_"),
        "verts": n_verts,
        "tris": n_faces,
        "origin_world_m": [round(loc.x, 5), round(loc.y, 5), round(loc.z, 5)],
        "bbox_min_m": [round(v, 5) for v in bbox_min],
        "bbox_max_m": [round(v, 5) for v in bbox_max],
        "dimensions_m": [round(v, 5) for v in dims],
        "non_manifold_edges": int(non_manifold),
        "zero_area_faces": int(zero_area),
        "zero_normals": int(zero_normals),
        "signed_volume_m3": round(signed_vol, 6),
        "normals_outward_consistent": bool(signed_vol > 1e-7 and zero_normals == 0),
        "uv_layers": int(uv_layers_count),
        "uv_area_total": round(uv_area_total, 6),
    }

visual_audits = [calc_signed_volume_and_audit(o) for o in visual_meshes]
ucx_audits = [calc_signed_volume_and_audit(o) for o in ucx_meshes]

total_non_manifold_visual = sum(a["non_manifold_edges"] for a in visual_audits)
total_non_manifold_ucx = sum(a["non_manifold_edges"] for a in ucx_audits)
total_non_manifold = total_non_manifold_visual + total_non_manifold_ucx
total_zero_area = sum(a["zero_area_faces"] for a in visual_audits + ucx_audits)
normals_consistent = (
    len(visual_audits) > 0
    and all(a["normals_outward_consistent"] for a in visual_audits + ucx_audits)
)
uv_ok = len(visual_audits) > 0 and all(a["uv_layers"] >= 1 and a["uv_area_total"] > 1e-5 for a in visual_audits)

# Bounding box global das malhas visuais (ou da malha primária se houver múltiplas variações posicionadas lado a lado)
primary_filter_prefix = spec.get("primary_prefix", "")
target_audits = [
    a for a in visual_audits
    if not primary_filter_prefix or a["name"].startswith(primary_filter_prefix)
]
if not target_audits:
    target_audits = visual_audits

if target_audits:
    g_min = [
        min(a["bbox_min_m"][0] for a in target_audits),
        min(a["bbox_min_m"][1] for a in target_audits),
        min(a["bbox_min_m"][2] for a in target_audits),
    ]
    g_max = [
        max(a["bbox_max_m"][0] for a in target_audits),
        max(a["bbox_max_m"][1] for a in target_audits),
        max(a["bbox_max_m"][2] for a in target_audits),
    ]
    g_dims = [round(g_max[i] - g_min[i], 5) for i in range(3)]
    primary_origin = target_audits[0]["origin_world_m"]
else:
    g_min = [0.0, 0.0, 0.0]
    g_max = [0.0, 0.0, 0.0]
    g_dims = [0.0, 0.0, 0.0]
    primary_origin = [999.0, 999.0, 999.0]

# Pivot Z_min alinhado: base da malha apoiada em Z=0 (+-0.01m) e origem da peça primária em (0,0,0) (+-0.01m)
pivot_origin_zero = all(abs(c) <= 0.01 for c in primary_origin)
z_min_aligned = len(target_audits) > 0 and abs(g_min[2]) <= 0.015
pivot_z_min_aligned = bool(pivot_origin_zero and z_min_aligned)

# Checagem de bounding_box_m dentro de +-2% da especificação @SPACE (quando fornecida)
expected_bbox = spec.get("expected_bbox_m")
tol_pct = float(spec.get("bbox_tolerance_pct", 2.0)) / 100.0
bbox_within_tol = True
bbox_rel_errors = [0.0, 0.0, 0.0]
if expected_bbox and len(expected_bbox) == 3:
    if len(target_audits) == 0:
        bbox_within_tol = False
    else:
        for i in range(3):
            exp_v = float(expected_bbox[i])
            act_v = float(g_dims[i])
            rel_err = abs(act_v - exp_v) / max(exp_v, 1e-6)
            bbox_rel_errors[i] = round(rel_err * 100.0, 4)
            if rel_err > tol_pct:
                bbox_within_tol = False

# Sockets (`EMPTY` ou objetos começando por `Socket_`)
sockets = []
for eo in empty_objects:
    loc = eo.matrix_world.translation
    sockets.append({
        "name": eo.name,
        "parent": eo.parent.name if eo.parent else None,
        "location_blender_m": [round(loc.x, 5), round(loc.y, 5), round(loc.z, 5)],
        "location_ue5_cm": [round(loc.x * 100.0, 3), round(loc.y * 100.0, 3), round(loc.z * 100.0, 3)],
    })

required_sockets = spec.get("required_sockets", [])
found_socket_names = {s["name"] for s in sockets}
sockets_ok = all(any(req in fn for fn in found_socket_names) for req in required_sockets)

min_variations = int(spec.get("min_visual_meshes", 1))
variations_ok = len(visual_audits) >= min_variations
require_ucx = bool(spec.get("require_ucx", True))
ucx_ok = (len(ucx_audits) >= 1 and total_non_manifold_ucx == 0) if require_ucx else True

# Verificar arquivos exportados (.glb / .fbx) em export_dir ou ao lado do script
search_dirs = list({export_dir.resolve(), target_script.parent.resolve()})
exported_files = []
for sdir in search_dirs:
    for ext in ("*.glb", "*.gltf", "*.fbx"):
        for fp in sorted(sdir.glob(ext)):
            sz = fp.stat().st_size
            if sz > 128:
                with open(fp, "rb") as fbin:
                    magic = fbin.read(18)
                valid_header = (
                    (fp.suffix.lower() == ".glb" and magic[:4] == b"glTF")
                    or (fp.suffix.lower() == ".fbx" and b"Kaydara" in magic)
                    or (fp.suffix.lower() == ".gltf" and b"asset" in magic)
                )
                exported_files.append({
                    "path": str(fp),
                    "format": fp.suffix.lower().lstrip("."),
                    "size_bytes": sz,
                    "valid_binary_header": bool(valid_header),
                })

exports_ok = any(ef["valid_binary_header"] and ef["size_bytes"] > 256 for ef in exported_files)

# Render ortográfico rápido Workbench headless (opcional, sem falhar se GPU/OpenGL offscreen indisponível em serviço)
render_preview_path = None
render_ok = False
if spec.get("try_headless_render", True) and len(visual_audits) > 0:
    try:
        cam_data = bpy.data.cameras.new("KEV_Audit_OrthoCam")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = max(g_dims[0], g_dims[1], g_dims[2], 1.0) * 1.65
        cam_obj = bpy.data.objects.new("KEV_Audit_OrthoCam", cam_data)
        scene.collection.objects.link(cam_obj)
        cx = (g_min[0] + g_max[0]) * 0.5
        cy = (g_min[1] + g_max[1]) * 0.5
        cz = (g_min[2] + g_max[2]) * 0.5
        dist = max(g_dims) * 2.5 + 2.0
        cam_obj.location = (cx + dist * 0.7, cy - dist * 0.85, cz + dist * 0.55)
        direction = Vector((cx, cy, cz)) - cam_obj.location
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        scene.camera = cam_obj
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x = 512
        scene.render.resolution_y = 512
        out_png = export_dir / "audit_workbench_ortho.png"
        scene.render.filepath = str(out_png)
        bpy.ops.render.render(write_still=True)
        if out_png.is_file() and out_png.stat().st_size > 512:
            render_preview_path = str(out_png)
            render_ok = True
    except Exception:
        render_ok = False

unit_ok = (unit_system == "METRIC" and abs(unit_scale - 1.0) <= 1e-4)

violacoes = []
if not script_ok or script_exit_code != 0 or script_traceback:
    violacoes.append(f"EXECUCAO_FALHOU: exit={script_exit_code} traceback={script_traceback[-400:]}")
if not variations_ok:
    violacoes.append(f"VARIACOES_INSUFICIENTES: esperado >= {min_variations} malhas visuais, obteve {len(visual_audits)}")
if not ucx_ok:
    violacoes.append(f"UCX_INVALIDO: ucx_count={len(ucx_audits)}, non_manifold_ucx={total_non_manifold_ucx}")
if total_non_manifold > 0:
    violacoes.append(f"NON_MANIFOLD_EDGES: {total_non_manifold} arestas abertas/não-manifold detectadas")
if total_zero_area > 0:
    violacoes.append(f"ZERO_AREA_FACES: {total_zero_area} faces degeneradas de área zero")
if not normals_consistent:
    violacoes.append("NORMAIS_INCONSISTENTES: volume assinado <= 0 ou normais degeneradas")
if not unit_ok:
    violacoes.append(f"ESCALA_UNIDADE_INVALIDA: system={unit_system}, scale_length={unit_scale} (exigido METRIC 1.0)")
if not pivot_z_min_aligned:
    violacoes.append(f"PIVOT_DESALINHADO: origin={primary_origin}, bbox_min={g_min} (exigido pivô (0,0,0) e Z_min=0)")
if not bbox_within_tol:
    violacoes.append(f"BOUNDING_BOX_FORA_DE_2PCT: medido={g_dims} vs esperado={expected_bbox} (erro_pct={bbox_rel_errors})")
if not uv_ok:
    violacoes.append("UV_AUSENTE_OU_DEGENERADA: malha visual sem UV válida")
if not sockets_ok:
    violacoes.append(f"SOCKETS_AUSENTES: requeridos={required_sockets}, encontrados={sorted(found_socket_names)}")
if not exports_ok:
    violacoes.append("EXPORT_GLB_FBX_AUSENTE: nenhum arquivo .glb/.fbx válido gravado em disco")

aprovado = len(violacoes) == 0

report = {
    "schema": "isaque.kev01.verificador_fisico_blender/1.0",
    "blender_version": bpy.app.version_string,
    "script_path": str(target_script),
    "aprovado_mecanico": aprovado,
    "exit_code": int(script_exit_code),
    "zero_traceback": bool(script_ok and not script_traceback),
    "traceback": script_traceback,
    "unit_system": unit_system,
    "unit_scale": unit_scale,
    "non_manifold_edges": int(total_non_manifold),
    "non_manifold_edges_ucx": int(total_non_manifold_ucx),
    "zero_area_faces": int(total_zero_area),
    "normals_consistent": normals_consistent,
    "uv_unwrapped_valid": uv_ok,
    "pivot_z_min_aligned": pivot_z_min_aligned,
    "primary_origin_m": primary_origin,
    "bounding_box_min_m": g_min,
    "bounding_box_max_m": g_max,
    "bounding_box_m": g_dims,
    "expected_bbox_m": expected_bbox,
    "bbox_error_pct": bbox_rel_errors,
    "bbox_within_2pct": bbox_within_tol,
    "visual_meshes": visual_audits,
    "ucx_colliders": ucx_audits,
    "sockets": sockets,
    "exported_files": exported_files,
    "headless_workbench_render_ok": render_ok,
    "headless_workbench_preview": render_preview_path,
    "violacoes": violacoes,
}

out_json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
'''


def verificar_script_blender(
    script_path: Path,
    expected_bbox_m: list[float] | None = None,
    bbox_tolerance_pct: float = 2.0,
    require_ucx: bool = True,
    required_sockets: list[str] | None = None,
    min_visual_meshes: int = 1,
    primary_prefix: str = "",
    export_dir: Path | None = None,
    try_headless_render: bool = True,
    blender_exe: Path = DEFAULT_BLENDER_EXE,
    timeout_s: float = 90.0,
) -> dict:
    if not blender_exe.is_file():
        return {
            "ok": False,
            "aprovado_mecanico": False,
            "bloqueio": f"BLOQUEADO_DEPENDENCIA_AUSENTE: blender.exe não encontrado em {blender_exe}",
        }
    if not script_path.is_file():
        return {
            "ok": False,
            "aprovado_mecanico": False,
            "violacoes": [f"SCRIPT_INEXISTENTE: {script_path}"],
        }

    LAB_TEMP_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="blender_audit_", dir=str(LAB_TEMP_DIR)))
    inner_py = run_dir / "_inner_bmesh_audit.py"
    spec_json = run_dir / "_spec.json"
    out_json = run_dir / "_audit_result.json"

    exp_dir = export_dir if export_dir is not None else (run_dir / "exports")
    exp_dir.mkdir(parents=True, exist_ok=True)

    inner_py.write_text(BLENDER_INNER_AUDIT_CODE, encoding="utf-8")
    spec_json.write_text(
        json.dumps(
            {
                "expected_bbox_m": expected_bbox_m,
                "bbox_tolerance_pct": bbox_tolerance_pct,
                "require_ucx": require_ucx,
                "required_sockets": required_sockets or [],
                "min_visual_meshes": min_visual_meshes,
                "primary_prefix": primary_prefix,
                "export_dir": str(exp_dir),
                "try_headless_render": try_headless_render,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["TEMP"] = str(LAB_TEMP_DIR)
    env["TMP"] = str(LAB_TEMP_DIR)
    env["KEV_EXPORT_DIR"] = str(exp_dir)

    t0 = time.perf_counter()
    cmd = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(inner_py),
        "--",
        str(script_path.resolve()),
        str(spec_json.resolve()),
        str(out_json.resolve()),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "schema": "isaque.kev01.verificador_fisico_blender/1.0",
            "aprovado_mecanico": False,
            "exit_code": -1,
            "zero_traceback": False,
            "latencia_verificacao_s": round(time.perf_counter() - t0, 3),
            "violacoes": [f"TIMEOUT_BLENDER_HEADLESS ({timeout_s}s)"],
        }

    dt = round(time.perf_counter() - t0, 3)
    stderr_txt = (proc.stderr or "").strip()
    stdout_txt = (proc.stdout or "").strip()
    has_outer_tb = "Traceback (most recent call last)" in stderr_txt or "Traceback (most recent call last)" in stdout_txt

    if not out_json.is_file():
        return {
            "schema": "isaque.kev01.verificador_fisico_blender/1.0",
            "aprovado_mecanico": False,
            "exit_code": proc.returncode,
            "zero_traceback": not has_outer_tb,
            "latencia_verificacao_s": dt,
            "violacoes": [
                f"BLENDER_CRASH_SEM_RECIBO: returncode={proc.returncode} stderr={stderr_txt[-500:]}"
            ],
        }

    report = json.loads(out_json.read_text(encoding="utf-8"))
    report["blender_cli_returncode"] = proc.returncode
    report["latencia_verificacao_s"] = dt
    if proc.returncode != 0 or has_outer_tb:
        report["aprovado_mecanico"] = False
        report["zero_traceback"] = False
        report["violacoes"].append(
            f"CLI_EXIT_OR_TRACEBACK: rc={proc.returncode}, outer_tb={has_outer_tb}"
        )
    return report


def main():
    ap = argparse.ArgumentParser(description="Verificador Físico Blender 5.2 Headless + BMesh")
    ap.add_argument("--script", required=True, help="Caminho do script .py gerado")
    ap.add_argument("--bbox", nargs=3, type=float, default=None, help="Dimensões esperadas X Y Z em metros")
    ap.add_argument("--tol-pct", type=float, default=2.0)
    ap.add_argument("--no-ucx", action="store_true")
    ap.add_argument("--sockets", nargs="*", default=[])
    ap.add_argument("--min-meshes", type=int, default=1)
    ap.add_argument("--primary-prefix", default="")
    ap.add_argument("--export-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    res = verificar_script_blender(
        script_path=Path(args.script),
        expected_bbox_m=args.bbox,
        bbox_tolerance_pct=args.tol_pct,
        require_ucx=not args.no_ucx,
        required_sockets=args.sockets,
        min_visual_meshes=args.min_meshes,
        primary_prefix=args.primary_prefix,
        export_dir=Path(args.export_dir) if args.export_dir else None,
    )
    txt = json.dumps(res, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(txt, encoding="utf-8")
    print(txt)
    sys.exit(0 if res.get("aprovado_mecanico") else 1)


if __name__ == "__main__":
    main()
