#!/usr/bin/env python3
"""
julga_rabula.py — julga em granularidade de PARTE, com o juiz do Rabula.

Substitui julga_sincrono.py, que divergia do Rabula em três pontos e por isso não
herdava a calibração humana (κ 0,821 discursiva / 0,784 peça):

  1. GRANULARIDADE — o julga_sincrono decidia por ITEM (406 decisões, tudo-ou-nada:
     acertar a tese e errar a citação dava zero). O Rabula decide por PARTE, cada
     peso da distribuição de pontos separadamente (940 decisões, crédito parcial).
  2. UMA CHAMADA POR QUESTÃO — o Rabula manda gabarito + lista completa de critérios
     numa só chamada e recebe um veredicto por parte. O julga_sincrono fazia uma
     chamada por critério, isolado, sem o resto da régua à vista.
  3. PROMPT — persona de examinador com 10 anos, regras de alternativa "ou",
     paráfrase e cumulatividade, mais o cache_buster. É esse prompt que o κ mediu.

Aqui o prompt e o parser vêm de rabula/consolidado/src (montar_prompt,
parsear_resposta_juiz); só o backend é nosso (Bedrock, juiz híbrido: Kimi K2.5 nas
discursivas, GPT-OSS 120B nas peças — os dois vencedores do alinhamento por tipo).

Entrada: avaliacao/resultados/.cache_{TAG}/fase1_respostas.json
Saída:   avaliacao/resultados/{tag}_partes.jsonl  (uma linha por parte × run)

Uso:
    python avaliacao/julga_rabula.py --model-id S1_S42 --n-runs 5
    python avaliacao/julga_rabula.py --model-id INSTRUCT --n-runs 5 --workers 4
"""
from __future__ import annotations

import argparse, json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_RABULA = ROOT / "rabula" / "consolidado" / "src"
if not (SRC_RABULA / "judge_llm.py").exists():
    raise SystemExit(
        f"dependência ausente: {SRC_RABULA}/judge_llm.py\n"
        "É de lá que vêm montar_prompt e parsear_resposta_juiz — o prompt exato em que\n"
        "o κ humano foi medido. Não reescreva o prompt: um prompt novo não herda a\n"
        "calibração e o número deixa de ser comparável com o benchmark publicado."
    )
sys.path.insert(0, str(SRC_RABULA))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from judge_llm import avaliar_questao  # noqa: E402

BENCH = ROOT / "data/oab/benchmark_v2.jsonl"
RES = ROOT / "avaliacao/resultados"

JUIZES = {"discursiva": "moonshotai.kimi-k2.5", "peca": "openai.gpt-oss-120b-1:0"}
TIPO_RABULA = {"discursiva": "discursive", "peca": "document_writing"}


def payload_criterios(q: dict) -> list[dict]:
    """Reconstrói o formato `formated_criteria` do Rabula — o prompt foi calibrado nele."""
    if q["tipo"] == "discursiva":
        return [{"letra": c["letra"], "parte": c["parte"],
                 "gabarito": c.get("gabarito_item", ""),
                 "criterio": c["texto"], "pontos": c["pontuacao_max"]}
                for c in q["criterios"]]
    return [{"numero": c["numero"], "parte": c["parte"], "titulo": c.get("titulo", ""),
             "descricao": c["texto"], "pontos": c["pontuacao_max"]}
            for c in q["criterios"]]


