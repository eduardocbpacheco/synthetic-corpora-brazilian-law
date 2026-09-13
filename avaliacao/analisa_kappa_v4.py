#!/usr/bin/env python3
"""
analisa_kappa_v4.py — pacote estatístico do eixo 1 (juízes contra golden humano).

Duas incertezas diferentes, que a literatura de LLM-as-judge costuma confundir ou omitir:

  BOOTSTRAP sobre as questões  → "o κ mudaria com outra amostra de questões?"
  DISPERSÃO entre repetições   → "o κ mudaria se eu rodasse o mesmo protocolo de novo?"

A segunda só existe porque o v4 repete o protocolo inteiro 5 vezes sob código congelado.
É ela que dá o PISO DE RUÍDO: a diferença mínima entre dois juízes abaixo da qual o
ranking não é reportável. Sem esse número, três casas decimais de κ sugerem uma precisão
que a medição não tem.

Uma nota sobre por que reimplementamos `chave_disc`/`chave_pratica` aqui em vez de
importar: o script que as define chama-se `5_juizes_kappa.py` e começa com dígito, o que
o torna não-importável como módulo. São quatro linhas; duplicar é melhor que renomear um
arquivo que já está em uso pelos experimentos em curso.

Uso:
    python avaliacao/analisa_kappa_v4.py                 # tabela principal
    python avaliacao/analisa_kappa_v4.py --area          # κ estratificado por área
    python avaliacao/analisa_kappa_v4.py --continuas     # RMSE, R², viés por questão
"""
from __future__ import annotations

import argparse, glob, json, os, sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import cohen_kappa_score, confusion_matrix

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "rabula/consolidado/src"))
from alignment import carregar_anotacoes_humanas  # noqa: E402
from judge_llm import voto_majoritario            # noqa: E402

V4 = ROOT / "rabula/consolidado/data/evaluations_v4"
ANNOT = ROOT / "rabula/consolidado/data/annotations"
DFS = ROOT / "rabula/Reconstrucao/LLM-as-judge-in-BR-legal-domain/data/dfs/human_alignment_experiment"
GENEROS = {"discursive": "discursivas", "document_writing": "praticas"}


def chave_disc(exame, area, numero, letra, parte):
    return f"exame_{exame}_area_{area}_questao_numero_{numero}_letra_{letra}_parte_{parte}"


def chave_pratica(exame, area, numero, parte):
    return f"exame_{exame}_area_{area}_questao_numero_{numero}_parte_{parte}"


def carrega_df(genero: str) -> pd.DataFrame:
    nome = ("df_discursive_answers_4o_mini.pkl" if genero == "discursive"
            else "df_legal_document_writing_4o_mini.pkl")
    return pd.read_pickle(DFS / nome)


def vereditos(rep: int, juiz: str, genero: str, df: pd.DataFrame) -> pd.DataFrame:
    """Voto majoritário dos 3 runs → uma linha por parte, com área e peso do critério."""
    d = V4 / f"rep{rep}" / f"alignment-{juiz}" / genero
    linhas = []
    for _, row in df.iterrows():
        qid = int(row["id"])
        arqs = sorted(d.glob(f"q{qid}_run*.json"))
        if not arqs:
            continue
        runs = []
        for a in arqs:
            try:
                runs.append(json.loads(a.read_text("utf-8")).get("resultado") or [])
            except Exception:
                pass
        if not runs:
            continue
        pesos = {}
        for c in (row["formated_criteria"] or []):
            k = (chave_disc(row["exam"], row["area"], row["number"], c.get("letra"), c.get("parte"))
                 if genero == "discursive"
                 else chave_pratica(row["exam"], row["area"], c.get("numero"), c.get("parte")))
            pesos[k] = float(c.get("pontos") or c.get("points") or 0)
        for item in voto_majoritario(runs):
            k = (chave_disc(row["exam"], row["area"], row["number"], item.get("letra"), item.get("parte"))
                 if genero == "discursive"
                 else chave_pratica(row["exam"], row["area"], item.get("numero"), item.get("parte")))
            linhas.append({"chave": k, "acerto": int(item.get("acerto") or 0),
                           "questao": qid, "area": row["area"], "peso": pesos.get(k, 0.0)})
    return pd.DataFrame(linhas)


def juizes_disponiveis() -> list[str]:
    js = set()
    for d in glob.glob(str(V4 / "rep*" / "alignment-*")):
        js.add(os.path.basename(d).replace("alignment-", ""))
    return sorted(js)


def reps_disponiveis() -> list[int]:
    return sorted(int(os.path.basename(p)[3:]) for p in glob.glob(str(V4 / "rep*")))


