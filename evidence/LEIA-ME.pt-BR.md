# Anexo de Evidências Forenses e Recibos Brutos — Isaque 2.0 (Tronco e Ramos)

* **DOI Oficial CERN/Zenodo:** [`10.5281/zenodo.24221509`](https://doi.org/10.5281/zenodo.24221509)
* **Anexo Forense Compilado PDF (Português):** [`anexo_evidencias_forenses_pt_br_doi_24221509.pdf`](anexo_evidencias_forenses_pt_br_doi_24221509.pdf)
* **Compiled Forensic Annex PDF (English):** [`annex_forensic_evidence_en_doi_24221509.pdf`](annex_forensic_evidence_en_doi_24221509.pdf)

## O Que Está Arquivado Aqui (Rigor `R-VERDADE-OU-AJUDA`)

1. **`receipts_act2_10waves/`**:
   - `PROVA_LIMITE_RUPTURA_E_BLENDER_AO_VIVO_02.json` (`70.457` B, SHA-256 `9a47a690..9da977b61033`) e `ato2_escada_ondas_3_a_10.json` (`58.311` B, SHA-256 `fcd12dd3..5ab83604dccd`): Escada completa com as **195 medições reais** (`65` células triangulares por regime nas Ondas `1..10` x `3` regimes: Monolítico, Cluster `LD-MoLE` e `LD-MoLE Top-2` cirúrgico).
   - **Definição Exata de `H0` vs. `H1..Hk`:** Os mínimos resumidos da curva avaliam as ondas aprendidas `H1..Hk` (ex.: `89,905%` em `H1` e `96,995%` de acurácia em `H3` no degrau `k=4`), enquanto a base pré-treino `H0_MotorHumano_0150` é acompanhada separadamente (`82,848%` de verossimilhança / `95,368%` de acurácia em `k=4`).
   - `ato1_desafio04_cego.json` e `ato1_promocao_e_precheck_ondas3_10.json`: Falha real no teste cego fora da distribuição (`pass@1 = false`, `7/8` invariantes C++20 por uso de `IsValid` em ponteiro `USTRUCT*` na linha 35).
2. **`receipts_ots_stage1/`**:
   - Recibos JSON originais ancorados no **Bloco `#975458` do Bitcoin** (`PROVA_ARENA_KEV_MOTOR_HUMANO_01.json`, `prova_treino_dora_olora_kev01.json`, `resultado_treino_real_peft_qwen35_4b.json`, `veredito_real_juiz_35b_llama_cpp.json`, `pre01_semble_prewarm.json`, `cli_auditar_hardware.json`).
3. **`solo_model_outputs_waves_3_to_10/` & `solo_model_outputs_arena_waves_1_to_2/`**:
   - **Ações 100% puras geradas sozinhas pelo Isaque 2.0 (`10/10` aprovadas no `Blender 5.2.1 LTS` sem tela e `clang++ -std=c++20`)**, com dupla reexecução determinística (`exports/` == `exports_recheck/` com mesmo SHA-256).
   - **Expurgo Total de Scripts Auxiliares:** Todos os arquivos de montagem GUI assistida (`construir_ao_vivo_na_tela.py`, `planta_industrial_kinsman*`) foram 100% excluídos.
4. **`negative_probe_token_fusion_collision/`**:
   - `FUSAO_2_ONDAS_1_3_pass1.py` e `FUSAO_2_ONDAS_1_3_pass2.py`: Preserva sem edição o `SyntaxError` na linha 58 (`s_out.parent = onda_3 := make_bmesh_solid(...)` após `2.160,52 s` / `1.471` tokens) que provou por que a fusão token a token colide e estabeleceu a **Composição Modular em DAG Estagiado**.
