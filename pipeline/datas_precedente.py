#!/usr/bin/env python3
"""datas_precedente.py — a data que a ficha diz não ter, recuperada da coleta.

Q6 · 19.070 das 23.530 fichas de precedente escrevem, no bloco `[IDENTIFICAÇÃO]`,
"Data: (informação insuficiente nas fontes fornecidas)". A causa não é o modelo-professor
ter inventado nem ter se recusado: a SEMENTE que ele recebeu não trazia a data. Os arquivos
de `augmentation/output/*_rica.jsonl` têm `juris_id`, `identificador`, `tipo`, `tribunal` e
`expansao`, e nenhum campo de data. O gerador escreveu a verdade sobre o que tinha à vista.

A data existe, mas nos arquivos de COLETA, e o que faltava era casar as duas pontas. As
chaves não casam sozinhas, e cada tribunal falha de um jeito:

  · o STF guarda a classe em `processo_classe_processual_unificada_sigla` e o número em
    `processo_numero`, e não num campo `processo` concatenado — casar por `processo` pega
    o acórdão simples e perde todo incidente (`Rcl-AgR`, `ARE-AgR`, `RE-ED-AgR`);
  · a caixa da classe importa: a ficha escreve `Rcl-AgR` e passar por `.upper()` derruba
    o casamento inteiro. Foi assim que a primeira medição deu 3,7%;
  · a nota de informativo do STJ tem id `JURIS:STJ:INFJ:0594:94690716`, onde o segundo
    segmento é um hash por nota. A data não é da nota, é do BOLETIM — então a chave é o
    número do informativo, e os 6.341 casos fecham de uma vez.

O que NÃO se recupera fica declarado: os 3.246 temas de repercussão geral não têm data
porque `repercussao_geral.jsonl` não tem campo de data NENHUM. Não é falha de casamento,
é ausência na coleta, e a correção é recoletar.

    python pipeline/datas_precedente.py          # relata a cobertura
"""
from __future__ import annotations

import json, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
_CAMPOS = ("julgamento_data", "data_julgamento", "julgado_em", "data",
           "publicacao_data", "data_publicacao")


