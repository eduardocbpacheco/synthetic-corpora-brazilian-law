#!/usr/bin/env python3
"""
stj_acordaos.py — Crawler de acórdãos do STJ via informativos de jurisprudência.

Fonte: https://ww2.stj.jus.br/jurisprudencia/externo/InformativoFeed
       920 informativos × ~66 notas = ~60.000 decisões com ementa + fundamentação

Cada nota contém:
  - Processo (REsp, AREsp, HC, CC, etc.)
  - Relator, Turma/Seção, data
  - Tema (quando repetitivo)
  - Ementa
  - Fundamento (ratio decidendi em 1-2 parágrafos)
  - Ramo do direito

Saída: decisoes/stj/stj_informativos_acordaos.jsonl

Uso:
    python augmentation/crawlers/stj_acordaos.py
    python augmentation/crawlers/stj_acordaos.py --limite 50   # teste
    python augmentation/crawlers/stj_acordaos.py --desde 800   # a partir do informativo 800
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

_ROOT      = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = _ROOT / "decisoes" / "stj"
OUTPUT     = OUTPUT_DIR / "stj_informativos_acordaos.jsonl"
STATE_FILE = OUTPUT_DIR / "stj_crawler_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

FEED_URL  = "https://ww2.stj.jus.br/jurisprudencia/externo/InformativoFeed"
INFJ_URL  = "https://ww2.stj.jus.br/jurisprudencia/externo/informativo/"
HEADERS   = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer":         "https://www.stj.jus.br/",
}
DELAY = 1.2


def carregar_estado() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"informativos_processados": [], "total_notas": 0}


def salvar_estado(estado: dict) -> None:
    STATE_FILE.write_text(json.dumps(estado, indent=2))


def listar_informativos() -> list[dict]:
    """Baixa o feed RSS e retorna lista de informativos com número e URL."""
    log.info("Baixando feed RSS do STJ...")
    try:
        r = requests.get(FEED_URL, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.error(f"Erro ao baixar feed: {e}")
        return []

    root = ET.fromstring(r.content)
    ns   = {"atom": "http://www.w3.org/2005/Atom"}

    informativos = []
    for entry in root.findall("atom:entry", ns):
        title = entry.find("atom:title", ns)
        link  = entry.find("atom:link",  ns)
        if title is None or link is None:
            continue
        texto_title = title.text or ""
        # Extrai número do informativo: "Informativo n. 890 - ..."
        m = re.search(r"n\.\s*(\d+)", texto_title)
        if not m:
            continue
        informativos.append({
            "numero": int(m.group(1)),
            "titulo": texto_title,
            "url":    link.get("href", ""),
        })

    informativos.sort(key=lambda x: x["numero"], reverse=True)
    log.info(f"Feed: {len(informativos)} informativos encontrados (mais recente: {informativos[0]['numero']})")
    return informativos


def parse_nota(div) -> dict | None:
    """Extrai campos estruturados de uma divLinha do informativo."""
    texto = div.get_text(" ", strip=True)
    if len(texto) < 60:
        return None

    # Processo
    m_proc = re.search(
        r"(REsp|AREsp|HC|RHC|EREsp|AgRg|EDcl|MS|CC|Rcl|Pet|ARE|RE|ADI|ADPF)\s+[\d\.,]+\s*/\s*[A-Z]{2}",
        texto
    )
    processo = m_proc.group(0) if m_proc else ""

    # Relator
    m_rel = re.search(r"Rel\.?\s*(Ministr[ao])\s+([A-ZÁÉÍÓÚÂÊÔÃÕÜ][a-záéíóúâêôãõü\s]+?)(?:,|\.|Turma|Seção)", texto)
    relator = m_rel.group(2).strip() if m_rel else ""

    # Turma/Seção/Corte
    m_org = re.search(r"(\d+[ªa]?\s*Turma|[12]ª?\s*Seção|Corte Especial|Terceira Seção|Primeira Seção|Segunda Seção)", texto)
    orgao = m_org.group(1) if m_org else ""

    # Data
    m_data = re.search(r"julgado[s]?\s+em\s+([\d/]+)", texto)
    data = m_data.group(1) if m_data else ""

    # Tema repetitivo
    m_tema = re.search(r"Tema\s+(\d+)", texto)
    tema = m_tema.group(1) if m_tema else ""

    # Ramo do direito (ex: "DIREITO PENAL. DIREITO PROCESSUAL PENAL.")
    ramos = re.findall(r"DIREITO\s+[A-ZÁÉÍÓÚÇÃ\s]+?(?=\.|$)", texto[:200])
    ramo = ramos[0].strip() if ramos else ""

    return {
        "processo":  processo,
        "relator":   relator,
        "orgao":     orgao,
        "data":      data,
        "tema_rep":  tema,
        "ramo":      ramo,
        "texto":     texto,
        "n_chars":   len(texto),
    }


def crawl_informativo(numero: int, url: str) -> list[dict]:
    """Baixa e extrai todas as notas de um informativo."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except Exception as e:
        log.error(f"  Erro no informativo {numero}: {e}")
        return []

    soup = BeautifulSoup(r.content, "html.parser", from_encoding="iso-8859-1")

    # ── Formato novo (informativos ~500+): divLinha ───────────────────────────
    divlinhas = soup.find_all("div", class_="divLinha")
    if divlinhas:
        return _parse_formato_novo(soup, divlinhas, numero)

    # ── Formato antigo (informativos <500): HTML simples sem divLinha ─────────
    return _parse_formato_antigo(soup, numero)


