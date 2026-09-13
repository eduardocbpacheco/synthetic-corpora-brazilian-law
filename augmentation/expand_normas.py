#!/usr/bin/env python3
"""
expand_normas.py — Expande normas jurídicas (CF88, códigos, leis) artigo a artigo.

Divide cada diploma legal em artigos individuais e aplica o PROMPT_NORMA
para gerar o hub semântico (EXPL, SYN, REL, EFFECT, JURIS, QA).

Fontes:
  cf88     — leis/cf88_adct.parquet (CF88 + ADCT)
  codigos  — leis/codigos_especificos.parquet (CC, CP, CPC, CLT, CDC...)
  federais — leis/leis_federais.jsonl (159 diplomas)
  sp       — leis/leis_sp.jsonl (26 diplomas)

Saída: augmentation/output/normas_expandidas.jsonl

Uso:
    python augmentation/expand_normas.py --fonte cf88 --limite 10 --dry-run
    python augmentation/expand_normas.py --fonte codigos --resume
    python augmentation/expand_normas.py --fonte todas --resume
"""

from __future__ import annotations

import argparse
import json
import threading
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")
sys.path.insert(0, str(_ROOT / "augmentation"))

from prompts import PROMPT_NORMA
from llm_client import get_client, chat as llm_chat
from sanitize import limpar_expansao, REGRA_FORMATO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

OUTPUT_DIR = _ROOT / "augmentation" / "output"
LEIS_DIR   = _ROOT / "leis"

DELAY = 0.3   # Azure/Groq — ajusta conforme necessário


# ── Mapeamento diploma → ID canônico ─────────────────────────────────────────

ID_MAP = {
    "CF88":                    "CF88",
    "Código Civil":            "CC",
    "Código Penal":            "CP",
    "Código de Processo Civil":"CPC",
    "Código de Processo Penal":"CPP",
    "CLT":                     "CLT",
    "Código de Defesa do Consumidor": "CDC",
    "Código Tributário Nacional":     "CTN",
    "Código Eleitoral":        "CE",
    "Código Florestal":        "CFLO",
    "ECA":                     "ECA",
    "Estatuto da OAB":         "EOAB",
}

def doc_id(nome: str) -> str:
    for k, v in ID_MAP.items():
        if k.lower() in nome.lower():
            return v
    # Fallback: sigla a partir do nome
    palavras = re.findall(r"[A-ZÁÉÍÓÚ][a-záéíóú]+", nome)
    return "".join(p[0] for p in palavras[:4]).upper() or "LEI"


# ── Divisão em artigos ────────────────────────────────────────────────────────

# Aceita "Art. 1º" (federal/códigos) E "Artigo 1° -" (padrão da ALESP nas leis de SP).
# Sem a alternativa "Artigo", as 27 leis paulistas rendiam 0 artigos e a fonte `sp`
# ficava vazia — foi o motivo de leis_sp_expandidas.jsonl nunca ter sido gerado.
_ART_RE = re.compile(
    r"(?:^|\n)\s*((?:Artigo|Art\.?)\s*\d+[º°]?[\s\-–\.]*[A-Z]?[\.\-]?)\s*",
    re.MULTILINE,
)


def dividir_em_artigos(texto: str, diploma: str, did: str | None = None) -> list[dict]:
    """Divide o texto de um diploma em artigos individuais.

    `did` permite forçar um doc_id único por diploma. Sem ele vale doc_id(), que
    monta sigla pelas iniciais do nome e COLIDE entre leis diferentes (o artigo 1º
    de duas leis vira o mesmo `X:ART:0001` e o segundo é descartado pelo --resume).
    """
    did = did or doc_id(diploma)
    partes = _ART_RE.split(texto)
    artigos = []
    num_global = 0

    i = 1
    while i < len(partes) - 1:
        cabecalho = partes[i].strip()
        corpo     = partes[i + 1].strip() if i + 1 < len(partes) else ""
        i += 2

        # Extrai número do artigo do cabeçalho
        m = re.search(r"(\d+)", cabecalho)
        num_art = int(m.group(1)) if m else num_global + 1
        num_global = num_art

        texto_art = f"{cabecalho} {corpo}".strip()
        if len(texto_art) < 30:
            continue

        artigos.append({
            "id":        f"{did}:ART:{num_art:04d}",
            "doc_id":    did,
            "diploma":   diploma,
            "num_art":   num_art,
            "texto":     texto_art[:3000],  # trunca artigos muito longos
            "fonte":     "leis",
        })

    # As páginas da ALESP repetem o marcador ("Artigo 1°" aparece como âncora e de
    # novo no corpo), o que gera o mesmo :ART:NNNN várias vezes — 24% de chamadas
    # desperdiçadas e IDs colidindo no corpus. Fica a ocorrência mais completa.
    melhor: dict[str, dict] = {}
    for a in artigos:
        anterior = melhor.get(a["id"])
        if anterior is None or len(a["texto"]) > len(anterior["texto"]):
            melhor[a["id"]] = a
    return list(melhor.values())


