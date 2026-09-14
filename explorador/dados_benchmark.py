#!/usr/bin/env python3
"""dados_benchmark.py — as coleções do artigo do benchmark.

O `dados.py` ao lado serve ao artigo da ablação: ele lê as 180 condições treinadas. Este lê
o outro lado do experimento, que é a régua em si: quem julga, quem responde, e o padrão-ouro
humano contra o qual os dois são medidos.

Três coleções e onde vivem:

  concordância por área   kappa_area.json                     — gravado por kappa_por_area.py
  notas dos respondentes  avaliacao/nota.py                   — a mesma função do artigo
  vereditos e padrão-ouro rabula/consolidado/data/            — o que o depósito traz

A anotação cega precisa do enunciado, da resposta e do critério, e de mais nada: mostrar o
veredito de um juiz ou a decisão de outro anotador ao lado contaminaria o que se quer medir.
"""
from __future__ import annotations

import functools, json, os, random, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "avaliacao"))
sys.path.insert(0, str(RAIZ / "rabula/consolidado/src"))
from nota import nota                                                  # noqa: E402

ARQ_KAPPA = Path(os.environ.get("KAPPA_AREA", "/tmp/kappa_area.json"))
AREAS = ["administrativo", "civil", "constitucional", "empresarial", "penal",
         "trabalhista", "tributário"]
TAREFAS = [("discursiva", "discursiva", "questão discursiva"),
           ("peca_formal", "peca_formal", "peça · critérios formais"),
           ("peca_merito", "peca_material", "peça · critérios de mérito")]
USADOS = {"gpt-oss-120b", "kimi-k2-5"}


@functools.lru_cache(maxsize=1)
def kappa() -> dict:
    if not ARQ_KAPPA.exists():
        return {}
    return json.loads(ARQ_KAPPA.read_text("utf-8"))


def regua(tarefa: str) -> dict:
    """Juízes e respondentes na mesma tarefa, por área. É a Tabela 2 ou 3 do artigo, viva."""
    tk_nota = dict((a, b) for a, b, _ in TAREFAS)[tarefa]
    K = kappa()
    juizes = [{"nome": j,
               "producao": j in USADOS,
               "areas": [c.get(tarefa, {}).get(a) for a in AREAS],
               "geral": c.get(tarefa, {}).get("_geral")}
              for j, c in K.items() if tarefa in c]
    juizes.sort(key=lambda x: -(x["geral"] if x["geral"] is not None else -1))
    for j in juizes:
        v = [x for x in j["areas"] if x is not None]
        j["ampl"] = max(v) - min(v) if len(v) > 1 else None

    resp = []
    for m in K:
        g = nota(f"resp_{m}", tk_nota)
        if g is None:
            continue
        resp.append({"nome": m, "geral": g,
                     "areas": [nota(f"resp_{m}", tk_nota, area=a) for a in AREAS]})
    resp.sort(key=lambda x: -x["geral"])
    return {"areas": AREAS, "juizes": juizes, "respondentes": resp,
            "rotulo": dict((a, r) for a, _, r in TAREFAS)[tarefa]}


# ───────────────────────── anotação cega
BENCH = RAIZ / "data/oab/benchmark_v2.jsonl"


@functools.lru_cache(maxsize=2)
def _frame(genero: str):
    import analisa_kappa_v4 as A
    return A.carrega_df(genero)


@functools.lru_cache(maxsize=1)
def _questoes() -> list[dict]:
    """As questões com os critérios ABERTOS, um a um.

    A coluna `criteria` das tabelas herdadas traz o espelho inteiro como texto corrido, o
    que serve para exibir e não para anotar: anotar exige um critério por vez. O
    `benchmark_v2.jsonl` é a mesma prova já decomposta, e é dele que sai a fila.
    """
    if not BENCH.exists():
        return []
    return [json.loads(l) for l in BENCH.read_text("utf-8").splitlines() if l.strip()]


@functools.lru_cache(maxsize=2)
def _respostas(genero: str) -> dict:
    """Resposta avaliada por `rabula_id`, para a tela mostrar o que se está julgando."""
    try:
        df = _frame(genero)
    except Exception:
        return {}
    return {int(r["id"]): str(r.get("answer") or "") for _, r in df.iterrows()}


def item_para_anotar(semente: int | None = None) -> dict | None:
    """Um par (questão, critério) sorteado, sem nenhum veredito ao lado.

    Devolve o enunciado, a resposta avaliada e o texto de UM critério. Quem anota decide se
    a resposta cumpre aquele critério, que é exatamente a decisão binária dos três juristas
    do padrão-ouro. Nem o gabarito do item, nem o veredito de qualquer juiz, nem a decisão
    de outro anotador entram na tela: mostrá-los contaminaria o que se quer medir.
    """
    qs = _questoes()
    if not qs:
        return None
    r = random.Random(semente)
    for _ in range(50):
        q = qs[r.randrange(len(qs))]
        crits = q.get("criterios") or []
        if crits:
            break
    else:
        return None
    i = r.randrange(len(crits))
    c = crits[i]
    genero = "discursive" if q["tipo"] == "discursiva" else "document_writing"
    resp = _respostas(genero).get(q.get("rabula_id"), "")
    return {
        "questao": q["id"],
        "criterio": str(c.get("id") or i),
        "genero": "questão discursiva" if q["tipo"] == "discursiva" else "redação de peça",
        "area": q.get("area"),
        "exame": q.get("exame"),
        "enunciado": str(q.get("enunciado") or "")[:4000],
        "resposta": resp[:6000],
        "titulo_criterio": c.get("titulo") or "",
        "texto_criterio": c.get("texto") or "",
        "pontos": c.get("pontuacao_max"),
        "indice": i + 1,
        "total_criterios": len(crits),
    }