def bootstrap_kappa(m: pd.DataFrame, n: int = 1000, semente: int = 42) -> tuple[float, float]:
    """IC 95% do κ reamostrando QUESTÕES (não critérios).

    Reamostrar critérios trataria as ~9 partes de uma mesma questão como independentes,
    o que elas não são: partilham enunciado, gabarito e a resposta do candidato. O IC
    sairia estreito demais.
    """
    rng = np.random.default_rng(semente)
    qs = m["questao"].unique()
    porq = {q: g for q, g in m.groupby("questao")}
    ks = []
    for _ in range(n):
        amostra = pd.concat([porq[q] for q in rng.choice(qs, len(qs), replace=True)])
        if amostra["golden"].nunique() > 1 and amostra["acerto"].nunique() > 1:
            ks.append(cohen_kappa_score(amostra["golden"], amostra["acerto"]))
    return (float(np.percentile(ks, 2.5)), float(np.percentile(ks, 97.5))) if ks else (np.nan, np.nan)


def main() -> None:
    ap = argparse.ArgumentParser(description="Estatística do benchmark de juízes (v4).")
    ap.add_argument("--area", action="store_true", help="κ estratificado por área do direito")
    ap.add_argument("--continuas", action="store_true", help="RMSE, MAE, R², viés por questão")
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--min-cobertura", type=float, default=0.85,
                    help="fração mínima de partes julgadas. Baixado de 0,95 para 0,85 em "
                         "24/08: modelos pequenos OMITEM critérios no JSON em vez de "
                         "falhar, e excluí-los perde informação. Mas cobertura parcial só "
                         "vale se a omissão for aleatória — ver --max-vies")
    ap.add_argument("--max-vies", type=float, default=0.05,
                    help="diferença máxima na taxa de golden=1 entre critérios julgados e "
                         "omitidos. O Sabiazinho-4 omite 51% de golden=1 em peça contra "
                         "39% nos julgados: ele deixa de fora as partes FÁCEIS, e o κ "
                         "sobre o resto está calculado numa amostra enriquecida em casos "
                         "difíceis. Acima deste limite o juiz é rotulado, não pontuado")
    args = ap.parse_args()

    reps = reps_disponiveis()
    juizes = juizes_disponiveis()
    if not reps:
        raise SystemExit(f"nada em {V4}")
    print(f"repetições encontradas: {reps} · juízes: {len(juizes)}\n")

    humanos = {g: carregar_anotacoes_humanas(ANNOT, tipo=GENEROS[g]) for g in GENEROS}
    dfs = {g: carrega_df(g) for g in GENEROS}
    esperado = {g: len(humanos[g]) for g in GENEROS}

    reg: list[dict] = []
    for juiz in juizes:
        for rep in reps:
            for g in GENEROS:
                v = vereditos(rep, juiz, g, dfs[g])
                if v.empty:
                    continue
                m = v.merge(humanos[g], on="chave", how="inner")
                cob = len(m) / esperado[g]
                if m.empty or m["golden"].nunique() < 2:
                    continue
                # viés de omissão: os critérios que ficaram de fora são diferentes?
                fora = humanos[g][~humanos[g]["chave"].isin(set(v["chave"]))]
                vies = (abs(m["golden"].mean() - fora["golden"].mean())
                        if len(fora) else 0.0)
                reg.append({"juiz": juiz, "rep": rep, "genero": g, "n": len(m),
                            "cobertura": cob, "vies": vies,
                            "kappa": cohen_kappa_score(m["golden"], m["acerto"]),
                            "_m": m})
    if not reg:
        raise SystemExit("nenhum julgamento utilizável ainda")
    d = pd.DataFrame(reg)

    print("=" * 84)
    print("TABELA PRINCIPAL — κ por juiz, média ± desvio entre repetições")
    print("=" * 84)
    print(f"{'juiz':20s} {'κ disc':>16s} {'κ peça':>16s} {'reps':>5s} {'cobertura':>10s}")
    print("-" * 84)
    linhas = []
    for juiz, g0 in d.groupby("juiz"):
        cel, cobmin, nreps = {}, 1.0, 0
        for gen, rot in [("discursive", "disc"), ("document_writing", "peca")]:
            sub = g0[(g0.genero == gen) & (g0.cobertura >= args.min_cobertura)
                     & (g0.vies <= args.max_vies)]
            if sub.empty:
                cel[rot] = None; cobmin = min(cobmin, g0[g0.genero == gen].cobertura.max()
                                              if (g0.genero == gen).any() else 0)
                continue
            cel[rot] = (sub.kappa.mean(), sub.kappa.std(ddof=1) if len(sub) > 1 else np.nan, len(sub))
            cobmin = min(cobmin, sub.cobertura.min()); nreps = max(nreps, len(sub))
        def fmt(c):
            if c is None: return f"{'—':>16s}"
            m_, s_, _ = c
            return f"{m_:9.3f} ±{s_:5.3f}" if not np.isnan(s_) else f"{m_:9.3f}      —"
        print(f"{juiz:20s} {fmt(cel['disc'])} {fmt(cel['peca'])} {nreps:5d} {100*cobmin:9.0f}%")
        if cel["disc"] and cel["peca"]:
            linhas.append({"juiz": juiz, "kd": cel["disc"][0], "sd": cel["disc"][1],
                           "kp": cel["peca"][0], "sp": cel["peca"][1]})

    if linhas:
        t = pd.DataFrame(linhas)
        sds = pd.concat([t.sd, t.sp]).dropna()
        if len(sds):
            print("\n" + "=" * 84)
            print("PISO DE RUÍDO")
            print("=" * 84)
            print(f"  desvio típico do κ sob protocolo idêntico: {sds.median():.4f} "
                  f"(mediana entre juízes e gêneros)")
            print(f"  → diferenças de κ abaixo de {2*1.96*sds.median():.3f} entre dois juízes")
            print(f"    não são distinguíveis do ruído de execução")

    if d.rep.nunique() >= 1:
        print("\n" + "=" * 84)
        print("IC 95% BOOTSTRAP (reamostra questões, repetição 1)")
        print("=" * 84)
        for gen, rot in [("discursive", "disc"), ("document_writing", "peça")]:
            sub = d[(d.rep == reps[0]) & (d.genero == gen) &
                    (d.cobertura >= args.min_cobertura)].sort_values("kappa", ascending=False)
            if sub.empty: continue
            print(f"\n  {rot}:")
            for _, r in sub.head(8).iterrows():
                lo, hi = bootstrap_kappa(r["_m"], args.boot)
                print(f"    {r.juiz:20s} {r.kappa:.3f}  [{lo:.3f}, {hi:.3f}]")

    if args.area:
        print("\n" + "=" * 84)
        print("κ POR ÁREA DO DIREITO (repetição 1, discursivas)")
        print("=" * 84)
        sub = d[(d.rep == reps[0]) & (d.genero == "discursive") &
                (d.cobertura >= args.min_cobertura)]
        areas = sorted({a for _, r in sub.iterrows() for a in r["_m"].area.unique()})
        print(f"{'juiz':20s}" + "".join(f"{a[:9]:>11s}" for a in areas))
        for _, r in sub.sort_values("kappa", ascending=False).head(12).iterrows():
            linha = f"{r.juiz:20s}"
            for a in areas:
                mm = r["_m"][r["_m"].area == a]
                linha += (f"{cohen_kappa_score(mm.golden, mm.acerto):11.2f}"
                          if len(mm) > 3 and mm.golden.nunique() > 1 and mm.acerto.nunique() > 1
                          else f"{'—':>11s}")
            print(linha)

    if args.continuas:
        print("\n" + "=" * 84)
        print("MÉTRICAS CONTÍNUAS POR QUESTÃO (nota ponderada pelos pontos do critério)")
        print("=" * 84)
        print(f"{'juiz':20s} {'gênero':6s} {'RMSE':>7s} {'MAE':>7s} {'R²':>7s} "
              f"{'viés':>8s} {'sens':>6s} {'espec':>6s}")
        for _, r in d[(d.rep == reps[0]) & (d.cobertura >= args.min_cobertura)].iterrows():
            m = r["_m"]
            nj = m.groupby("questao").apply(lambda x: (x.acerto*x.peso).sum()/max(x.peso.sum(), 1e-9),
                                            include_groups=False)
            nh = m.groupby("questao").apply(lambda x: (x.golden*x.peso).sum()/max(x.peso.sum(), 1e-9),
                                            include_groups=False)
            rmse = float(np.sqrt(((nj-nh)**2).mean())); mae = float((nj-nh).abs().mean())
            r2 = float(np.corrcoef(nj, nh)[0, 1]**2) if len(nj) > 2 else np.nan
            vies = float((nj-nh).mean())
            tn, fp, fn, tp = confusion_matrix(m.golden, m.acerto, labels=[0, 1]).ravel()
            sens = tp/(tp+fn) if tp+fn else np.nan
            espec = tn/(tn+fp) if tn+fp else np.nan
            print(f"{r.juiz:20s} {r.genero[:6]:6s} {rmse:7.3f} {mae:7.3f} {r2:7.3f} "
                  f"{vies:+8.3f} {sens:6.2f} {espec:6.2f}")

    # Friedman entre juízes, pareado por questão
    sub = d[(d.rep == reps[0]) & (d.genero == "discursive") & (d.cobertura >= args.min_cobertura)]
    if len(sub) >= 3:
        porjuiz = {}
        for _, r in sub.iterrows():
            m = r["_m"]
            porjuiz[r.juiz] = m.groupby("questao").apply(
                lambda x: (x.acerto == x.golden).mean(), include_groups=False)
        comuns = sorted(set.intersection(*(set(s.index) for s in porjuiz.values())))
        if len(comuns) >= 10:
            mat = [ [porjuiz[j][q] for q in comuns] for j in porjuiz ]
            chi, p = stats.friedmanchisquare(*mat)
            print("\n" + "=" * 84)
            print(f"FRIEDMAN entre {len(mat)} juízes, {len(comuns)} questões pareadas: "
                  f"χ²={chi:.1f}  p={p:.2e}")
            print("  → os juízes NÃO são equivalentes" if p < 0.05
                  else "  → não se rejeita a hipótese de equivalência")


if __name__ == "__main__":
    main()
