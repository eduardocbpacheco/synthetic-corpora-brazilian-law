#!/usr/bin/env python3
"""
gera_cards_v3.py — as fichas que faltam no braço expandido do corpus v3, com ORÇAMENTO.

Mesmo professor e mesmo prompt das fichas que já existem — é a condição para o braço
expandido continuar sendo UM regime e não dois:
  · artigo de lei → `expand_normas.gerar_expansao` (PROMPT_NORMA + REGRA_FORMATO,
    temperatura 0,4, até 2.000 tokens), Mistral Large 3 no Bedrock;
  · súmula/OJ/PN/tese do TST e súmula do CARF → PROMPT_JURISPRUDENCIA, como em
    `gera_cards_enunciados.py` para o TST (temperatura 0,35, até 3.500 tokens).

O que falta é calculado por `monta_corpus_v3.pendencias`, DEPOIS de devolvida a validação
de 30/08: ficha que só tinha ido para a validação não é regerada, volta de graça.

ORÇAMENTO (decisão do autor): piloto de ~50 artigos; mede tokens e custo REAIS (o Bedrock
devolve `usage` e `llm_client.USO` acumula); extrapola; a geração completa só roda se o
total estimado ficar abaixo do teto (US$ 150). Acima disso, para e reporta.

Preço: US$ 0,50 / 1M tokens de entrada e US$ 1,50 / 1M de saída para
`mistral.mistral-large-3-675b-instruct` sob demanda em us-east-1 (tabela em
`.env.aws.shared`, conferida na página de preços do Bedrock).

Saídas: data/ablacao_regime_v3/cards_v3.jsonl (acumula; retomável)
        data/ablacao_regime_v3/custo_api.jsonl (uma linha por execução, custo medido)

Uso:
    juridico-env/bin/python pipeline/gera_cards_v3.py --piloto 50 --piloto-juris 10
    juridico-env/bin/python pipeline/gera_cards_v3.py --completo [--teto-usd 150]
"""
from __future__ import annotations
import argparse, collections, datetime, json, os, random, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "pipeline"))
sys.path.insert(0, str(RAIZ / "augmentation"))

PRECO_ENTRADA = 0.50 / 1e6
PRECO_SAIDA = 1.50 / 1e6
SAIDA = RAIZ / "data/ablacao_regime_v3"
CARDS = SAIDA / "cards_v3.jsonl"
CUSTO = SAIDA / "custo_api.jsonl"


def credenciais() -> None:
    """Carrega as credenciais do Bedrock sem imprimi-las, e FORÇA o Bedrock: o `.env` do
    projeto também tem chave do Azure, e o professor do corpus é o Mistral Large 3."""
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env.aws.shared", override=False)
    os.environ["LLM_PROVIDER"] = "bedrock"


def ja_feitos() -> set:
    if not CARDS.exists():
        return set()
    return {json.loads(l)["id"] for l in CARDS.open(encoding="utf-8")
            if (json.loads(l).get("expansao") or "").startswith("<<ID=")}


