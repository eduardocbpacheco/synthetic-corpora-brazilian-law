#!/usr/bin/env python3
"""Constroi os corpora da ablacao de regime (bruto vs expandido) a 51M tokens.

O orcamento e por familia de tokenizador: Tucano usa vocabulario de 49k
otimizado para portugues e Qwen3 usa 151k, entao o mesmo texto rende
contagens diferentes. Para manter a composicao identica entre as familias,
os documentos sao embaralhados uma unica vez e o corte do Qwen e um prefixo
do corte do Tucano.
"""
import json, random, sys, collections, os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(RAIZ, "data/pretrain_v4/train.jsonl")
SAIDA = os.path.join(RAIZ, "data/ablacao_regime")
ORCAMENTO = 50_500_000  # teto do braco bruto e 50,58M: assim os quatro arquivos ficam iguais
ORC_CASADO = 32_000_000  # maior orcamento em que as duas composicoes podem ser identicas
SEMENTE_AMOSTRA = 42  # fixa: a amostragem do corpus nao e um fator do desenho

# (categoria, fonte) -> (braco, grupo). Fonte None casa com qualquer fonte.
MAPA = {
    # ---- BRUTO: texto juridico escrito por humanos, sem passagem por LLM
    ("Jurisprudência bruta", "TJSP — 2º grau"):        ("bruto", "caso"),
    ("Acórdão STF (inteiro teor)", None):              ("bruto", "caso"),
    ("Jurisprudência bruta", "STJ — informativo"):     ("bruto", "juris"),
    ("Jurisprudência bruta", "STF — controle concentrado"): ("bruto", "juris"),
    ("Jurisprudência bruta", "STF — repercussão geral"):    ("bruto", "juris"),
    ("Jurisprudência bruta", "STJ — tema repetitivo"): ("bruto", "juris"),
    ("Jurisprudência bruta", "STF — súmula"):          ("bruto", "juris"),
    ("Jurisprudência bruta", "STJ — súmula"):          ("bruto", "juris"),
    ("Jurisprudência bruta", "STF — súmula vinculante"): ("bruto", "juris"),
    ("Jurisprudência bruta", "TJSP — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TJSP — súmula"):         ("bruto", "juris"),
    ("Jurisprudência bruta", "IAC — tese"):            ("bruto", "juris"),
    ("Lei Federal (bruta)", None):                     ("bruto", "norma"),
    ("Código (bruta)", None):                          ("bruto", "norma"),
    ("Lei Estadual SP (bruta)", None):                 ("bruto", "norma"),
    ("CF88 (bruta)", None):                            ("bruto", "norma"),
    ("Enunciado (bruto)", None):                       ("bruto", "enunciado"),
    # ---- EXPANDIDO: cards gerados por LLM sobre o mesmo material
    ("Acórdão STJ (rico)", None):                      ("expandido", "caso"),
    ("Acórdão STF (rico)", None):                      ("expandido", "caso"),
    ("Caso TJSP", None):                               ("expandido", "caso"),
    ("RG STF (rico)", None):                           ("expandido", "juris"),
    ("Tema STJ (rico)", None):                         ("expandido", "juris"),
    ("Súmula STF (rico)", None):                       ("expandido", "juris"),
    ("Súmula/OJ TST (card)", None):                    ("expandido", "juris"),
    ("Lei Federal", None):                             ("expandido", "norma"),
    ("Código", None):                                  ("expandido", "norma"),
    ("Lei Estadual SP", None):                         ("expandido", "norma"),
    ("CF88", None):                                    ("expandido", "norma"),
    ("Enunciado doutrinário (card)", None):            ("expandido", "enunciado"),
}
# Doutrina (SciELO, revistas) e OAB (escada I-III) ficam de fora dos dois bracos:
# nao tem contraparte no outro regime, entao entrariam como confusao pura.

FAMILIAS = {
    "tucano": "Polygl0t/Tucano2-qwen-3.7B-Instruct",
    "qwen":   "Qwen/Qwen3-8B",
}


def classifica(d):
    cat, fon = d.get("categoria"), d.get("fonte")
    if (cat, fon) in MAPA:
        return MAPA[(cat, fon)]
    return MAPA.get((cat, None))


