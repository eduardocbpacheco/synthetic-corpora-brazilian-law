#!/usr/bin/env python3
"""kappa_por_classe.py — a concordância do juiz na peça, separada em forma e mérito.

O relatório do benchmark reivindica a decomposição da peça em forma e mérito como uma das
contribuições sobre o trabalho original, mas nenhuma tabela dele usa essa decomposição: o
κ de peça sai num número só. Isso é a mesma falha que o outro artigo documentou na nota —
os critérios formais são 148 dos 561 da peça, então um κ agregado é, em boa medida, o κ de
mérito, e o comportamento do juiz nas duas classes não tem razão de ser o mesmo. Julgar
"a peça foi endereçada ao juízo competente" é casar uma string com um gabarito; julgar "há
violação a direito líquido e certo" é avaliar uma tese.

O rótulo de classe não está no dataframe de critérios; ele é derivado do TÍTULO que a banca
dá a cada um. O mapa sai dos arquivos de julgamento da ablação, onde a classe já está
resolvida, e é conferido aqui: nenhum título aparece nas duas classes.

Uso:  juridico-env/bin/python avaliacao/kappa_por_classe.py [--min-cobertura 0.85]
Saída: /tmp/kappa_classe.json e tabela no stdout
"""
from __future__ import annotations

import argparse, collections, glob, json, os, statistics as st, sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "rabula/consolidado/src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))
from alignment import carregar_anotacoes_humanas          # noqa: E402
from judge_llm import voto_majoritario                    # noqa: E402
from analisa_kappa_v4 import (V4, ANNOT, DFS, chave_pratica, carrega_df,  # noqa: E402
                              juizes_disponiveis, reps_disponiveis)

ABLACAO = RAIZ / "avaliacao/resultados/instruct_v5_partes.jsonl"


def mapa_classe() -> dict[str, str]:
    """titulo → classe, conferido contra ambiguidade."""
    m: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    with ABLACAO.open(encoding="utf-8") as f:
        for l in f:
            r = json.loads(l)
            if r["tipo"] == "peca":
                m[(r.get("titulo") or "").strip()][r.get("classe")] += 1
    ambiguos = [t for t, c in m.items() if len(c) > 1]
    if ambiguos:
        raise SystemExit(f"título em duas classes: {ambiguos}")
    return {t: c.most_common(1)[0][0] for t, c in m.items()}


def classe_por_chave(df: pd.DataFrame, mapa: dict[str, str]) -> dict[str, str]:
    fora, sem = {}, collections.Counter()
    for _, row in df.iterrows():
        for c in (row["formated_criteria"] or []):
            k = chave_pratica(row["exam"], row["area"], c.get("numero"), c.get("parte"))
            t = (c.get("titulo") or "").strip()
            if t in mapa:
                fora[k] = mapa[t]
            else:
                sem[t] += 1
    if sem:
        print(f"  aviso: {sum(sem.values())} critério(s) com título fora do mapa: "
              f"{list(sem)[:3]}")
    return fora


