#!/usr/bin/env python3
"""
build_juris_bruto.py — Jurisprudência BRUTA padronizada para o CPT.

O corpus só tinha a versão CARD da jurisprudência (texto gerado por LLM). O acórdão
original — a linguagem que o tribunal de fato escreve — estava em `decisoes/` e nunca
tinha entrado. Este script traz esse material com o mesmo desenho semi-bruto das leis:
cabeçalho de identificação e resumo REPETIDOS em cada parte do documento.

DOIS ESTRATOS, e a diferença é do pesquisador:

  CONSOLIDAÇÃO — súmulas (STF, STJ, TJSP), teses de repercussão geral, temas
  repetitivos, IRDR e IAC. **Entra INTEIRA, sem seleção nenhuma.** Enunciado de
  consolidação é único por definição: não há redundância a cortar, e descartar um
  deles é perder entendimento, não repetição.

  ACÓRDÃO — decisões individuais (STF, controle concentrado, informativos do STJ).
  Aqui sim há repetição, e vale o procedimento:
    1. descarta o que não tem questão de fato ou de direito — texto curto demais e
       acórdãos do STF que são só cabeçalho processual (lista de partes, sem ementa);
    2. modelagem de tópicos (--metodo lsa | bertopic | top2vec);
    3. dentro de cada tópico olha os N primeiros e mantém os distintos entre si;
    4. o resto do tópico fica de fora, por ser variação do mesmo entendimento.

O resumo do cabeçalho é a EMENTA oficial quando existe — não uma paráfrase de LLM.

Saída: data/juris_bruto/juris_bruto_chunks.jsonl
Uso:   python pipeline/build_juris_bruto.py [--k 800] [--por-cluster 5] [--limiar 0.6]
"""
from __future__ import annotations

import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAIDA = ROOT / "data" / "juris_bruto" / "juris_bruto_chunks.jsonl"

# Corpo de ~5.000 chars: com o cabeçalho repetido, o chunk fecha perto de 1.600 tokens
# e cabe nos 2.048 do treino sem truncar. Chunk maior perderia o fim de cada parte.
ALVO_CHARS = 5000

CAB_RE = re.compile(r"RELATOR:|PARTES:|ADV\.\(A/S\)|LEG-FED|LEG FED", re.I)
SUBST_RE = re.compile(r"ementa|decis[ãa]o|ac[óo]rd[ãa]o|tese|inconstitucional|"
                      r"recurso (?:conhecid|provid)|vistos|relat[óo]rio", re.I)

STOP = """a o e de da do das dos em no na nos nas um uma uns umas para por com sem sob sobre ao aos que se como
mais menos ja nao não ou entre ate até pelo pela pelos pelas seu sua seus suas este esta estes estas esse essa
esses essas aquele aquela isso isto ser foi sao são tem ter havia haver quando onde qual quais cujo cuja art
artigo inciso paragrafo parágrafo caput lei n nº num numero número acordao acórdão ementa relator ministro
ministra turma seção secao julgado julgamento unanimidade maioria processo recurso stf stj tribunal federal
superior justica justiça direito""".split()


