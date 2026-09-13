#!/usr/bin/env python3
"""
expand_jurisprudencia.py — Expande jurisprudência STF/STJ com hub semântico.

Fontes:
  rg_stf        — RG STF (2.000 temas de repercussão geral)
  sumulas_stf   — Súmulas STF (63 vinculantes + 736 não-vinculantes)
  temas_stj     — Temas repetitivos STJ (1.007)
  stj_acordaos  — Informativos STJ (4.093 notas com holding + fundamentação) ← NOVO
  stf_acordaos  — Acórdãos STF coletados via API (4.515) ← NOVO

Uso:
    python augmentation/expand_jurisprudencia.py --fonte rg_stf --limite 10
    python augmentation/expand_jurisprudencia.py --fonte temas_stj --resume
    python augmentation/expand_jurisprudencia.py --fonte sumulas_stf --vinculantes-apenas
    python augmentation/expand_jurisprudencia.py --fonte stj_acordaos --resume
    python augmentation/expand_jurisprudencia.py --fonte stf_acordaos --resume
    python augmentation/expand_jurisprudencia.py --fonte todas --resume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT / "augmentation"))

from prompts import PROMPT_JURISPRUDENCIA
from llm_client import get_client, chat as llm_chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

OUTPUT_DIR = _ROOT / "augmentation" / "output"
DECISOES   = _ROOT / "decisoes"

DELAY = 0.3   # Azure/Groq — ajusta conforme necessário


# ── Carregadores de dados ──────────────────────────────────────────────────────

def carregar_rg_stf(limite: int | None = None) -> list[dict]:
    path = DECISOES / "stf" / "repercussao_geral.jsonl"
    itens = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    # Filtra só os que têm tese definida
    itens = [i for i in itens if i.get("descricao") and i.get("tema")]
    if limite:
        itens = itens[:limite]
    registros = []
    for i in itens:
        num = str(i.get("numero_tema", "")).zfill(4)
        juris_id = f"JURIS:STF:RG:TEMA{num}"
        documento = (
            f"Tema {i.get('numero_tema')} — {i.get('titulo','')}\n\n"
            f"Relator: {i.get('relator','')}\n\n"
            f"Descrição/Tese:\n{i.get('descricao','')}\n\n"
            f"Título: {i.get('tema','')}"
        )
        registros.append({
            "fonte": "rg_stf",
            "juris_id": juris_id,
            "tipo": "Tese de Repercussão Geral",
            "tribunal": "STF",
            "identificador_label": "Tema",
            "identificador_valor": str(i.get("numero_tema","")),
            "area": "",
            "status_vinculante": "Vinculante (art. 927, III, CPC)",
            "documento": documento,
            "raw": i,
        })
    return registros


def carregar_temas_stj(limite: int | None = None) -> list[dict]:
    path = DECISOES / "stj" / "temas_stj.jsonl"
    itens = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    itens = [i for i in itens if i.get("tese")]
    if limite:
        itens = itens[:limite]
    registros = []
    for i in itens:
        num = str(i.get("numero", "")).zfill(4)
        juris_id = f"JURIS:STJ:REP:TEMA{num}"
        documento = (
            f"Tema Repetitivo STJ {i.get('numero')} — {i.get('titulo','')}\n\n"
            f"Tese:\n{i.get('tese','')}\n\n"
            f"Label: {i.get('label','') or ''}"
        )
        registros.append({
            "fonte": "temas_stj",
            "juris_id": juris_id,
            "tipo": "Tema Repetitivo",
            "tribunal": "STJ",
            "identificador_label": "Tema",
            "identificador_valor": str(i.get("numero","")),
            "area": "",
            "status_vinculante": "Vinculante (art. 927, III, CPC)",
            "documento": documento,
            "raw": i,
        })
    return registros


def carregar_sumulas_stf(vinculantes_apenas: bool = False, limite: int | None = None) -> list[dict]:
    fontes = ["sumulas_vinculantes.jsonl"]
    if not vinculantes_apenas:
        fontes.append("sumulas_nao_vinculantes.jsonl")

    registros = []
    for fname in fontes:
        path = DECISOES / "stf" / fname
        itens = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
        for i in itens:
            num = str(i.get("sumula_numero", "")).zfill(4)
            is_vinc = i.get("is_vinculante", False)
            if is_vinc:
                juris_id = f"JURIS:STF:SUM:VINC:{num}"
                tipo = "Súmula Vinculante"
                status = "Vinculante (art. 103-A CF)"
            else:
                juris_id = f"JURIS:STF:SUM:{num}"
                tipo = "Súmula"
                status = "Persuasivo"
            documento = (
                f"{'Súmula Vinculante' if is_vinc else 'Súmula'} {i.get('sumula_numero')} — STF\n\n"
                f"{i.get('titulo','')}\n\n"
                f"Enunciado:\n{i.get('sumula_texto','')}"
            )
            registros.append({
                "fonte": "sumulas_stf",
                "juris_id": juris_id,
                "tipo": tipo,
                "tribunal": "STF",
                "identificador_label": "Súmula",
                "identificador_valor": str(i.get("sumula_numero","")),
                "area": "",
                "status_vinculante": status,
                "documento": documento,
                "raw": i,
            })
    if limite:
        registros = registros[:limite]
    return registros


# ── Geração ────────────────────────────────────────────────────────────────────

def gerar_expansao(registro: dict, client, model: str) -> str:
    prompt = PROMPT_JURISPRUDENCIA.format(
        juris_id=registro["juris_id"],
        tipo=registro["tipo"],
        tribunal=registro["tribunal"],
        identificador_label=registro["identificador_label"],
        identificador_valor=registro["identificador_valor"],
        area=registro["area"],
        status_vinculante=registro["status_vinculante"],
        documento=registro["documento"],
    )
    return llm_chat(client, model, prompt, max_tokens=3000, temperature=0.4)


# ── Pipeline ───────────────────────────────────────────────────────────────────

def processar(registros: list[dict], output_path: Path, client, model: str, dry_run: bool, delay: float) -> None:
    ja_feitos: set[str] = set()
    if output_path.exists():
        for l in output_path.read_text("utf-8").splitlines():
            try:
                d = json.loads(l)
                if d.get("expansao"):
                    ja_feitos.add(d["juris_id"])
            except Exception:
                pass
        if ja_feitos:
            log.info(f"Resume: {len(ja_feitos)} já expandidos, pulando.")

    pendentes = [r for r in registros if r["juris_id"] not in ja_feitos]
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
            log.info(f"[{i}/{len(pendentes)}] {reg['juris_id']} ({reg['tipo']})")
            try:
                if dry_run:
                    expansao = f"[DRY-RUN] expansão para {reg['juris_id']}"
                else:
                    expansao = gerar_expansao(reg, client, model)

                resultado = {
                    "juris_id":       reg["juris_id"],
                    "fonte":          reg["fonte"],
                    "tipo":           reg["tipo"],
                    "tribunal":       reg["tribunal"],
                    "identificador":  reg["identificador_valor"],
                    "expansao":       expansao,
                    "modelo_gerador": model if not dry_run else "dry-run",
                }
                f_out.write(json.dumps(resultado, ensure_ascii=False) + "\n")
                f_out.flush()

                eta = (time.time() - inicio) / i * (len(pendentes) - i)
                log.info(f"  ✓ {len(expansao)} chars | ETA: {eta/60:.1f} min")
            except Exception as e:
                log.error(f"  ✗ {reg['juris_id']}: {e}")
                erros += 1
                f_out.write(json.dumps({"juris_id": reg["juris_id"], "expansao": None, "erro": str(e)}, ensure_ascii=False) + "\n")
                f_out.flush()

            if i < len(pendentes) and not dry_run:
                time.sleep(delay)

    log.info(f"\n✓ {len(pendentes)-erros}/{len(pendentes)} expandidos | {erros} erros | {(time.time()-inicio)/60:.1f} min")
    log.info(f"Saída: {output_path}")


# ── Carregadores novos: STJ informativos + STF acórdãos ──────────────────────

def carregar_stj_acordaos(limite: int | None = None) -> list[dict]:
    """Informativos STJ coletados — cada nota vira um registro para fichamento."""
    path = _ROOT / "decisoes" / "stj" / "stj_informativos_acordaos.jsonl"
    if not path.exists():
        log.error(f"Arquivo não encontrado: {path}")
        return []

    itens = [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]
    # Filtra notas com conteúdo mínimo
    itens = [i for i in itens if len(i.get("texto", "")) > 150]
    if limite:
        itens = itens[:limite]

    registros = []
    for i in itens:
        proc   = i.get("processo", "") or ""
        num    = re.sub(r"[^\d]", "", proc)[:10] or str(hash(i["texto"]))[-8:]
        juris_id = f"JURIS:STJ:INFJ:{i.get('informativo',0):04d}:{num}"

        documento = i.get("texto", "")
        tipo = "Acórdão STJ" if proc else "Nota de Informativo STJ"

        registros.append({
            "fonte":              "stj_acordaos",
            "juris_id":           juris_id,
            "tipo":               tipo,
            "tribunal":           "STJ",
            "identificador_label":"Informativo",
            "identificador_valor": str(i.get("informativo", "")),
            "area":               i.get("ramo", ""),
            "status_vinculante":  "Persuasivo",
            "documento":          documento,
            "raw":                i,
        })

    log.info(f"STJ informativos: {len(registros)} notas carregadas")
    return registros


def carregar_stf_acordaos(limite: int | None = None) -> list[dict]:
    """Acórdãos STF coletados via API — fichamento completo."""
    path = _ROOT / "decisoes" / "stf" / "stf_acordaos.jsonl"
    if not path.exists():
        log.error(f"Arquivo não encontrado: {path}")
        return []

    itens = [json.loads(l) for l in path.read_text("utf-8").splitlines() if l.strip()]
    # Prioriza os que têm ementa + acórdão relevante
    itens = [i for i in itens if len(i.get("texto", "")) > 300]
    # Ordena: primeiro os com ementa, depois os com tese RG
    itens.sort(key=lambda x: (
        bool(x.get("ementa")),
        bool(x.get("tema_rg")),
        x.get("n_chars", 0)
    ), reverse=True)
    if limite:
        itens = itens[:limite]

    registros = []
    for i in itens:
        classe = i.get("classe", "")
        numero = i.get("numero", "")
        juris_id = f"JURIS:STF:{classe}:{numero}" if classe and numero else f"JURIS:STF:{i.get('doc_id','?')}"

        is_vinc  = classe in ("ADI", "ADPF", "ADC", "ADO") or i.get("is_repercussao_geral")
        status   = "Vinculante (efeito erga omnes)" if is_vinc else "Persuasivo"

        documento = i.get("texto", "")
        if i.get("tema_rg"):
            documento = f"TEMA: {i['tema_rg']}\n\n{documento}"

        registros.append({
            "fonte":              "stf_acordaos",
            "juris_id":           juris_id,
            "tipo":               f"Acórdão STF — {classe}",
            "tribunal":           "STF",
            "identificador_label": "Processo",
            "identificador_valor": f"{classe} {numero}",
            "area":               "",
            "status_vinculante":  status,
            "documento":          documento[:4000],
            "raw":                i,
        })

    log.info(f"STF acórdãos: {len(registros)} carregados")
    return registros


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fonte",
        choices=["rg_stf", "temas_stj", "sumulas_stf", "stj_acordaos", "stf_acordaos", "todas"],
        default="todas")
    parser.add_argument("--vinculantes-apenas", action="store_true")
    parser.add_argument("--limite", type=int, default=None)
    parser.add_argument("--resume",  action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay",   type=float, default=DELAY)
    args = parser.parse_args()

    if args.dry_run:
        client, model = None, "dry-run"
    else:
        client, model = get_client()

    fontes_map = {
        "rg_stf":       lambda: carregar_rg_stf(args.limite),
        "temas_stj":    lambda: carregar_temas_stj(args.limite),
        "sumulas_stf":  lambda: carregar_sumulas_stf(args.vinculantes_apenas, args.limite),
        "stj_acordaos": lambda: carregar_stj_acordaos(args.limite),
        "stf_acordaos": lambda: carregar_stf_acordaos(args.limite),
    }

    fontes_rodar = list(fontes_map.keys()) if args.fonte == "todas" else [args.fonte]

    for nome_fonte in fontes_rodar:
        log.info(f"\n=== Fonte: {nome_fonte} ===")
        registros = fontes_map[nome_fonte]()
        output_path = OUTPUT_DIR / f"{nome_fonte}_expandida.jsonl"
        processar(registros, output_path, client, model, args.dry_run, args.delay)


if __name__ == "__main__":
    main()