def vereditos_peca(rep: int, juiz: str, df: pd.DataFrame) -> pd.DataFrame:
    d = V4 / f"rep{rep}" / f"alignment-{juiz}" / "document_writing"
    linhas = []
    for _, row in df.iterrows():
        arqs = sorted(d.glob(f"q{int(row['id'])}_run*.json"))
        runs = []
        for a in arqs:
            try:
                runs.append(json.loads(a.read_text("utf-8")).get("resultado") or [])
            except Exception:
                pass
        if not runs:
            continue
        for item in voto_majoritario(runs):
            linhas.append({
                "chave": chave_pratica(row["exam"], row["area"], item.get("numero"),
                                       item.get("parte")),
                "acerto": int(item.get("acerto") or 0)})
    return pd.DataFrame(linhas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-cobertura", type=float, default=0.85)
    a = ap.parse_args()

    mapa = mapa_classe()
    df = carrega_df("document_writing")
    classe = classe_por_chave(df, mapa)
    humanos = carregar_anotacoes_humanas(ANNOT, tipo="praticas")
    humanos = humanos.assign(classe=humanos["chave"].map(classe))
    n_tot = len(humanos)
    print(f"padrão-ouro de peça: {n_tot} critérios · "
          f"{(humanos.classe=='formal').sum()} formais · "
          f"{(humanos.classe=='merito').sum()} de mérito\n")

    reps, juizes = reps_disponiveis(), juizes_disponiveis()
    reg = []
    for juiz in juizes:
        for rep in reps:
            v = vereditos_peca(rep, juiz, df)
            if v.empty:
                continue
            m = v.merge(humanos, on="chave", how="inner")
            if len(m) / n_tot < a.min_cobertura:
                continue
            linha = {"juiz": juiz, "rep": rep, "cobertura": len(m) / n_tot}
            for rot, sel in [("agregado", m),
                             ("formal", m[m.classe == "formal"]),
                             ("merito", m[m.classe == "merito"])]:
                linha[rot] = (cohen_kappa_score(sel["golden"], sel["acerto"])
                              if len(sel) and sel["golden"].nunique() > 1
                              and sel["acerto"].nunique() > 1 else np.nan)
            reg.append(linha)

    d = pd.DataFrame(reg)
    if d.empty:
        raise SystemExit("nenhum juiz com cobertura suficiente")

    ag = d.groupby("juiz").agg(
        formal=("formal", "mean"), sf=("formal", "std"),
        merito=("merito", "mean"), sm=("merito", "std"),
        agregado=("agregado", "mean"), sa=("agregado", "std"),
        reps=("rep", "count")).sort_values("agregado", ascending=False)

    print(f"{'juiz':22s} {'κ formal':>16s} {'κ mérito':>16s} {'κ agregado':>16s} {'reps':>5s}")
    print("-" * 80)
    f = lambda v, s: f"{v:9.3f} ±{s:5.3f}" if not np.isnan(s) else f"{v:9.3f}      —"
    for j, r in ag.iterrows():
        print(f"{j:22s} {f(r.formal,r.sf)} {f(r.merito,r.sm)} {f(r.agregado,r.sa)} {int(r.reps):5d}")

    # As ordens sao as mesmas nas duas classes?
    of = ag.sort_values("formal", ascending=False).index.tolist()
    om = ag.sort_values("merito", ascending=False).index.tolist()
    oa = ag.index.tolist()
    rho = st.correlation if False else None
    from scipy.stats import spearmanr
    pos = lambda ordem: [ordem.index(j) for j in ag.index]
    print("\nconcordância entre as ordens (Spearman sobre a posição de cada juiz):")
    print(f"  formal × mérito    ρ = {spearmanr(pos(of), pos(om)).statistic:+.3f}")
    print(f"  formal × agregado  ρ = {spearmanr(pos(of), pos(oa)).statistic:+.3f}")
    print(f"  mérito × agregado  ρ = {spearmanr(pos(om), pos(oa)).statistic:+.3f}")
    print(f"\ntopo por classe:\n  formal:   {', '.join(of[:3])}"
          f"\n  mérito:   {', '.join(om[:3])}\n  agregado: {', '.join(oa[:3])}")

    ruido = {}
    for rot, col in [("formal", "sf"), ("merito", "sm"), ("agregado", "sa")]:
        s = ag[col].dropna()
        ruido[rot] = {"desvio_mediano": float(s.median()),
                      "limiar": float(2 * 1.96 * s.median())}
        print(f"\npiso de ruído · {rot}: desvio {s.median():.4f} → limiar {2*1.96*s.median():.3f}")

    json.dump({"juizes": ag.reset_index().to_dict("records"), "ruido": ruido},
              open("/tmp/kappa_classe.json", "w"), ensure_ascii=False, indent=1, default=float)
    print("\n→ /tmp/kappa_classe.json")


if __name__ == "__main__":
    main()