def _parse_formato_novo(soup, divlinhas, numero: int) -> list[dict]:
    """Informativos recentes com divLinha — agrupa por processo."""
    notas = []
    acordaos_raw: list[list] = []
    atual: list = []

    for div in divlinhas:
        t = div.get_text(" ", strip=True)
        if re.match(r"^Processo\s+(REsp|AREsp|HC|RHC|EREsp|AgRg|MS|CC|Rcl|Pet|ARE|RE)", t):
            if atual:
                acordaos_raw.append(atual)
            atual = [div]
        elif atual:
            atual.append(div)
    if atual:
        acordaos_raw.append(atual)

    for grupo in acordaos_raw:
        texto_completo = " ".join(d.get_text(" ", strip=True) for d in grupo).strip()
        if len(texto_completo) < 100:
            continue
        nota = parse_nota(grupo[0])
        if nota:
            nota["texto"]      = texto_completo
            nota["n_chars"]    = len(texto_completo)
            nota["informativo"] = numero
            nota["fonte"]      = "stj_informativo"
            notas.append(nota)

    return notas


def _parse_formato_antigo(soup, numero: int) -> list[dict]:
    """
    Informativos antigos (<~500): HTML sem divLinha.
    Estrutura: blocos de texto separados por títulos de turma/seção.
    """
    notas = []
    PROC_RE = re.compile(
        r"(REsp|AREsp|HC|RHC|EREsp|AgRg|MS|CC|Rcl|Pet|ARE|RE)\s+[\d\.,]+\s*/\s*[A-Z]{2}"
    )
    TURMA_RE = re.compile(
        r"(PRIMEIRA|SEGUNDA|TERCEIRA|QUARTA|QUINTA|SEXTA|TURMA|SE[ÇC][ÃA]O|CORTE ESPECIAL)",
        re.IGNORECASE,
    )

    # Extrai todo o texto do body principal e divide por decisão
    # Cada decisão começa com uma linha "Rel. Ministro X" ou processo identificável
    texto_total = soup.get_text("\n", strip=True)
    # Divide por padrão de processo
    blocos = re.split(r"\n(?=(?:REsp|AREsp|HC|RHC|EREsp|MS|CC|Rcl)\s+[\d\.,]+)", texto_total)

    for bloco in blocos:
        if len(bloco.strip()) < 80:
            continue
        nota = parse_nota_texto(bloco.strip(), numero)
        if nota:
            notas.append(nota)

    return notas


