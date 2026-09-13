#!/usr/bin/env python3
"""confere_vazamento.py — os exames da avaliação entraram no corpus de treino?

A ficha do conjunto afirma que os exames 39, 40 e 41 foram excluídos de todo o material de
treino. Afirmação desse tipo é a primeira coisa que um revisor testa, e é a última que um
autor confere — a exclusão é feita uma vez, na montagem, e depois se torna folclore do
projeto. Aqui ela é reexecutável em um comando.

A verificação é pelo campo `_meta.id`, que carrega o número do exame como prefixo, e não por
busca no texto: um enunciado pode mencionar "o 41º Exame" sem vir dele.

    juridico-env/bin/python dataset/confere_vazamento.py
Sai com código 1 se achar vazamento.
"""
from __future__ import annotations

import collections, json, re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BLOCOS = ("I", "II", "III", "IV", "VII", "X")
AVALIACAO = {"39", "40", "41"}          # exames de onde vêm as 105 questões do benchmark

ruim = 0
print(f"{'bloco':7s} {'linhas':>7s} {'exames':>7s}  faixa")
for b in BLOCOS:
    c: collections.Counter = collections.Counter()
    n = 0
    for split in ("train", "valid"):
        p = RAIZ / f"data/finetune/blocos/{b}/{split}.jsonl"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for linha in f:
                n += 1
                ident = (json.loads(linha).get("_meta") or {}).get("id") or ""
                m = re.match(r"(\d{2})-", ident)
                c[m.group(1) if m else None] += 1
    exames = sorted(k for k in c if k)
    vaz = sorted(set(exames) & AVALIACAO)
    ruim += len(vaz)
    faixa = f"{exames[0]}–{exames[-1]}" if exames else "sem identificador de exame"
    print(f"{b:7s} {n:7,} {len(exames):7d}  {faixa}"
          + (f"   VAZAMENTO: {vaz}" if vaz else ""))

print("\n" + ("VAZAMENTO ENCONTRADO" if ruim else
              "nenhum dos exames 39, 40 e 41 aparece no corpus de treino"))
sys.exit(1 if ruim else 0)