def chave(q: dict, d: dict) -> str | None:
    """Chave de casamento entre o veredicto devolvido e a parte do benchmark."""
    if q["tipo"] == "discursiva":
        letra, parte = d.get("letra"), d.get("parte")
        return f"{letra}-{parte}" if letra and parte else None
    num, parte = d.get("numero"), d.get("parte")
    return f"{num}-{parte}" if num is not None and parte else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Julga por parte, com o juiz do Rabula.")
    ap.add_argument("--model-id", required=True, help="tag da condição (ex.: S1_S42)")
    ap.add_argument("--n-runs", type=int, default=5)
    ap.add_argument("--workers", type=int, default=24,
                    help="o teto real é o RPM do juiz, não 4: o limite antigo veio do "
                         "Llama 3.3 70B, que tem 8 RPM cross-region. Kimi K2.5 e "
                         "GPT-OSS 120B têm 100 RPM on-demand (medido em 21/08), e a "
                         "4 workers usávamos 13% disso")
    ap.add_argument("--saida", default=None)
    args = ap.parse_args()

    if not BENCH.exists():
        raise SystemExit(f"benchmark ausente: {BENCH}\n"
                         "Monte com: python pipeline/monta_benchmark_v2.py")
    questoes = {json.loads(l)["id"]: json.loads(l)
                for l in BENCH.read_text("utf-8").splitlines() if l.strip()}
    cache = RES / f".cache_{args.model_id}" / "fase1_respostas.json"
    if not cache.exists():
        sys.exit(f"sem respostas geradas: {cache}")
    respostas = json.loads(cache.read_text("utf-8"))

    saida = Path(args.saida) if args.saida else RES / f"{args.model_id.lower()}_partes.jsonl"
    feitos: set[tuple[str, int]] = set()
    if saida.exists():
        for l in saida.read_text("utf-8").splitlines():
            try:
                d = json.loads(l)
                feitos.add((d["questao_id"], d["run"]))
            except Exception:
                pass

    tarefas = []
    for qid, runs in respostas.items():
        q = questoes.get(qid)
        if not q or not q.get("criterios"):
            continue
        for i, r in enumerate(runs[:args.n_runs], 1):
            if (qid, i) not in feitos and r:
                tarefas.append((qid, i, r))

    n_partes = sum(len(questoes[t[0]]["criterios"]) for t in tarefas)
    print(f"{len(respostas)} questões com resposta · {len(questoes)} no benchmark")
    print(f"chamadas pendentes: {len(tarefas)} (questão × run) → {n_partes} partes")
    if not tarefas:
        print("nada a julgar")
        return

    lock = threading.Lock()
    t0 = time.time()
    ok = falha = 0

    def julga(t):
        qid, run, resposta = t
        q = questoes[qid]
        res = avaliar_questao(
            tipo=TIPO_RABULA[q["tipo"]],
            resposta_candidato=resposta,
            gabarito=q.get("gabarito") or "",
            criterios=payload_criterios(q),
            backend="bedrock",
            judge_model=JUIZES[q["tipo"]],
        )
        vereditos = {}
        for d in res.get("resultado") or []:
            k = chave(q, d)
            if k:
                vereditos[k] = 1 if str(d.get("acerto")).strip() in ("1", "True", "true") else 0
        linhas = []
        for c in q["criterios"]:
            linhas.append({
                "questao_id": qid, "run": run, "tipo": q["tipo"], "area": q.get("area"),
                "exame": q.get("exame"), "criterio_id": c["id"],
                "titulo": c.get("titulo", ""), "classe": c.get("classe", "merito"),
                "pontuacao_max": c["pontuacao_max"],
                "atendeu": vereditos.get(c["id"], 0),
                "julgado": int(c["id"] in vereditos),
                "juiz": JUIZES[q["tipo"]],
            })
        return linhas

    with open(saida, "a", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(julga, t): t for t in tarefas}
            for fut in as_completed(futs):
                qid, run, _ = futs[fut]
                try:
                    linhas = fut.result()
                except Exception as e:
                    with lock:
                        falha += 1
                        print(f"  ✗ {qid} run{run}: {str(e)[:90]}", flush=True)
                    continue
                with lock:
                    ok += 1
                    for l in linhas:
                        f.write(json.dumps(l, ensure_ascii=False) + "\n")
                    f.flush()
                    if ok % 20 == 0 or ok + falha == len(tarefas):
                        dt = time.time() - t0
                        eta = dt / ok * (len(tarefas) - ok) if ok else 0
                        naojulg = sum(1 for l in linhas if not l["julgado"])
                        print(f"  {ok}/{len(tarefas)} · {dt/60:.0f}min · ETA {eta/60:.0f}min "
                              f"· falhas {falha}" + (f" · {naojulg} partes sem veredicto" if naojulg else ""),
                              flush=True)

    print(f"✓ {ok} chamadas ok, {falha} falhas → {saida.name}")


if __name__ == "__main__":
    main()