# ── Carregadores de dados ─────────────────────────────────────────────────────

def carregar_cf88(limite: int | None = None) -> list[dict]:
    df = pd.read_parquet(LEIS_DIR / "cf88_adct.parquet")
    artigos = []
    for _, row in df.iterrows():
        diploma = row["lei"]
        arts = dividir_em_artigos(str(row["texto"]), diploma)
        artigos.extend(arts)
    log.info(f"CF88+ADCT: {len(artigos)} artigos extraídos")
    return artigos[:limite] if limite else artigos


def carregar_codigos(limite: int | None = None) -> list[dict]:
    df = pd.read_parquet(LEIS_DIR / "codigos_especificos.parquet")
    artigos = []
    for _, row in df.iterrows():
        diploma = row.get("apelido") or row.get("lei", "Código")
        arts = dividir_em_artigos(str(row["texto"]), diploma)
        log.info(f"  {diploma}: {len(arts)} artigos")
        artigos.extend(arts)
    log.info(f"Códigos: {len(artigos)} artigos total")
    return artigos[:limite] if limite else artigos


def carregar_federais(limite: int | None = None) -> list[dict]:
    linhas = [
        json.loads(l)
        for l in (LEIS_DIR / "leis_federais.jsonl").read_text("utf-8").splitlines()
        if l.strip()
    ]
    artigos = []
    for lei in linhas:
        diploma = lei.get("apelido") or lei.get("lei", "Lei")
        texto   = str(lei.get("texto", ""))
        if len(texto) < 100:
            continue
        # doc_id único por diploma, tirado de "Lei 9.099/1995" -> LF9099-1995.
        # Com a sigla por iniciais, 157 leis viravam 85 ids ("LEI" sozinho juntava
        # 31 delas) e o --resume descartava 1.785 artigos (24%) como repetidos.
        m = re.search(r"(\d[\d\.]*)\s*/\s*(\d{4})", str(lei.get("lei", "")))
        did = f"LF{m.group(1).replace('.', '')}-{m.group(2)}" if m else doc_id(diploma)
        arts = dividir_em_artigos(texto, diploma, did=did)
        artigos.extend(arts)
    unicos = len({a["id"] for a in artigos})
    log.info(f"Leis federais: {len(artigos)} artigos ({unicos} ids únicos) de {len(linhas)} diplomas")
    return artigos[:limite] if limite else artigos


def carregar_sp(limite: int | None = None) -> list[dict]:
    linhas = [
        json.loads(l)
        for l in (LEIS_DIR / "leis_sp.jsonl").read_text("utf-8").splitlines()
        if l.strip()
    ]
    artigos = []
    for lei in linhas:
        diploma = lei.get("apelido") or lei.get("lei", "Lei SP")
        texto   = str(lei.get("texto", ""))
        if len(texto) < 100:
            continue
        # doc_id único por diploma: SP:<numero>-<ano>. A sigla por iniciais colidia
        # entre leis paulistas distintas e o --resume descartava o artigo repetido.
        did = f"SP{lei.get('numero','')}-{lei.get('ano','')}".replace(" ", "")
        arts = dividir_em_artigos(texto, diploma, did=did)
        artigos.extend(arts)
    log.info(f"Leis SP: {len(artigos)} artigos extraídos de {len(linhas)} diplomas")
    return artigos[:limite] if limite else artigos


# ── Geração ───────────────────────────────────────────────────────────────────

