#!/usr/bin/env python3
"""
diagnostico_corpus.py — diagnostico de proveniencia do corpus de pre-treino.

Percorre o caminho de cada pedaco de dado, da coleta ao braco de treino, nomeia o script
responsavel por cada transformacao, mede as contagens em cada estagio e aplica seis
verificacoes automaticas. Escreve as lacunas encontradas como pendencias.

Existe porque, em 12/09/2026, tres perguntas do usuario sobre a tabela de fontes do
relatorio produziram quatro correcoes de defeito e duas afirmacoes minhas erradas. Todas
se resolveram medindo. As verificacoes abaixo sao exatamente as medicoes que teriam pego
cada um dos casos, automatizadas para nao dependerem de alguem perguntar.

Uso:  juridico-env/bin/python pipeline/diagnostico_corpus.py
Saida: docs/DIAGNOSTICO_CORPUS.md  ·  logs/diagnostico_corpus.json
"""
from __future__ import annotations
import json, os, re, collections, statistics as st

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def c(p): return os.path.join(RAIZ, p)
def existe(p): return os.path.exists(c(p))

# ---------------------------------------------------------------- o mapa do caminho
# Cada familia declara o caminho completo. `script` nomeia quem faz a transformacao,
# para que a pergunta "quem produziu este arquivo?" tenha resposta sem grep.
CAMINHO = [
 {"familia": "STF · acórdãos",
  "coleta":  {"arq": "decisoes/stf/stf_acordaos.jsonl", "script": "augmentation/crawlers/stf_acordaos.py",
              "id": ["processo"], "conteudo": ["texto", "ementa"]},
  "enriquecimento": {"arq": "data/juris_bruto/inteiro_teor_stf.jsonl", "script": "pipeline/retoma_inteiro_teor.py",
                     "id": ["processo"], "conteudo": ["inteiro_teor", "ementa"]},
  "expansao": {"arq": "augmentation/output/stf_acordaos_expandida.jsonl",
               "script": "augmentation/expand_jurisprudencia.py (via run_all_paralelo.py)"},
  "mestre_bruto": "Acórdão STF (inteiro teor)|STF — inteiro teor",
  "mestre_exp":   "Acórdão STF (rico)|",
  "trib": "STF"},
 {"familia": "STJ · informativos",
  "coleta":  {"arq": "decisoes/stj/stj_informativos_acordaos.jsonl", "script": "augmentation/crawlers/stj_acordaos.py",
              "id": ["informativo"], "conteudo": ["texto"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/stj_acordaos_expandida.jsonl",
               "script": "augmentation/expand_jurisprudencia.py (via run_all_paralelo.py)"},
  "mestre_bruto": "Jurisprudência bruta|STJ — informativo",
  "mestre_exp":   "Acórdão STJ (rico)|",
  "trib": "STJ"},
 {"familia": "TJSP · 2º grau",
  "coleta":  {"arq": "data/juris_bruto/juris_bruto_chunks.jsonl", "script": "(coleta anterior ao versionamento)",
              "id": ["processo", "id"], "conteudo": ["texto"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/casos_tjsp_expandidos.jsonl", "script": "augmentation/expand_casos.py"},
  "mestre_bruto": "Jurisprudência bruta|TJSP — 2º grau",
  "mestre_exp":   "Caso TJSP|",
  "trib": "TJSP"},
 {"familia": "STF · repercussão geral",
  "coleta":  {"arq": "decisoes/stf/repercussao_geral.jsonl", "script": "augmentation/crawlers/stf_acordaos.py",
              "id": ["tema", "id"], "conteudo": ["tese"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/rg_stf_expandida.jsonl", "script": "augmentation/expand_jurisprudencia.py"},
  "mestre_bruto": "Jurisprudência bruta|STF — repercussão geral",
  "mestre_exp":   "RG STF (rico)|", "trib": None},
 {"familia": "STF · súmulas",
  "coleta":  {"arq": "decisoes/stf/sumulas_nao_vinculantes.jsonl", "script": "augmentation/crawlers/stf_acordaos.py",
              "id": ["numero", "id"], "conteudo": ["texto"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/sumulas_stf_expandida.jsonl", "script": "augmentation/expand_fichas_consolidacao.py"},
  "mestre_bruto": "Jurisprudência bruta|STF — súmula",
  "mestre_exp":   "Súmula STF (rico)|", "trib": None},
 {"familia": "STJ · temas repetitivos",
  "coleta":  {"arq": "decisoes/stj/temas_stj.jsonl", "script": "augmentation/crawlers/stj_acordaos.py",
              "id": ["tema", "numero", "id"], "conteudo": ["texto", "tese"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/temas_stj_expandida.jsonl", "script": "augmentation/expand_fichas_consolidacao.py"},
  "mestre_bruto": "Jurisprudência bruta|STJ — tema repetitivo",
  "mestre_exp":   "Tema STJ (rico)|", "trib": None},
 {"familia": "STF · controle concentrado",
  "coleta":  {"arq": "decisoes/stf/controle_concentrado.jsonl", "script": "augmentation/crawlers/stf_acordaos.py",
              "id": ["processo"], "conteudo": ["ementa_texto"]},
  "enriquecimento": None, "expansao": None,
  "mestre_bruto": "Jurisprudência bruta|STF — controle concentrado", "mestre_exp": None, "trib": None},
 {"familia": "IRDR e IAC",
  "coleta":  {"arq": "decisoes/irdr_iac/tjsp_irdr.jsonl", "script": "augmentation/crawlers/irdr_iac.py",
              "id": ["numero", "processo"], "conteudo": ["texto", "questao"]},
  "enriquecimento": None, "expansao": None,
  "mestre_bruto": "Jurisprudência bruta|TJSP — IRDR", "mestre_exp": None, "trib": None},
 {"familia": "Normas · códigos",
  "coleta":  {"arq": "leis/codigos_especificos.parquet", "script": "(coleta do Planalto)",
              "id": ["lei"], "conteudo": ["texto"]},
  "enriquecimento": None,
  "expansao": {"arq": "augmentation/output/codigos_expandidos.jsonl", "script": "augmentation/expand_normas.py"},
  "mestre_bruto": "Código (bruta)|leis/ (texto original)", "mestre_exp": "Código|", "trib": None},
]
LIMIAR_QUEDA = 0.20   # queda de cobertura acima disto vira pendencia


def le(arq):
    if not existe(arq): return None
    if arq.endswith(".parquet"):
        import pandas as pd
        return pd.read_parquet(c(arq)).to_dict("records")
    with open(c(arq), encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def perfil(regs, campos_id, campos_conteudo):
    if regs is None: return None
    ids = set()
    for d in regs:
        for k in campos_id:
            if d.get(k) not in (None, "", "None"):
                ids.add(str(d[k]).strip().upper()); break
    cont = {}
    for k in campos_conteudo:
        tam = [len(str(d.get(k) or "")) for d in regs if k in d]
        if tam:
            cheios = [t for t in tam if t > 0]
            cont[k] = {"preenchidos": len(cheios), "de": len(tam),
                       "mediana": int(st.median(cheios)) if cheios else 0}
    return {"registros": len(regs), "ids": len(ids), "conteudo": cont, "_ids": ids}


def mestre():
    lin = collections.Counter(); doc = collections.defaultdict(set)
    if not existe("data/pretrain_v4/train.jsonl"): return {}
    with open(c("data/pretrain_v4/train.jsonl"), encoding="utf-8") as f:
        for l in f:
            d = json.loads(l); k = f"{d.get('categoria')}|{d.get('fonte') or ''}"
            lin[k] += 1
            t = d["text"]; m = re.match(r"<<([^>]*)>>", t[:260])
            if m:
                h = m.group(1); g = re.search(r"DOC=([^|>\s]+)", h)
                doc[k].add(g.group(1) if g else (h.split("|")[-1] if "|" in h else h))
            else: doc[k].add(t[:120])
    return {k: {"linhas": v, "docs": len(doc[k]), "_docs": doc[k]} for k, v in lin.items()}


def ids_por_tribunal():
    """Identificadores normalizados nos dois bracos, para medir o pareamento."""
    def norma(s): return re.sub(r"[\s.\-/]", "", str(s)).upper()
    bru = collections.defaultdict(set); exp = collections.defaultdict(set)
    if existe("data/ablacao_regime/bruto_completo.jsonl"):
        for l in open(c("data/ablacao_regime/bruto_completo.jsonl"), encoding="utf-8"):
            m = re.match(r"<<JURIS\|BRUTO\|([A-Z]+)\|([^>]*)>>", json.loads(l)["text"][:200])
            if m: bru[m.group(1)].add(norma(m.group(2)))
    if existe("data/ablacao_regime/expandido_completo.jsonl"):
        for l in open(c("data/ablacao_regime/expandido_completo.jsonl"), encoding="utf-8"):
            m = re.search(r"DOC=(?:JURIS|CASE)[:\-]([A-Z]+)[:\-](.+?)(?=[|>\s])",
                          json.loads(l)["text"][:220])
            if m:
                p = m.group(2).split(":")
                exp[m.group(1)].add(norma(p[-2] + p[-1]) if len(p) >= 2 else norma(m.group(2)))
    return bru, exp


def main():
    M = mestre(); BRU, EXP = ids_por_tribunal()
    linhas_md = []; pend = []
    for f in CAMINHO:
        col = perfil(le(f["coleta"]["arq"]), f["coleta"]["id"], f["coleta"]["conteudo"])
        enr = perfil(le(f["enriquecimento"]["arq"]), f["enriquecimento"]["id"],
                     f["enriquecimento"]["conteudo"]) if f["enriquecimento"] else None
        exp = perfil(le(f["expansao"]["arq"]), ["juris_id", "case_id"], ["expansao"]) if f["expansao"] else None
        mb = M.get(f["mestre_bruto"] or "", {}); me = M.get(f["mestre_exp"] or "", {})
        nome = f["familia"]

        # ---- verificacao 1: campo de conteudo vazio onde o campo existe
        for etapa, p in (("coleta", col), ("enriquecimento", enr)):
            if not p: continue
            for k, v in p["conteudo"].items():
                if v["de"] and v["preenchidos"] / v["de"] < 0.5:
                    pend.append({"familia": nome, "tipo": "campo vazio", "gravidade": "alta",
                        "achado": f"no {etapa}, o campo `{k}` está preenchido em apenas "
                                  f"{v['preenchidos']:,} de {v['de']:,} registros"})
        # ---- verificacao 2: queda de cobertura da coleta ao braco
        if col and mb.get("docs"):
            q = 1 - mb["docs"] / max(col["ids"], 1)
            if q > LIMIAR_QUEDA:
                pend.append({"familia": nome, "tipo": "queda de cobertura", "gravidade": "média",
                    "achado": f"do arquivo de coleta ({col['ids']:,} ids) ao braço bruto "
                              f"({mb['docs']:,} docs) perdem-se {100*q:.0f}%"})
        # ---- verificacao 3: identificador nulo
        for etapa, p in (("coleta", col), ("enriquecimento", enr)):
            if p and p["ids"] <= 1 and p["registros"] > 10:
                pend.append({"familia": nome, "tipo": "identificador ausente", "gravidade": "alta",
                    "achado": f"no {etapa}, {p['registros']:,} registros têm {p['ids']} identificador distinto"})
        # ---- verificacao 4: coletado e nao expandido
        if col and not f["expansao"]:
            pend.append({"familia": nome, "tipo": "não expandido", "gravidade": "média",
                "achado": f"{col['registros']:,} registros colhidos, nenhuma ficha gerada"})
        # ---- verificacao 5: pareamento entre os bracos
        if f["trib"]:
            b, e = BRU.get(f["trib"], set()), EXP.get(f["trib"], set())
            if b and e:
                inter = len(b & e); cob = inter / len(b)
                if cob < 0.5:
                    pend.append({"familia": nome, "tipo": "pareamento quebrado", "gravidade": "alta",
                        "achado": f"dos {len(b):,} documentos do braço bruto, apenas {inter:,} "
                                  f"({100*cob:.1f}%) têm correspondente no expandido"})
        # ---- verificacao 6: granularidade divergente
        if mb.get("docs") and me.get("docs"):
            r = me["docs"] / mb["docs"]
            if r > 1.5 or r < 0.67:
                pend.append({"familia": nome, "tipo": "granularidade divergente", "gravidade": "baixa",
                    "achado": f"o braço expandido tem {me['docs']:,} documentos contra {mb['docs']:,} "
                              f"do bruto ({r:.1f}×): a unidade de 'documento' difere entre os braços"})

        linhas_md += [f"## {nome}", ""]
        cc = f["coleta"]
        linhas_md.append(f"**1 · coleta** · `{cc['arq']}` · script `{cc['script']}`")
        if col:
            linhas_md.append(f"- {col['registros']:,} registros · {col['ids']:,} identificadores distintos")
            for k, v in col["conteudo"].items():
                marca = " ⚠" if v["de"] and v["preenchidos"]/v["de"] < 0.5 else ""
                linhas_md.append(f"- campo `{k}`: {v['preenchidos']:,}/{v['de']:,} preenchidos, mediana {v['mediana']:,} chars{marca}")
        else: linhas_md.append("- arquivo ausente")
        if f["enriquecimento"]:
            e2 = f["enriquecimento"]
            linhas_md += ["", f"**2 · enriquecimento** · `{e2['arq']}` · script `{e2['script']}`"]
            if enr:
                linhas_md.append(f"- {enr['registros']:,} registros · {enr['ids']:,} identificadores")
                for k, v in enr["conteudo"].items():
                    marca = " ⚠" if v["de"] and v["preenchidos"]/v["de"] < 0.5 else ""
                    linhas_md.append(f"- campo `{k}`: {v['preenchidos']:,}/{v['de']:,} preenchidos, mediana {v['mediana']:,} chars{marca}")
        if f["expansao"]:
            linhas_md += ["", f"**3 · expansão** · `{f['expansao']['arq']}` · script `{f['expansao']['script']}`"]
            linhas_md.append(f"- {exp['registros']:,} registros" if exp else "- arquivo ausente")
        else:
            linhas_md += ["", "**3 · expansão** · não expandida ⚠"]
        linhas_md += ["", "**4 · corpus mestre** (`pipeline/rechunk_v4.py`)"]
        linhas_md.append(f"- braço bruto: {mb.get('linhas',0):,} linhas · {mb.get('docs',0):,} documentos")
        linhas_md.append(f"- braço expandido: {me.get('linhas',0):,} linhas · {me.get('docs',0):,} documentos")
        if f["trib"]:
            b, e = BRU.get(f["trib"], set()), EXP.get(f["trib"], set())
            if b and e:
                linhas_md += ["", "**5 · braços** (`aws/build_ablacao_regime.py`)",
                              f"- pareamento: {len(b&e):,} dos {len(b):,} documentos do bruto têm "
                              f"correspondente no expandido ({100*len(b&e)/len(b):.1f}%)"]
        linhas_md.append("")

    ordem = {"alta": 0, "média": 1, "baixa": 2}
    pend.sort(key=lambda x: (ordem[x["gravidade"]], x["familia"]))
    cab = ["# Diagnóstico do caminho dos dados", "",
           "Gerado por `pipeline/diagnostico_corpus.py`. Percorre cada família da coleta ao braço de",
           "treino, nomeia o script de cada transformação e aplica seis verificações automáticas.", "",
           f"**{len(pend)} pendências** encontradas nesta execução.", "",
           "## Pendências", "", "| gravidade | família | tipo | achado |", "|---|---|---|---|"]
    for p in pend:
        cab.append(f"| {p['gravidade']} | {p['familia']} | {p['tipo']} | {p['achado']} |")
    cab += ["", "## As seis verificações", "",
            "1. **campo vazio** — campo de conteúdo preenchido em menos de metade dos registros",
            "2. **queda de cobertura** — mais de 20% dos documentos perdidos entre a coleta e o braço",
            "3. **identificador ausente** — muitos registros compartilhando um único identificador",
            "4. **não expandido** — fonte colhida sem ficha correspondente",
            "5. **pareamento quebrado** — menos de metade do braço bruto tem correspondente no expandido",
            "6. **granularidade divergente** — a unidade de 'documento' difere entre os braços", "",
            "## O caminho, família a família", ""]
    os.makedirs(c("logs"), exist_ok=True)
    json.dump(pend, open(c("logs/diagnostico_corpus.json"), "w"), ensure_ascii=False, indent=1)
    open(c("docs/DIAGNOSTICO_CORPUS.md"), "w").write("\n".join(cab + linhas_md))
    print(f"{len(pend)} pendências · docs/DIAGNOSTICO_CORPUS.md")
    for p in pend:
        print(f"  [{p['gravidade']:6s}] {p['familia']:26s} {p['tipo']:24s} {p['achado'][:70]}")


if __name__ == "__main__":
    main()