def _limpa(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def carregar_acordaos() -> list[dict]:
    """Decisões individuais — sujeitas à seleção por tópico."""
    docs = []
    for l in open(ROOT / "decisoes/stf/stf_acordaos.jsonl", errors="replace"):
        d = json.loads(l)
        docs.append(dict(id=f"BRUTO:STF:{d.get('processo') or d.get('doc_id')}",
                         fonte="STF — acórdão", tribunal="STF", classe=d.get("classe") or "",
                         numero=str(d.get("numero") or ""), processo=d.get("processo") or "",
                         relator=d.get("relator") or "", orgao=d.get("orgao") or "",
                         data=d.get("data_julgamento") or "", ementa=_limpa(d.get("ementa")),
                         texto=_limpa(d.get("texto"))))
    for l in open(ROOT / "decisoes/stf/controle_concentrado.jsonl", errors="replace"):
        d = json.loads(l)
        em = _limpa(d.get("ementa_texto"))
        rel = d.get("relator_acordao_nome")
        docs.append(dict(id=f"BRUTO:STF:CC:{d.get('processo') or d.get('id')}",
                         fonte="STF — controle concentrado", tribunal="STF",
                         classe=d.get("classe") or "", numero=str(d.get("numero") or ""),
                         processo=d.get("processo") or "", relator=rel if rel not in (None, "None") else "",
                         orgao="", data=d.get("julgamento_data") or "", ementa=em, texto=em))
    for i, l in enumerate(open(ROOT / "decisoes/stj/stj_informativos_acordaos.jsonl", errors="replace")):
        d = json.loads(l)
        txt = _limpa(d.get("texto"))
        proc = d.get("processo") or ""
        m = re.search(r"((?:REsp|AREsp|HC|RHC|CC|MS|AgInt|EDcl)[\s\.\d\-/A-Z]{4,25})", txt)
        if not proc and m:
            proc = m.group(1).strip()
        docs.append(dict(id=f"BRUTO:STJ:INFJ:{d.get('informativo')}:{i}", fonte="STJ — informativo",
                         tribunal="STJ", classe="", numero=str(d.get("informativo") or ""),
                         processo=proc, relator=d.get("relator") or "", orgao=d.get("orgao") or "",
                         data=d.get("data") or "", ementa="", texto=txt))
    return docs


def carregar_consolidacao() -> list[dict]:
    """Súmulas, teses de RG, temas repetitivos, IRDR e IAC. NUNCA passam por seleção."""
    docs = []

    def add(id_, fonte, tribunal, classe, numero, texto, orgao=""):
        texto = _limpa(texto)
        if len(texto) < 30:
            return
        rotulo = f"{classe} {numero}".strip()
        docs.append(dict(id=id_, fonte=fonte, tribunal=tribunal, classe=classe,
                         numero=str(numero or ""), processo=f"{rotulo} do {tribunal}".strip(),
                         relator="", orgao=orgao, data="", ementa=texto, texto=texto))

    for arq, fonte, classe in [("sumulas_vinculantes.jsonl", "STF — súmula vinculante", "Súmula Vinculante"),
                               ("sumulas_nao_vinculantes.jsonl", "STF — súmula", "Súmula")]:
        p = ROOT / "decisoes/stf" / arq
        if not p.exists():
            continue
        for l in open(p, errors="replace"):
            d = json.loads(l)
            add(f"BRUTO:STF:{classe.upper().replace(' ', '')}:{d.get('numero')}", fonte, "STF",
                classe, d.get("numero"), d.get("sumula_texto"))

    for l in open(ROOT / "decisoes/stj/sumulas_stj.jsonl", errors="replace"):
        d = json.loads(l)
        add(f"BRUTO:STJ:SUM:{d.get('numero')}", "STJ — súmula", "STJ", "Súmula",
            d.get("numero"), d.get("texto"), d.get("orgao_julgador") or "")

    for l in open(ROOT / "decisoes/stj/temas_stj.jsonl", errors="replace"):
        d = json.loads(l)
        add(f"BRUTO:STJ:TEMA:{d.get('tema') or d.get('numero')}", "STJ — tema repetitivo", "STJ",
            "Tema repetitivo", d.get("tema") or d.get("numero"), d.get("tese"))

    p = ROOT / "decisoes/stf/repercussao_geral.jsonl"
    if p.exists():
        for l in open(p, errors="replace"):
            d = json.loads(l)
            tese = _limpa(d.get("tese"))
            # SEM TESE FIXADA = tema com repercussão reconhecida mas ainda NÃO JULGADO.
            # São 716 dos 2.000. Entram só título e descrição, ou seja, a PERGUNTA sem a
            # resposta — o modelo aprenderia a controvérsia como se fosse entendimento.
            if not tese:
                continue
            corpo = f"[QUESTÃO] {_limpa(d.get('titulo'))} {_limpa(d.get('descricao'))}\n[TESE FIXADA] {tese}"
            add(f"BRUTO:STF:RG:{d.get('tema') or d.get('numero')}", "STF — repercussão geral", "STF",
                "Tema de repercussão geral", d.get("tema") or d.get("numero"), corpo)

    p = ROOT / "decisoes/tjsp/sumulas_tjsp.jsonl"
    if p.exists():
        for l in open(p, errors="replace"):
            d = json.loads(l)
            add(f"BRUTO:TJSP:SUM:{d.get('numero')}", "TJSP — súmula", "TJSP", "Súmula",
                d.get("numero"), d.get("texto"))

    for arq, fonte, classe in [("tjsp_irdrs_oficiais.jsonl", "TJSP — IRDR", "IRDR"),
                               ("iac_teses.jsonl", "IAC — tese", "IAC")]:
        p = ROOT / "decisoes/irdr_iac" / arq
        if not p.exists():
            continue
        for i, l in enumerate(open(p, errors="replace")):
            d = json.loads(l)
            tese = _limpa(d.get("tese"))
            if not tese:            # mesma regra: incidente sem tese fixada fica de fora
                continue
            corpo = (f"[QUESTÃO] {_limpa(d.get('nome_tema'))} {_limpa(d.get('questao'))}\n"
                     f"[TESE FIXADA] {tese}")
            add(f"BRUTO:{classe}:{d.get('tema') or d.get('numero') or i}", fonte,
                d.get("tribunal") or "TJSP", classe, d.get("tema") or d.get("numero") or i, corpo)

    return docs


def carregar_tjsp(grau: str) -> list[dict]:
    """Acórdãos do TJSP. O CSV local já traz o CONTEÚDO INTEGRAL da decisão — não é
    extrato, ao contrário do que o crawler das superiores havia guardado.

    2º grau: 21.353 decisões, 97% com ementa (que vira o resumo do cabeçalho).
    1º grau: 5.778 sentenças, SEM ementa — o resumo tem de ser gerado (ver
    `pipeline/resume_sentencas_tjsp.py`), e só para as selecionadas.
    """
    p = ROOT / "decisoes/tjsp" / f"tjsp_{grau}.csv"
    if not p.exists():
        return []
    csv.field_size_limit(sys.maxsize)
    docs = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for i, row in enumerate(csv.DictReader(f)):
            corpo = _limpa(row.get("conteudo"))
            if len(corpo) < 200:
                continue
            nup = (row.get("nup") or "").strip()
            classe = _limpa(row.get("classe"))
            docs.append(dict(
                id=f"BRUTO:TJSP:{grau}:{nup or i}", fonte=f"TJSP — {grau.replace('_', 'º ')}",
                tribunal="TJSP", classe=classe, numero=nup, processo=nup or f"{classe} {i}",
                relator=_limpa(row.get("magistrado")),
                orgao=_limpa(row.get("orgao_julgador")) or _limpa(row.get("vara")),
                data=_limpa(row.get("data_julgamento")) or _limpa(row.get("data_publicacao")),
                ementa=_limpa(row.get("ementa")), texto=corpo,
                assunto=_limpa(row.get("assunto")), comarca=_limpa(row.get("comarca"))))
    return docs


def elegivel(d: dict) -> bool:
    t = d["texto"]
    if len(t) < 200:
        return False
    # Acórdão do STF cujo texto é só o cabeçalho processual não tem questão de direito
    return not (len(CAB_RE.findall(t[:1500])) >= 2 and not SUBST_RE.search(t))


def _topicos(textos: list[str], metodo: str, k: int):
    """Devolve o rótulo de tópico de cada documento. -1 = não coube em tópico nenhum.

    Comparação medida em 18/08/2026 sobre os 10.178 acórdãos elegíveis, no espaço de
    embeddings (neutro para os três métodos):

        método               tópicos  coesão  silhueta   seleciona
        LSA + k-means K=800      800   0,857    -0,159       3.434
        BERTopic                 193   0,901     0,056         844 (+4.371 outliers)
        Top2Vec                  149   0,818    -0,090         655

    BERTopic vence nas duas medidas de qualidade e é a única com silhueta positiva —
    o k-means com K=800 força fronteiras onde não há. Por isso é o padrão.
    """
    if metodo == "bertopic":
        from bertopic import BERTopic
        from sentence_transformers import SentenceTransformer
        from umap import UMAP
        modelo = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        E = modelo.encode([t[:1500] for t in textos], batch_size=64, convert_to_numpy=True)
        # random_state fixo no UMAP: sem ele o BERTopic é estocástico e o mesmo comando
        # devolvia 5.425 acórdãos numa rodada e 5.089 na seguinte. Para dissertação, o
        # corpus precisa ser reprodutível.
        umap = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42)
        rot, _ = BERTopic(language="multilingual", calculate_probabilities=False, min_topic_size=8,
                          umap_model=umap).fit_transform([t[:1500] for t in textos], embeddings=E)
        return list(rot)
    if metodo == "top2vec":
        from top2vec import Top2Vec
        m = Top2Vec(documents=[t[:1500] for t in textos], speed="learn", workers=8, min_count=10)
        return list(m.doc_top)
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import Normalizer
    from sklearn.pipeline import make_pipeline
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    X = TfidfVectorizer(max_features=60000, ngram_range=(1, 2), min_df=5, max_df=0.35,
                        sublinear_tf=True, strip_accents="unicode", stop_words=STOP).fit_transform(textos)
    Z = make_pipeline(TruncatedSVD(200, random_state=42), Normalizer(copy=False)).fit_transform(X)
    return list(KMeans(n_clusters=k, random_state=42, n_init=3).fit_predict(Z))


