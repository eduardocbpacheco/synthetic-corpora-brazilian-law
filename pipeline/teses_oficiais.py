#!/usr/bin/env python3
"""teses_oficiais.py — a tese como a corte publicou, e não a paráfrase do gerador.

Q1 · A ficha de precedente não diz o que foi decidido. A objeção do item é doutrinária e
está certa: `ratio decidendi` é o motivo pelo qual a tese prevaleceu, e a tese em si é
outra coisa. O que faltava era medir se a distinção tinha consequência no corpus, e tem.

Medido contra as teses oficiais que a coleta guarda: nas 2.252 fichas cujo tema tem tese
publicada, a **cobertura literal da tese dentro da ficha é 0% na mediana**, e apenas 4,7%
reproduzem 90% ou mais dela. O bloco `[RATIO DECIDENDI]` enuncia *uma* regra em 93,1% dos
casos — abre com "A razão determinante da decisão é que..." e segue com uma proposição
normativa — mas é paráfrase do modelo-professor, não o texto que vincula.

Num corpus jurídico essa diferença não é estilística. A tese de repetitivo e a de
repercussão geral são o texto de eficácia vinculante; ensinar a paráfrase no lugar dela
ensina a citar de memória.

O conserto não é geração: são 3.929 teses e enunciados já colhidos, e 3.038 das 10.901
fichas de precedente casam com um deles. Onde não casa — informativo e acórdão comum, que
não têm tese publicada — o bloco não entra, porque ali a ratio é mesmo o que existe.

    python pipeline/teses_oficiais.py
"""
from __future__ import annotations

import json, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ROTULO = "[TESE FIXADA — TEXTO OFICIAL]"


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


def _n(v) -> str | None:
    d = re.sub(r"[^0-9]", "", str(v or ""))
    return f"{int(d):04d}" if d else None


def indice() -> dict[str, str]:
    """juris_id → texto oficial da tese ou do enunciado."""
    T: dict[str, str] = {}
    for d in _linhas("decisoes/stj/temas_stj_oficial.jsonl"):
        n = _n(d.get("numero"))
        if d.get("tese") and n:
            T[f"JURIS:STJ:REP:TEMA{n}"] = d["tese"]
    for d in _linhas("decisoes/stj/iac_stj_oficial.jsonl"):
        n = _n(d.get("numero"))
        if d.get("tese") and n:
            T[f"JURIS:STJ:IAC:{n}"] = d["tese"]
    for d in _linhas("decisoes/stf/repercussao_geral.jsonl"):
        n = _n(d.get("numero_tema") or d.get("tema"))
        if d.get("tese") and n:
            T[f"JURIS:STF:RG:TEMA{n}"] = d["tese"]
    for rel, meio in (("decisoes/stf/sumulas_nao_vinculantes.jsonl", "SUM"),
                      ("decisoes/stf/sumulas_vinculantes.jsonl", "SUM:VINC")):
        for d in _linhas(rel):
            n = _n(d.get("sumula_numero"))
            if d.get("sumula_texto") and n:
                T[f"JURIS:STF:{meio}:{n}"] = d["sumula_texto"]
    for d in _linhas("decisoes/stj/sumulas_stj.jsonl"):
        n = _n(d.get("numero"))
        if d.get("texto") and n:
            T[f"JURIS:STJ:SUM:{n}"] = d["texto"]
    return T


def _ja_tem(tese: str, texto: str) -> bool:
    """A tese já está no corpo? Mede por janelas de 8 palavras, não por igualdade.

    Igualdade exata nunca casa: a ficha reformata espaço e pontuação. Janela deslizante
    responde a pergunta certa — quanto do texto oficial aparece ali dentro.
    """
    pal = re.sub(r"\s+", " ", tese).split()
    low = re.sub(r"\s+", " ", texto).lower()
    if len(pal) < 8:
        return tese[:40].lower() in low
    jan = [" ".join(pal[i:i + 8]) for i in range(0, len(pal) - 7, 4)]
    return sum(1 for j in jan if j.lower() in low) / len(jan) >= 0.9


def insere(texto: str, tese: str | None) -> str:
    """Põe o texto oficial logo após o cabeçalho, se ele ainda não estiver ali."""
    if not tese or ROTULO in texto or _ja_tem(tese, texto):
        return texto
    fim = texto.find("\n")
    if fim < 0:
        return texto
    corpo = re.sub(r"\s+", " ", tese).strip()
    return f"{texto[:fim]}\n{ROTULO}\n{corpo}\n{texto[fim + 1:]}"


if __name__ == "__main__":
    import collections
    T = indice()
    print(f"teses e enunciados oficiais: {len(T):,}")
    print(" por prefixo:", dict(collections.Counter(":".join(k.split(':')[:3])
                                                    for k in T).most_common()))
    RX_DOC = re.compile(r"\|DOC=([^|]+)\|")
    alvo = RAIZ / "data/ablacao_regime/expandido_completo.jsonl"
    docs, casa, ja = set(), set(), 0
    for l in alvo.open(encoding="utf-8"):
        t = json.loads(l)["text"]
        if "|TYPE=PREC|" not in t[:200]:
            continue
        m = RX_DOC.search(t[:220])
        if not m:
            continue
        docs.add(m.group(1))
        if m.group(1) in T:
            casa.add(m.group(1))
            if _ja_tem(T[m.group(1)], t):
                ja += 1
    print(f"\nfichas de precedente: {len(docs):,}")
    print(f"  com tese oficial disponível: {len(casa):,} ({len(casa)/len(docs):.1%})")
    print(f"  que já trazem a tese no corpo: {ja:,}")
