#!/usr/bin/env python3
"""
referencia_v3.py — a LISTA DE REFERÊNCIA de diplomas do corpus v3, e as medidas de cobertura.

A lista nasceu da auditoria de 14/11/2026: são os diplomas que os gabaritos da OAB (questões
de 2ª fase do `sft_oab.jsonl` e do `benchmark_v2.jsonl`) citam por artigo. A auditoria
mediu, para cada um, quantos artigos estavam nos dois braços congelados e achou o que o
corpus nunca tinha medido: o Código Civil com 37 de 2.046 artigos no bruto, o Código Penal
com zero (o `DOC=CP` era o Penal Militar), e 32 diplomas citados que nunca foram coletados.

Este módulo é a régua do PORTÃO do v3: todo diploma daqui precisa ter ≥ 98% dos artigos
VIGENTES nos dois braços. Ele não monta nada; quem monta é `monta_corpus_v3.py`.

Três definições, e elas importam porque foi a falta delas que deixou o defeito passar:

  · ARTIGO VIGENTE: o que `expand_normas.dividir_em_artigos` encontra no texto da fonte
    DEPOIS de tirar o riscado (`<revogado>…</revogado>`, que é como o Planalto marca a
    redação superada — ver A7/V6). O divisor já descarta o artigo cujo corpo é só a nota
    "(Revogado pela Lei …)". É a mesma definição que governa a geração das fichas (V4).
  · PRESENTE NO BRUTO: o artigo abre linha ("Art. 5º", "Art . 36", "Artigo 1º") dentro de um
    bloco `<<LEI|BRUTO|…>>` daquele diploma, depois de tirado o riscado.
  · PRESENTE NO EXPANDIDO: existe ficha `<<ID=DOC:ART:NNNN|…|TYPE=ART` com um dos DOC do
    diploma — há diploma com dois DOC no congelado, porque ele entrou por duas fontes
    (CTB e LF9503-1997, LPI e LF9279-1996, EOAB e LF8906-1994).

A cobertura é medida por NÚMERO-BASE do artigo (75, 75-A e 75-B contam como 75), como a
auditoria fez: as fichas antigas gravavam `:ART:0075` também para o 75-A (o prompt formata
`{num_art:04d}` e o sufixo se perdia), então não há como contar sufixo no expandido
congelado. O sufixo é contado à parte onde é mensurável.
"""
from __future__ import annotations
import json, os, re, sys
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "pipeline"))
sys.path.insert(0, str(RAIZ / "augmentation"))