def gera(tarefas: list[dict], workers: int, fase: str) -> dict:
    import llm_client
    from llm_client import get_client, chat
    from expand_normas import gerar_expansao
    from prompts import PROMPT_JURISPRUDENCIA
    from sanitize import limpar_expansao, REGRA_FORMATO
    client, model = get_client()
    antes = json.loads(json.dumps(llm_client.USO.get(model, {"chamadas": 0, "entrada": 0, "saida": 0})))
    trava = threading.Lock()
    n_ok = n_err = 0
    t0 = time.time()

    def um(x: dict) -> dict:
        if x["tarefa"] == "norma":
            exp = gerar_expansao({"id": x["id"], "doc_id": x["doc_id"], "diploma": x["diploma"],
                                  "num_art": x["num_art"], "texto": x["texto"]}, client, model)
            ident = x["id"]
        else:
            pedido = PROMPT_JURISPRUDENCIA.format(
                juris_id=x["jid"], tipo=x["tipo"], tribunal=x["tribunal"],
                identificador_label="Número", identificador_valor=x["numero"], area=x["area"],
                status_vinculante=x["status"], documento=x["texto"][:6000])
            exp = limpar_expansao(chat(client, model, pedido + REGRA_FORMATO,
                                       max_tokens=3500, temperature=0.35))
            ident = x["jid"]
        return {**{k: v for k, v in x.items() if k != "texto"}, "id": ident,
                "texto_original": x["texto"], "expansao": exp, "modelo_gerador": model,
                "fase": fase, "gerado_em": datetime.datetime.now().isoformat(timespec="seconds")}

    SAIDA.mkdir(parents=True, exist_ok=True)
    with open(CARDS, "a", encoding="utf-8") as f, ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(um, x): x for x in tarefas}
        for fut in as_completed(futs):
            x = futs[fut]
            try:
                r = fut.result()
                ok = (r["expansao"] or "").startswith("<<ID=")
            except Exception as e:                       # registra e segue; --completo retoma
                r, ok = {"id": x.get("jid") or x["id"], "tarefa": x["tarefa"], "expansao": None,
                         "erro": f"{type(e).__name__}: {str(e)[:200]}", "fase": fase}, False
            with trava:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                f.flush()
                n_ok += ok
                n_err += not ok
                n = n_ok + n_err
                if n % 50 == 0 or n == len(tarefas):
                    gasto = llm_client.USO.get(model, {})
                    print(f"  {n}/{len(tarefas)} · ok {n_ok} · falhas {n_err} · "
                          f"{(time.time()-t0)/60:.1f} min · entrada {gasto.get('entrada',0):,} "
                          f"saída {gasto.get('saida',0):,}", flush=True)
    depois = llm_client.USO.get(model, {"chamadas": 0, "entrada": 0, "saida": 0})
    d = {k: depois[k] - antes[k] for k in ("chamadas", "entrada", "saida")}
    reg = {"quando": datetime.datetime.now().isoformat(timespec="seconds"), "fase": fase,
           "modelo": model, "itens": len(tarefas), "ok": n_ok, "falhas": n_err,
           "por_tarefa": dict(collections.Counter(x["tarefa"] for x in tarefas)), **d,
           "custo_usd": round(d["entrada"] * PRECO_ENTRADA + d["saida"] * PRECO_SAIDA, 4),
           "minutos": round((time.time() - t0) / 60, 1)}
    with open(CUSTO, "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")
    print(f"  custo medido desta execução: US$ {reg['custo_usd']:.2f} "
          f"({d['chamadas']} chamadas, {d['entrada']:,} entrada, {d['saida']:,} saída)")
    return reg


def custo_medio_piloto() -> dict:
    """US$ por item, por tipo de tarefa, medido nos pilotos (fase começando com 'piloto')."""
    acc = collections.defaultdict(lambda: [0.0, 0])
    for l in CUSTO.open(encoding="utf-8") if CUSTO.exists() else []:
        r = json.loads(l)
        if r["fase"].startswith("piloto") and len(r["por_tarefa"]) == 1:
            t = next(iter(r["por_tarefa"]))
            acc[t][0] += r["custo_usd"]
            acc[t][1] += r["chamadas"]
    return {t: c / n for t, (c, n) in acc.items() if n}


def gasto_total() -> float:
    return sum(json.loads(l)["custo_usd"] for l in CUSTO.open(encoding="utf-8")) if CUSTO.exists() else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--piloto", type=int, default=0, help="nº de artigos de lei no piloto")
    ap.add_argument("--piloto-juris", type=int, default=0, help="nº de verbetes TST/CARF no piloto")
    ap.add_argument("--completo", action="store_true")
    ap.add_argument("--estima", action="store_true", help="só imprime a estimativa")
    ap.add_argument("--teto-usd", type=float, default=150.0)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    import monta_corpus_v3 as M
    pend = M.pendencias(M.base_congelada())
    feitos = ja_feitos()
    normas = [x for x in pend["normas"] if x["id"] not in feitos]
    juris = [x for x in pend["juris"] if x["jid"] not in feitos]
    print(f"pendentes: {len(normas)} artigos de lei, {len(juris)} verbetes TST/CARF "
          f"(já gerados: {len(feitos)})")
    print("  por diploma:", dict(collections.Counter(x["chave"] for x in normas).most_common()))

    credenciais()
    if a.piloto or a.piloto_juris:
        rng = random.Random(42)
        if a.piloto:
            gera(rng.sample(normas, min(a.piloto, len(normas))), a.workers, "piloto_normas")
        if a.piloto_juris:
            gera(rng.sample(juris, min(a.piloto_juris, len(juris))), a.workers, "piloto_juris")
        return

    medio = custo_medio_piloto()
    if not {"norma", "juris"} <= set(medio):
        raise SystemExit("sem piloto medido para os dois tipos de tarefa: rode --piloto antes")
    est = len(normas) * medio["norma"] + len(juris) * medio["juris"]
    ja = gasto_total()
    print(f"custo médio medido no piloto: norma US$ {medio['norma']:.4f}/ficha · "
          f"juris US$ {medio['juris']:.4f}/ficha")
    print(f"estimativa do restante: US$ {est:.2f} · já gasto: US$ {ja:.2f} · "
          f"total projetado US$ {est + ja:.2f} (teto {a.teto_usd:.0f})")
    if a.estima:
        return
    if est + ja >= a.teto_usd:
        raise SystemExit("PARA · o total projetado passa do teto; nada foi gerado.")
    if a.completo:
        gera(normas + juris, a.workers, "completo")


if __name__ == "__main__":
    main()
