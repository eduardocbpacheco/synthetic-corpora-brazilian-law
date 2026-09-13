#!/usr/bin/env python3
"""nota.py — a nota de uma condicao, sempre discriminada por tarefa.

Existe porque cada tabela do relatorio recalculava a nota com um recorte proprio, e
duas delas discordavam: uma pesava os criterios por igual, outra pela pontuacao que a
banca da a cada um. Sao escalas diferentes e davam 18,1% e 25,0% para a mesma condicao.
Aqui ha uma funcao so, e ela pesa pela pontuacao da banca, que e a escala do relatorio.

A peca nunca se reporta num numero so. A banca divide os criterios da peca em duas
classes com rotulo proprio no espelho: os FORMAIS (enderecamento, qualificacao, pedido,
fecho) e os de MERITO (a tese juridica). Sao 14,9% e 85,1% dos pontos, entao o agregado
da peca e quase a nota de merito e esconde inteiramente o que acontece na parte formal —
que e justamente onde o pre-treino mais mexe. As tres saem sempre juntas.
"""
from __future__ import annotations

import collections, json, statistics as st
from pathlib import Path

RES = Path(__file__).resolve().parent / "resultados"

MODELOS = ["1.5B", "3.7B", "8B", "14B"]
NOME = {"1.5B": "Tucano 1,5B", "3.7B": "Tucano 3,7B", "8B": "Qwen3 8B", "14B": "Qwen3 14B"}
BLOCOS = ["I", "II", "III", "IV", "VII", "X"]
REGIMES = ["bruto", "expandido", "nenhum"]
BASE = {"1.5B": "base_t15", "3.7B": "instruct_v5", "8B": "v5_qwen8_base", "14B": "v5_qwen14_base"}

# As quatro tarefas reportaveis. `peca` e o agregado das duas classes, e vem por ultimo
# de proposito: nas tabelas ele e a coluna de conferencia, nao a coluna que se le.
TAREFAS = [
    ("discursiva",    "discursiva",     None),
    ("peca_formal",   "peça formal",    ("peca", "formal")),
    ("peca_material", "peça material",  ("peca", "merito")),
    ("peca",          "peça agregada",  ("peca", None)),
]
ROTULO = {k: r for k, r, _ in TAREFAS}


def _casa(r: dict, tarefa: str) -> bool:
    if tarefa == "discursiva":
        return r["tipo"] == "discursiva"
    if r["tipo"] != "peca":
        return False
    if tarefa == "peca":
        return True
    return r.get("classe") == ("formal" if tarefa == "peca_formal" else "merito")


AREAS = ["administrativo", "civil", "constitucional", "empresarial", "penal",
         "trabalhista", "tributário"]


def nota(cond: str, tarefa: str, area: str | None = None) -> float | None:
    """Nota percentual de `cond` na tarefa dada, pesada pela pontuacao da banca.

    Media por execucao das medias por questao — nao media simples sobre criterios, que
    daria mais peso as questoes com mais itens no espelho.
    """
    f = RES / f"{cond}_partes.jsonl"
    if not f.exists():
        return None
    acc: dict = collections.defaultdict(lambda: [0.0, 0.0])
    with f.open(encoding="utf-8") as fh:
        for l in fh:
            r = json.loads(l)
            if not _casa(r, tarefa):
                continue
            if area is not None and r.get("area") != area:
                continue
            p = float(r.get("pontuacao_max", 1))
            a = acc[(r["run"], r["questao_id"])]
            a[1] += p
            if r.get("atendeu"):
                a[0] += p
    por_run: dict = collections.defaultdict(list)
    for (run, _q), (a, b) in acc.items():
        if b > 0:
            por_run[run].append(a / b)
    v = [st.mean(x) for x in por_run.values()]
    return 100 * st.mean(v) if v else None


# O bloco 0 e o ponto de partida do fine-tuning: o modelo depois do pre-treino continuado e
# antes de qualquer SFT. Ele tem uma semente so, e nao a mesma em todos — o Qwen3 8B saiu na
# 43 e os outros tres na 42. No regime `nenhum`, que pula o pre-treino, o bloco 0 e o proprio
# modelo base, porque nao houve tratamento nenhum ate ali.
FAM_CPT = {"1.5B": "t15", "3.7B": "t37", "8B": "q8", "14B": "qwen14b"}
SEM_BLOCO0 = {"1.5B": 42, "3.7B": 42, "8B": 43, "14B": 42}


def cond_bloco0(modelo: str, regime: str) -> str:
    if regime == "nenhum":
        return BASE[modelo]
    return f"ab_{regime}_s{SEM_BLOCO0[modelo]}_{FAM_CPT[modelo]}"


def bloco0(modelo: str, regime: str, tarefa: str, area: str | None = None) -> float | None:
    return nota(cond_bloco0(modelo, regime), tarefa, area)


def cond_sft(bloco: str, regime: str, semente: int, modelo: str) -> str:
    return f"sft_{bloco.lower()}_{regime}_s{semente}_{modelo.lower()}"


def media_sementes(bloco: str, regime: str, modelo: str, tarefa: str,
                   sementes=(42, 43, 44), area: str | None = None) -> float | None:
    v = [nota(cond_sft(bloco, regime, s, modelo), tarefa, area) for s in sementes]
    v = [x for x in v if x is not None]
    return st.mean(v) if v else None


def por_questao(cond: str, tarefa: str) -> dict[str, float]:
    """Nota media por questao, para os testes pareados."""
    acc: dict = collections.defaultdict(lambda: [0.0, 0.0])
    f = RES / f"{cond}_partes.jsonl"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8") as fh:
        for l in fh:
            r = json.loads(l)
            if not _casa(r, tarefa):
                continue
            p = float(r.get("pontuacao_max", 1))
            a = acc[(r["run"], r["questao_id"])]
            a[1] += p
            if r.get("atendeu"):
                a[0] += p
    q: dict = collections.defaultdict(list)
    for (_run, qid), (a, b) in acc.items():
        if b > 0:
            q[qid].append(a / b)
    return {k: st.mean(v) for k, v in q.items()}


def pt(x: float | None, casas: int = 1, suf: str = "") -> str:
    return "—" if x is None else f"{x:.{casas}f}{suf}".replace(".", ",")


def ptd(x: float | None, casas: int = 1, suf: str = "") -> str:
    return "—" if x is None else f"{x:+.{casas}f}{suf}".replace(".", ",")


def cls(x: float | None, lim: float = 0.3) -> str:
    if x is None:
        return "g"
    return "up" if x > lim else ("dn" if x < -lim else "g")
