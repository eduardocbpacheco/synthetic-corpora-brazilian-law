#!/usr/bin/env python3
"""
expande_cascata.py — Expansão por semente, dois saltos e propagação para carreiras.

Implementa o método de `docs/METODO_EXPANSAO_POR_SEMENTE.md`:

  I → II    questão objetiva  ──> par pergunta/resposta dissertativo
  II → III  dissertativa      ──> par enunciado/peça

Duas extensões que faltavam:

  CASCATA (I → II → III). As dissertativas GERADAS a partir da 1ª fase viram semente de
  peça. Multiplica o nível III, que é o mais escasso. Mas cada salto afasta da âncora
  oficial, então esses exemplos saem marcados `cascata: true` e entram como CONDIÇÃO
  PRÓPRIA da ablação — nunca misturados sem marca.

  CARREIRAS. Magistratura, AGU, defensoria e procuradoria têm a mesma escada: fase
  objetiva, dissertativa e tarefa-de-carreira (sentença, parecer, peça). O que muda é o
  gênero do nível III, não a estrutura. Aqui o salto é II → III usando o espelho oficial
  da questão-semente e few-shot do gênero-alvo da própria carreira.

Uso:
    python pipeline/expande_cascata.py --modo cascata   --workers 4
    python pipeline/expande_cascata.py --modo carreiras --workers 4
"""
from __future__ import annotations

import argparse, json, random, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "augmentation"))
SFT = ROOT / "data/finetune"

# O enunciado tem que ser a NARRATIVA DE UM CASO, nunca uma peça. Em 19/08 saiu sem esta
# checagem e 428 dos 514 pares vieram com PETIÇÃO no campo do enunciado — o modelo copiava
# a forma do exemplo real que o proprio prompt injeta como referencia de formato. O exemplo
# de treino virava "aqui esta uma peça, escreva outra", que nao e formato que o benchmark
# apresente. A unica validacao existente era len(resposta) >= 500.
ABERTURA_DE_PECA = re.compile(
    r"^\W*(EXCELENT[ÍI]SSIM|EXMO|EXMA|ILUSTR[ÍI]SSIM|AO\s+(JU[ÍI]Z|MM|EXMO)|MERIT[ÍI]SSIM|"
    r"SENHOR\s+(DOUTOR\s+)?(JU[ÍI]Z|DESEMBARGADOR|MINISTRO|PRESIDENTE))", re.I)


def enunciado_e_caso(t: str) -> bool:
    """Rejeita enunciado que abre como peticao, e o exigido pelo passo 2 do PROMPT."""
    t = re.sub(r"^#*\s*CASO[^\n]*\n", "", (t or "").strip())
    return bool(t) and not ABERTURA_DE_PECA.match(t)


GENERO_ALVO = {"magistratura_tjsp": ("sentença", "sentenca"),
               "agu": ("parecer jurídico", "parecer"),
               "bancas_abertas": ("peça processual", "peca")}

PROMPT = """Você é examinador de concurso jurídico. A partir da questão-semente abaixo, CRIE um
exercício NOVO do gênero {genero}, com o mesmo nível de exigência.

Passos:
1. Construa um CASO concreto e litigável na mesma área da semente, com partes, fatos e uma
   postura processual que exija {genero}. NÃO reaproveite os fatos da semente.
2. Escreva o ENUNCIADO no estilo da banca: narrativa do caso e a instrução final.
   O ENUNCIADO É A PERGUNTA DA PROVA, NÃO A PEÇA. Ele descreve fatos em prosa e termina
   pedindo a peça. NUNCA comece o enunciado por endereçamento ("Excelentíssimo…") —
   endereçamento só existe dentro da RESPOSTA.
3. Escreva a RESPOSTA-MODELO completa, do gênero pedido, em texto puro.

REGRAS: sem markdown; sem lacuna entre colchetes — invente nome, cidade e data plausíveis e
escreva por extenso; fundamente em dispositivo de cuja existência você tenha alta confiança.

Retorne SOMENTE JSON: {{"enunciado": "...", "resposta": "..."}}

ÁREA: {area}
QUESTÃO-SEMENTE (enunciado): {enunciado}
RESPOSTA ESPERADA DA SEMENTE: {resposta}
{exemplo}"""


def json_do_texto(s: str):
    import re
    s = re.sub(r"^```(?:json)?|```$", "", (s or "").strip(), flags=re.M).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        return None
    try:
        return json.loads(s[i:j + 1])
    except Exception:
        return None


def carrega(nome):
    p = SFT / nome
    return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()] if p.exists() else []


