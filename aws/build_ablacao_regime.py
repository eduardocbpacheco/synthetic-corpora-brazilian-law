#!/usr/bin/env python3
"""Constroi os corpora da ablacao de regime (bruto vs expandido) a 51M tokens.

O orcamento e por familia de tokenizador: Tucano usa vocabulario de 49k
otimizado para portugues e Qwen3 usa 151k, entao o mesmo texto rende
contagens diferentes. Para manter a composicao identica entre as familias,
os documentos sao embaralhados uma unica vez e o corte do Qwen e um prefixo
do corte do Tucano.
"""
import json, random, re, sys, collections, os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTE = os.path.join(RAIZ, "data/pretrain_v4/train.jsonl")
SAIDA = os.path.join(RAIZ, "data/ablacao_regime")
ORCAMENTO = 50_500_000  # teto do braco bruto e 50,58M: assim os quatro arquivos ficam iguais
ORC_CASADO = 32_000_000  # maior orcamento em que as duas composicoes podem ser identicas
SEMENTE_AMOSTRA = 42  # fixa: a amostragem do corpus nao e um fator do desenho

# (categoria, fonte) -> (braco, grupo). Fonte None casa com qualquer fonte.
MAPA = {
    # ---- BRUTO: o texto juridico como a fonte o publica, sem reescrita por LLM
    #
    # A definicao antiga dizia "sem passagem por LLM", e isso nunca foi exato: o cabecalho
    # de cada bloco de lei traz `[RESUMO DA LEI]`, gerado por modelo. Sao 2.479 blocos, 822
    # mil caracteres, ~228 mil tokens — 0,43% do braco.
    #
    # E de PROPOSITO, e a razao e o corte: o diploma e quebrado em varios blocos, e sem uma
    # linha de contexto no cabecalho o modelo le um trecho de articulado sem saber de que
    # norma se trata. O resumo identifica o documento, nao reescreve o seu conteudo — o
    # articulado abaixo dele e o texto da fonte, intacto.
    #
    # O que muda aqui e a DESCRICAO, que estava errada, e nao o corpus. Fica declarado para
    # que o artigo possa dize-lo: o braco bruto e o texto da fonte com um cabecalho de
    # identificacao, e 99,57% dele nao passou por modelo nenhum.
    ("Jurisprudência bruta", "TJSP — 2º grau"):        ("bruto", "caso"),
    # G1 · sentenca de 1o grau. Faltava aqui, e essa era a SEGUNDA porta fechada: mesmo que
    # o construtor a carregasse, o `classifica` devolveria None e ela cairia no descarte.
    # E CASO, nao juris: e decisao sobre fato concreto, o mesmo papel do acordao de 2o grau.
    ("Jurisprudência bruta", "TJSP — 1º grau"):        ("bruto", "caso"),
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
    # C1 · o que o portal de dados abertos do STJ trouxe, e o que já existia sem rótulo
    # aqui. Medido em 17/09: quatro das seis fontes de acórdão do corpus NÃO estavam no
    # MAPA, somando ~120 M tokens que simplesmente não entrariam em braço nenhum — o
    # `classifica` devolve None e o documento cai fora sem reclamar.
    #
    # A divisão entre `caso` e `juris` segue o que o MAPA já fazia: inteiro teor de acórdão
    # é CASO (como "Acórdão STF (inteiro teor)"), e o registro destilado — ementa, tese,
    # nota de informativo — é JURIS (como "STJ — informativo").
    ("Jurisprudência bruta", "STJ — acórdão"):         ("bruto", "caso"),
    # G2 · a monocrática do STJ é inteiro teor de decisão, logo CASO, como o acórdão.
    # Sem esta linha a montagem abortaria pelo teto de descarte do MAPA — que é
    # exatamente a rede que faltava no G1, onde o TJSP de 1º grau ficou fora sem
    # que nada reclamasse.
    ("Jurisprudência bruta", "STJ — decisão monocrática"): ("bruto", "caso"),
    ("Jurisprudência bruta", "STF — acórdão"):         ("bruto", "caso"),
    ("Jurisprudência bruta", "STJ — espelho"):         ("bruto", "juris"),
    ("Jurisprudência bruta", "STF — informativo"):     ("bruto", "juris"),
    ("Jurisprudência bruta", "STJ — precedente qualificado"): ("bruto", "juris"),
    # C13 · as teses de IRDR dos dez tribunais, colhidas uma a uma dos NUGEPs.
    ("Jurisprudência bruta", "TJPR — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TRF4 — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TJRS — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TRF1 — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TRF2 — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TJSC — IRDR"):           ("bruto", "juris"),
    ("Jurisprudência bruta", "TJRJ — precedente"):     ("bruto", "juris"),
    ("Jurisprudência bruta", "TJMG — precedente"):     ("bruto", "juris"),
    ("Lei Federal (bruta)", None):                     ("bruto", "norma"),
    ("Código (bruta)", None):                          ("bruto", "norma"),
    ("Lei Estadual SP (bruta)", None):                 ("bruto", "norma"),
    ("CF88 (bruta)", None):                            ("bruto", "norma"),
    ("Enunciado (bruto)", None):                       ("bruto", "enunciado"),
    # ---- EXPANDIDO: cards gerados por LLM sobre o mesmo material
    # B2 · o mesmo material está em `juris` no braço bruto ("STJ — informativo") e
    # estava em `caso` aqui. São 10,8M tokens contados em grupos diferentes nos dois
    # lados, o que aparecia como assimetria de COMPOSIÇÃO entre os braços quando era
    # erro de rótulo — e a ablação compara justamente composição.
    ("Nota de informativo STJ (rico)", None):          ("expandido", "juris"),
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


# F3 · fração mínima do braço expandido que precisa ter contraparte no bruto.
#
# A regra de desenho D4 diz que o expandido é a ficha do que está no bruto, mesma lista.
# Medido no corpus de agosto: 0,5%. Ou seja, os dois braços descrevem documentos em boa
# parte diferentes, e a comparação entre eles mede também essa diferença, não só a forma.
# A trava existe para que isso não volte a passar em silêncio: montar um v2 abaixo do piso
# aborta, e quem quiser rodar assim mesmo declara com `--pareamento-livre`.
PISO_PAREAMENTO = 0.90

# Fracao maxima do corpus (em caracteres) que pode ficar fora dos dois bracos sem que a
# montagem aborte. Nao ha razao de principio para 20%: e o valor que teria pego o descarte
# de 17/09 muito antes de ele virar ~120 M tokens.
TETO_DESCARTE = 0.20


def _chave_canonica(trib: str, classe: str, numero: str) -> str:
    """Tribunal, classe e número, que é o que os dois braços têm em comum.

    O bruto escreve `<<JURIS|BRUTO|STF|RE 1601303>>` e o expandido
    `<<ID=...|DOC=JURIS:STF:RE:1601303|...>>`. Comparar só o número junta processos de
    classes diferentes e mede errado para menos; comparar a cadeia inteira separa o que é
    o mesmo processo escrito de dois jeitos.
    """
    # O incidente sai da classe. O bruto grava "Rcl 12345" e o expandido
    # "Rcl-AgR 12345": é agravo regimental NO MESMO processo, e tratá-los como processos
    # distintos derrubava 1.100 pares. Também some o `MC`, `ED`, `QO` e afins, pela mesma
    # razão — medida cautelar e embargos de declaração não mudam o processo, mudam a fase.
    c = re.sub(r'[^A-Z]', '', classe.upper())
    for incid in ("AGRED", "AGR", "ED", "QO", "MC", "REF", "SEGUNDO", "SEGUNDOS",
                  "TERCEIRO", "ACORDO", "EI", "EDV"):
        if c.endswith(incid) and len(c) > len(incid):
            c = c[:-len(incid)]
    return f"{trib.upper()}:{c}:{re.sub(r'[^0-9]', '', numero)}"


def chaves_do_braco(docs: list[dict], braco: str) -> set:
    fora = set()
    for d in docs:
        cab = d["text"][:220]
        if braco == "bruto":
            m = re.match(r"<<JURIS\|BRUTO\|([^|]+)\|([^>]+)>>", cab)
            if not m:
                continue
            # A UF vem colada ao número e de duas formas: o bruto escreve
            # "REsp 2.195.921-AL" e o expandido "REsp 2.195.921/AL". Exigir que a cadeia
            # termine em dígito fazia a expressão casar com 3 processos em 4.060, e o
            # pareamento do STJ aparecia como zero quando na verdade era quase total.
            mm = re.match(r"([A-Za-zÀ-ÿ\-\. ]+?)\s*([\d][\d.]*)(?:\s*[-/]\s*[A-Z]{2})?\s*$",
                          m.group(2).strip())
            if mm:
                fora.add(_chave_canonica(m.group(1), mm.group(1), mm.group(2)))
        else:
            m = re.search(r"<<ID=[^|]*\|DOC=JURIS:([^:]+):([^:]+):([^|:]+)\|", cab)
            if m:
                fora.add(_chave_canonica(m.group(1), m.group(2), m.group(3)))
    return fora


def confere_pareamento(docs: dict, livre: bool = False) -> float:
    b = chaves_do_braco(docs["bruto"], "bruto")
    e = chaves_do_braco(docs["expandido"], "expandido")
    if not e:
        print("  pareamento: nenhuma chave no expandido, conferência impossível")
        return 0.0
    frac = len(b & e) / len(e)
    print(f"  pareamento: {len(b & e)} de {len(e)} chaves do expandido têm contraparte "
          f"no bruto ({frac:.1%}; piso {PISO_PAREAMENTO:.0%})")
    if frac < PISO_PAREAMENTO and not livre:
        raise SystemExit(
            f"  ABORTADO · o expandido não é a ficha do que está no bruto ({frac:.1%}).\n"
            f"  Os dois braços descrevem documentos diferentes, então a comparação entre\n"
            f"  eles mede a diferença de conteúdo junto com a diferença de forma.\n"
            f"  Para montar assim mesmo, e declarar isso, use --pareamento-livre.")
    return frac


def main():
    from transformers import AutoTokenizer

    docs = {"bruto": [], "expandido": []}
    fora = collections.Counter()
    for linha in open(FONTE):
        d = json.loads(linha)
        alvo = classifica(d)
        if alvo is None:
            # Por (categoria, FONTE), nao so categoria: o descarte de ~120 M tokens de
            # acordao em 17/09 ficou invisivel porque "Jurisprudencia bruta" aparecia dos
            # dois lados — parte classificada, parte fora — e a contagem por categoria
            # somava as duas numa linha so.
            fora[(d.get("categoria"), d.get("fonte"))] += len(d.get("text", ""))
            continue
        braco, grupo = alvo
        docs[braco].append({"text": d["text"], "grupo": grupo,
                            "categoria": d["categoria"], "fonte": d.get("fonte")})

    # PORTA DE DESCARTE: falhar alto, nao em silencio.
    #
    # A versao anterior imprimia "fora dos bracos: N docs" e seguia. Um numero impresso no
    # meio de um log nao e uma verificacao — ninguem o le, e foi assim que quatro das seis
    # fontes de acordao ficaram de fora sem que nada reclamasse. Agora o descarte e medido
    # em CARACTERES (docs de tamanhos diferentes pesam diferente), listado por par, e
    # aborta acima do teto. Quem quiser descartar mais declara com `--descarte-livre`.
    chars_dentro = sum(len(x["text"]) for b in docs for x in docs[b])
    chars_fora = sum(fora.values())
    frac = chars_fora / max(1, chars_fora + chars_dentro)
    print(f"fora dos bracos: {chars_fora/1e6:.1f} M chars ({frac:.1%}) "
          f"em {len(fora)} pares (categoria, fonte)")
    for (cat, fon), c in fora.most_common(15):
        print(f"    {c/1e6:>7.1f} M  {cat} · {fon}")
    if frac > TETO_DESCARTE and "--descarte-livre" not in sys.argv:
        raise SystemExit(
            f"\nABORTA: {frac:.1%} do corpus nao casa com o MAPA (teto {TETO_DESCARTE:.0%}).\n"
            "Cada par listado acima e material coletado que nao entra em braco nenhum.\n"
            "Acrescente a chave ao MAPA, ou declare o descarte com --descarte-livre.")
    for b in docs:
        print(f"  {b}: {len(docs[b])} docs")
    manifesto_pareamento = confere_pareamento(docs, "--pareamento-livre" in sys.argv)

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