def selecionar(docs: list[dict], k: int, por_cluster: int, limiar: float, metodo: str = "bertopic"):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    textos = [(d["ementa"] or d["texto"])[:4000] for d in docs]
    X = TfidfVectorizer(max_features=60000, ngram_range=(1, 2), min_df=5, max_df=0.35,
                        sublinear_tf=True, strip_accents="unicode", stop_words=STOP).fit_transform(textos)
    lab = _topicos(textos, metodo, k)

    escolhidos, avaliados = [], 0
    porc = {}
    for i, c in enumerate(lab):
        porc.setdefault(int(c), []).append(i)
    # Documento que não coube em tópico nenhum (-1) é o caso singular por definição:
    # entra INTEIRO, sem teto. Amostramos e são ementas completas, não ruído — mediana
    # de 2.577 chars contra 2.534 dos agrupados.
    escolhidos += porc.pop(-1, [])
    for c, idx in porc.items():
        idx = idx[:por_cluster]
        avaliados += len(idx)
        S = cosine_similarity(X[idx])
        mant = []
        for a in range(len(idx)):
            if all(S[a][b] < limiar for b in mant):
                mant.append(a)
        escolhidos += [idx[a] for a in mant]
    return escolhidos, lab, avaliados


_RESUMOS_SENTENCA = None


