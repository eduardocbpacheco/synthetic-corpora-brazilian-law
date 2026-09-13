#!/usr/bin/env python3
"""
expand_casos.py — Expande acórdãos TJSP/TJRJ com hub semântico.

Usa dados locais em decisoes/tjsp/ e decisoes/tjrj/.
Como o TJSP tem 5.7M de linhas, opera por AMOSTRAGEM estratificada por área.
Gera corpus em augmentation/output/casos_expandidos.jsonl.

Uso:
    python augmentation/expand_casos.py --tribunal tjsp --n-por-area 5 --dry-run
    python augmentation/expand_casos.py --tribunal tjsp --n-por-area 20 --resume
    python augmentation/expand_casos.py --tribunal tjrj --n-por-area 10 --resume
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT / "augmentation"))

from prompts import PROMPT_CASO
from llm_client import get_client, chat as llm_chat
from sanitize import limpar_expansao, REGRA_FORMATO

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

OUTPUT_DIR = _ROOT / "augmentation" / "output"
DECISOES   = _ROOT / "decisoes"

# Um acórdão inteiro cabe numa célula do CSV e estoura o limite padrão do módulo
# csv (131072 chars): o reader levanta _csv.Error e a amostragem morre no meio.
# Foi o que travou a coleta do TJSP em 8 casos.
csv.field_size_limit(sys.maxsize)

DELAY = 0.3   # Azure/Groq — ajusta conforme necessário
SEED  = 42


# ── Mapeamento de assuntos → áreas do direito ─────────────────────────────────
# Agrupa assuntos do TJSP em áreas para estratificação
AREA_KEYWORDS = {
    "Direito Penal":       ["crim", "penal", "tráfico", "furto", "roubo", "homicídio", "lesão"],
    "Direito Civil":       ["civil", "contrat", "família", "inventário", "herança", "divórcio", "aliment"],
    "Direito do Trabalho": ["trabalho", "trabalhist", "CLT", "emprego", "rescisão", "FGTS"],
    "Direito do Consumidor": ["consum", "CDC", "produto", "serviço", "fornecedor"],
    "Direito Tributário":  ["tribut", "imposto", "ICMS", "ISS", "IPTU", "fiscal"],
    "Direito Administrativo": ["admin", "licitação", "concurso", "servidor", "municipio", "estado"],
    "Direito Previdenciário": ["previd", "INSS", "aposentadoria", "benefício", "seguro"],
}


def classificar_area(assunto: str, classe: str) -> str:
    texto = (assunto + " " + classe).lower()
    for area, kws in AREA_KEYWORDS.items():
        if any(k.lower() in texto for k in kws):
            return area
    return "Outras"


def case_id_from_row(row: dict, tribunal: str) -> str:
    nup = row.get("nup", row.get("processo", "")).replace("/", "-").replace(".", "")
    if not nup:
        # Fallback: hash do conteúdo
        nup = hashlib.md5(row.get("conteudo", row.get("ementa","")).encode()).hexdigest()[:12]
    return f"CASE:{tribunal.upper()}:{nup}"


# ── Carregador TJSP ───────────────────────────────────────────────────────────

def amostrar_tjsp(n_por_area: int, grau: str = "2_grau") -> list[dict]:
    path = DECISOES / "tjsp" / f"tjsp_{grau}.csv"
    log.info(f"Carregando {path.name} (pode demorar para 5.7M linhas)...")

    por_area: dict[str, list] = {a: [] for a in list(AREA_KEYWORDS.keys()) + ["Outras"]}
    total_lidas = 0

    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_lidas += 1
            # Para só quando todas as áreas têm n_por_area * 5 candidatos (para sortear depois)
            if all(len(v) >= n_por_area * 5 for v in por_area.values()):
                break
            # Filtra: precisa ter ementa não vazia
            ementa = row.get("ementa", "").strip()
            if len(ementa) < 100:
                continue
            area = classificar_area(row.get("assunto",""), row.get("classe",""))
            if len(por_area[area]) < n_por_area * 5:
                por_area[area].append(row)

    log.info(f"Lidas {total_lidas:,} linhas. Candidatos por área: { {k: len(v) for k,v in por_area.items()} }")

    random.seed(SEED)
    registros = []
    for area, candidatos in por_area.items():
        selecionados = random.sample(candidatos, min(n_por_area, len(candidatos)))
        for row in selecionados:
            cid = case_id_from_row(row, "TJSP")
            conteudo = row.get("conteudo", row.get("ementa", ""))
            documento = (
                f"Tribunal: TJSP | Classe: {row.get('classe','')} | "
                f"Assunto: {row.get('assunto','')} | "
                f"Magistrado: {row.get('magistrado','')} | "
                f"Data julgamento: {row.get('data_julgamento','')} | "
                f"Órgão: {row.get('orgao_julgador','')}\n\n"
                f"Ementa:\n{row.get('ementa','')}\n\n"
                f"Conteúdo:\n{conteudo[:3000]}"
            )
            registros.append({
                "fonte": "tjsp",
                "case_id": cid,
                "tribunal": f"TJSP — {row.get('orgao_julgador','')}",
                "instancia": "2º grau",
                "tipo_acao": row.get("classe",""),
                "processo": row.get("nup",""),
                "data": row.get("data_julgamento",""),
                "area": area,
                "documento": documento,
            })
    log.info(f"Amostrados {len(registros)} casos do TJSP")
    return registros


# ── Carregador TJRJ ───────────────────────────────────────────────────────────

def carregar_tjrj(n_por_area: int) -> list[dict]:
    path = DECISOES / "tjrj" / "tjrj_acordaos.csv"
    if not path.exists():
        log.warning(f"Arquivo não encontrado: {path}")
        return []

    rows = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    por_area: dict[str, list] = {}
    for row in rows:
        area = classificar_area(row.get("assunto",""), row.get("classe",""))
        por_area.setdefault(area, []).append(row)

    random.seed(SEED)
    registros = []
    for area, candidatos in por_area.items():
        selecionados = random.sample(candidatos, min(n_por_area, len(candidatos)))
        for row in selecionados:
            cid = case_id_from_row(row, "TJRJ")
            documento = (
                f"Tribunal: TJRJ | Classe: {row.get('classe','')} | "
                f"Processo: {row.get('processo','')} | "
                f"Data: {row.get('data_julgamento','')}\n\n"
                f"Ementa:\n{row.get('ementa','')}\n\n"
                f"Conteúdo:\n{row.get('conteudo','')[:3000]}"
            )
            registros.append({
                "fonte": "tjrj",
                "case_id": cid,
                "tribunal": "TJRJ",
                "instancia": "2º grau",
                "tipo_acao": row.get("classe",""),
                "processo": row.get("processo",""),
                "data": row.get("data_julgamento",""),
                "area": area,
                "documento": documento,
            })
    log.info(f"Amostrados {len(registros)} casos do TJRJ")
    return registros


# ── Geração ────────────────────────────────────────────────────────────────────

def gerar_expansao(reg: dict, client, model: str) -> str:
    prompt = PROMPT_CASO.format(
        case_id=reg["case_id"],
        tribunal=reg["tribunal"],
        instancia=reg["instancia"],
        tipo_acao=reg["tipo_acao"],
        processo=reg["processo"],
        data=reg["data"],
        area=reg["area"],
        documento=reg["documento"],
    ) + REGRA_FORMATO
    # O Mistral L3 embrulha a resposta em markdown (**[BLOCO]**, ### <<ID=...>>) e o
    # rechunk_v3 não reconhece bloco nenhum assim. Regra no prompt + limpeza na saída.
    return limpar_expansao(llm_chat(client, model, prompt, max_tokens=3000, temperature=0.5))


# ── Pipeline ───────────────────────────────────────────────────────────────────

def processar(registros: list[dict], output_path: Path, client, model: str, dry_run: bool, delay: float) -> None:
    # O dry-run NÃO pode escrever no arquivo real: os placeholders "[DRY-RUN]" ficam
    # com campo `expansao` preenchido e o --resume seguinte os trata como prontos,
    # pulando para sempre a geração de verdade.
    if dry_run:
        output_path = output_path.with_suffix(".dryrun.jsonl")

    ja_feitos: set[str] = set()
    if output_path.exists():
        for l in output_path.read_text("utf-8").splitlines():
            try:
                d = json.loads(l)
                if d.get("expansao"):
                    ja_feitos.add(d["case_id"])
            except Exception:
                pass
        if ja_feitos:
            log.info(f"Resume: {len(ja_feitos)} já expandidos, pulando.")

    pendentes = [r for r in registros if r["case_id"] not in ja_feitos]
    log.info(f"Total: {len(registros)} | Pendentes: {len(pendentes)}")
    if not pendentes:
        log.info("Nada a fazer.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    modo  = "a" if ja_feitos else "w"
    erros = 0
    inicio = time.time()

    with open(output_path, modo, encoding="utf-8") as f_out:
        for i, reg in enumerate(pendentes, 1):
            log.info(f"[{i}/{len(pendentes)}] {reg['case_id']} ({reg['area']})")
            try:
                expansao = f"[DRY-RUN] {reg['case_id']}" if dry_run else gerar_expansao(reg, client, model)
                resultado = {
                    "case_id":        reg["case_id"],
                    "fonte":          reg["fonte"],
                    "area":           reg["area"],
                    "tipo_acao":      reg["tipo_acao"],
                    "expansao":       expansao,
                    "modelo_gerador": model if not dry_run else "dry-run",
                }
                f_out.write(json.dumps(resultado, ensure_ascii=False) + "\n")
                f_out.flush()
                eta = (time.time() - inicio) / i * (len(pendentes) - i)
                log.info(f"  ✓ {len(expansao)} chars | ETA: {eta/60:.1f} min")
            except Exception as e:
                log.error(f"  ✗ {reg['case_id']}: {e}")
                erros += 1
                f_out.write(json.dumps({"case_id": reg["case_id"], "expansao": None, "erro": str(e)}, ensure_ascii=False) + "\n")
                f_out.flush()

            if i < len(pendentes) and not dry_run:
                time.sleep(delay)

    log.info(f"\n✓ {len(pendentes)-erros}/{len(pendentes)} expandidos | {erros} erros | {(time.time()-inicio)/60:.1f} min")
    log.info(f"Saída: {output_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tribunal", choices=["tjsp", "tjrj", "ambos"], default="tjsp")
    parser.add_argument("--grau",     choices=["1_grau", "2_grau"],      default="2_grau")
    parser.add_argument("--n-por-area", type=int, default=10,
                        help="Casos a amostrar por área (default: 10 → ~80 casos TJSP)")
    parser.add_argument("--resume",  action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay",   type=float, default=DELAY)
    args = parser.parse_args()

    if args.dry_run:
        client, model = None, "dry-run"
    else:
        client, model = get_client()

    if args.tribunal in ("tjsp", "ambos"):
        registros = amostrar_tjsp(args.n_por_area, args.grau)
        processar(registros, OUTPUT_DIR / "casos_tjsp_expandidos.jsonl", client, model, args.dry_run, args.delay)

    if args.tribunal in ("tjrj", "ambos"):
        registros = carregar_tjrj(args.n_por_area)
        processar(registros, OUTPUT_DIR / "casos_tjrj_expandidos.jsonl", client, model, args.dry_run, args.delay)


if __name__ == "__main__":
    main()