def main():
    from transformers import AutoTokenizer

    docs = {"bruto": [], "expandido": []}
    fora = collections.Counter()
    for linha in open(FONTE):
        d = json.loads(linha)
        alvo = classifica(d)
        if alvo is None:
            fora[d.get("categoria")] += 1
            continue
        braco, grupo = alvo
        docs[braco].append({"text": d["text"], "grupo": grupo,
                            "categoria": d["categoria"], "fonte": d.get("fonte")})

    print(f"fora dos bracos: {sum(fora.values())} docs em {len(fora)} categorias")
    for b in docs:
        print(f"  {b}: {len(docs[b])} docs")

    # Uma unica ordem aleatoria por braco, reusada pelas duas familias.
    for b in docs:
        random.Random(SEMENTE_AMOSTRA).shuffle(docs[b])

    tokens = {f: {} for f in FAMILIAS}
    manifesto = {"orcamento_tokens": ORCAMENTO, "semente_amostra": SEMENTE_AMOSTRA,
                 "fonte": os.path.relpath(FONTE, RAIZ), "bracos": {}}

    for fam, nome_tok in FAMILIAS.items():
        tok = AutoTokenizer.from_pretrained(nome_tok)
        for braco, lista in docs.items():
            textos = [x["text"] for x in lista]
            n = []
            LOTE = 2000
            for i in range(0, len(textos), LOTE):
                n.extend(len(e) for e in tok(textos[i:i + LOTE])["input_ids"])
                print(f"\r  {fam}/{braco}: {i + LOTE}/{len(textos)}", end="", file=sys.stderr)
            print(file=sys.stderr)
            tokens[fam][braco] = n
            disponivel = sum(n)

            acum, corte = 0, len(lista)
            for i, k in enumerate(n):
                if acum + k > ORCAMENTO:
                    corte = i
                    break
                acum += k

            comp = collections.Counter()
            for x, k in zip(lista[:corte], n[:corte]):
                comp[x["grupo"]] += k

            cam = os.path.join(SAIDA, f"{fam}_{braco}.jsonl")
            with open(cam, "w") as f:
                for x in lista[:corte]:
                    f.write(json.dumps({"text": x["text"]}, ensure_ascii=False) + "\n")

            manifesto["bracos"][f"{fam}_{braco}"] = {
                "arquivo": os.path.relpath(cam, RAIZ),
                "docs_disponiveis": len(lista), "docs_usados": corte,
                "tokens_disponiveis": disponivel, "tokens_usados": acum,
                "fracao_do_disponivel": round(acum / disponivel, 4),
                "epocas_equivalentes": round(ORCAMENTO / disponivel, 3),
                "composicao_tokens": dict(comp),
                "composicao_pct": {g: round(100 * v / acum, 1) for g, v in comp.items()},
            }
            print(f"{fam}/{braco}: {corte}/{len(lista)} docs, "
                  f"{acum/1e6:.2f}M de {disponivel/1e6:.2f}M tokens "
                  f"({100*acum/disponivel:.0f}%)")
            print(f"    composicao: "
                  + "  ".join(f"{g} {100*v/acum:.0f}%" for g, v in comp.most_common()))

    # ---- par com composicao casada -------------------------------------
    # A 50,5M os dois bracos tem misturas muito diferentes (bruto e 78% caso).
    # Casar a composicao so e possivel ate ~32M, o teto da soma dos minimos por
    # grupo. Gerado aqui para ficar disponivel sem refazer a tokenizacao; nao
    # faz parte da etapa 1.
    cotas = {}
    for g in ("caso", "juris", "norma", "enunciado"):
        disp = {b: sum(k for x, k in zip(docs[b], tokens["tucano"][b]) if x["grupo"] == g)
                for b in docs}
        cotas[g] = min(disp.values())
    escala = ORC_CASADO / sum(cotas.values())
    cotas = {g: v * escala for g, v in cotas.items()}
    manifesto["casado"] = {"orcamento_tokens": ORC_CASADO,
                           "cotas_pct": {g: round(100 * v / ORC_CASADO, 1) for g, v in cotas.items()},
                           "bracos": {}}
    for fam in FAMILIAS:
        for braco, lista in docs.items():
            restante = dict(cotas)
            sel, comp = [], collections.Counter()
            for x, k in zip(lista, tokens[fam][braco]):
                g = x["grupo"]
                if restante[g] - k < 0:
                    continue
                restante[g] -= k
                sel.append(x); comp[g] += k
            cam = os.path.join(SAIDA, f"casado_{fam}_{braco}.jsonl")
            with open(cam, "w") as f:
                for x in sel:
                    f.write(json.dumps({"text": x["text"]}, ensure_ascii=False) + "\n")
            manifesto["casado"]["bracos"][f"{fam}_{braco}"] = {
                "arquivo": os.path.relpath(cam, RAIZ), "docs_usados": len(sel),
                "tokens_usados": sum(comp.values()),
                "composicao_pct": {g: round(100 * v / sum(comp.values()), 1)
                                   for g, v in comp.items()}}
            print(f"casado {fam}/{braco}: {len(sel)} docs, {sum(comp.values())/1e6:.2f}M  "
                  + "  ".join(f"{g} {100*v/sum(comp.values()):.0f}%" for g, v in comp.most_common()))

    with open(os.path.join(SAIDA, "manifesto.json"), "w") as f:
        json.dump(manifesto, f, indent=2, ensure_ascii=False)
    print(f"\nmanifesto em {SAIDA}/manifesto.json")


if __name__ == "__main__":
    main()
