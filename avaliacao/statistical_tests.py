"""
Testes estatísticos para comparação de modelos no benchmark jurídico OAB.

Funções principais:
  - wilcoxon_pareado():       Teste de Wilcoxon pareado entre dois modelos.
  - cohens_d():               Tamanho de efeito d de Cohen.
  - bonferroni_correction():  Correção de Bonferroni para múltiplas comparações.
  - full_comparison_report(): Tabela completa de comparações M1→M2, M1→M3, etc.

Pares de comparação pré-definidos (5 pares × 2 tipos = 10 testes):
  M1→M2, M1→M3, M1→M4, M2→M3, M3→M4

Uso:
    import pandas as pd
    from statistical_tests import full_comparison_report

    resultados = {
        "M1": {"discursiva": [0.5, 0.6, ...], "peca": [0.4, 0.5, ...]},
        "M2": {"discursiva": [0.7, 0.8, ...], "peca": [0.6, 0.7, ...]},
        ...
    }
    df = full_comparison_report(resultados, questao_ids)
    print(df.to_markdown(index=False))
"""

from __future__ import annotations

import math
import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pares canônicos de comparação
# ---------------------------------------------------------------------------

PARES_COMPARACAO = [
    ("M1", "M2"),
    ("M1", "M3"),
    ("M1", "M4"),
    ("M2", "M3"),
    ("M3", "M4"),
]

TIPOS_QUESTAO = ["discursiva", "peca"]

# ---------------------------------------------------------------------------
# Wilcoxon pareado
# ---------------------------------------------------------------------------

