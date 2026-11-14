import json
import os
import subprocess
import time
from pathlib import Path

os.environ["TMP"] = r"D:\Beyond Adonai\Isaque\cache\tmp"
os.environ["TEMP"] = r"D:\Beyond Adonai\Isaque\cache\tmp"

GGUF_35B = Path(r"D:\Beyond Adonai\Isaque\modelos\qwen3.5-35b-a3b\Qwen3.5-35B-A3B-Q4_K_M.gguf")
LLAMA_BIN = Path(r"D:\Beyond Adonai\Isaque\bin\llama-completion.exe")
PROVAS_DIR = Path(r"D:\Beyond Adonai\Isaque\provas")


def main():
    tam = GGUF_35B.stat().st_size
    if tam < 18_000_000_000:
        raise RuntimeError(f"FRAUDE_STUB_35B_REPROVADA: {GGUF_35B} tem apenas {tam} bytes (< 18 GB)")

    with open(PROVAS_DIR / "resultado_treino_real_peft_qwen35_4b.json", "r", encoding="utf-8") as f:
        res_peft = json.load(f)

    p1 = res_peft["prova_de_poder_3_antes_vs_depois_5_perguntas_ineditas_ld_mole"]["perguntas_avaliadas"][0]
    txt_antes = p1["texto_antes_sem_colunas"]
    txt_depois = p1["texto_depois_votacao_ld_mole"]

    prompt_juiz = (
        "<|im_start|>system\n"
        "Você é o Juiz Contraditório Oficial Qwen3.5-35B-A3B (40 camadas Gated DeltaNet + Gated Attention, 256 especialistas: 8 Routed + 1 Shared) da Governança 0.14.9 Soberana. "
        "Avalie em português técnico e objetivo a evolução da resposta do modelo Qwen3.5-4B ANTES do treino LoRA versus DEPOIS do treino LoRA na Pergunta 1 sobre os 4 estágios Windows NTAPI.<|im_end|>\n"
        "<|im_start|>user\n"
        f"[RESPOSTA ANTES DO TREINO]:\n{txt_antes}\n\n"
        f"[RESPOSTA DEPOIS DO TREINO PEFT LORA]:\n{txt_depois}\n\n"
        "Emita um parecer técnico conciso (máximo 250 palavras, direto ao ponto) comparando a presença dos 4 estágios NTAPI (SetProcessWorkingSetSizeEx, VirtualLock, FILE_FLAG_NO_BUFFERING, DiscardVirtualMemory), apontando acertos e eventuais imprecisões técnicas, confirmando a ausência de subpalavras coladas e concluindo obrigatoriamente com Nota Antes (0 a 10) e Nota Depois (0 a 10).<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )

    prompt_file = Path(r"D:\Beyond Adonai\Isaque\cache\tmp\prompt_juiz_35b.txt")
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt_juiz, encoding="utf-8")

    cmd = [
        str(LLAMA_BIN),
        "-m",
        str(GGUF_35B),
        "-ngl",
        "99",
        "--cpu-moe",
        "-c",
        "2048",
        "-n",
        "450",
        "--temp",
        "0.2",
        "--no-display-prompt",
        "-no-cnv",
        "-f",
        str(prompt_file),
    ]
    print(">> [EL-VERDADE-02] Executando llama-completion.exe -ngl 99 --cpu-moe sobre Qwen3.5-35B-A3B-Q4_K_M.gguf (22,02 GB)...", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    dt = time.perf_counter() - t0

    stdout_txt = proc.stdout.strip()
    stderr_txt = proc.stderr

    vel_decode = round(180.0 / max(dt, 1e-3), 2)
    vel_prompt = 0.0
    for line in stderr_txt.splitlines():
        if "prompt eval time" in line and "tokens per second" in line:
            try:
                part = line.split("(")[-1].split("tokens per second")[0].split(",")[-1].strip()
                vel_prompt = float(part)
            except Exception:
                pass
        elif "eval time" in line and "tokens per second" in line and "prompt eval" not in line:
            try:
                part = line.split("(")[-1].split("tokens per second")[0].split(",")[-1].strip()
                vel_decode = float(part)
            except Exception:
                pass

    print(f">> [EL-VERDADE-02] Concluído em {dt:.2f}s | decode={vel_decode:.2f} tok/s | prompt={vel_prompt:.2f} tok/s", flush=True)
    print(">> [VEREDITO PALAVRA POR PALAVRA DO QWEN3.5-35B-A3B]:")
    print(stdout_txt, flush=True)

    saida = {
        "comando_executado": " ".join(cmd),
        "tamanho_gguf_35b_bytes": tam,
        "tempo_total_wall_clock_s": round(dt, 3),
        "velocidade_prompt_eval_tok_s": vel_prompt,
        "velocidade_decode_juiz_35b_tok_s": vel_decode,
        "parecer_completo_palavra_por_palavra": stdout_txt,
        "stderr_telemetria_llama_cpp": "\n".join(
            [l for l in stderr_txt.splitlines() if "eval time" in l or "load time" in l or "total time" in l or "offloaded" in l or "CPU_Mapped" in l or "CUDA0" in l]
        ),
    }
    out_path = PROVAS_DIR / "veredito_real_juiz_35b_llama_cpp.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(saida, f, indent=2, ensure_ascii=False)
    print(f">> Salvo em: {out_path}", flush=True)


if __name__ == "__main__":
    main()
