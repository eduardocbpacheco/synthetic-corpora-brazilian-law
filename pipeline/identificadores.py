#!/usr/bin/env python3
"""identificadores.py — a mesma chave de diploma nos dois braços.

C16 · O braço bruto identificava a lei paulista pela forma humana, "LC SP 180/1978", e o
expandido pela forma de código, "SP180-1978". As duas saem do MESMO `leis_sp.jsonl`, que
traz tipo, número e ano em campos separados, e ainda assim não pareavam: a regra de
desenho D4 diz que o expandido é a ficha do que está no bruto, e sem chave comum não há
como sequer conferir isso.

A forma de código também descartava o TIPO. Hoje não colide por sorte — são 10 leis e 17
leis complementares, e nenhum par divide número e ano. Mas é a mesma armadilha que já
custou três identificadores neste projeto: o Código Penal Militar herdando `CP` do Penal
comum, o Código Comercial herdando `CC` do Civil, e quatro decretos-lei virando `DL`.
Aqui o tipo entra antes de morder.

A fonte da lei federal traz o número embutido no nome ("Lei nº 8.078, de 1990"), então a
função aceita as duas formas de entrada.
"""
from __future__ import annotations

import re

# `lei.complementar` → LC, `lei` → L, `decreto.lei` → DL. Duas letras bastam e o ponto do
# nome do campo não entra.
_SIGLA_TIPO = {"lei": "L", "lei.complementar": "LC", "leicomplementar": "LC",
               "decreto": "D", "decreto.lei": "DL", "decretolei": "DL",
               "emenda.constitucional": "EC", "medida.provisoria": "MP",
               # Sem esta entrada a Constituição Estadual caía no padrão e virava
               # `SP-L-0-1989`, um identificador que diz que ela é uma lei número zero.
               "constituicao": "CE", "constituicao.estadual": "CE", "adct": "ADCT"}


def sigla_tipo(tipo: str) -> str:
    t = re.sub(r"[\s_-]+", ".", str(tipo or "").strip().lower())
    return _SIGLA_TIPO.get(t) or _SIGLA_TIPO.get(t.replace(".", "")) or "L"


def chave_diploma(uf: str, tipo: str, numero: str, ano: str) -> str:
    """A chave canônica: `SP-LC-180-1978`.

    Serve aos dois braços e à conferência de pareamento. Legível o bastante para aparecer
    num cabeçalho e estável o bastante para casar entre arquivos.
    """
    num = re.sub(r"[^\d]", "", str(numero or ""))
    ano = re.sub(r"[^\d]", "", str(ano or ""))[:4]
    return f"{str(uf or 'BR').upper()}-{sigla_tipo(tipo)}-{num}-{ano}"


def chave_de_registro(d: dict, uf_padrao: str = "BR") -> str:
    """A chave a partir de um registro de `leis_sp.jsonl` ou `leis_federais.jsonl`."""
    tipo = d.get("tipo")
    num, ano = d.get("numero"), d.get("ano")
    if not (num and ano):
        # A fonte federal não separa: o número mora no nome ("Lei nº 8.078, de 1990").
        # O ano exigia começar em 19 ou 20, e com isso o século XIX ficava de fora: o
        # Código Comercial é a Lei 556 de 1850, e a chave saía `BR-L--`, sem número e sem
        # ano. É o mesmo diploma que já havia perdido a identidade uma vez, no N1, por
        # herdar `CC` do Código Civil. Um identificador vazio não colide hoje por sorte —
        # há um só diploma anterior a 1900 no corpus —, mas dois teriam a MESMA chave.
        m = re.search(r"(\d[\d.]*)\D+(1[5-9]\d{2}|20\d{2})", str(d.get("lei") or ""))
        if m:
            num, ano = m.group(1), m.group(2)
        if not tipo:
            nome = str(d.get("lei") or "").lower()
            # A inferência só conhecia as formas POR EXTENSO. A fonte federal escreve a
            # SIGLA — "LC 101/2000", "DL 911/1969" —, e "lc 101/2000" não contém
            # "complementar" nem "decreto-lei", então caía no ramo final e virava `lei`:
            # 17 diplomas ficaram com `BR-L-…` no lugar de `BR-LC-…` e `BR-DL-…`. Hoje
            # não colidem por sorte, e é exatamente a armadilha que o cabeçalho deste
            # módulo descreve: o tipo existe na chave para entrar ANTES de morder. Uma
            # `BR-L-101-2000` para a LC 101 colide com a Lei 101 do mesmo ano no dia em
            # que ela entrar. A URL da fonte também declara (`/leis/lcp/lcp101.htm`) e
            # entra como segunda testemunha.
            url = str(d.get("url") or "").lower()
            # A URL vem ANTES do rótulo, e a ordem custou duas idas: o rótulo erra nos dois
            # sentidos. "Bens Imóveis da União" está escrito "Decreto 9.760/1946" e é o
            # DECRETO-LEI 9.760; "Prescrição Fazenda" está escrito "DL 20.910/1932" e é o
            # DECRETO 20.910. Em ambos quem acerta é o caminho do arquivo no Planalto, que
            # é onde a norma de fato está publicada.
            if "/lcp/" in url:
                tipo = "lei.complementar"
            elif "/decreto-lei/" in url:
                tipo = "decreto.lei"
            elif "/decreto/" in url:
                tipo = "decreto"
            else:
                tipo = ("lei.complementar" if re.match(r"\s*lc[\s.º-]", nome)
                        or "complementar" in nome else
                        "decreto.lei" if re.match(r"\s*dl[\s.º-]", nome)
                        or "decreto-lei" in nome else
                        "decreto" if nome.startswith("decreto") else "lei")
    uf = "SP" if " SP " in f" {d.get('lei', '')} " else uf_padrao
    return chave_diploma(uf, tipo, num, ano)


if __name__ == "__main__":
    import json, sys
    from pathlib import Path
    RAIZ = Path(__file__).resolve().parent.parent
    for arq, uf in (("leis/leis_sp.jsonl", "SP"), ("leis/leis_federais.jsonl", "BR")):
        p = RAIZ / arq
        if not p.exists():
            continue
        L = [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]
        ch = [chave_de_registro(d, uf) for d in L]
        import collections
        col = {k: v for k, v in collections.Counter(ch).items() if v > 1}
        print(f"{arq}: {len(L)} diplomas · {len(set(ch))} chaves · colisões: {col or 'nenhuma'}")
        for d, k in list(zip(L, ch))[:3]:
            print(f"   {str(d.get('lei'))[:28]:30s} → {k}")
