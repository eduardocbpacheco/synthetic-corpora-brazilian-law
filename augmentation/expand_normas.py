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

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / 'pipeline'))
from identificadores import chave_de_registro          # noqa: E402

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

# Sigla canônica por diploma. Duas armadilhas moram aqui, e as duas já custaram corpus.
#
# A primeira é o casamento por substring: "Código Penal Militar" CONTÉM "Código Penal", e
# "Código Comercial" começa igual a "Código Civil" para quem abrevia. Com as chaves na
# ordem de escrita, o Código Penal Militar herdava `CP` do Penal comum e os dois artigos
# de diplomas diferentes se fundiam num identificador só. A varredura passa da chave mais
# longa para a mais curta, então a entrada específica sempre vence a genérica.
#
# A segunda é o fallback por iniciais: "Lei 10.406/2002" e "Lei 13.105/2015" produzem
# ambos `L`, e "Decreto-Lei 3.689/1941" e "Decreto-Lei 5.452/1943" produzem `DL`. Isso
# colapsava Código Civil, CPC, CPP e CLT em duas siglas. O fallback agora usa o número do
# diploma, que é o que de fato o distingue.
ID_MAP = {
    "CF88":                           "CF88",
    "Código Penal Militar":           "CPM",     # antes de "Código Penal"
    "Código Penal":                   "CP",
    "Código de Processo Civil":       "CPC",
    "Código de Processo Penal":       "CPP",
    "Código Civil":                   "CC",
    "Código Comercial":               "CCOM",    # não é o Civil
    "CLT":                            "CLT",
    "Código de Defesa do Consumidor": "CDC",
    "Código Tributário Nacional":     "CTN",
    "Código de Trânsito Brasileiro":  "CTB",
    # A mesma lei aparece nas duas fontes com nomes diferentes: "Código de Trânsito
    # Brasileiro" no parquet de códigos e "CTB Código de Trânsito" no jsonl federal.
    # Sem a forma curta, um lado casava e o outro caía na chave canônica, e o par
    # deixava de parear. Vale o mesmo para a Lei de Propriedade Industrial.
    "Código de Trânsito":             "CTB",
    "Propriedade Industrial":         "LPI",
    "Código Brasileiro de Telecomunica": "CBT",
    "Código Eleitoral":               "CE",
    "Código Florestal":               "CFLO",
    "Código de Águas":                "CAGUAS",  # sem acento na sigla
    "Código de Minas":                "CMIN",
    "Lei de Propriedade Industrial":  "LPI",
    "ECA":                            "ECA",
    "Estatuto da OAB":                "EOAB",
}


def sigla_conhecida(nome: str) -> str | None:
    """A sigla consagrada do diploma, ou None se ele não tiver uma.

    Existe porque os dois braços precisam responder à MESMA pergunta: "este diploma tem
    apelido?". Sem separar isso do fallback, o bruto chamava `doc_id` e recebia iniciais
    (`A`, `AF`, `AI`) para as leis sem apelido, enquanto o expandido usava a chave
    canônica — e o pareamento da legislação caía a 7,9% por divergência de convenção, não
    de conteúdo.
    """
    for k in sorted(ID_MAP, key=len, reverse=True):
        if k.lower() in nome.lower():
            return ID_MAP[k]
    return None


def doc_id(nome: str) -> str:
    # Da chave mais longa para a mais curta: sem isso "Código Penal Militar" casa com
    # "Código Penal" e os dois diplomas passam a dividir o mesmo identificador.
    for k in sorted(ID_MAP, key=len, reverse=True):
        if k.lower() in nome.lower():
            return ID_MAP[k]
    # Fallback pelo número do diploma, que é o que o distingue. "Lei 10.406/2002" vira
    # L10406-2002, e não `L` como antes.
    m = re.search(r"(\d[\d.]*)\s*/\s*(\d{4})", nome)
    if m:
        pre = "DL" if "decreto-lei" in nome.lower() else "D" if "decreto" in nome.lower() else "L"
        return f"{pre}{m.group(1).replace('.', '')}-{m.group(2)}"
    palavras = re.findall(r"[A-ZÁÉÍÓÚ][a-záéíóú]+", nome)
    return "".join(p[0] for p in palavras[:4]).upper() or "LEI"


# ── Divisão em artigos ────────────────────────────────────────────────────────

# Aceita "Art. 1º" (federal/códigos) E "Artigo 1° -" (padrão da ALESP nas leis de SP).
# Sem a alternativa "Artigo", as 27 leis paulistas rendiam 0 artigos e a fonte `sp`
# ficava vazia — foi o motivo de leis_sp_expandidas.jsonl nunca ter sido gerado.
# O número aceita separador de milhar: `\d+` sozinho parava no ponto, e "Art. 1.000" era
# dividido como "Art. 1" com ".000" caindo no corpo. Os 76 artigos da faixa 1.000–1.072 do
# CPC colidiam com os artigos 1 a 72 e eram descartados na deduplicação — o CPC rendia
# exatamente 999 artigos, número que denuncia o defeito.
#
# O sufixo exige hífen COLADO ao número e letra isolada. Duas armadilhas: `[A-Z]?` engolia
# a primeira letra do corpo ("Art. 5. A parte..." virava cabeçalho "Art. 5. A"); e a CLT
# escreve "Art. 1º - Esta Consolidação", em que o hífen separa o corpo e não marca sufixo.
# Aceitar o hífen com espaços rendia 685 sufixos falsos em 886 artigos da CLT, partindo a
# palavra seguinte ao meio. Sufixo de verdade vem colado e sozinho: "58-A", "75-B".
_ART_RE = re.compile(
    r"(?:^|\n)\s*((?:Artigo|Art\.?)\s*\d{1,3}(?:\.\d{3})*[º°]?"
    # `[ \t]*` e não `\s*` no fim: com `\s*` a expressão consome a quebra de linha que o
    # PRÓXIMO marcador precisa para ser reconhecido, e dois artigos separados apenas por
    # espaço em branco viram um só — o segundo desaparece. Foi assim que o art. 239 do
    # Código Eleitoral sumiu: ele vem logo depois de uma remissão que abre linha
    # ("observado o disposto no\nArt. 141."), e o `\s*` do 141 comeu a quebra do 239.
    r"(?:[-–][A-Za-z](?![a-zà-úA-ZÀ-Ú]))?[\.\-]?)[ \t]*",
    re.MULTILINE,
)


