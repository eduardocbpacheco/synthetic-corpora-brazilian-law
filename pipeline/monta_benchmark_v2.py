#!/usr/bin/env python3
"""
monta_benchmark_v2.py — reconstrói o benchmark a partir da extração canônica do Rabula.

Por que não reparsear PDF: o Rabula já tem a extração pronta e validada em
rabula/Reconstrucao/.../data/dfs/base/{df_discursive,df_practical}.pkl, e é sobre
ELA que as anotações humanas e o Kappa foram computados. Nosso parser de PDF era
uma segunda extração, pior e lossy: perdia 24 discursivas do exame 39 (cabeçalho
antigo "QUESTÃO 1"), 4 questões por rótulo "A)" em vez de "A.", truncava texto de
critério na coluna de pontuação e errava pontuação máxima em pelo menos um caso.

Diferença central: GRANULARIDADE. O parser antigo produzia um critério por ITEM
(406 no total, tudo-ou-nada). O Rabula anota por PARTE — cada peso da distribuição
de pontos é uma decisão binária separada (940 no total), e é nessa granularidade que
o κ de 0,821 (discursiva) e 0,784 (peça) foi medido.

  discursivas: 84 questões, 379 partes  (campos letra/parte/criterio/pontos)
  peças:       21 questões, 561 partes  (campos numero/parte/titulo/descricao/pontos)

O campo `titulo` das peças é a taxonomia da própria banca (Endereçamento,
Qualificação das partes, Pedidos, Fundamentação...), o que permite separar critério
formal de critério de mérito sem heurística nossa.

Saída: data/oab/benchmark_v2.jsonl
Uso:   python pipeline/monta_benchmark_v2.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "rabula/Reconstrucao/LLM-as-judge-in-BR-legal-domain/data/dfs/base"
OUT = ROOT / "data/oab/benchmark_v2.jsonl"

AREA = {"administrativo": "admin", "civil": "civil", "constitucional": "const",
        "empresarial": "empre", "penal": "penal", "trabalhista": "traba",
        "tributário": "tribu", "tributario": "tribu"}

# Rótulos que a banca usa para exigência ESTRUTURAL da peça (forma), não de mérito.
# Serve para decompor o ganho: um modelo pode subir só acertando o esqueleto.
FORMAL = {
    "endereçamento", "fechamento", "encerramento", "interposição", "tempestividade",
    "qualificação das partes", "qualificação dos interessados/ requerentes", "partes",
    "peça", "petição de interposição", "prazo e fechamento", "valor da causa / fechamento",
    "menção ao valor da causa", "procedimento", "requisitos de admissibilidade recursal",
    "requisitos tempestividade", "honorários advocatícios",
    "gratuidade de justiça e prioridade", "partes e fundamento legal",
}


def classe(titulo: str) -> str:
    return "formal" if (titulo or "").strip().lower() in FORMAL else "merito"


def main() -> None:
    faltando = [f for f in ("df_discursive.pkl", "df_practical.pkl")
                if not (BASE / f).exists()]
    if faltando:
        raise SystemExit(
            f"fonte canônica ausente: {', '.join(faltando)}\n"
            f"esperada em {BASE}\n"
            "Vem do repositório do Rabula (LLM-as-judge-in-BR-legal-domain, data/dfs/base/).\n"
            "Sem ela NÃO reparse os PDFs: pipeline/parse_oab_pdfs.py perde 24 questões e\n"
            "funde as partes dos itens. Recupere a fonte."
        )
    disc = pd.read_pickle(BASE / "df_discursive.pkl")
    peca = pd.read_pickle(BASE / "df_practical.pkl")
    linhas = []

    for _, r in disc.iterrows():
        area = AREA[r["area"]]
        crits = [{
            "id": f"{c['letra']}-{c['parte']}",
            "letra": c["letra"], "parte": c["parte"],
            "texto": c["criterio"],
            "gabarito_item": c.get("gabarito", ""),
            "pontuacao_max": float(c["pontos"]),
            "classe": "merito",
        } for c in r["formated_criteria"]]
        linhas.append({
            "id": f"{r['exam']}-disc-{area}-{r['number']}",
            "rabula_id": int(r["id"]), "exame": str(r["exam"]), "tipo": "discursiva",
            "area": r["area"], "enunciado": r["question"], "gabarito": r["answer"],
            "criterios": crits, "split": "benchmark",
        })

    for _, r in peca.iterrows():
        area = AREA[r["area"]]
        crits = [{
            "id": f"{c['numero']}-{c['parte']}",
            # 18 critérios são subnumerados (5.1, 5.2, 8.1, 8.2): int() colidiria
            # com o item 5 e o juiz devolveria dois vereditos com a mesma chave
            "numero": c["numero"], "parte": c["parte"],
            "titulo": c.get("titulo", ""),
            "texto": c["descricao"],
            "pontuacao_max": float(c["pontos"]),
            "classe": classe(c.get("titulo", "")),
        } for c in r["formated_criteria"]]
        linhas.append({
            "id": f"{r['exam']}-peca-{area}",
            "rabula_id": int(r["id"]), "exame": str(r["exam"]), "tipo": "peca",
            "area": r["area"], "tipo_peca": r["legal document"],
            "enunciado": r["question"], "gabarito": r["answer"],
            "criterios": crits, "split": "benchmark",
        })

    with open(OUT, "w", encoding="utf-8") as f:
        for x in linhas:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    for t in ("discursiva", "peca"):
        S = [x for x in linhas if x["tipo"] == t]
        n = sum(len(x["criterios"]) for x in S)
        pts = sum(c["pontuacao_max"] for x in S for c in x["criterios"])
        print(f"{t:11s}: {len(S):3d} questões | {n:4d} partes | {pts:7.2f} pontos")
    fm = [(c["classe"], c["pontuacao_max"]) for x in linhas if x["tipo"] == "peca"
          for c in x["criterios"]]
    for k in ("formal", "merito"):
        sub = [p for c, p in fm if c == k]
        print(f"  peça {k:7s}: {len(sub):3d} partes | {sum(sub):6.2f} pontos")
    print(f"✓ {len(linhas)} questões → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
