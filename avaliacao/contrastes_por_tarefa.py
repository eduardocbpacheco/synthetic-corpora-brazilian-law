#!/usr/bin/env python3
"""
contrastes_por_tarefa.py — os contrastes pareados, separados por tarefa.

Regra fechada com o usuario em 13/09: **nunca agregar peca e discursiva na mesma nota**.
Os dois generos respondem de forma oposta ao pre-treino, entao somar os dois produz a
diferenca entre um efeito positivo e um negativo, e nao o efeito de coisa nenhuma.

Refaz os 36 contrastes do desenho em cada tarefa separadamente, com Wilcoxon pareado por
questao e as tres sementes empilhadas.

Uso:  juridico-env/bin/python avaliacao/contrastes_por_tarefa.py
Saida: /tmp/contrastes_tarefa.json
"""
from __future__ import annotations
import json, os, collections, statistics as st
from scipy import stats

RES = "avaliacao/resultados"
MOD = ["1.5B", "3.7B", "8B", "14B"]
PARES = [("I", "II"), ("II", "III"), ("IV", "X"), ("I", "IV")]
# A peca sai nas tres: os criterios FORMAIS (enderecamento, qualificacao, pedido, fecho)
# valem 14,9% dos pontos da banca e os de MERITO 85,1%, entao o agregado e quase a nota de
# merito e apaga o que acontece na parte formal. Regra do usuario em 13/09: em toda analise
# de peca, os tres recortes discriminados.
TAREFAS = [("discursiva", "discursiva"), ("peca_formal", "peça formal"),
           ("peca_material", "peça material"), ("peca", "peça agregada")]


def por_questao(caminho: str, tarefa: str):
    """{questao: fracao de pontos}, dentro da fatia pedida."""
    acc = collections.defaultdict(lambda: [0.0, 0.0])
    with open(caminho, encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            if tarefa == "discursiva" and r["tipo"] != "discursiva":
                continue
            if tarefa.startswith("peca") and r["tipo"] != "peca":
                continue
            if tarefa == "peca_formal" and r.get("classe") != "formal":
                continue
            if tarefa == "peca_material" and r.get("classe") != "merito":
                continue
            p = float(r.get("pontuacao_max", 1))
            k = (r["run"], r["questao_id"])
            acc[k][1] += p
            if r.get("atendeu"):
                acc[k][0] += p
    q = collections.defaultdict(list)
    for (run, qid), (a, b) in acc.items():
        if b > 0:
            q[qid].append(a / b)
    return {k: st.mean(v) for k, v in q.items()}


def bloco(mod, bl, reg, tarefa):
    """empilha as tres sementes, uma entrada por (semente, questao)."""
    fora = {}
    for s in (42, 43, 44):
        c = f"{RES}/sft_{bl.lower()}_{reg}_s{s}_{mod.lower()}_partes.jsonl"
        if os.path.exists(c):
            for q, v in por_questao(c, tarefa).items():
                fora[(s, q)] = v
    return fora


def main():
    saida = {}
    for tarefa, rot in TAREFAS:
        print(f"\n=== {rot.upper()}")
        print(f"{'contraste':10s} {'modelo':7s} {'regime':10s} {'Δ pp':>7s} {'p':>9s} {'n':>5s}")
        for a, b in PARES:
            for mod in MOD:
                for reg in ("nenhum", "bruto", "expandido"):
                    x, y = bloco(mod, a, reg, tarefa), bloco(mod, b, reg, tarefa)
                    k = sorted(set(x) & set(y))
                    if len(k) < 20:
                        continue
                    dif = [y[i] - x[i] for i in k]
                    if all(abs(d) < 1e-9 for d in dif):
                        continue
                    p = float(stats.wilcoxon([x[i] for i in k], [y[i] for i in k]).pvalue)
                    d = 100 * st.mean(dif)
                    saida[f"{tarefa}|{mod}|{reg}|{a}x{b}"] = {
                        "delta_pp": round(d, 2), "p": round(p, 5), "n": len(k)}
                    s = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
                    print(f"{a+'×'+b:10s} {mod:7s} {reg:10s} {d:+7.2f} {p:9.5f} {len(k):5d} {s}")
    json.dump(saida, open("/tmp/contrastes_tarefa.json", "w"), ensure_ascii=False, indent=1)
    print(f"\n{len(saida)} contrastes · /tmp/contrastes_tarefa.json")


if __name__ == "__main__":
    main()