def wilcoxon_pareado(
    scores_a: List[float],
    scores_b: List[float],
    questao_ids: Optional[List[str]] = None,
    alpha: float = 0.05,
) -> dict:
    """
    Teste de Wilcoxon de postos com sinais (pareado) entre dois modelos.

    Cada elemento das listas corresponde ao score médio de um modelo
    em uma mesma questão (pareamento por questão).

    Args:
        scores_a:    Scores do modelo A (um valor por questão).
        scores_b:    Scores do modelo B (um valor por questão).
        questao_ids: IDs das questões (apenas para logging).
        alpha:       Nível de significância (padrão 0.05).

    Returns:
        {
            "statistic": float,       # estatística W de Wilcoxon
            "p_value": float,         # p-valor (bicaudal)
            "n_pairs": int,           # número de pares com diferença != 0
            "significativo": bool,    # p_value < alpha
            "alpha": float,
        }
    """
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        raise ImportError("scipy não instalado. Execute: pip install scipy")

    if len(scores_a) != len(scores_b):
        raise ValueError(
            f"scores_a e scores_b devem ter o mesmo tamanho "
            f"({len(scores_a)} vs {len(scores_b)})"
        )

    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)
    diffs = b - a

    # Remove pares sem diferença (o teste Wilcoxon exige n > 0 pares com diff != 0)
    nonzero_mask = diffs != 0
    n_pares = int(nonzero_mask.sum())

    if n_pares < 10:
        logger.warning(
            f"[Wilcoxon] Apenas {n_pares} pares com diferença não-nula. "
            "Resultado pode ser pouco confiável."
        )

    if n_pares == 0:
        logger.warning("[Wilcoxon] Todos os pares são idênticos. p=1.0.")
        return {
            "statistic": 0.0,
            "p_value": 1.0,
            "n_pairs": 0,
            "significativo": False,
            "alpha": alpha,
        }

    stat, pval = wilcoxon(a[nonzero_mask], b[nonzero_mask], alternative="two-sided")

    return {
        "statistic": float(stat),
        "p_value": float(pval),
        "n_pairs": n_pares,
        "significativo": bool(pval < alpha),
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# d de Cohen
# ---------------------------------------------------------------------------

def cohens_d(
    scores_a: List[float],
    scores_b: List[float],
) -> dict:
    """
    Calcula o d de Cohen (tamanho de efeito) entre dois grupos.

    Usa o desvio-padrão combinado (pooled SD) como denominador.

    Interpretação convencional (Cohen 1988):
      |d| < 0.2  → desprezível
      |d| < 0.5  → pequeno
      |d| < 0.8  → médio
      |d| >= 0.8 → grande

    Args:
        scores_a: Scores do modelo A.
        scores_b: Scores do modelo B.

    Returns:
        {
            "d": float,
            "interpretacao": str,   # "desprezível" / "pequeno" / "médio" / "grande"
            "mean_a": float,
            "mean_b": float,
            "std_pooled": float,
        }
    """
    a = np.array(scores_a, dtype=float)
    b = np.array(scores_b, dtype=float)

    mean_a = float(np.mean(a))
    mean_b = float(np.mean(b))

    # Desvio-padrão pooled (amostral, ddof=1)
    std_a = float(np.std(a, ddof=1))
    std_b = float(np.std(b, ddof=1))
    n_a, n_b = len(a), len(b)

    if n_a + n_b < 4:
        logger.warning("[Cohen's d] Amostras muito pequenas.")
        return {
            "d": float("nan"),
            "interpretacao": "indefinido",
            "mean_a": mean_a,
            "mean_b": mean_b,
            "std_pooled": float("nan"),
        }

    # Pooled SD ponderado pelos graus de liberdade
    std_pooled = math.sqrt(
        ((n_a - 1) * std_a ** 2 + (n_b - 1) * std_b ** 2) / (n_a + n_b - 2)
    )

    if std_pooled == 0:
        d = 0.0
    else:
        d = (mean_b - mean_a) / std_pooled

    abs_d = abs(d)
    if abs_d < 0.2:
        interpretacao = "desprezível"
    elif abs_d < 0.5:
        interpretacao = "pequeno"
    elif abs_d < 0.8:
        interpretacao = "médio"
    else:
        interpretacao = "grande"

    return {
        "d": float(d),
        "interpretacao": interpretacao,
        "mean_a": mean_a,
        "mean_b": mean_b,
        "std_pooled": float(std_pooled),
    }


# ---------------------------------------------------------------------------
# Correção de Bonferroni
# ---------------------------------------------------------------------------

def bonferroni_correction(
    p_valores: Dict[str, float],
    alpha: float = 0.05,
) -> dict:
    """
    Aplica correção de Bonferroni para múltiplas comparações.

    O alpha corrigido é alpha / n_comparacoes. Uma comparação é considerada
    significativa se seu p-valor original for menor que o alpha corrigido.

    Args:
        p_valores: Dicionário {nome_comparacao: p_valor}.
        alpha:     Nível de significância familiar (padrão 0.05).

    Returns:
        {
            "alpha_original": float,
            "n_comparacoes": int,
            "alpha_corrigido": float,
            "resultados": {
                nome_comparacao: {
                    "p_valor": float,
                    "significativo_corrigido": bool,
                }
            }
        }
    """
    n = len(p_valores)
    if n == 0:
        raise ValueError("p_valores não pode ser vazio.")

    alpha_corr = alpha / n

    resultados = {}
    for nome, pval in p_valores.items():
        resultados[nome] = {
            "p_valor": pval,
            "significativo_corrigido": bool(pval < alpha_corr),
        }

    return {
        "alpha_original": alpha,
        "n_comparacoes": n,
        "alpha_corrigido": float(alpha_corr),
        "resultados": resultados,
    }


# ---------------------------------------------------------------------------
# Relatório completo de comparações
# ---------------------------------------------------------------------------

def full_comparison_report(
    resultados_por_modelo: Dict[str, Dict[str, List[float]]],
    questao_ids: Optional[Dict[str, List[str]]] = None,
    alpha: float = 0.05,
) -> "pd.DataFrame":
    """
    Gera tabela completa de comparações estatísticas entre todos os modelos.

    Args:
        resultados_por_modelo:
            Dicionário com estrutura:
            {
                "M1": {
                    "discursiva": [score_q1, score_q2, ...],
                    "peca":       [score_q1, score_q2, ...],
                },
                "M2": {...},
                ...
            }
            Cada lista deve estar alinhada por questão (mesma ordem).

        questao_ids:
            Opcional. Dicionário {"discursiva": ["41-disc-1", ...], "peca": [...]}
            para logging. Se None, usa índices numéricos.

        alpha:
            Nível de significância familiar para Bonferroni (padrão 0.05).

    Returns:
        pd.DataFrame com colunas:
          Par, tipo, mean_a, mean_b, delta_mean,
          W, p_raw, p_corr, significativo, d_cohen, interpretacao

    Pares comparados: M1→M2, M1→M3, M1→M4, M2→M3, M3→M4
    Tipos: discursiva, peca  →  10 linhas no total (se todos os modelos existirem)
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas não instalado. Execute: pip install pandas")

    modelos_disponiveis = set(resultados_por_modelo.keys())
    linhas = []

    # Coleta p-valores para correção de Bonferroni
    p_valores_coletados: Dict[str, float] = {}

    for modelo_a, modelo_b in PARES_COMPARACAO:
        if modelo_a not in modelos_disponiveis or modelo_b not in modelos_disponiveis:
            logger.info(
                f"[Relatório] Par {modelo_a}→{modelo_b} ignorado: "
                "um dos modelos não está disponível."
            )
            continue

        for tipo in TIPOS_QUESTAO:
            scores_a = resultados_por_modelo[modelo_a].get(tipo, [])
            scores_b = resultados_por_modelo[modelo_b].get(tipo, [])

            if not scores_a or not scores_b:
                logger.info(
                    f"[Relatório] {modelo_a}→{modelo_b} / {tipo}: sem dados."
                )
                continue

            if len(scores_a) != len(scores_b):
                logger.warning(
                    f"[Relatório] {modelo_a}→{modelo_b} / {tipo}: "
                    f"tamanhos diferentes ({len(scores_a)} vs {len(scores_b)}). Pulando."
                )
                continue

            ids = (questao_ids or {}).get(tipo)
            wilcox = wilcoxon_pareado(scores_a, scores_b, questao_ids=ids)
            cohen = cohens_d(scores_a, scores_b)

            chave = f"{modelo_a}→{modelo_b}_{tipo}"
            p_valores_coletados[chave] = wilcox["p_value"]

            linhas.append({
                "par": f"{modelo_a}→{modelo_b}",
                "tipo": tipo,
                "mean_a": round(cohen["mean_a"], 4),
                "mean_b": round(cohen["mean_b"], 4),
                "delta_mean": round(cohen["mean_b"] - cohen["mean_a"], 4),
                "W": round(wilcox["statistic"], 2),
                "p_raw": round(wilcox["p_value"], 6),
                "p_corr": None,              # preenchido após Bonferroni
                "significativo": None,        # preenchido após Bonferroni
                "d_cohen": round(cohen["d"], 4) if not math.isnan(cohen["d"]) else float("nan"),
                "interpretacao": cohen["interpretacao"],
                "_chave": chave,
            })

    if not linhas:
        logger.warning("[Relatório] Nenhuma comparação gerada.")
        try:
            import pandas as pd
            return pd.DataFrame(columns=[
                "par", "tipo", "mean_a", "mean_b", "delta_mean",
                "W", "p_raw", "p_corr", "significativo", "d_cohen", "interpretacao",
            ])
        except ImportError:
            raise

    # Aplica Bonferroni
    bonf = bonferroni_correction(p_valores_coletados, alpha=alpha)
    alpha_corr = bonf["alpha_corrigido"]

    for linha in linhas:
        chave = linha.pop("_chave")
        res = bonf["resultados"].get(chave, {})
        linha["p_corr"] = round(alpha_corr, 6)           # alpha corrigido (limiar)
        linha["significativo"] = res.get("significativo_corrigido", False)

    import pandas as pd
    df = pd.DataFrame(linhas)

    # Reordena colunas
    colunas = [
        "par", "tipo", "mean_a", "mean_b", "delta_mean",
        "W", "p_raw", "p_corr", "significativo", "d_cohen", "interpretacao",
    ]
    df = df[colunas]

    # Rodapé informativo
    logger.info(
        f"[Relatório] {len(df)} comparações geradas. "
        f"Alpha Bonferroni corrigido: {alpha_corr:.4f} "
        f"({len(p_valores_coletados)} testes)."
    )

    return df


# ---------------------------------------------------------------------------
# Helpers para carregar resultados de JSONL
# ---------------------------------------------------------------------------

def scores_medios_por_questao(
    resultados_jsonl: List[dict],
    modelo_id: str,
    tipo: Optional[str] = None,
) -> tuple[List[str], List[float]]:
    """
    Extrai score médio por questão de uma lista de resultados JSONL.

    Args:
        resultados_jsonl: Lista de dicts no formato de saída do run_evaluation.
        modelo_id:        ID do modelo a filtrar (ex: "M2").
        tipo:             Filtrar por tipo ("discursiva" ou "peca"). None = todos.

    Returns:
        (questao_ids, scores) — listas alinhadas por questão.
    """
    filtrado = [
        r for r in resultados_jsonl
        if r.get("model_id") == modelo_id
        and (tipo is None or r.get("tipo") == tipo)
    ]
    # Ordena por questao_id para garantir alinhamento entre modelos
    filtrado.sort(key=lambda r: r["questao_id"])

    questao_ids = [r["questao_id"] for r in filtrado]
    scores = [r.get("mean_score", r.get("mean", 0.0)) for r in filtrado]
    return questao_ids, scores
