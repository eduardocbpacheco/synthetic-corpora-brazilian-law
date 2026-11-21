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
import hashlib
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

    # O número do processo mora no CORPO da nota ("Processo REsp 2.195.921-AL , Rel. ..."),
    # e o campo `processo` do coletor fica vazio em 4.033 das 4.093 — é o mesmo defeito que
    # o C1 encontrou. A consequência aqui era grave e dupla.
    #
    # Primeira: o identificador caía no fallback `str(hash(texto))[-8:]`. Isso não é id de
    # banco, é hash do Python, e o hash de `str` é ALEATORIZADO por execução: rodar de novo
    # produzia outro identificador para a mesma nota. As 4.195 fichas existentes têm
    # identidade irreprodutível, e é por isso que nenhum dos seus ids aparece na semente.
    #
    # Segunda: sem o processo, a ficha não sabe QUAL julgado ela ficha, e o braço bruto —
    # que identifica pelo processo — não tem como parear com ela. É a metade do B1 que
    # sobrou depois de a legislação chegar a 100%.
    #
    # Agora o processo sai do texto, e o fallback é sha1, que é estável.
    # O informativo escreve a cadeia de incidentes antes da classe: "Processo AgRg no HC
    # 1.080.161-RS". A classe do PROCESSO é a última antes do número — o agravo regimental
    # é fase, não processo — e é assim que o braço bruto e a conferência de pareamento a
    # leem. Sem aceitar o prefixo, 385 notas ficavam sem identidade e caíam no sha1.
    RX_PROC = re.compile(r"Processo\s+(?:(?:AgRg|AgInt|EDcl|EAREsp|RCD|QO)\s+n[oa]\s+)*"
                         r"([A-Za-zÇç]{1,8})\s*([\d][\d.]*)\s*[-/]\s*([A-Z]{2})")
    registros = []
    for i in itens:
        texto_nota = i.get("texto", "") or ""
        proc = (i.get("processo") or "").strip()
        if not proc:
            m = RX_PROC.search(texto_nota[:400])
            if m:
                proc = f"{m.group(1)} {m.group(2)}/{m.group(3)}"
        # A FORMA do identificador tem de ser a mesma dos outros: JURIS:{tribunal}:{classe}:
        # {número}. Com o informativo no meio — JURIS:STJ:INFJ:0890:2195921 — a conferência
        # de pareamento lê "INFJ" como classe e "0890" como número do processo, e o casamento
        # cai de 97,7% para 56,4%. O informativo é metadado da nota, não identidade do
        # julgado, e passa a viver em campo próprio.
        m_cl = re.match(r"\s*([A-Za-zÇç]+)", proc)
        classe = (m_cl.group(1).upper() if m_cl else "INFJ")
        num = re.sub(r"[^\d]", "", proc)[:10] or hashlib.sha1(
            texto_nota.encode("utf-8")).hexdigest()[:8]
        juris_id = f"JURIS:STJ:{classe}:{num}"

        documento = texto_nota
        # B2 · a nota de informativo é nota, mesmo quando traz o número do processo. Rotular
        # de acórdão as que tinham `processo` preenchido é o que punha 10,8M tokens no grupo
        # errado da ablação.
        tipo = "Nota de Informativo STJ"

        registros.append({
            "fonte":              "stj_acordaos",
            "juris_id":           juris_id,
            "tipo":               tipo,
            "tribunal":           "STJ",
            "identificador_label":"Informativo",
            "identificador_valor": str(i.get("informativo", "")),
            "area":               i.get("ramo", ""),
            "status_vinculante":  "Persuasivo",
            "processo":           proc,      # a identidade que faltava
            "informativo":        str(i.get("informativo", "")),
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
    # C17 · Fora o DESPACHO, que não é acórdão. São 2.555 dos 4.520 registros deste arquivo,
    # com mediana de 955 caracteres e nenhuma ementa: "cite-se", "manifeste-se", o
    # expediente que move o processo sem decidir questão de direito. Fichá-los produz 2.029
    # fichas de precedente sobre documentos que não têm precedente nenhum.
    #
    # A exclusão tem de valer nos DOIS braços ao mesmo tempo. Tirar o despacho só do bruto
    # derruba o pareamento de 93,3% para 66,7% e o F3 aborta a montagem — e aborta com
    # razão, porque aí o expandido realmente ficha material que o bruto não tem. O portão
    # não estava reclamando da limpeza; estava dizendo onde mais ela faltava.
    itens = [i for i in itens if not str(i.get("doc_id") or "").startswith("despacho")]
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

    # A classe vem vazia em 2.491 dos 4.456 registros, e sem ela o identificador caía num
    # `doc_id` interno do tipo `despacho1784114` — um número de documento, não de processo,
    # que o braço bruto não tem como casar. Mas o campo `processo` traz "ADI 7322", com a
    # classe dentro: 2.488 dos 2.491 são recuperáveis dali. É a mesma correção que o lado do
    # STJ acabou de receber, e a mesma família do C1: o dado existe e está no campo vizinho.
    RX_CLASSE = re.compile(r"\b(ADI|ADPF|ADC|ADO|RE|ARE|HC|RHC|MS|MI|Rcl|AP|Inq|ACO|AR|AI|"
                           r"EREsp|Pet|SS|STA|SL|Cm)\b", re.IGNORECASE)
    registros = []
    for i in itens:
        classe = (i.get("classe") or "").strip()
        numero = str(i.get("numero") or "").strip()
        if not classe:
            m = RX_CLASSE.search(str(i.get("processo") or ""))
            if m:
                classe = m.group(1).upper()
        if not numero:
            m = re.search(r"(\d[\d.]*)", str(i.get("processo") or ""))
            if m:
                numero = m.group(1).replace(".", "")
        juris_id = (f"JURIS:STF:{classe}:{numero}" if classe and numero
                    else f"JURIS:STF:{i.get('doc_id','?')}")

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
