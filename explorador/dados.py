#!/usr/bin/env python3
"""dados.py — carregamento das três coleções que o explorador mostra.

Tudo em memória e com cache, porque o conjunto é pequeno para o padrão de hoje: 105
questões, 940 critérios, ~5 MB por condição. Um banco aqui seria infraestrutura para um
problema que não existe, e tornaria o artefato mais difícil de rodar do que de ler.

As três coleções e onde elas vivem:

  questões e critérios   data/oab/benchmark_v2.jsonl        — a definição do benchmark
  respostas geradas      avaliacao/resultados/.cache_*/     — 10 execuções por questão
  vereditos              avaliacao/resultados/*_partes.jsonl — um por (execução, critério)
"""
from __future__ import annotations

import collections, functools, json, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BENCH = RAIZ / "data/oab/benchmark_v2.jsonl"
RES = RAIZ / "avaliacao/resultados"

# Nomes de condição legíveis. O disco guarda `sft_i_bruto_s42_3.7b`; a tela mostra
# "bloco I · texto cru · semente 42 · Tucano 3,7B".
MODELO = {"1.5b": "Tucano 1,5B", "3.7b": "Tucano 3,7B", "8b": "Qwen3 8B", "14b": "Qwen3 14B",
          "t15": "Tucano 1,5B", "t37": "Tucano 3,7B", "q8": "Qwen3 8B", "qwen14b": "Qwen3 14B"}
REGIME = {"bruto": "texto cru", "expandido": "ficha", "nenhum": "sem pré-treino"}


@functools.lru_cache(maxsize=1)
def questoes() -> dict[str, dict]:
    fora = {}
    with BENCH.open(encoding="utf-8") as f:
        for linha in f:
            d = json.loads(linha)
            fora[d["id"]] = d
    return fora


def rotulo(cond: str) -> str:
    """Nome de condição em português, ou o próprio nome quando não se reconhece o padrão."""
    m = re.fullmatch(r"sft_([ivx]+)_(\w+?)_s(\d+)_([\w.]+)", cond, re.I)
    if m:
        bl, reg, sem, mod = m.groups()
        return (f"bloco {bl.upper()} · {REGIME.get(reg, reg)} · semente {sem} · "
                f"{MODELO.get(mod.lower(), mod)}")
    m = re.fullmatch(r"ab_(\w+?)_s(\d+)_([\w.]+)", cond, re.I)
    if m:
        reg, sem, mod = m.groups()
        return (f"bloco 0 · {REGIME.get(reg, reg)} · semente {sem} · "
                f"{MODELO.get(mod.lower(), mod)}")
    return cond


@functools.lru_cache(maxsize=1)
def condicoes() -> list[dict]:
    """Toda condição com veredito. `tem_resposta` diz se o texto gerado também está aqui."""
    fora = []
    for p in sorted(RES.glob("*_partes.jsonl")):
        c = p.name[: -len("_partes.jsonl")]
        cache = _cache_de(c)
        fora.append({"cond": c, "rotulo": rotulo(c), "tem_resposta": cache is not None})
    return fora


def _cache_de(cond: str) -> Path | None:
    """O diretório de gerações da condição. O nome varia de caixa entre as séries."""
    p = RES / f".cache_{cond}"
    if (p / "fase1_respostas.json").exists():
        return p
    alvo = f".cache_{cond}".lower()
    for d in RES.glob(".cache_*"):
        if d.name.lower() == alvo and (d / "fase1_respostas.json").exists():
            return d
    return None


@functools.lru_cache(maxsize=8)
def respostas(cond: str) -> dict[str, list[str]]:
    p = _cache_de(cond)
    return json.loads((p / "fase1_respostas.json").read_text("utf-8")) if p else {}


@functools.lru_cache(maxsize=8)
def vereditos(cond: str) -> dict:
    """{questao: {execucao: {criterio: atendeu}}} mais os metadados de cada critério."""
    p = RES / f"{cond}_partes.jsonl"
    por_q: dict = collections.defaultdict(lambda: collections.defaultdict(dict))
    meta: dict = {}
    with p.open(encoding="utf-8") as f:
        for linha in f:
            r = json.loads(linha)
            por_q[r["questao_id"]][r["run"]][r["criterio_id"]] = int(bool(r.get("atendeu")))
            meta.setdefault((r["questao_id"], r["criterio_id"]), {
                "titulo": r.get("titulo"), "classe": r.get("classe"),
                "pontuacao_max": float(r.get("pontuacao_max") or 0)})
    return {"por_questao": {k: dict(v) for k, v in por_q.items()}, "meta": meta}


def nota_questao(cond: str, qid: str, execucao: int | None = None) -> float | None:
    """Fração de pontos da banca naquela questão; média das execuções se não pedir uma."""
    v = vereditos(cond)
    runs = v["por_questao"].get(qid)
    if not runs:
        return None
    alvo = [execucao] if execucao is not None else list(runs)
    notas = []
    for r in alvo:
        itens = runs.get(r) or {}
        ganho = soma = 0.0
        for cid, ok in itens.items():
            p = v["meta"].get((qid, cid), {}).get("pontuacao_max", 0)
            soma += p
            ganho += p * ok
        if soma:
            notas.append(ganho / soma)
    return 100 * sum(notas) / len(notas) if notas else None