# (chave, nome, área, lei = identificador do bloco bruto no congelado (é o campo `lei` da
#  fonte), DOCs das fichas no congelado, DOC para fichas novas, arquivo de recoleta)
#
# `rec` aponta a melhor fonte de texto: `v3:CHAVE` é leis/recoleta_v3/CHAVE.json (coleta
# desta etapa), `v2:arquivo` é leis/recoleta_v2/arquivo.json; sem `rec`, vale o texto mais
# longo entre `leis_federais.jsonl` e `codigos_especificos.parquet`.
REFERENCIA = [
    ("CF88",   "CF/88 (corpo permanente)",           "todas",  "CF/1988",                ["CF88"],                 "CF88",          None),
    ("CPC",    "CPC/2015",                           "transv.", "Lei 13.105/2015",       ["CPC"],                  "CPC",           None),
    ("LINDB",  "LINDB (DL 4.657/42)",                "transv.", "Decreto-Lei 4.657/1942", [],                      "LINDB",         "v3:LINDB"),
    ("L8906",  "Estatuto da OAB (L 8.906/94)",       "ética",  "Lei 8.906/1994",         ["EOAB", "LF8906-1994"],  "EOAB",          None),
    ("CED-OAB","Código de Ética e Disciplina da OAB","ética",  "Resolução CFOAB 02/2015", [],                      "CED-OAB",       "v3:CED-OAB"),
    ("L9868",  "Lei 9.868/99 (ADI/ADC)",             "const",  "Lei 9.868/1999",         ["LF9868-1999"],          "LF9868-1999",   None),
    ("L9882",  "Lei 9.882/99 (ADPF)",                "const",  "Lei 9.882/1999",         [],                       "LF9882-1999",   "v3:L9882"),
    ("L12016", "Lei 12.016/09 (MS)",                 "const/adm", "Lei 12.016/2009",     ["LF12016-2009"],         "LF12016-2009",  None),
    ("L4717",  "Lei 4.717/65 (Ação Popular)",        "const/adm", "Lei 4.717/1965",      [],                       "LF4717-1965",   "v3:L4717"),
    ("L7347",  "Lei 7.347/85 (ACP)",                 "const/adm", "Lei 7.347/1985",      ["LF7347-1985"],          "LF7347-1985",   None),
    ("L13300", "Lei 13.300/16 (MI)",                 "const",  "Lei 13.300/2016",        [],                       "LF13300-2016",  "v3:L13300"),
    ("L9507",  "Lei 9.507/97 (HD)",                  "const",  "Lei 9.507/1997",         [],                       "LF9507-1997",   "v3:L9507"),
    ("L11417", "Lei 11.417/06 (SV)",                 "const",  "Lei 11.417/2006",        [],                       "LF11417-2006",  "v3:L11417"),
    ("L8112",  "Lei 8.112/90",                       "adm",    "Lei 8.112/1990",         ["LF8112-1990"],          "LF8112-1990",   "v2:lei_8112"),
    ("L14133", "Lei 14.133/21",                      "adm",    "Lei 14.133/2021",        ["LF14133-2021"],         "LF14133-2021",  None),
    ("L8666",  "Lei 8.666/93 (revogada em 2023)",    "adm",    "Lei 8.666/1993",         ["LF8666-1993"],          "LF8666-1993",   "v2:lei_8666"),
    ("L9784",  "Lei 9.784/99",                       "adm",    "Lei 9.784/1999",         ["LF9784-1999"],          "LF9784-1999",   None),
    ("L8429",  "Lei 8.429/92 (LIA)",                 "adm",    "Lei 8.429/1992",         ["LF8429-1992"],          "LF8429-1992",   "v2:lei_8429"),
    ("L8987",  "Lei 8.987/95 (Concessões)",          "adm",    "Lei 8.987/1995",         ["LF8987-1995"],          "LF8987-1995",   None),
    ("L11079", "Lei 11.079/04 (PPP)",                "adm",    "Lei 11.079/2004",        [],                       "LF11079-2004",  "v3:L11079"),
    ("DL3365", "DL 3.365/41 (Desapropriação)",       "adm",    "DL 3.365/1941",          ["LF3365-1941"],          "LF3365-1941",   None),
    ("L12846", "Lei 12.846/13 (Anticorrupção)",      "adm",    "Lei 12.846/2013",        [],                       "LF12846-2013",  "v3:L12846"),
    ("L13303", "Lei 13.303/16 (Estatais)",           "adm",    "Lei 13.303/2016",        [],                       "LF13303-2016",  "v3:L13303"),
    ("L11107", "Lei 11.107/05 (Consórcios)",         "adm",    "Lei 11.107/2005",        [],                       "LF11107-2005",  "v3:L11107"),
    ("L10257", "Lei 10.257/01 (Estatuto da Cidade)", "adm",    "Lei 10.257/2001",        [],                       "LF10257-2001",  "v3:L10257"),
    ("L13019", "Lei 13.019/14 (MROSC)",              "adm",    "Lei 13.019/2014",        [],                       "LF13019-2014",  "v3:L13019"),
    ("LC101",  "LC 101/00 (LRF)",                    "adm/fin", "LC 101/2000",           ["LF101-2000"],           "LF101-2000",    "v2:lc_101"),
    ("CC",     "Código Civil",                       "civ/emp", "Lei 10.406/2002",       ["CC"],                   "CC",            "v2:lei_10406"),
    ("CDC",    "CDC",                                "civ",    "Lei 8.078/1990",         ["CDC"],                  "CDC",           None),
    ("ECA",    "ECA",                                "civ/pen", "Lei 8.069/1990",        ["ECA"],                  "ECA",           "v2:lei_8069"),
    ("L8245",  "Lei 8.245/91 (Locações)",            "civ/emp", "Lei 8.245/1991",        ["LF8245-1991"],          "LF8245-1991",   None),
    ("L8009",  "Lei 8.009/90 (Bem de família)",      "civ",    "Lei 8.009/1990",         ["LF8009-1990"],          "LF8009-1990",   None),
    ("L5478",  "Lei 5.478/68 (Alimentos)",           "civ",    "Lei 5.478/1968",         [],                       "LF5478-1968",   "v3:L5478"),
    ("L10741", "Lei 10.741/03 (Estatuto da Pessoa Idosa)", "civ", "Lei 10.741/2003",     ["LF10741-2003"],         "LF10741-2003",  "v3:L10741"),
    ("L13146", "Lei 13.146/15 (EPD)",                "civ",    "Lei 13.146/2015",        ["LF13146-2015"],         "LF13146-2015",  None),
    ("L11101", "Lei 11.101/05 (Falências)",          "emp",    "Lei 11.101/2005",        ["LF11101-2005"],         "LF11101-2005",  "v2:lei_11101"),
    ("L6404",  "Lei 6.404/76 (S.A.)",                "emp",    "Lei 6.404/1976",         ["LF6404-1976"],          "LF6404-1976",   "v2:lei_6404"),
    ("D57663", "LUG (Dec. 57.663/66)",               "emp",    "Decreto 57.663/1966",    [],                       "LUG",           "v3:D57663"),
    ("L5474",  "Lei 5.474/68 (Duplicata)",           "emp",    "Lei 5.474/1968",         ["LF5474-1968"],          "LF5474-1968",   "v3:L5474"),
    ("L7357",  "Lei 7.357/85 (Cheque)",              "emp",    "Lei 7.357/1985",         ["LF7357-1985"],          "LF7357-1985",   "v3:L7357"),
    ("D2044",  "Dec. 2.044/1908 (Letra/NP)",         "emp",    "Decreto 2.044/1908",     [],                       "LF2044-1908",   "v3:D2044"),
    ("L9279",  "Lei 9.279/96 (LPI)",                 "emp",    "Lei 9.279/1996",         ["LPI", "LF9279-1996"],   "LPI",           None),
    ("L8934",  "Lei 8.934/94 (Registro de Empresas)", "emp",   "Lei 8.934/1994",         [],                       "LF8934-1994",   "v3:L8934"),
    ("LC123",  "LC 123/06 (Simples)",                "emp/trib", "LC 123/2006",          ["LF123-2006"],           "LF123-2006",    "v2:lc_123"),
    ("L4886",  "Lei 4.886/65 (Representação comercial)", "emp", "Lei 4.886/1965",        [],                       "LF4886-1965",   "v3:L4886"),
    ("L9307",  "Lei 9.307/96 (Arbitragem)",          "emp/civ", "Lei 9.307/1996",        ["LF9307-1996"],          "LF9307-1996",   None),
    ("CP",     "Código Penal (DL 2.848/40)",         "pen",    "Decreto-Lei 2.848/1940", [],                       "CP",            "v2:dl_2848"),
    ("CPP",    "CPP",                                "pen",    "Decreto-Lei 3.689/1941", ["CPP"],                  "CPP",           None),
    ("L7210",  "LEP (L 7.210/84)",                   "pen",    "Lei 7.210/1984",         ["LF7210-1984"],          "LF7210-1984",   None),
    ("L9099",  "Lei 9.099/95 (Juizados)",            "pen/civ", "Lei 9.099/1995",        ["LF9099-1995"],          "LF9099-1995",   None),
    ("L11343", "Lei 11.343/06 (Drogas)",             "pen",    "Lei 11.343/2006",        ["LF11343-2006"],         "LF11343-2006",  None),
    ("L8072",  "Lei 8.072/90 (Hediondos)",           "pen",    "Lei 8.072/1990",         ["LF8072-1990"],          "LF8072-1990",   None),
    ("L11340", "Lei 11.340/06 (Maria da Penha)",     "pen",    "Lei 11.340/2006",        ["LF11340-2006"],         "LF11340-2006",  None),
    ("L12850", "Lei 12.850/13 (Organização criminosa)", "pen", "Lei 12.850/2013",        [],                       "LF12850-2013",  "v3:L12850"),
    ("L10826", "Lei 10.826/03 (Desarmamento)",       "pen",    "Lei 10.826/2003",        ["LF10826-2003"],         "LF10826-2003",  "v3:L10826"),
    ("L9296",  "Lei 9.296/96 (Interceptação)",       "pen",    "Lei 9.296/1996",         [],                       "LF9296-1996",   "v3:L9296"),
    ("L8137",  "Lei 8.137/90 (Crimes tributários)",  "pen/trib", "Lei 8.137/1990",       [],                       "LF8137-1990",   "v3:L8137"),
    ("L9605",  "Lei 9.605/98 (Crimes ambientais)",   "pen",    "Lei 9.605/1998",         [],                       "LF9605-1998",   "v3:L9605"),
    ("L9613",  "Lei 9.613/98 (Lavagem)",             "pen",    "Lei 9.613/1998",         [],                       "LF9613-1998",   "v3:L9613"),
    ("L13869", "Lei 13.869/19 (Abuso de autoridade)", "pen",   "Lei 13.869/2019",        [],                       "LF13869-2019",  "v3:L13869"),
    ("L9503",  "CTB",                                "pen",    "Lei 9.503/1997",         ["CTB", "LF9503-1997"],   "CTB",           None),
    ("CLT",    "CLT (DL 5.452/43)",                  "trab",   "Decreto-Lei 5.452/1943", ["CLT"],                  "CLT",           "v2:dl_5452"),
    ("L8036",  "Lei 8.036/90 (FGTS)",                "trab",   "Lei 8.036/1990",         [],                       "LF8036-1990",   "v3:L8036"),
    ("L5584",  "Lei 5.584/70 (Processo do trabalho)", "trab",  "Lei 5.584/1970",         [],                       "LF5584-1970",   "v3:L5584"),
    ("L7783",  "Lei 7.783/89 (Greve)",               "trab",   "Lei 7.783/1989",         [],                       "LF7783-1989",   "v3:L7783"),
    ("LC150",  "LC 150/15 (Doméstico)",              "trab",   "LC 150/2015",            [],                       "LF150-2015",    "v3:LC150"),
    ("L6019",  "Lei 6.019/74 (Temporário/Terceirização)", "trab", "Lei 6.019/1974",      [],                       "LF6019-1974",   "v3:L6019"),
    ("L605",   "Lei 605/49 (RSR)",                   "trab",   "Lei 605/1949",           [],                       "LF605-1949",    "v3:L605"),
    ("L8213",  "Lei 8.213/91 (Benefícios)",          "trab",   "Lei 8.213/1991",         ["LF8213-1991"],          "LF8213-1991",   "v2:lei_8213"),
    ("L8212",  "Lei 8.212/91 (Custeio)",             "trab/trib", "Lei 8.212/1991",      ["LF8212-1991"],          "LF8212-1991",   "v2:lei_8212"),
    ("CTN",    "CTN (L 5.172/66)",                   "trib",   "Lei 5.172/1966",         ["CTN"],                  "CTN",           None),
    ("L6830",  "LEF (L 6.830/80)",                   "trib",   "Lei 6.830/1980",         ["LF6830-1980"],          "LF6830-1980",   None),
    ("LC87",   "LC 87/96 (Kandir/ICMS)",             "trib",   "LC 87/1996",             ["LF87-1996"],            "LF87-1996",     "v2:lc_87"),
    ("LC116",  "LC 116/03 (ISS)",                    "trib",   "LC 116/2003",            ["LF116-2003"],           "LF116-2003",    None),
    ("L8397",  "Lei 8.397/92 (Cautelar fiscal)",     "trib",   "Lei 8.397/1992",         [],                       "LF8397-1992",   "v3:L8397"),
    ("LC24",   "LC 24/75 (Convênios ICMS)",          "trib",   "LC 24/1975",             [],                       "LF24-1975",     "v3:LC24"),
    ("L9430",  "Lei 9.430/96",                       "trib",   "Lei 9.430/1996",         ["LF9430-1996"],          "LF9430-1996",   "v2:lei_9430"),
    ("LC214",  "LC 214/25 (IBS/CBS)",                "trib",   "LC 214/2025",            [],                       "LF214-2025",    "v3:LC214"),
]
CAMPOS = ("chave", "nome", "area", "lei", "docs", "novo_doc", "rec")
DIPLOMAS = [dict(zip(CAMPOS, r)) for r in REFERENCIA]
POR_CHAVE = {d["chave"]: d for d in DIPLOMAS}