def resumo_de(d: dict) -> str:
    """Ementa oficial quando existe; para sentença de 1º grau, o resumo gerado."""
    global _RESUMOS_SENTENCA
    if d["ementa"]:
        return d["ementa"][:1200]
    if _RESUMOS_SENTENCA is None:
        p = ROOT / "data/juris_bruto/resumos_sentencas_tjsp.json"
        _RESUMOS_SENTENCA = json.loads(p.read_text("utf-8")) if p.exists() else {}
    gerado = _RESUMOS_SENTENCA.get(d["id"])
    if gerado:
        return gerado[:1200]
    corte = d["texto"][:1200]
    ponto = corte.rfind(". ")
    return corte[:ponto + 1] if ponto > 300 else corte


def cabecalho(d: dict) -> str:
    ident = " · ".join(x for x in [
        d["processo"] or f"{d['classe']} {d['numero']}".strip(),
        d["tribunal"] + (f" ({d['orgao']})" if d["orgao"] else ""),
        f"Rel. {d['relator']}" if d["relator"] else "",
        f"j. {d['data']}" if d["data"] else "",
    ] if x)
    return (f"<<JURIS|BRUTO|{d['tribunal']}|{d['processo'] or d['id']}>>\n"
            f"[DECISÃO] {ident}\n"
            f"[RESUMO DA DECISÃO] {resumo_de(d)}")