def _norm(s) -> str | None:
    """Data em ISO, a partir das duas formas que a coleta usa."""
    s = str(s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else None


def _data(d: dict) -> str | None:
    for k in _CAMPOS:
        v = _norm(d.get(k))
        if v:
            return v
    return None


def _linhas(rel: str):
    p = RAIZ / rel
    if not p.exists():
        return
    for l in p.open(encoding="utf-8", errors="replace"):
        if l.strip():
            try:
                yield json.loads(l)
            except json.JSONDecodeError:
                continue


def indice() -> tuple[dict, dict]:
    """(por juris_id, por número de informativo do STJ)."""
    idx: dict[str, str] = {}

    for rel in ("decisoes/stf/stf_acordaos_historico.jsonl", "decisoes/stf/stf_acordaos.jsonl",
                "decisoes/stf/stf_faltantes.jsonl",
                "decisoes/stf/stf_inteiro_teor_concentrado.jsonl",
                "decisoes/stf/controle_concentrado.jsonl"):
        for d in _linhas(rel):
            dt = _data(d)
            if not dt:
                continue
            # duas rotas, porque os arquivos do STF não têm o mesmo esquema
            sig = str(d.get("processo_classe_processual_unificada_sigla")
                      or d.get("classe") or "").strip()
            num = re.sub(r"[^0-9]", "", str(d.get("processo_numero") or d.get("numero") or ""))
            if sig and num:
                idx.setdefault(f"JURIS:STF:{sig}:{num}", dt)
            m = re.match(r"([A-Za-zÀ-ÿ\-]+)\s*([\d.]+)",
                         str(d.get("processo") or d.get("titulo") or "").strip())
            if m:
                idx.setdefault(f"JURIS:STF:{m.group(1)}:{re.sub(r'[^0-9]','',m.group(2))}", dt)

    for rel, vinc in (("decisoes/stf/sumulas_nao_vinculantes.jsonl", False),
                      ("decisoes/stf/sumulas_vinculantes.jsonl", True)):
        for d in _linhas(rel):
            dt = _data(d)
            n = re.sub(r"[^0-9]", "", str(d.get("sumula_numero") or ""))
            if dt and n:
                meio = "SUM:VINC" if vinc else "SUM"
                idx.setdefault(f"JURIS:STF:{meio}:{int(n):04d}", dt)
                idx.setdefault(f"JURIS:STF:{meio}:{n}", dt)

    for rel, pre in (("decisoes/stj/temas_stj_oficial.jsonl", "JURIS:STJ:REP:TEMA"),
                     ("decisoes/stj/iac_stj_oficial.jsonl", "JURIS:STJ:IAC:")):
        for d in _linhas(rel):
            dt = _data(d)
            if dt and d.get("numero") is not None:
                idx.setdefault(f"{pre}{int(d['numero']):04d}", dt)
                idx.setdefault(f"{pre}{d['numero']}", dt)

    # Q6 · a data do tema de repercussão geral, colhida do ACÓRDÃO que fixou a tese.
    # `repercussao_geral.jsonl` não tem campo de data nenhum — os campos são descricao,
    # ha_repercussao_geral, numero_tema, relator, tema, tese, titulo e url_detalhe — então
    # a data nunca esteve na coleta original. Ela está no acórdão, que carrega
    # `documental_tese_tema_texto` com o número do tema; `augmentation/crawlers/rg_datas.py`
    # faz essa consulta e grava aqui. 1.416 dos 1.434 temas fecharam.
    for d in _linhas("decisoes/stf/rg_datas.jsonl"):
        dt = _norm(d.get("julgamento_data"))
        if dt and d.get("tema") is not None:
            idx.setdefault(f"JURIS:STF:RG:TEMA{int(d['tema']):04d}", dt)
            idx.setdefault(f"JURIS:STF:RG:TEMA{d['tema']}", dt)

    # A data da nota é a do boletim que a publicou.
    inf: dict[str, str] = {}
    for d in _linhas("decisoes/stj/stj_informativos_acordaos.jsonl"):
        dt = _norm(d.get("data"))
        n = re.sub(r"[^0-9]", "", str(d.get("informativo") or ""))
        if dt and n:
            inf.setdefault(f"{int(n):04d}", dt)
    return idx, inf


def data_de(juris_id: str, idx: dict, inf: dict) -> str | None:
    base = str(juris_id).split(":QA:")[0]
    if base in idx:
        return idx[base]
    if base.startswith("JURIS:STJ:INFJ:"):
        p = base.split(":")
        if len(p) > 3:
            return inf.get(p[3])
    return None


if __name__ == "__main__":
    import collections
    idx, inf = indice()
    print(f"índice: {len(idx):,} identificadores · {len(inf):,} boletins de informativo")
    RX_ID = re.compile(r"<<ID=([^|]+)\|")
    RX_FALTA = re.compile(r"Data[^:|\n]{0,18}:\s*\(?\s*(informa[çc][ãa]o insuficiente"
                          r"|n[ãa]o (?:informad|consta|especificad)|indispon)", re.I)
    alvo = RAIZ / "data/ablacao_regime/expandido_completo.jsonl"
    falta = rec = 0
    pf, pr = collections.Counter(), collections.Counter()
    for l in alvo.open(encoding="utf-8"):
        t = json.loads(l)["text"]
        if "|TYPE=PREC|" not in t[:200] or not RX_FALTA.search(t[:900]):
            continue
        falta += 1
        m = RX_ID.match(t)
        if not m:
            continue
        base = m.group(1).split(":QA:")[0]
        p3 = ":".join(base.split(":")[:3])
        pf[p3] += 1
        if data_de(base, idx, inf):
            rec += 1
            pr[p3] += 1
    print(f"\nfichas com data faltante: {falta:,} · recuperadas: {rec:,} ({rec/max(falta,1):.1%})")
    print(f"{'prefixo':26s} {'faltam':>8s} {'recup.':>8s} {'%':>6s}")
    for k, v in pf.most_common(12):
        print(f"{k:26s} {v:8,d} {pr[k]:8,d} {pr[k]/v:6.0%}")