def gerar_expansao(artigo: dict, client, model: str, dry_run: bool = False) -> str:
    if dry_run:
        return f"[DRY-RUN] expansão para {artigo['id']}"

    identificacao = f"{artigo['diploma']} — {artigo['id'].replace(':', ' ')}"
    prompt = PROMPT_NORMA.format(
        doc_id        = artigo["doc_id"],
        num_art       = artigo["num_art"],
        identificacao = identificacao,
        documento     = artigo["texto"],
    ) + REGRA_FORMATO
    # O Mistral L3 embrulha a resposta em markdown (**[BLOCO]**, ### <<ID=...>>) e o
    # rechunk_v3 não reconhece bloco nenhum assim. Regra no prompt + limpeza na saída.
    return limpar_expansao(llm_chat(client, model, prompt, max_tokens=2000, temperature=0.4))


# ── Pipeline ──────────────────────────────────────────────────────────────────

def processar(artigos: list[dict], output_path: Path, client, model: str, dry_run: bool,
              delay: float, workers: int = 1) -> None:
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
                    ja_feitos.add(d["id"])
            except Exception:
                pass
        if ja_feitos:
            log.info(f"Resume: {len(ja_feitos)} já expandidos, pulando.")

    pendentes = [a for a in artigos if a["id"] not in ja_feitos]
    log.info(f"Total: {len(artigos)} | Pendentes: {len(pendentes)}")
    if not pendentes:
        log.info("Nada a fazer.")
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    modo   = "a" if ja_feitos else "w"
    erros  = 0
    inicio = time.time()
    lock   = threading.Lock()
    feitos = 0

    def _um(art: dict) -> dict:
        expansao = gerar_expansao(art, client, model, dry_run=dry_run)
        return {
            "id":            art["id"],
            "doc_id":        art["doc_id"],
            "diploma":       art["diploma"],
            "num_art":       art["num_art"],
            "texto_original": art["texto"],
            "expansao":      expansao,
            "modelo_gerador": model if not dry_run else "dry-run",
        }

    with open(output_path, modo, encoding="utf-8") as f_out:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futuros = {pool.submit(_um, a): a for a in pendentes}
            for fut in as_completed(futuros):
                art = futuros[fut]
                try:
                    resultado = fut.result()
                except Exception as e:
                    with lock:
                        erros += 1
                        log.error(f"  ✗ {art['id']}: {e}")
                        f_out.write(json.dumps({"id": art["id"], "expansao": None, "erro": str(e)},
                                               ensure_ascii=False) + "\n")
                        f_out.flush()
                    continue
                with lock:
                    feitos += 1
                    f_out.write(json.dumps(resultado, ensure_ascii=False) + "\n")
                    f_out.flush()
                    if feitos % 25 == 0 or feitos == len(pendentes):
                        decorrido = time.time() - inicio
                        eta = decorrido / feitos * (len(pendentes) - feitos)
                        log.info(f"  {feitos}/{len(pendentes)} · {feitos/decorrido:.1f}/s · ETA {eta/60:.0f} min")

    log.info(f"\n✓ {len(pendentes)-erros}/{len(pendentes)} expandidos | {erros} erros | {(time.time()-inicio)/60:.1f} min")
    log.info(f"Saída: {output_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Expande normas jurídicas artigo a artigo.")
    parser.add_argument("--fonte", choices=["cf88", "codigos", "federais", "sp", "todas"], default="todas")
    parser.add_argument("--limite", type=int, default=None, help="Máximo de artigos por fonte")
    parser.add_argument("--resume",  action="store_true", default=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay",   type=float, default=DELAY)
    parser.add_argument("--workers", type=int, default=1,
                        help="Chamadas simultâneas ao LLM (serial = 1)")
    args = parser.parse_args()

    if args.dry_run:
        client, model = None, "dry-run"
        log.info("MODO DRY-RUN")
    else:
        client, model = get_client()

    fontes_map = {
        "cf88":     (carregar_cf88,     "cf88_expandida.jsonl"),
        "codigos":  (carregar_codigos,  "codigos_expandidos.jsonl"),
        "federais": (carregar_federais, "leis_federais_expandidas.jsonl"),
        "sp":       (carregar_sp,       "leis_sp_expandidas.jsonl"),
    }

    fontes_rodar = list(fontes_map.keys()) if args.fonte == "todas" else [args.fonte]

    for nome in fontes_rodar:
        loader, out_name = fontes_map[nome]
        log.info(f"\n=== Fonte: {nome} ===")
        artigos = loader(args.limite)
        processar(artigos, OUTPUT_DIR / out_name, client, model, args.dry_run, args.delay, args.workers)


if __name__ == "__main__":
    main()
