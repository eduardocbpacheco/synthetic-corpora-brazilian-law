#!/usr/bin/env python3
"""app.py — explorador do experimento: ver as respostas, não só as notas.

Um artigo reporta que uma condição marcou 25,4% e outra 17,7%. O que ele não pode mostrar,
por falta de espaço, é o que essas duas condições escreveram na mesma questão e em qual
critério elas divergiram. É isso que este artefato faz — e é o que separa um número que se
acredita de um número que se confere.

Três vistas, e cada uma existe por um motivo distinto:

  /condicoes  compara duas condições treinadas na mesma questão, critério a critério
  /regua      a régua de juízes, com as discordâncias contra o padrão-ouro abertas
  /anotar     anotação binária cega, para estender o padrão-ouro humano

Sem login. Roda em 127.0.0.1 salvo pedido explícito.
"""
from __future__ import annotations

import argparse, json, os, sys, time, uuid
from pathlib import Path

from flask import Flask, Response, jsonify, redirect, request, send_from_directory

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dados

AQUI = Path(__file__).resolve().parent
ANOT = AQUI / "anotacoes"

app = Flask(__name__, static_folder=str(AQUI / "static"), static_url_path="/static")


def pagina(titulo: str, vista: str) -> Response:
    abas = [("condicoes", "condições"), ("regua", "régua de juízes"), ("anotar", "anotar")]
    nav = "".join(
        f'<a href="/{v}" class="aba{" sel" if v == vista else ""}">{r}</a>' for v, r in abas)
    html = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo} · explorador</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&display=swap">
<link rel="stylesheet" href="/static/estilo.css">
</head><body data-vista="{vista}">
<header><b>Explorador</b><nav>{nav}</nav><span class="dir" id="dir"></span></header>
<main id="raiz"></main>
<script src="/static/explorador.js" defer></script>
</body></html>"""
    return Response(html, mimetype="text/html; charset=utf-8")


@app.get("/")
def raiz():
    return redirect("/condicoes")


@app.get("/condicoes")
def v_condicoes():
    return pagina("Comparar condições", "condicoes")


@app.get("/regua")
def v_regua():
    return pagina("Régua de juízes", "regua")


@app.get("/anotar")
def v_anotar():
    return pagina("Anotar", "anotar")


# ───────────────────────── api comum
@app.get("/api/questoes")
def api_questoes():
    return jsonify([{"id": q["id"], "tipo": q["tipo"], "area": q["area"], "exame": q["exame"],
                     "criterios": len(q.get("criterios") or [])}
                    for q in dados.questoes().values()])


@app.get("/api/condicoes")
def api_condicoes():
    return jsonify(dados.condicoes())


@app.get("/api/questao/<qid>")
def api_questao(qid: str):
    q = dados.questoes().get(qid)
    if not q:
        return jsonify({"erro": "questão desconhecida"}), 404
    return jsonify(q)


@app.get("/api/comparar")
def api_comparar():
    """As duas respostas e a tabela de critérios com o veredito de cada lado."""
    qid = request.args.get("q", "")
    lados = [request.args.get("a", ""), request.args.get("b", "")]
    execucao = int(request.args.get("run", 0))
    q = dados.questoes().get(qid)
    if not q:
        return jsonify({"erro": "questão desconhecida"}), 404

    saida = {"questao": q, "lados": []}
    marcas: dict[str, list] = {}
    for cond in lados:
        if not cond:
            saida["lados"].append(None)
            continue
        resp = dados.respostas(cond).get(qid) or []
        v = dados.vereditos(cond)
        runs = v["por_questao"].get(qid, {})
        # A execução pedida pode não existir em toda condição; cai na primeira disponível.
        chave = execucao if execucao in runs else (sorted(runs)[0] if runs else None)
        itens = runs.get(chave, {})
        for cid, ok in itens.items():
            marcas.setdefault(cid, []).append(ok)
        saida["lados"].append({
            "cond": cond, "rotulo": dados.rotulo(cond),
            "execucoes": sorted(runs), "execucao": chave,
            "resposta": resp[chave] if chave is not None and chave < len(resp) else None,
            "nota": dados.nota_questao(cond, qid, chave),
            "nota_media": dados.nota_questao(cond, qid),
            "vereditos": itens,
            "meta": {cid: v["meta"].get((qid, cid), {}) for cid in itens},
        })
    saida["divergem"] = [c for c, vs in marcas.items() if len(vs) == 2 and vs[0] != vs[1]]
    return jsonify(saida)


# ───────────────────────── anotação cega
def _arq_anot(anotador: str) -> Path:
    seguro = "".join(c for c in anotador if c.isalnum() or c in "-_") or "anonimo"
    return ANOT / f"{seguro}.json"


@app.get("/api/anotacoes/<anotador>")
def le_anotacoes(anotador: str):
    p = _arq_anot(anotador)
    return jsonify(json.loads(p.read_text("utf-8")) if p.exists() else {})


@app.post("/api/anotacoes/<anotador>")
def grava_anotacao(anotador: str):
    d = request.get_json(force=True)
    p = _arq_anot(anotador)
    ANOT.mkdir(parents=True, exist_ok=True)
    atual = json.loads(p.read_text("utf-8")) if p.exists() else {}
    atual.setdefault(d["questao"], {})[d["criterio"]] = {
        "atendeu": int(bool(d["atendeu"])),
        "quando": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(atual, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, p)
    return jsonify({"ok": True, "anotados": sum(len(v) for v in atual.values())})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7788)
    ap.add_argument("--exposto", action="store_true")
    a = ap.parse_args()
    print(f"  questões: {len(dados.questoes())} · condições: {len(dados.condicoes())}")
    print(f"  abra:     http://127.0.0.1:{a.porta}")
    app.run(host="0.0.0.0" if a.exposto else "127.0.0.1", port=a.porta, debug=False)


if __name__ == "__main__":
    main()
