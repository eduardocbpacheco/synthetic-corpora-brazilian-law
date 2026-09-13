#!/usr/bin/env python3
"""
coleta_stf_historico.py — amplia os acórdãos do STF de 2010 em diante.

O arquivo atual (`decisoes/stf/stf_acordaos.jsonl`) é uma JANELA de dois anos, não uma
amostra do acervo: a consulta ordena por julgamento decrescente e corta no limite por
classe, então as 464 ações penais colhidas são todas de 2026 e as 1.358 reclamações, todas
de 2025-2026. Nada anterior entrou.

Este script varre **classe por classe, ano por ano**, com teto por célula, de modo que a
profundidade histórica seja construída por desenho e não por sobra do ranking de data.

Teto fechado com o usuário em 12/09: **200 por classe por ano, de 2010 a 2026**, o que dá
até 200 × 9 classes × 17 anos ≈ 30.600 acórdãos no pior caso.

Retomável: cada célula (classe, ano) já colhida é registrada e pulada na execução seguinte.
Grava em `decisoes/stf/stf_acordaos_historico.jsonl`, sem tocar no arquivo atual.
Relatório em `docs/RELATORIO_COLETA_V2.md`, atualizado a cada célula.

Uso:  juridico-env/bin/python pipeline/coleta_stf_historico.py
      juridico-env/bin/python pipeline/coleta_stf_historico.py --teto 100 --desde 2015
"""
from __future__ import annotations
import argparse, json, os, sys, datetime, time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from augmentation.crawlers.stf_acordaos import crawl_stf_playwright, CLASSES_STF

SAIDA  = os.path.join(RAIZ, "decisoes/stf/stf_acordaos_historico.jsonl")
ESTADO = os.path.join(RAIZ, "logs/coleta_stf_historico_estado.json")
REL    = os.path.join(RAIZ, "docs/RELATORIO_COLETA_STF.md")


def carrega_estado() -> dict:
    if os.path.exists(ESTADO):
        return json.load(open(ESTADO, encoding="utf-8"))
    return {"celulas": {}, "inicio": datetime.datetime.now().isoformat(timespec="seconds")}


def escreve_relatorio(est: dict, teto: int, anos: list[int]) -> None:
    cel = est["celulas"]
    total = sum(v.get("n", 0) for v in cel.values())
    feitas = len(cel)
    previstas = len(CLASSES_STF) * len(anos)
    md = [
        "# Coleta histórica de acórdãos do STF", "",
        f"Atualizado em {datetime.datetime.now():%d/%m/%Y %H:%M}. Gerado por "
        "`pipeline/coleta_stf_historico.py`, reescrito a cada célula.", "",
        "## Por que esta coleta existe", "",
        "O arquivo atual é uma **janela de dois anos**: a consulta ordena por data de",
        "julgamento decrescente e corta no limite por classe, então tudo é de 2025–2026.",
        "As 464 ações penais são todas de 2026 e as 1.358 reclamações, de 2025–2026.",
        "Nada anterior entrou, o que enviesa o corpus para a linguagem e os temas dos",
        "últimos meses.", "",
        f"**Teto: {teto} por classe por ano, de {min(anos)} a {max(anos)}.**", "",
        f"**Progresso: {feitas} de {previstas} células · {total:,} acórdãos colhidos.**", "",
        "| classe | " + " | ".join(str(a) for a in anos) + " | total |",
        "|---" * (len(anos) + 2) + "|",
    ]
    for c in CLASSES_STF:
        linha = [c]
        soma = 0
        for a in anos:
            v = cel.get(f"{c}|{a}")
            if v is None:
                linha.append("·")
            else:
                linha.append(str(v.get("n", 0))); soma += v.get("n", 0)
        linha.append(f"**{soma:,}**")
        md.append("| " + " | ".join(linha) + " |")
    md += ["", "Um ponto significa célula ainda não coletada.", "",
           "## Onde grava", "",
           "`decisoes/stf/stf_acordaos_historico.jsonl`. O arquivo atual não é tocado: a",
           "junção dos dois fica para a montagem do corpus v2.", ""]
    open(REL, "w", encoding="utf-8").write("\n".join(md))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teto",  type=int, default=200)
    ap.add_argument("--desde", type=int, default=2010)
    ap.add_argument("--ate",   type=int, default=2026)
    args = ap.parse_args()
    anos = list(range(args.desde, args.ate + 1))

    est = carrega_estado()
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    escreve_relatorio(est, args.teto, anos)

    for classe in CLASSES_STF:
        for ano in anos:
            chave = f"{classe}|{ano}"
            if chave in est["celulas"]:
                continue
            t0 = time.time()
            print(f"[{datetime.datetime.now():%H:%M}] {classe} {ano}...", flush=True)
            try:
                regs = crawl_stf_playwright(
                    classe=classe, limite=args.teto, estado=None,
                    desde=f"{ano}-01-01", ate=f"{ano}-12-31") or []
            except Exception as e:
                print(f"    falhou: {type(e).__name__}: {e}", flush=True)
                est["celulas"][chave] = {"n": 0, "erro": f"{type(e).__name__}"}
                json.dump(est, open(ESTADO, "w"), ensure_ascii=False)
                escreve_relatorio(est, args.teto, anos)
                continue
            with open(SAIDA, "a", encoding="utf-8") as f:
                for r in regs:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            est["celulas"][chave] = {"n": len(regs), "seg": round(time.time() - t0)}
            json.dump(est, open(ESTADO, "w"), ensure_ascii=False)
            escreve_relatorio(est, args.teto, anos)
            print(f"    {len(regs)} acórdãos em {time.time()-t0:.0f}s", flush=True)
    print("\nconcluído")


if __name__ == "__main__":
    main()