def partir(texto: str, alvo: int) -> list[str]:
    if len(texto) <= alvo:
        return [texto]
    partes, atual = [], ""
    for frase in re.split(r"(?<=[.;:])\s+", texto):
        if atual and len(atual) + len(frase) > alvo:
            partes.append(atual.strip())
            atual = ""
        atual += frase + " "
    if atual.strip():
        partes.append(atual.strip())
    return partes


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta a jurisprudência bruta padronizada.")
    ap.add_argument("--k", type=int, default=800)
    ap.add_argument("--por-cluster", type=int, default=5)
    ap.add_argument("--limiar", type=float, default=0.6)
    ap.add_argument("--metodo", default="bertopic", choices=["bertopic", "top2vec", "lsa"])
    ap.add_argument("--tjsp", default="2_grau", choices=["nenhum", "2_grau", "1_grau", "ambos"],
                    help="quais acórdãos do TJSP incluir (espaço de tópicos próprio)")
    args = ap.parse_args()

    consolidacao = carregar_consolidacao()
    print(f"consolidação (súmulas, teses, temas, IRDR/IAC): {len(consolidacao)} — TODA preservada")

    sel = list(consolidacao)
    # Cada acervo é agrupado no SEU espaço de tópicos: junto, o TJSP (21 mil decisões
    # longas e repetitivas) dominaria os clusters e afogaria as superiores.
    acervos = [("superiores", carregar_acordaos())]
    if args.tjsp in ("2_grau", "ambos"):
        acervos.append(("TJSP 2º grau", carregar_tjsp("2_grau")))
    if args.tjsp in ("1_grau", "ambos"):
        acervos.append(("TJSP 1º grau", carregar_tjsp("1_grau")))

    for nome, acervo in acervos:
        if not acervo:
            continue
        elig = [d for d in acervo if elegivel(d)]
        escolhidos, lab, _ = selecionar(elig, args.k, args.por_cluster, args.limiar, args.metodo)
        n_top = len({int(c) for c in lab if int(c) != -1})
        print(f"{nome}: {len(acervo)} em disco | {len(elig)} elegíveis | {n_top} tópicos "
              f"| selecionados: {len(escolhidos)}")
        sel += [elig[i] for i in escolhidos]
    print(f"TOTAL a padronizar: {len(sel)}")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    n_chunks = 0
    with open(SAIDA, "w", encoding="utf-8") as out:
        # Sufixo sequencial: decisões distintas do MESMO processo (ex.: acórdão e embargos)
        # geravam id igual e colidiam, o que atrapalharia qualquer dedup posterior.
        for seq, d in enumerate(sel):
            cab = cabecalho(d)
            partes = partir(d["texto"], ALVO_CHARS)
            for k, p in enumerate(partes):
                texto = f"{cab}\n[TEXTO — parte {k+1}/{len(partes)}]\n{p}"
                out.write(json.dumps({
                    "id": f"{d['id']}~{seq}#{k}", "categoria": f"Jurisprudência bruta — {d['tribunal']}",
                    "proveniencia": "semi_bruto", "fonte_arquivo": d["fonte"],
                    "titulo": d["processo"] or d["id"], "licenca": "obra_publica_gov",
                    "url": "", "chunk_ix": k, "n_chunks": len(partes),
                    "n_chars": len(texto), "text": texto,
                }, ensure_ascii=False) + "\n")
                n_chunks += 1
    print(f"✓ {len(sel)} decisões → {n_chunks} chunks em {SAIDA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