# ── texto da fonte ────────────────────────────────────────────────────────────────────

def _tabela_cp():
    import rechunk_v3 as R3
    return R3._CP1250                       # A7: só a recoleta_v2 precisa; idempotente


@lru_cache(maxsize=None)
def _fontes_antigas() -> dict:
    """lei -> texto mais longo entre leis_federais.jsonl e codigos_especificos.parquet."""
    import pandas as pd
    out = {}
    for l in (RAIZ / "leis/leis_federais.jsonl").read_text("utf-8").splitlines():
        if l.strip():
            d = json.loads(l)
            if len(d.get("texto") or "") > len(out.get(d["lei"], "")):
                out[d["lei"]] = d["texto"]
    for _, r in pd.read_parquet(RAIZ / "leis/codigos_especificos.parquet").iterrows():
        if len(r["texto"] or "") > len(out.get(r["lei"], "")):
            out[r["lei"]] = r["texto"]
    cf = pd.read_parquet(RAIZ / "leis/cf88_adct.parquet")
    out["CF/1988"] = str(cf[cf["lei"] == "CF88"]["texto"].iloc[0])
    return out


@lru_cache(maxsize=None)
def fonte(chave: str) -> dict:
    """{texto, origem, url} do diploma, pela melhor fonte disponível."""
    d = POR_CHAVE[chave]
    rec = d["rec"] or ""
    if rec.startswith("v3:"):
        p = RAIZ / "leis/recoleta_v3" / f"{rec[3:]}.json"
        if p.exists():
            r = json.loads(p.read_text("utf-8"))
            if r.get("texto"):
                return {"texto": r["texto"], "origem": str(p.relative_to(RAIZ)),
                        "url": r.get("url", ""), "coletado_em": r.get("coletado_em", "")}
    if rec.startswith("v2:"):
        p = RAIZ / "leis/recoleta_v2" / f"{rec[3:]}.json"
        if p.exists():
            r = json.loads(p.read_text("utf-8"))
            return {"texto": r["texto"].translate(_tabela_cp()), "origem": str(p.relative_to(RAIZ)),
                    "url": r.get("url") or "", "coletado_em": "2026-09 (recoleta_v2)"}
    t = _fontes_antigas().get(d["lei"], "")
    return {"texto": t, "origem": "leis_federais.jsonl / codigos_especificos.parquet / cf88_adct.parquet",
            "url": "", "coletado_em": "2026-02/04 (coleta original)"}