def main() -> None:
    ap = argparse.ArgumentParser(description="Expansão por semente: cascata e carreiras.")
    ap.add_argument("--modo", required=True, choices=["cascata", "carreiras"])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limite", type=int, default=None)
    args = ap.parse_args()

    from llm_client import get_client, chat as llm_chat
    from sanitize import limpar_expansao
    random.seed(42)

    if args.modo == "cascata":
        # sementes: dissertativas que JÁ SÃO fruto do salto I→II
        sementes = [d for d in carrega("v4/train.jsonl")
                    if d["_meta"].get("origem") == "1fase_transformada"]
        exemplos = [d for d in carrega("v4/train.jsonl")
                    if d["_meta"].get("tipo") == "peca" and d["_meta"].get("ancorado")]
        alvo = ("peça processual", "peca")
        saida_p, cache_p = SFT / "sft_cascata.jsonl", SFT / "_cascata_cache.json"
    else:
        sementes = [d for d in carrega("sft_carreiras.jsonl")
                    if d["_meta"].get("tipo") in ("discursiva", "dissertacao")
                    and d["_meta"].get("ancorado")]
        exemplos = [d for d in carrega("sft_carreiras.jsonl")
                    if d["_meta"].get("tipo") in ("sentenca", "parecer", "peca")]
        alvo = None
        saida_p, cache_p = SFT / "sft_carreiras_expandido.jsonl", SFT / "_carreiras_exp_cache.json"

    if args.limite:
        sementes = sementes[:args.limite]
    print(f"modo {args.modo}: {len(sementes)} sementes · {len(exemplos)} exemplos do gênero-alvo")

    cache = json.loads(cache_p.read_text("utf-8")) if cache_p.exists() else {}
    pendentes = [d for d in sementes if d["_meta"]["id"] not in cache]
    print(f"em cache: {len(cache)} | pendentes: {len(pendentes)}")

    if pendentes:
        client, model = get_client()
        trava = threading.Lock()
        feitos = erros = 0
        inicio = time.time()

        def um(d, tentativas=3):
            ultimo = None
            for _ in range(tentativas):
                try:
                    return _um(d)
                except ValueError as e:
                    ultimo = e
            raise ultimo

        def _um(d):
            m = d["_meta"]
            genero, tipo = alvo or GENERO_ALVO.get(m.get("origem"), ("peça processual", "peca"))
            ex = random.choice(exemplos) if exemplos else None
            trecho = ""
            if ex:
                resp = next(x["content"] for x in ex["messages"] if x["role"] == "assistant")
                trecho = f"\n\nEXEMPLO REAL do gênero (só para formato e rigor, NÃO copie o conteúdo):\n{resp[:2500]}"
            user = next(x["content"] for x in d["messages"] if x["role"] == "user")
            resposta = next(x["content"] for x in d["messages"] if x["role"] == "assistant")
            r = llm_chat(client, model,
                         PROMPT.format(genero=genero, area=m.get("area", ""),
                                       enunciado=user[:3500], resposta=resposta[:3500], exemplo=trecho),
                         max_tokens=4000, temperature=0.5)
            j = json_do_texto(r)
            if not j or len(j.get("resposta", "")) < 500:
                raise ValueError("JSON inválido ou resposta curta")
            if not enunciado_e_caso(j.get("enunciado", "")):
                raise ValueError("enunciado veio como peça, não como caso")
            return m["id"], {"enunciado": limpar_expansao(j["enunciado"]),
                             "resposta": limpar_expansao(j["resposta"]),
                             "tipo": tipo, "area": m.get("area", ""), "origem_semente": m["id"],
                             "carreira": m.get("origem", "oab")}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for fut in as_completed([pool.submit(um, d) for d in pendentes]):
                try:
                    k, v = fut.result()
                except Exception as e:
                    with trava:
                        erros += 1
                        if erros <= 3:
                            print(f"  ✗ {str(e)[:70]}")
                    continue
                with trava:
                    cache[k] = v
                    feitos += 1
                    if feitos % 25 == 0 or feitos == len(pendentes):
                        cache_p.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")
                        dec = time.time() - inicio
                        print(f"  {feitos}/{len(pendentes)} · {feitos/dec:.1f}/s · erros {erros}", flush=True)
        cache_p.write_text(json.dumps(cache, ensure_ascii=False), "utf-8")

    SISTEMA = {"peca": "Você é advogado redigindo peça processual. Estrutura formal, TEXTO PURO, sem lacuna.",
               "sentenca": "Você é magistrado redigindo sentença: relatório, fundamentação e dispositivo. TEXTO PURO.",
               "parecer": "Você é advogado público redigindo parecer. TEXTO PURO, sem lacuna."}
    n = 0
    with open(saida_p, "w", encoding="utf-8") as f:
        for k, v in cache.items():
            f.write(json.dumps({
                "messages": [
                    {"role": "system", "content": SISTEMA.get(v["tipo"], SISTEMA["peca"])},
                    # o gerador às vezes repete o marcador dentro do enunciado
                    {"role": "user", "content": "### CASO ###\n" +
                     re.sub(r"^#*\s*CASO\s*#*\s*", "", v["enunciado"]).strip()},
                    {"role": "assistant", "content": v["resposta"]}],
                "_meta": {"id": f"casc-{k}" if args.modo == "cascata" else f"carrexp-{k}",
                          "tipo": v["tipo"], "area": v["area"],
                          "origem": "cascata_I_II_III" if args.modo == "cascata" else "carreira_expandida",
                          "origem_semente": v["origem_semente"], "carreira": v.get("carreira"),
                          "cascata": args.modo == "cascata",
                          "ancorado": False, "fonte_resposta": "gerada_livre",
                          "split": "train", "modelo_gerador": "mistral.mistral-large-3-675b-instruct"},
            }, ensure_ascii=False) + "\n")
            n += 1
    print(f"✓ {n} exemplos → {saida_p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
