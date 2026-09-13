#!/usr/bin/env python3
"""
complementaridade.py — os dois regimes de pre-treino melhoram AS MESMAS COISAS?

O fatorial mostrou que ficha estruturada e texto cru batem o controle sem pre-treino. A
pergunta seguinte e outra: eles ganham nos mesmos criterios, ou cada um ganha no seu? Se
for no seu, a uniao dos dois vale mais que qualquer um isolado, e isso muda a receita.

A unidade de analise e o CRITERIO (questao x item do espelho), nao a nota agregada. Para
cada criterio mede-se a taxa de atendimento sob cada regime, agregando blocos, sementes e
execucoes, e compara-se contra o controle.

So o Tucano 3,7B entra, porque e o unico com o regime `nenhum`.

Uso:  juridico-env/bin/python avaliacao/complementaridade.py
Saida: /tmp/complementaridade.json e relatorio no stdout
"""
from __future__ import annotations
import json, glob, os, re, collections, statistics as st
from scipy import stats

RES = "avaliacao/resultados"
BLOCOS = ["I", "II", "III", "IV", "VII", "X"]


def carrega():
    """{(regime, questao, criterio): [atendeu...]} para o 3,7B."""
    acc = collections.defaultdict(list)
    meta = {}
    for f in glob.glob(f"{RES}/sft_*_3.7b_partes.jsonl"):
        m = re.match(r"sft_([ivx]+)_(\w+?)_s(\d+)_", os.path.basename(f), re.I)
        if not m:
            continue
        reg = m.group(2).lower()
        with open(f, encoding="utf-8") as fh:
            for l in fh:
                d = json.loads(l)
                if not d.get("julgado"):
                    continue
                k = (d["questao_id"], d["criterio_id"])
                acc[(reg,) + k].append(int(d.get("atendeu", 0)))
                if k not in meta:
                    meta[k] = (d.get("area", "?"), d.get("tipo", "?"), d.get("classe", "?"))
    return acc, meta


def taxa(acc, reg):
    out = {}
    for (r, q, c), v in acc.items():
        if r == reg and v:
            out[(q, c)] = sum(v) / len(v)
    return out


def main():
    acc, meta = carrega()
    N, B, E = (taxa(acc, r) for r in ("nenhum", "bruto", "expandido"))
    comuns = sorted(set(N) & set(B) & set(E))
    print(f"critérios com as três medições: {len(comuns):,}\n")

    dB = {k: B[k] - N[k] for k in comuns}
    dE = {k: E[k] - N[k] for k in comuns}

    # ---- 1. correlacao entre os ganhos
    xb = [dB[k] for k in comuns]; xe = [dE[k] for k in comuns]
    r_p = stats.pearsonr(xb, xe); r_s = stats.spearmanr(xb, xe)
    print("=== 1. OS GANHOS ANDAM JUNTOS?")
    print(f"   Pearson  r = {r_p.statistic:+.3f}  (p = {r_p.pvalue:.2g})")
    print(f"   Spearman ρ = {r_s.statistic:+.3f}  (p = {r_s.pvalue:.2g})")
    print("   r perto de 1 = melhoram as mesmas coisas · perto de 0 = melhoram coisas diferentes")

    # ---- 2. quem ganha onde
    LIM = 0.05   # ganho minimo para contar como melhora naquele criterio
    q = collections.Counter()
    for k in comuns:
        b, e = dB[k] > LIM, dE[k] > LIM
        q[("ambos" if b and e else "só bruto" if b else "só expandido" if e else "nenhum dos dois")] += 1
    print(f"\n=== 2. ONDE CADA UM MELHORA (ganho > {LIM:.0%} no critério)")
    tot = sum(q.values())
    for k in ("ambos", "só bruto", "só expandido", "nenhum dos dois"):
        print(f"   {k:18s} {q[k]:6,}  {100*q[k]/tot:5.1f}%")
    melhorados = tot - q["nenhum dos dois"]
    print(f"\n   critérios melhorados por ao menos um: {melhorados:,} ({100*melhorados/tot:.1f}%)")
    print(f"   melhorados pelos dois:                {q['ambos']:,} ({100*q['ambos']/tot:.1f}%)")
    print(f"   EXCLUSIVOS de um dos regimes:         {q['só bruto']+q['só expandido']:,} "
          f"({100*(q['só bruto']+q['só expandido'])/tot:.1f}%)")

    # ---- 3. por natureza do criterio e por area
    for eixo, idx in (("classe do critério", 2), ("gênero", 1), ("área do direito", 0)):
        print(f"\n=== 3. GANHO MÉDIO POR {eixo.upper()}")
        g = collections.defaultdict(lambda: [[], []])
        for k in comuns:
            v = meta.get(k, ("?", "?", "?"))[idx]
            g[v][0].append(dB[k]); g[v][1].append(dE[k])
        print(f"   {'valor':18s} {'n':>6s} {'Δ bruto':>9s} {'Δ expandido':>12s} {'diferença':>10s}")
        for v in sorted(g, key=lambda x: -len(g[x][0])):
            b, e = g[v]
            if len(b) < 20:
                continue
            print(f"   {str(v)[:18]:18s} {len(b):6,} {100*st.mean(b):+8.2f}pp "
                  f"{100*st.mean(e):+11.2f}pp {100*(st.mean(e)-st.mean(b)):+9.2f}pp")

    json.dump({"n": len(comuns), "pearson": r_p.statistic, "spearman": r_s.statistic,
               "quadrantes": dict(q)}, open("/tmp/complementaridade.json", "w"))


if __name__ == "__main__":
    main()