# ── artigos ───────────────────────────────────────────────────────────────────────────

def tira_riscado(texto: str) -> str:
    return re.sub(r"\n{3,}", "\n\n",
                  re.sub(r"<revogado>.*?</revogado>", " ", texto or "", flags=re.S))


# "Artigo 1º" por extenso (LUG, CED, leis da ALESP), "Art . 36" com espaço (Cheque,
# Duplicata), separador de milhar ("Art. 1.089") e sufixo colado ("Art. 149-A").
# O espaço inclui o NBSP (\xa0): o Planalto escreve "Art.\xa01º", e com só [ \t] a Lei
# 8.112 aparecia com 47 de 239 artigos no bruto congelado, quando tinha os 239. E o número
# pode vir na LINHA SEGUINTE ("Art.\n135", herança do HTML): sem o `\n?` a Lei 14.133
# aparecia com 7 de 193 artigos.
RX_ART_LINHA = re.compile(
    r"(?m)^[ \t\xa0]*Art(?:igo)?[ \t\xa0]*\.?[ \t\xa0]*\n?[ \t\xa0]*(\d{1,2}\.\d{3}|\d{1,4})[ \t\xa0]*[ºo°]?"
    r"(?:[ \t\xa0]*[-–][ \t\xa0]?([A-Z])(?![a-zà-ú]))?")