# V4 · artigo cujo corpo é só a nota de revogação ou de veto.
#
# Duas notações convivem na fonte: o parêntese ("Art. 262. (Revogado pela Lei nº 13.281,
# de 2016)") e a etiqueta ("Art. 233. <revogado></revogado>", que é como a CF/88 vem). Uma
# contagem por marca solta de texto acha mais de mil, mas quase todos são artigos EM VIGOR
# com um inciso revogado, que devem ficar. O alvo são os 44 em que não sobrou dispositivo.
#
# Importa barrar aqui, antes da geração: cada um destes rendia de 4 a 14 blocos de ficha —
# explicação, síntese, relação, efeito prático, jurisprudência e perguntas — sobre um
# dispositivo que não existe mais. Barrar antes economiza a chamada e evita o conteúdo.
_SO_REVOGACAO = re.compile(
    r"^\s*(?:Art\.?|Artigo)\s*[\d.]+\s*[ºo°]?\s*[\.\-–]?\s*"
    r"(?:[\(\[]?\s*(?:Revogad[oa]|VETADO)\b.{0,200}"
    r"|<\s*revogad[oa]\s*>\s*</\s*revogad[oa]\s*>"
    r"|<\s*vetado\s*>\s*</\s*vetado\s*>)\s*[\)\]]?\s*$",
    re.IGNORECASE | re.DOTALL)


def revogado_por_inteiro(texto_art: str) -> bool:
    return bool(_SO_REVOGACAO.match(texto_art.strip()))

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

        # Extrai número do artigo do cabeçalho.
        #
        # `(\d+)` sozinho parava no separador de milhar e no sufixo: "Art. 1.000" virava 1,
        # "Art. 75-A" virava 75. Como a deduplicação logo abaixo guarda uma ocorrência por
        # identificador, os artigos colididos não eram só mal rotulados — eram DESCARTADOS.
        # O Código Civil perdia a faixa dos 1.000 inteira para o artigo 1º.
        m = re.search(r"(\d[\d.]*)\s*(?:º|°)?(?:[-–]([A-Za-z])(?![a-zà-úA-ZÀ-Ú]))?", cabecalho)
        if m:
            num_art = int(m.group(1).replace(".", "").rstrip(".") or 0)
            sufixo = (m.group(2) or "").upper()
        else:
            num_art, sufixo = num_global + 1, ""
        num_global = num_art

        texto_art = f"{cabecalho} {corpo}".strip()
        if len(texto_art) < 30:
            continue
        if revogado_por_inteiro(texto_art):     # V4
            continue

        artigos.append({
            # O sufixo entra no identificador: 75, 75-A e 75-B são três artigos, e sem ele
            # os dois últimos sumiam por colisão com o primeiro.
            "id":        f"{did}:ART:{num_art:04d}" + (f"-{sufixo}" if sufixo else ""),
            "doc_id":    did,
            "diploma":   diploma,
            "num_art":   num_art,
            "sufixo":    sufixo,
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
        # C16 · a chave canônica, a mesma que o braço bruto usa. Sem isso os dois braços
        # identificavam o MESMO diploma de formas incompatíveis e o pareamento da regra D4
        # não era nem conferível.
        did = sigla_conhecida(diploma) or chave_de_registro(lei, "BR")
        arts = dividir_em_artigos(texto, diploma, did=did)
        artigos.extend(arts)
    unicos = len({a["id"] for a in artigos})
    log.info(f"Leis federais: {len(artigos)} artigos ({unicos} ids únicos) de {len(linhas)} diplomas")
    return artigos[:limite] if limite else artigos


def carregar_cesp(limite: int | None = None) -> list[dict]:
    """A6 · Constituição do Estado de São Paulo, o diploma que faltava nos dois braços."""
    p = LEIS_DIR / "cesp.jsonl"
    if not p.exists():
        log.warning("cesp.jsonl ausente; rode pipeline/coleta_cesp.py")
        return []
    artigos = []
    for linha in p.read_text("utf-8").splitlines():
        if not linha.strip():
            continue
        d = json.loads(linha)
        artigos.extend(dividir_em_artigos(str(d.get("texto") or ""),
                                          d.get("apelido") or "Constituição Estadual de SP",
                                          did=d.get("chave") or chave_de_registro(d, "SP")))
    log.info(f"CESP: {len(artigos)} artigos")
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
        did = sigla_conhecida(diploma) or chave_de_registro(lei, "SP")   # C16
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
    parser.add_argument("--fonte", choices=["cf88", "codigos", "federais", "sp", "cesp", "todas"], default="todas")
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
        "cesp":     (carregar_cesp,     "cesp_expandida.jsonl"),
    }

    fontes_rodar = list(fontes_map.keys()) if args.fonte == "todas" else [args.fonte]

    for nome in fontes_rodar:
        loader, out_name = fontes_map[nome]
        log.info(f"\n=== Fonte: {nome} ===")
        artigos = loader(args.limite)
        processar(artigos, OUTPUT_DIR / out_name, client, model, args.dry_run, args.delay, args.workers)


if __name__ == "__main__":
    main()