def parse_nota_texto(texto: str, numero: int) -> dict | None:
    """Versão de parse_nota que opera sobre texto bruto (formato antigo)."""
    if len(texto) < 80:
        return None

    m_proc = re.search(
        r"(REsp|AREsp|HC|RHC|EREsp|AgRg|MS|CC|Rcl|Pet|ARE|RE)\s+[\d\.,]+\s*/\s*[A-Z]{2}",
        texto
    )
    processo = m_proc.group(0) if m_proc else ""

    m_rel = re.search(r"Rel\.?\s*(Ministr[ao])\s+([A-ZÁÉÍÓÚÂÊÔÃÕÜ][a-záéíóúâêôãõü\s\.]+?)(?:,|\.|Turma|Seção|\n)", texto)
    relator = m_rel.group(2).strip() if m_rel else ""

    m_org = re.search(r"(\d+[ªa]?\s*Turma|[12]ª?\s*Seção|Corte Especial)", texto)
    orgao = m_org.group(1) if m_org else ""

    m_data = re.search(r"julgado[s]?\s+em\s+([\d/]+)", texto)
    data = m_data.group(1) if m_data else ""

    m_tema = re.search(r"Tema\s+(\d+)", texto)
    tema = m_tema.group(1) if m_tema else ""

    return {
        "processo":  processo,
        "relator":   relator,
        "orgao":     orgao,
        "data":      data,
        "tema_rep":  tema,
        "ramo":      "",
        "texto":     texto[:2000],
        "n_chars":   len(texto),
        "informativo": numero,
        "fonte":     "stj_informativo_antigo",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawler de acórdãos STJ via informativos")
    parser.add_argument("--limite",  type=int, default=None,
                        help="Número máximo de informativos a processar")
    parser.add_argument("--desde",   type=int, default=None,
                        help="Processa a partir deste número de informativo")
    parser.add_argument("--ate",     type=int, default=None,
                        help="Processa até este número de informativo")
    parser.add_argument("--force",   action="store_true",
                        help="Reprocessa informativos já baixados")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    estado = carregar_estado()

    informativos = listar_informativos()
    if not informativos:
        log.error("Não foi possível obter a lista de informativos.")
        return

    # Filtra por faixa
    if args.desde:
        informativos = [i for i in informativos if i["numero"] >= args.desde]
    if args.ate:
        informativos = [i for i in informativos if i["numero"] <= args.ate]
    if not args.force:
        ja_feitos = set(estado["informativos_processados"])
        informativos = [i for i in informativos if i["numero"] not in ja_feitos]
    if args.limite:
        informativos = informativos[:args.limite]

    log.info(f"Informativos a processar: {len(informativos)}")
    if not informativos:
        log.info("Nada a fazer. Use --force para reprocessar.")
        return

    total_notas = estado["total_notas"]
    inicio = time.time()

    with open(OUTPUT, "a", encoding="utf-8") as f_out:
        for i, inf in enumerate(informativos, 1):
            num = inf["numero"]
            log.info(f"[{i}/{len(informativos)}] Informativo {num}")

            notas = crawl_informativo(num, inf["url"])
            for nota in notas:
                f_out.write(json.dumps(nota, ensure_ascii=False) + "\n")
            f_out.flush()

            total_notas += len(notas)
            estado["informativos_processados"].append(num)
            estado["total_notas"] = total_notas
            salvar_estado(estado)

            elapsed = time.time() - inicio
            eta     = elapsed / i * (len(informativos) - i)
            log.info(
                f"  {len(notas)} notas | acumulado: {total_notas} | "
                f"ETA: {eta/60:.1f} min"
            )
            time.sleep(DELAY)

    elapsed_total = time.time() - inicio
    log.info(f"\n✓ Concluído: {total_notas} notas em {elapsed_total/60:.1f} min")
    log.info(f"Saída: {OUTPUT}")


if __name__ == "__main__":
    main()