def base(n) -> int:
    return int(str(n).replace(".", ""))


def artigos_presentes_texto(texto: str) -> set[tuple[int, str]]:
    """(número, sufixo) dos artigos que abrem linha num texto de lei, sem o riscado."""
    t = tira_riscado(texto)
    return {(base(m.group(1)), (m.group(2) or "").upper()) for m in RX_ART_LINHA.finditer(t)}


def _normaliza_artigo_por_extenso(texto: str) -> str:
    """Duas grafias de cabeçalho que o divisor do expandido não lê, e que somem com a ficha:
    "Art . 36", com espaço antes do ponto (Cheque, Duplicata, Representação Comercial —
    o Cheque rendia ZERO artigos), e "Artigo 1.º" (Anexo I da LUG)."""
    texto = re.sub(r"(?m)^([ \t]*Art)[ \t]+\.", r"\1.", texto)
    return re.sub(r"(?m)^([ \t]*Artigo[ \t]*\d+)\.[ \t]*º", r"\1º", texto)


@lru_cache(maxsize=None)
def artigos_vigentes(chave: str) -> dict:
    """{(número, sufixo): texto do artigo} dos artigos vigentes, pelo divisor do expandido.

    É o mesmo `dividir_em_artigos` que gera as fichas: o que é vigente para o portão é,
    por construção, o que pode virar ficha. Sem o riscado e sem o artigo só-revogação (V4).
    """
    from expand_normas import dividir_em_artigos
    t = _normaliza_artigo_por_extenso(tira_riscado(fonte(chave)["texto"]))
    d = POR_CHAVE[chave]
    arts = dividir_em_artigos(t, d["nome"], did=d["novo_doc"])
    out = {}
    for a in arts:
        k = (int(a["num_art"]), a.get("sufixo", "") or "")
        if k not in out or len(a["texto"]) > len(out[k]["texto"]):
            out[k] = a
    return out


