#!/usr/bin/env python3
"""
gera_remoto.py — gera as respostas do benchmark num vLLM remoto, em vez do MLX local.

Escreve EXATAMENTE o mesmo `avaliacao/resultados/.cache_<ID>/fase1_respostas.json` que a
fase 1 do `run_evaluation_bedrock.py` produz. É a única coisa que o `julga_rabula.py` lê,
então o juiz e toda a análise seguem sem alteração — a origem da resposta muda, o formato
não. Isso também mantém as duas rotas comparáveis: mesmo prompt canônico, mesma
temperatura, mesmo max_tokens.

O que faz a rota remota valer a pena:

1. `n=5` numa chamada só. O vLLM prefila o enunciado UMA vez e amostra as cinco runs em
   cima do mesmo cache de KV. Localmente cada run reprocessa o prompt inteiro — num
   enunciado de peça de ~900 tokens isso é 4/5 do prefill jogado fora.
2. Várias condições ao mesmo tempo. Cada adapter é um `model` diferente na API e o
   batching contínuo do vLLM mistura tudo no mesmo passo, então mandar S0..S4 juntos custa
   pouco mais que mandar um.

O prompt vem de pipeline/prompt_padrao.py e é enviado como `messages`; o template de chat
é aplicado pelo servidor, que carrega o mesmo tokenizador da base. Não montamos o texto
aqui de propósito: duas montagens do template é como o desalinhamento de prompt apareceu
da primeira vez.

Uso:
    python aws/gera_remoto.py --host 1.2.3.4 --conds S0_S42 S1_S42 --n-runs 5
    python aws/gera_remoto.py --host 1.2.3.4 --conds INSTRUCT --adapter ""   # base pura
"""
from __future__ import annotations

import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "avaliacao"))
from prompt_padrao import mensagens, VERSAO as PROMPT_VERSAO  # noqa: E402
from benchmark_schema import load_benchmark_split             # noqa: E402

BASE_HF = "Polygl0t/Tucano2-qwen-3.7B-Instruct"


def gera_condicao(host: str, porta: int, cond: str, modelo: str, questoes,
                  n_runs: int, temp: float, max_tokens: int, workers: int) -> Path:
    destino = ROOT / "avaliacao/resultados" / f".cache_{cond}"
    destino.mkdir(parents=True, exist_ok=True)
    alvo = destino / "fase1_respostas.json"
    cache: dict = json.loads(alvo.read_text("utf-8")) if alvo.exists() else {}

    pend = [q for q in questoes if len(cache.get(q.id, [])) < n_runs]
    if not pend:
        print(f"  {cond}: já completo ({len(questoes)} questões)")
        return alvo
    print(f"  {cond}: {len(pend)} questões pendentes · modelo={modelo or BASE_HF}")

    url = f"http://{host}:{porta}/v1/chat/completions"
    t0 = time.time()

    def uma(q):
        faltam = n_runs - len(cache.get(q.id, []))
        r = requests.post(url, timeout=1800, json={
            "model": modelo or BASE_HF,
            "messages": mensagens(q.tipo, q.enunciado),
            "temperature": temp,
            "max_tokens": max_tokens,
            "n": faltam,
        })
        r.raise_for_status()
        return q.id, [c["message"]["content"].strip() for c in r.json()["choices"]]

    feitas = falhas = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(uma, q): q for q in pend}
        for fut in as_completed(futs):
            q = futs[fut]
            try:
                qid, textos = fut.result()
            except Exception as e:
                falhas += 1
                print(f"    ✗ {q.id}: {str(e)[:100]}", flush=True)
                continue
            cache.setdefault(qid, []).extend(textos)
            feitas += 1
            if feitas % 10 == 0 or feitas + falhas == len(pend):
                alvo.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
                dt = time.time() - t0
                print(f"    {feitas}/{len(pend)} · {dt/60:.0f}min · "
                      f"ETA {dt/feitas*(len(pend)-feitas)/60:.0f}min · falhas {falhas}",
                      flush=True)

    alvo.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
    completas = sum(1 for q in questoes if len(cache.get(q.id, [])) >= n_runs)
    print(f"  {cond}: {completas}/{len(questoes)} completas → {alvo}")
    return alvo


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera respostas num vLLM remoto.")
    ap.add_argument("--host", required=True)
    ap.add_argument("--porta", type=int, default=8000)
    ap.add_argument("--conds", nargs="+", required=True,
                    help="tags das condições (ex.: S0_S42 S1_S42). O nome do adapter no "
                         "servidor é o mesmo, salvo --adapter")
    ap.add_argument("--adapter", default=None,
                    help='nome do adapter no servidor; "" força a base sem LoRA')
    ap.add_argument("--modelo-base", default=BASE_HF,
                    help="id da base no servidor, usado quando --adapter é vazio. O "
                         "THINK é outra base e o servidor a expõe com outro id — sem "
                         "isto o pedido ia para o id do Instruct e voltava 404")
    ap.add_argument("--benchmark", default="data/oab/benchmark_v2.jsonl")
    ap.add_argument("--n-runs", type=int, default=5)
    ap.add_argument("--temp", type=float, default=0.1,
                    help="0,1 é a constante do protocolo desde 22/08. O card do Tucano2 "
                         "recomenda 0,1; medimos e adotamos. A penalidade de repetição "
                         "1,2 do mesmo card fica DESLIGADA (--generation-config vllm no "
                         "servidor): ela desconta o logit de todo token já no contexto, "
                         "inclusive o <|im_end|> que aparece duas vezes no prompt, e com "
                         "isso o modelo nunca emitia parada — finish_reason=length em "
                         "100% das chamadas e 14 pontos de nota a menos")
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--workers", type=int, default=32,
                    help="requisições em voo; o vLLM enfileira o excedente sozinho")
    args = ap.parse_args()

    questoes = load_benchmark_split(str(ROOT / args.benchmark), split="benchmark")
    print(f"{len(questoes)} questões · prompt canônico {PROMPT_VERSAO}")

    disp = requests.get(f"http://{args.host}:{args.porta}/v1/models", timeout=30).json()
    nomes = {m["id"] for m in disp.get("data", [])}
    print(f"servidor expõe: {sorted(nomes)}")

    for cond in args.conds:
        modelo = args.adapter if args.adapter is not None else cond
        if not modelo:
            modelo = args.modelo_base
        if modelo not in nomes:
            print(f"  ✗ {cond}: adapter '{modelo}' não está no servidor — pulando")
            continue
        gera_condicao(args.host, args.porta, cond, modelo, questoes,
                      args.n_runs, args.temp, args.max_tokens, args.workers)


if __name__ == "__main__":
    main()
