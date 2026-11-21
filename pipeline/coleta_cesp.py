#!/usr/bin/env python3
"""coleta_cesp.py — a Constituição do Estado de São Paulo.

A6 · Ela faltava nos DOIS braços. É a norma fundamental do estado cujo tribunal fornece a
maior parte da jurisprudência de primeiro e segundo grau do corpus: são 21.381 documentos
do TJSP no braço bruto, julgados sob uma constituição que o modelo nunca viu.

A fonte é o repositório da ALESP, o mesmo de onde vêm as 27 leis paulistas já coletadas.
O texto vem em HTML com entidade nomeada e âncora repetida — o marcador "Artigo 1°"
aparece uma vez como índice e outra no corpo, o que já era conhecido e é a razão de
`dividir_em_artigos` guardar a ocorrência mais longa por identificador.

Saída: leis/cesp.jsonl, no mesmo formato de leis_sp.jsonl.

    python pipeline/coleta_cesp.py
"""
from __future__ import annotations

import html as H
import json
import re
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "augmentation"))
sys.path.insert(0, str(RAIZ / "pipeline"))

URL = ("https://www.al.sp.gov.br/repositorio/legislacao/constituicao/1989/"
       "compilacao-constituicao-0-05.10.1989.html")
SAIDA = RAIZ / "leis/cesp.jsonl"
CABECA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")}


def texto_limpo(bruto: bytes) -> str:
    h = bruto.decode("utf-8", errors="replace")
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", h)
    # Quebra de linha ANTES do bloco, e não só depois. Os artigos que abrem uma seção
    # vêm como `</h4><p><strong>Artigo 73`, e converter apenas as tags de fechamento
    # deixava 47 deles colados ao cabeçalho anterior — o divisor de artigos exige
    # início de linha, e com razão: o texto do artigo 83 cita "no artigo 5°, XXXVIII
    # da Constituição Federal", e uma expressão frouxa criaria um artigo 5 fantasma
    # a partir de uma referência.
    h = re.sub(r"(?i)<br\s*/?>|</?(?:p|div|tr|li|h[1-6]|table)\b[^>]*>", "\\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    h = H.unescape(h)
    # A ALESP usa espaço rígido em abundância; ele quebra a detecção de artigo.
    h = h.replace("\xa0", " ")
    h = re.sub(r"[ \t]+", " ", h)
    return re.sub(r"\n{3,}", "\n\n", h).strip()


def main() -> None:
    from expand_normas import dividir_em_artigos
    from identificadores import chave_diploma

    req = urllib.request.Request(URL, headers=CABECA)
    with urllib.request.urlopen(req, timeout=90) as r:
        bruto = r.read()
    texto = texto_limpo(bruto)
    print(f"baixado: {len(bruto):,} bytes · {len(texto):,} caracteres de texto")

    # O ADCT RECOMEÇA a numeração do artigo 1. Num documento só, o artigo 11 transitório
    # colide com o 11 permanente e a deduplicação por identificador descarta um dos dois em
    # silêncio — foram 10 colisões na primeira tentativa. São dois diplomas, com chaves
    # distintas, exatamente como a CF/88 e o seu ADCT.
    corte = texto.upper().find("ATO DAS DISPOSI")
    if corte < 0:
        corte = len(texto)
    partes = [("constituicao", "Constituição do Estado de São Paulo",
               "Constituição Estadual de São Paulo", texto[:corte]),
              ("adct", "ADCT da Constituição do Estado de São Paulo",
               "ADCT da Constituição Estadual de São Paulo", texto[corte:])]

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        for tipo, nome, apelido, corpo in partes:
            if len(corpo) < 500:
                continue
            chave = chave_diploma("SP", tipo, "0", "1989")
            arts = dividir_em_artigos(corpo, apelido, did=chave)
            if not arts:
                continue
            nums = sorted(a["num_art"] for a in arts)
            print(f"{apelido}: {len(arts)} artigos · faixa {nums[0]}–{nums[-1]} · "
                  f"chave {chave}")
            f.write(json.dumps({
                "lei": nome, "apelido": apelido,
                "tipo": tipo, "numero": "0", "ano": "1989",
                "chave": chave, "fonte": URL, "url": URL,
                "texto": corpo, "n_artigos": len(arts),
            }, ensure_ascii=False) + "\n")
    print(f"→ {SAIDA.relative_to(RAIZ)}  ({SAIDA.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