def bases_vigentes(chave: str) -> set[int]:
    return {n for n, _ in artigos_vigentes(chave)}


# ── presença nos braços ───────────────────────────────────────────────────────────────

RX_CAB_LEI = re.compile(r"^<<LEI\|BRUTO\|([^>]+)>>")
RX_FICHA_ART = re.compile(r"<<ID=([^|>]+):ART:(\d{1,4})(?:-([A-Za-z]))?(?=[|:>])[^>]*?\|DOC=([^|>]+)\|TYPE=ART\b")


def presenca_bruto(textos) -> dict:
    """ident do bloco -> {(número, sufixo)} presentes."""
    out: dict = {}
    for t in textos:
        m = RX_CAB_LEI.match(t)
        if m:
            out.setdefault(m.group(1), set()).update(artigos_presentes_texto(t))
    return out


def presenca_cards(textos) -> dict:
    """DOC -> {(número, sufixo)} com ficha TYPE=ART."""
    out: dict = {}
    for t in textos:
        for m in RX_FICHA_ART.finditer(t):
            out.setdefault(m.group(4), set()).add((int(m.group(2)), (m.group(3) or "").upper()))
    return out


def cobertura(chave: str, pres_b: dict, pres_c: dict, idents_b=None) -> dict:
    d = POR_CHAVE[chave]
    vig = bases_vigentes(chave)
    idents_b = idents_b or [d["lei"]]
    b = set().union(*[{n for n, _ in pres_b.get(i, set())} for i in idents_b]) if idents_b else set()
    docs = set(d["docs"]) | {d["novo_doc"]}
    c = set().union(*[{n for n, _ in pres_c.get(x, set())} for x in docs])
    nb, nc = len(vig & b), len(vig & c)
    return {"vigentes": len(vig), "bruto": nb, "cards": nc,
            "pct_bruto": round(100 * nb / len(vig), 1) if vig else 0.0,
            "pct_cards": round(100 * nc / len(vig), 1) if vig else 0.0,
            "faltam_bruto": sorted(vig - b), "faltam_cards": sorted(vig - c)}


if __name__ == "__main__":
    for d in DIPLOMAS:
        f = fonte(d["chave"])
        print(f"{d['chave']:8} {len(f['texto']):>9,} chars  vigentes {len(bases_vigentes(d['chave'])):>5}  {f['origem']}")
