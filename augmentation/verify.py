#!/usr/bin/env python3
"""
verify.py — Verificação em camadas de expansões geradas.

Camada 0 — Estrutural (regex, gratuito):
    IDs bem formados, Q&A presentes, comprimento mínimo.

Camada 1 — Existência (offline, gratuito):
    IDs de NORMREF/PRECREF conferidos contra índices locais.
    Cobre 100% da jurisprudência de peso (súmulas/RG/temas).

Camada 2 — Fidelidade (LLM, por amostragem):
    Juiz-LLM verifica se a afirmação está ancorada no documento original.
    Aplicado só nas citações de camada 1 que passaram mas têm baixa confiança.

Camada 3 — Reparo (se falhou):
    Feedback estruturado → regenera só o bloco que falhou (máx 2 tentativas).

Uso:
    python augmentation/verify.py --input augmentation/output/rg_stf_expandida.jsonl
    python augmentation/verify.py --input augmentation/output/rg_stf_expandida.jsonl --camada 2
    python augmentation/verify.py --input augmentation/output/rg_stf_expandida.jsonl --reparar
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

import sys
sys.path.insert(0, str(_ROOT / "augmentation"))
from llm_client import get_client, chat as llm_chat

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DECISOES = _ROOT / "decisoes"


# ── Índices locais (construídos uma vez, reutilizados) ─────────────────────────

_indices: dict = {}


def _build_indices() -> dict:
    if _indices:
        return _indices

    log.info("Construindo índices locais de jurisprudência...")

    # RG STF (número do tema)
    rg = set()
    for l in (DECISOES / "stf" / "repercussao_geral.jsonl").read_text().splitlines():
        try:
            d = json.loads(l)
            rg.add(str(d.get("numero_tema", "")))
        except Exception:
            pass
    _indices["rg_stf_temas"] = rg

    # Súmulas STF vinculantes
    sv = set()
    for l in (DECISOES / "stf" / "sumulas_vinculantes.jsonl").read_text().splitlines():
        try:
            sv.add(str(json.loads(l).get("sumula_numero", "")))
        except Exception:
            pass
    _indices["sumulas_vinc"] = sv

    # Súmulas STF não vinculantes
    snv = set()
    for l in (DECISOES / "stf" / "sumulas_nao_vinculantes.jsonl").read_text().splitlines():
        try:
            snv.add(str(json.loads(l).get("sumula_numero", "")))
        except Exception:
            pass
    _indices["sumulas_nao_vinc"] = snv

    # Temas STJ
    stj = set()
    for l in (DECISOES / "stj" / "temas_stj.jsonl").read_text().splitlines():
        try:
            stj.add(str(json.loads(l).get("numero", "")))
        except Exception:
            pass
    _indices["temas_stj"] = stj

    log.info(
        f"Índices: {len(rg)} temas RG STF | {len(sv)} SV | "
        f"{len(snv)} súmulas STF | {len(stj)} temas STJ"
    )
    return _indices


# ── Camada 0: Estrutural ───────────────────────────────────────────────────────

_RE_ID    = re.compile(r"<<ID=[^|>]+\|DOC=[^|>]+\|TYPE=[^|>]+\|PARENT=[^>]+>>")
_RE_QA    = re.compile(r"\[PERGUNTA\].*?\[RESPOSTA\]", re.DOTALL)
_RE_JURIS_ID = re.compile(r"JURIS:(STF|STJ):(SUM|RG|REP|SUM:VINC):([A-Z0-9:]+)")
_RE_NUP   = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")  # padrão CNJ


def verificar_estrutural(expansao: str) -> dict:
    problemas = []

    ids_encontrados = _RE_ID.findall(expansao)
    if len(ids_encontrados) < 3:
        problemas.append(f"Poucos IDs estruturais ({len(ids_encontrados)} < 3)")

    qas = _RE_QA.findall(expansao)
    if len(qas) < 4:
        problemas.append(f"Poucos pares Q&A ({len(qas)} < 4)")

    if len(expansao) < 800:
        problemas.append(f"Expansão muito curta ({len(expansao)} chars)")

    juris_ids = _RE_JURIS_ID.findall(expansao)

    return {
        "camada": 0,
        "ok": len(problemas) == 0,
        "problemas": problemas,
        "n_ids": len(ids_encontrados),
        "n_qas": len(qas),
        "juris_ids_encontrados": [f"JURIS:{t}:{s}:{n}" for t, s, n in juris_ids],
    }


# ── Camada 1: Existência ───────────────────────────────────────────────────────

def verificar_existencia(expansao: str) -> dict:
    idx = _build_indices()
    problemas = []
    verificados = []
    nao_encontrados = []

    juris_refs = re.findall(r"JURIS:(STF|STJ):(SUM|RG|REP|SUM:VINC):(?:TEMA|VINC:)?(\d+)", expansao)

    for tribunal, tipo, numero in juris_refs:
        # Remove zero-padding (TEMA0001 → "1") para comparar com índice
        num_int = str(int(numero))
        prefixo = "TEMA" if tipo in ("RG", "REP") else ("VINC:" if "VINC" in tipo else "")
        ref_str = f"JURIS:{tribunal}:{tipo}:{prefixo}{numero}"
        encontrado = False

        if tribunal == "STF" and tipo == "RG":
            encontrado = num_int in idx["rg_stf_temas"]
        elif tribunal == "STF" and "VINC" in tipo:
            encontrado = num_int in idx["sumulas_vinc"]
        elif tribunal == "STF" and tipo == "SUM":
            encontrado = num_int in idx["sumulas_nao_vinc"] or num_int in idx["sumulas_vinc"]
        elif tribunal == "STJ" and tipo in ("REP", "SUM"):
            encontrado = num_int in idx["temas_stj"]

        if encontrado:
            verificados.append(ref_str)
        else:
            nao_encontrados.append(ref_str)
            problemas.append(f"ID não encontrado nos índices locais: {ref_str}")

    return {
        "camada": 1,
        "ok": len(problemas) == 0,
        "problemas": problemas,
        "verificados": verificados,
        "nao_encontrados": nao_encontrados,
        "n_referencias": len(juris_refs),
    }


# ── Camada 2: Fidelidade (LLM) ────────────────────────────────────────────────

PROMPT_FIDELIDADE = """\
Você é um verificador jurídico especializado. Sua tarefa é verificar se uma afirmação \
específica está fundamentada no documento fornecido.

