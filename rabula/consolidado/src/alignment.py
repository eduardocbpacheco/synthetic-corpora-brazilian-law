"""
Métricas de alinhamento entre juízes LLM e anotadores humanos.

Reproduz seção do Paper.ipynb (cells 16-45) do subprojeto 2:
- Cohen's kappa (pairwise)
- Fleiss kappa (multi-rater)
- ICC (intraclass correlation)
- MAE, Pearson, Spearman entre notas normalizadas
- Acurácia vs golden label (voto majoritário humano)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from sklearn.metrics import cohen_kappa_score, mean_absolute_error, accuracy_score
from scipy.stats import pearsonr, spearmanr
from statsmodels.stats.inter_rater import fleiss_kappa


# ---------------------------------------------------------------------------
# Carregar anotações humanas
# ---------------------------------------------------------------------------

def carregar_anotacoes_humanas(
    annotations_dir: Path,
    tipo: str = "discursivas",
) -> pd.DataFrame:
    """
    Lê os 3 humano{1,2,3}_anotacoes_{tipo}.json e devolve dataframe
    longo (uma linha por critério com colunas humano_{0,1,2}).

    `tipo` ∈ {'discursivas', 'praticas'}.
    """
    dados = {0: [], 1: [], 2: []}
    for ix, h in enumerate([1, 2, 3]):
        p = annotations_dir / f"humano{h}_anotacoes_{tipo}.json"
        obj = json.loads(p.read_text("utf-8"))
        for _qid, criterios in obj.items():
            for chave, v in criterios.items():
                dados[ix].append((chave, 1 if str(v).strip().lower().startswith("s") else 0))

    df0 = pd.DataFrame(dados[0], columns=["chave", "humano_0"])
    df1 = pd.DataFrame(dados[1], columns=["chave", "humano_1"])
    df2 = pd.DataFrame(dados[2], columns=["chave", "humano_2"])
    out = df0.merge(df1, on="chave").merge(df2, on="chave")
    out["golden"] = ((out["humano_0"] + out["humano_1"] + out["humano_2"]) >= 2).astype(int)
    return out


# ---------------------------------------------------------------------------
# Métricas binárias (critério a critério)
# ---------------------------------------------------------------------------

def kappa_cohen_pairs(*ratings: Iterable[int]) -> dict:
    rs = [np.array(list(r), dtype=int) for r in ratings]
    out = {}
    for i in range(len(rs)):
        for j in range(i + 1, len(rs)):
            k = cohen_kappa_score(rs[i], rs[j])
            out[f"kappa_{i}_{j}"] = round(float(k), 4)
    return out


def kappa_fleiss(*ratings: Iterable[int]) -> float:
    """Espera N avaliadores avaliando os mesmos M itens em escala binária."""
    arr = np.array([list(r) for r in ratings], dtype=int).T  # (M, N)
    M, N = arr.shape
    # matriz (M, K=2): contagens por categoria
    mat = np.zeros((M, 2), dtype=int)
    for i in range(M):
        ones = int(arr[i].sum())
        mat[i, 1] = ones
        mat[i, 0] = N - ones
    return float(fleiss_kappa(mat))


def acuracia_vs_golden(predicoes: Iterable[int], golden: Iterable[int]) -> float:
    return float(accuracy_score(list(golden), list(predicoes)))


# ---------------------------------------------------------------------------
# Métricas contínuas (notas normalizadas 0-100)
# ---------------------------------------------------------------------------

def metricas_contínuas(notas_juiz: Iterable[float], notas_humano: Iterable[float]) -> dict:
    j = np.array(list(notas_juiz), dtype=float)
    h = np.array(list(notas_humano), dtype=float)
    if len(j) < 2:
        return {"mae": None, "pearson": None, "spearman": None}
    mae = mean_absolute_error(h, j)
    pr, pp = pearsonr(j, h)
    sr, sp = spearmanr(j, h)
    return {
        "mae": round(float(mae), 4),
        "pearson_r": round(float(pr), 4),
        "pearson_p": round(float(pp), 4),
        "spearman_r": round(float(sr), 4),
        "spearman_p": round(float(sp), 4),
        "n": int(len(j)),
    }


def icc_2_1(ratings: np.ndarray) -> float:
    """
    ICC(2,1) two-way random effects, single measurement.
    ratings: matriz (M itens × N raters) com escala contínua.
    Implementação direta a partir das fórmulas Shrout-Fleiss.
    """
    M, N = ratings.shape
    mean_rows = ratings.mean(axis=1, keepdims=True)
    mean_cols = ratings.mean(axis=0, keepdims=True)
    mean_total = ratings.mean()

    ss_total = ((ratings - mean_total) ** 2).sum()
    ss_rows = N * ((mean_rows - mean_total) ** 2).sum()
    ss_cols = M * ((mean_cols - mean_total) ** 2).sum()
    ss_err = ss_total - ss_rows - ss_cols

    ms_rows = ss_rows / (M - 1)
    ms_cols = ss_cols / (N - 1) if N > 1 else 0
    ms_err = ss_err / ((M - 1) * (N - 1)) if (M - 1) * (N - 1) else np.nan

    if ms_rows + (N - 1) * ms_err + (N / M) * (ms_cols - ms_err) == 0:
        return float("nan")
    icc = (ms_rows - ms_err) / (
        ms_rows + (N - 1) * ms_err + (N / M) * (ms_cols - ms_err)
    )
    return float(icc)


# ---------------------------------------------------------------------------
# Pipeline de comparação juiz × humano
# ---------------------------------------------------------------------------

def relatorio_alinhamento(
    df_juiz: pd.DataFrame,
    df_humanos: pd.DataFrame,
    chave: str = "chave",
    coluna_juiz: str = "acerto",
) -> dict:
    """
    df_juiz: colunas [chave, acerto] (acerto = 0/1 do juiz LLM consolidado)
    df_humanos: colunas [chave, humano_0, humano_1, humano_2, golden]
    """
    m = df_juiz.merge(df_humanos, on=chave, how="inner")
    if m.empty:
        return {"erro": "interseção vazia entre juiz e humanos"}

    return {
        "n_itens": len(m),
        "acuracia_vs_golden": acuracia_vs_golden(m[coluna_juiz], m["golden"]),
        "kappa_juiz_vs_golden": float(cohen_kappa_score(m["golden"], m[coluna_juiz])),
        "kappa_juiz_vs_h0": float(cohen_kappa_score(m["humano_0"], m[coluna_juiz])),
        "kappa_juiz_vs_h1": float(cohen_kappa_score(m["humano_1"], m[coluna_juiz])),
        "kappa_juiz_vs_h2": float(cohen_kappa_score(m["humano_2"], m[coluna_juiz])),
        "kappa_humanos_pair": kappa_cohen_pairs(m["humano_0"], m["humano_1"], m["humano_2"]),
        "kappa_humanos_fleiss": kappa_fleiss(m["humano_0"], m["humano_1"], m["humano_2"]),
    }