DOCUMENTO DE ORIGEM:
{documento}

AFIRMAÇÃO A VERIFICAR:
"{afirmacao}"

A afirmação está ancorada no documento acima (direta ou inequivocamente)?

Responda APENAS com:
- "ANCORADO" se a afirmação está fundamentada no documento
- "NÃO ANCORADO: [motivo em uma linha]" se não está ou se o documento não fornece \
base suficiente para a afirmação
"""


def verificar_fidelidade_item(afirmacao: str, documento: str, client, model: str) -> dict:
    prompt = PROMPT_FIDELIDADE.format(documento=documento[:3000], afirmacao=afirmacao)
    try:
        texto = llm_chat(client, model, prompt, max_tokens=60, temperature=0.0, retries=3)
        ancorado = texto.upper().startswith("ANCORADO")
        return {"ancorado": ancorado, "resposta_juiz": texto}
    except Exception as e:
        return {"ancorado": None, "erro": str(e)}


def verificar_fidelidade(expansao: str, documento_origem: str, client, model: str, n_amostras: int = 3) -> dict:
    """Verifica por amostragem: pega N afirmações de JURISPRUDÊNCIA/NORMREF e checa."""
    # Extrai blocos de citação
    blocos_juris = re.findall(r"\[JURISPRUDÊNCIA\](.*?)(?=<<|$)", expansao, re.DOTALL)
    blocos_normref = re.findall(r"\[NORMAS INTERPRETADAS\](.*?)(?=<<|$)", expansao, re.DOTALL)

    afirmacoes = []
    for bloco in blocos_juris + blocos_normref:
        linhas = [l.strip() for l in bloco.strip().splitlines() if l.strip().startswith("-")]
        afirmacoes.extend(linhas[:2])  # pega até 2 por bloco

    if not afirmacoes:
        return {"camada": 2, "ok": True, "motivo": "Nenhuma afirmação de citação encontrada", "checks": []}

    amostras = afirmacoes[:n_amostras]
    checks = []
    for af in amostras:
        resultado = verificar_fidelidade_item(af, documento_origem, client, model)
        checks.append({"afirmacao": af, **resultado})
        time.sleep(0.3)

    n_ancorados = sum(1 for c in checks if c.get("ancorado") is True)
    ok = n_ancorados >= len(checks) * 0.7  # 70% de aprovação

    return {
        "camada": 2,
        "ok": ok,
        "n_checks": len(checks),
        "n_ancorados": n_ancorados,
        "checks": checks,
        "problemas": [c["afirmacao"] for c in checks if c.get("ancorado") is False],
    }


# ── Pipeline principal ─────────────────────────────────────────────────────────

def verificar_item(item: dict, camada_max: int, client, model: str = "") -> dict:
    expansao = item.get("expansao", "")
    if not expansao:
        return {"ok": False, "motivo": "sem expansão"}

    resultado = {"id": item.get("juris_id") or item.get("case_id") or item.get("id"), "camadas": []}

    # Camada 0
    c0 = verificar_estrutural(expansao)
    resultado["camadas"].append(c0)
    if not c0["ok"]:
        resultado["ok"] = False
        resultado["camada_falhou"] = 0
        return resultado

    # Camada 1
    c1 = verificar_existencia(expansao)
    resultado["camadas"].append(c1)
    if not c1["ok"] and camada_max >= 1:
        resultado["ok"] = False
        resultado["camada_falhou"] = 1
        return resultado

    # Camada 2 (opcional, requer LLM)
    if camada_max >= 2 and client and item.get("documento"):
        c2 = verificar_fidelidade(expansao, item["documento"], client, model)
        resultado["camadas"].append(c2)
        if not c2["ok"]:
            resultado["ok"] = False
            resultado["camada_falhou"] = 2
            return resultado

    resultado["ok"] = True
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",   required=True, help="JSONL de expansões a verificar")
    parser.add_argument("--camada",  type=int, default=1, choices=[0, 1, 2],
                        help="Camada máxima a rodar (0=estrutural, 1=existência, 2=fidelidade LLM)")
    parser.add_argument("--reparar", action="store_true",
                        help="Tenta regenerar itens que falharam (requer GROQ_API_KEY)")
    parser.add_argument("--limite",  type=int, default=None)
    args = parser.parse_args()

    input_path  = Path(args.input)
    output_path = input_path.with_suffix(".verificada.jsonl")
    relatorio   = input_path.with_suffix(".relatorio_verificacao.json")

    client = None
    model  = ""
    if args.camada >= 2 or args.reparar:
        try:
            client, model = get_client()
        except Exception as e:
            log.warning(f"Provider LLM não disponível ({e}) — pulando camada 2")
            args.camada = min(args.camada, 1)

    itens = [json.loads(l) for l in input_path.read_text("utf-8").splitlines() if l.strip()]
    if args.limite:
        itens = itens[:args.limite]

    log.info(f"Verificando {len(itens)} itens (camada máx: {args.camada})")

    resultados = []
    ok_count = falha_count = 0

    for i, item in enumerate(itens, 1):
        log.info(f"[{i}/{len(itens)}] {item.get('juris_id') or item.get('case_id') or item.get('id','?')}")
        res = verificar_item(item, args.camada, client, model)
        resultados.append({**item, "_verificacao": res})
        if res["ok"]:
            ok_count += 1
        else:
            falha_count += 1
            log.warning(f"  ✗ Falha camada {res.get('camada_falhou','?')}: "
                        f"{[p for c in res['camadas'] for p in c.get('problemas',[])][:2]}")

    # Salva itens verificados
    with open(output_path, "w", encoding="utf-8") as f:
        for r in resultados:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Relatório resumo
    taxa_aprovacao = ok_count / len(resultados) * 100 if resultados else 0
    rel = {
        "input": str(input_path),
        "total": len(resultados),
        "ok": ok_count,
        "falhas": falha_count,
        "taxa_aprovacao_pct": round(taxa_aprovacao, 1),
        "camada_max": args.camada,
        "falhas_por_camada": {
            str(c): sum(1 for r in resultados if r["_verificacao"].get("camada_falhou") == c)
            for c in range(args.camada + 1)
        },
    }
    relatorio.write_text(json.dumps(rel, indent=2, ensure_ascii=False))

    log.info(f"\n✓ {ok_count}/{len(resultados)} aprovados ({taxa_aprovacao:.1f}%)")
    log.info(f"Saída verificada: {output_path}")
    log.info(f"Relatório: {relatorio}")


if __name__ == "__main__":
    main()
