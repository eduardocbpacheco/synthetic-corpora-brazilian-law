#!/usr/bin/env python3
"""
coleta_trab_trib_v3.py — jurisprudência consolidada do TST e súmulas do CARF, UM VERBETE
POR DOCUMENTO e só o que está EM VIGOR. Etapa 2 da réplica (corpus v3), item 4.

O que havia no corpus congelado, e por que não serve:

  · TST, braço bruto: 210 blocos `<<ENUNCIADO|TST>>` que são o LIVRO de súmulas fatiado em
    pedaços de tamanho fixo (o defeito C15/B5, corrigido no v4 mas não no congelado). Um
    pedaço começa no meio de um verbete e termina no meio de outro, e o livro traz os
    CANCELADOS ao lado dos vigentes, com o mesmo peso tipográfico: o modelo lia "SUM-2
    GRATIFICAÇÃO NATALINA (cancelada)" seguido do texto cancelado como se fosse direito.
  · TST, braço expandido: 1.804 fichas sobre 855 verbetes, geradas da edição de 2023 do
    livro — inclusive sobre verbetes cancelados (a Súmula 2, cancelada em 2003, tem ficha).
  · Tributário administrativo: nada. O CARF não aparecia em braço nenhum.

Fontes (todas públicas, sem desafio, robots.txt permitindo; datas registradas na saída):

  1. Livro "Súmulas, OJs (TP/OE, SBDI-I, SBDI-I Transitória, SBDI-II, SDC) e Precedentes
     Normativos", PDF publicado pelo TST em www.tst.jus.br/livro-de-sumulas-ojs-e-pns
     (edição de 26/09/2025). O status de cada verbete está no próprio título: "(cancelada)",
     "(cancelamento mantido)", "(convertida na Súmula nº …)". Fica o texto vigente; o
     "Histórico:" sai, porque é a redação SUPERADA — mesma regra do V6 para lei riscada.
  2. "Índice Temático — Precedentes Trabalhistas" (Comissão Gestora de Precedentes do TST,
     versão de 13/11/2026, CC BY-NC-SA 4.0): os temas de Incidente de Recursos de Revista
     Repetitivos (IRR) e de Assunção de Competência (IAC), que são as TESES VINCULANTES do
     TST (art. 896-C da CLT). Só entra tema com tese firmada; tema afetado e pendente não
     tem conteúdo jurídico, só a pergunta.
     NÃO usei jurisprudencia.tst.jus.br: o robots.txt dele é `Disallow: /`.
  3. "Súmulas Consolidadas com os Acórdãos Precedentes", página do CARF em gov.br
     (atualizada em 09/10/2026). Os "dados abertos" do CARF são só gerenciais (PDF de
     estoque e produtividade) — não há conjunto de súmulas nem de acórdãos para baixar,
     então a fonte é a página oficial. Súmula "revogada" fica fora.

Acórdãos do TST e do CARF ficaram de fora: ver docs/CORPUS_V3.md, seção "o que ficou de fora".

Saída: data/trabalho_v3/tst_verbetes.jsonl, data/trabalho_v3/tst_teses.jsonl,
       data/tributario_v3/carf_sumulas.jsonl  (+ PDFs/HTML de origem em raw/)
"""
from __future__ import annotations
import datetime, hashlib, html, json, os, re, subprocess, sys, time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAB = os.path.join(RAIZ, "data/trabalho_v3")
TRIB = os.path.join(RAIZ, "data/tributario_v3")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/120.0.0.0 Safari/537.36",
      "Accept-Language": "pt-BR,pt;q=0.9"}

URL_LIVRO = "https://www.tst.jus.br/documents/d/guest/livrointernet-12-pdf"
URL_INDICE = "https://www.tst.jus.br/documents/d/guest/livro-precedentes-trabalhistas-v182025"
URL_CARF = ("https://www.gov.br/carf/pt-br/jurisprudencia/sumulas-carf/"
            "sumulas-consolidadas-com-os-acordaos-precedentes")


def baixa(url: str, destino: str) -> dict:
    import requests
    if not os.path.exists(destino):
        time.sleep(2)
        r = requests.get(url, headers=UA, timeout=300)
        r.raise_for_status()
        open(destino, "wb").write(r.content)
    b = open(destino, "rb").read()
    return {"url": url, "arquivo": os.path.relpath(destino, RAIZ),
            "sha256": hashlib.sha256(b).hexdigest(),
            "baixado_em": datetime.datetime.fromtimestamp(os.path.getmtime(destino)).isoformat(timespec="seconds")}


def pdf_texto(caminho: str) -> str:
    return subprocess.run(["pdftotext", caminho, "-"], capture_output=True, text=True).stdout


# ── TST: súmulas, OJs e PNs ───────────────────────────────────────────────────────────

ROTULO = {"SUM": "Súmula", "OJ-TP/OE": "OJ do Tribunal Pleno/Órgão Especial",
          "OJ-SDI1": "OJ da SBDI-I", "OJ-SDI1T": "OJ Transitória da SBDI-I",
          "OJ-SDI2": "OJ da SBDI-II", "OJ-SDC": "OJ da SDC", "PN": "Precedente Normativo"}
# `(?!\d)` e não `\b`: o PDF cola número e título em dois verbetes ("SUM-228ADICIONAL",
# "SUM-311BENEF…"), e com `\b` as Súmulas 228 e 311 sumiam.
_CABECA = re.compile(r"^(SUM|OJ-TP/OE|OJ-SDI1T|OJ-SDI1|OJ-SDI2|OJ-SDC|PN)-(\d+)(?!\d)\s*(.*)$")
# Onde um verbete termina sem que comece outro: a tese de IRR que o livro intercala depois
# da súmula que ela reafirma, e o índice remissivo no fim do volume.
_PARA = re.compile(r"^(IRR-\d+|Índice Remissivo|ÍNDICE)")
# Cabeçalhos e rodapés de página que o pdftotext intercala no meio do verbete.
_LIXO = re.compile(
    r"^(?:[A-G]\s?-\s?\d{1,3}|\d{1,3}|Súmulas|SÚMULAS|SBDI\s*[-–]\s*I{1,2}|SDC|Transitória|"
    r"PRECEDENTES|NORMATIVOS|Precedentes Normativos|DE|do|Orientação Jurisprudencial"
    r"(?: da SBDI-I{1,2}(?: – Transitória)?| da SDC)?|Tribunal Superior do Trabalho|"
    r"Tribunal Pleno/Órgão Especial|Orientações Jurisprudenciais.*)$")
# Status de vigência, lido SÓ no título do verbete (antes da primeira linha de conteúdo):
# o corpo de um verbete vigente pode mencionar "súmula cancelada" de outro. "Incorporadas
# as OJs" (a súmula que absorveu) é vigente; "incorporada à OJ nº" (a absorvida) não é.
_MORTO = re.compile(r"cancelad[ao]|cancelamento mantido|convertid[ao]s? n[ao]s?\b|"
                    r"incorporad[ao]s? (?:à|ao|na|no)\b", re.I)


def _limpa(linhas: list[str]) -> str:
    out = []
    for l in linhas:
        s = l.strip()
        if s.startswith("Histórico:"):
            break                          # redação superada, regra do V6
        if not s or _LIXO.match(s):
            continue
        out.append(s)
    t = " ".join(out)
    t = re.sub(r"\s+", " ", t)
    # itens romanos voltam a abrir linha: "I - ...", "II. ..."
    t = re.sub(r"\s(?=(?:[IVX]{1,5})\s?[-–.]\s)", "\n", t)
    return t.strip()


def verbetes_tst(texto: str) -> list[dict]:
    """Um registro por verbete; cada verbete aparece várias vezes no PDF (corpo, índices),
    e vale a ocorrência mais longa, que é a do corpo.

    O índice remissivo do fim do volume é cortado ANTES: ali o mesmo rótulo `PN-54`
    encabeça uma lista de títulos em caixa baixa seguidos de "(cancelada)" repetido, que
    às vezes é mais longa que o verbete e era escolhida no lugar dele."""
    i = texto.find("ÍNDICE REMISSIVO")
    texto = texto[:i] if i > 0 else texto
    ocorr, cur = [], None
    for l in texto.split("\n"):
        s = l.strip()
        m = _CABECA.match(s)
        if m or _PARA.match(s):
            if cur:
                ocorr.append(cur)
            cur = [m.group(1), int(m.group(2)), [s]] if m else None
        elif cur:
            cur[2].append(l)
    if cur:
        ocorr.append(cur)
    melhor: dict = {}
    for tipo, n, linhas in ocorr:
        k = (tipo, n)
        if k not in melhor or sum(map(len, linhas)) > sum(map(len, melhor[k])):
            melhor[k] = linhas
    saida = []
    for (tipo, n), linhas in sorted(melhor.items()):
        # título = da cabeça até a primeira linha que termina a parêntese de status
        # (ou as 4 primeiras linhas); é aí que mora o "(cancelada)".
        cab = " ".join(x.strip() for x in linhas[:12])
        titulo = cab.split("Histórico:")[0][:700]
        # O status mora num PARÊNTESE logo após o título em caixa alta; procurar a
        # palavra solta pegava o corpo ("…Súmula cancelada…") e, com janela curta, perdia
        # o status de título longo, que quebra em seis ou sete linhas no PDF.
        status = " ".join(re.findall(r"\(([^()]*)\)", titulo))
        # "item I cancelado" mata o ITEM, não o verbete (Súmula 331, desde 2025): o
        # verbete fica e a linha do item cancelado sai do corpo.
        # Item cancelado mata o ITEM, não o verbete (Súmulas 6 e 331, desde 2025): o status
        # fala em "itens I, II, VI, alínea b, e item X cancelados", e é preciso tirar essas
        # menções antes de perguntar se o verbete inteiro morreu.
        st_vivo = re.sub(r"\b(?:ite(?:m|ns)|alíneas?)\s+[^()]*?cancelad[ao]s?", "", status, flags=re.I)
        st_vivo = re.sub(r"\bcancelad[ao]s? (?:o|os|a|as) (?:ite(?:m|ns)|alíneas?)\b[^()]*", "", st_vivo, flags=re.I)
        vigente = not _MORTO.search(st_vivo)
        corpo = _limpa(linhas)
        # E no corpo sai o item (linha que abre com numeral romano) marcado "(item
        # cancelado …)", e a alínea marcada "(alínea cancelada …)" até a sua nota.
        linhas_c = []
        for x in corpo.split("\n"):
            if re.match(r"^[IVX]{1,5}\s?[-–.]", x) and re.search(r"\(ite(?:m|ns)[^()]*cancelad", x, re.I):
                continue
            x = re.sub(r"\s[a-z]\)\s(?:(?![a-z]\)\s).)*?\(alínea cancelada[^)]*\)[^\n]*?(?=$|\s[a-z]\)\s)",
                       "", x)
            linhas_c.append(x)
        corpo = "\n".join(linhas_c)
        corpo = re.sub(rf"^{re.escape(tipo)}-{n}(?!\d)\s*", "", corpo)
        saida.append({"id": f"TST:{tipo}-{n}", "tipo": tipo, "numero": n,
                      "rotulo": f"{ROTULO[tipo]} nº {n} do TST", "vigente": vigente,
                      "texto": corpo})
    return saida


# ── TST: teses de IRR e IAC ───────────────────────────────────────────────────────────

_TEMA = re.compile(r"^(?:⃝\s*)?(IRR|IAC|RG) Tema:\s*0*(\d+)\s*$")


def teses_tst(texto: str) -> list[dict]:
    blocos, cur = [], None
    for l in texto.split("\n"):
        s = l.strip()
        m = _TEMA.match(s)
        # o sumário repete "IRR Tema: 82 ........ 20" — não casa por causa dos pontos
        if m:
            if cur:
                blocos.append(cur)
            cur = [m.group(1), int(m.group(2)), []]
        elif cur is not None:
            if re.match(r"^\d{1,2}\.\d?\s+[A-ZÁÉÍÓÚ]", s) or re.match(r"^\d{1,2}\. [A-Z]", s):
                blocos.append(cur)         # título de seção temática: fim do tema
                cur = None
                continue
            if not re.match(r"^\d{1,3}$", s):
                cur[2].append(s)
    if cur:
        blocos.append(cur)
    melhor: dict = {}
    for tipo, n, linhas in blocos:
        if tipo == "RG":
            continue                       # tese do STF: já está no corpus pela fonte do STF
        corpo = " ".join(linhas)
        mt = re.search(r"Título:\s*(.*?)(?=\s(?:Tese(?: Firmada)?:|Determinada|Observação|"
                       r"Transitado|Acórdão\.|Processo\(s\):)|$)", corpo)
        mtese = re.search(r"Tese(?: Firmada)?:\s*(.*?)(?=\s(?:Transitado em julgado|Observação"
                          r"|Determinada a suspensão|Processo\(s\):)|$)", corpo, re.I)
        if not mtese:
            continue                       # afetado, sem tese firmada
        reg = {"id": f"TST:{tipo}-{n}", "tipo": tipo, "numero": n,
               "rotulo": f"Tema {n} de {'IRR' if tipo == 'IRR' else 'IAC'} do TST",
               "vigente": True, "titulo": (mt.group(1).strip() if mt else ""),
               "texto": re.sub(r"\s+", " ", mtese.group(1)).strip()}
        k = (tipo, n)
        if k not in melhor or len(reg["texto"]) > len(melhor[k]["texto"]):
            melhor[k] = reg
    return [melhor[k] for k in sorted(melhor)]


# ── CARF ──────────────────────────────────────────────────────────────────────────────

def sumulas_carf(html_bruto: str) -> list[dict]:
    sys.path.insert(0, RAIZ)
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html_bruto, "html.parser")
    t = (s.find(id="content") or s).get_text("\n", strip=True)
    partes = re.split(r"\n(?=S[ÚU]MULA CARF N[ºo°]\s*\d+\s*\n)", t, flags=re.I)
    saida = {}
    for p in partes[1:]:
        m = re.match(r"S[ÚU]MULA CARF N[ºo°]\s*(\d+)\s*\n(.*)", p, re.S | re.I)
        if not m:
            continue
        n, resto = int(m.group(1)), m.group(2)
        resto = resto.split("Acórdãos Precedentes")[0]
        linhas = [x for x in resto.split("\n") if x.strip()]
        aprov = linhas[0] if linhas and linhas[0].startswith("Aprovada") else ""
        corpo = " ".join(linhas[1:] if aprov else linhas)
        corpo = re.sub(r"\s+([,.;)])", r"\1", re.sub(r"\(\s+", "(", corpo))
        corpo = re.sub(r"\s+", " ", corpo).strip()
        revogada = bool(re.search(r"S[úu]mula revogada", corpo, re.I))
        # "(Vinculante, conforme Portaria ...)" é metadado de efeito, não enunciado: vai
        # para campo próprio, e o enunciado fica limpo.
        vinc = re.search(r"\(\s*Vinculante.*?\)\.?", corpo)
        efeito_revogado = bool(re.search(r"(?:Caráter|Efeito) vinculante revogado", corpo, re.I))
        enunciado = re.sub(r"\(\s*(?:Vinculante|Caráter vinculante|Efeito vinculante|Súmula revogada).*$",
                           "", corpo).strip()
        saida[n] = {"id": f"CARF:SUM-{n}", "tipo": "SUM-CARF", "numero": n,
                    "rotulo": f"Súmula CARF nº {n}", "aprovacao": aprov,
                    "vinculante": bool(vinc) and not efeito_revogado,
                    "vigente": not revogada, "texto": enunciado}
    return [saida[k] for k in sorted(saida)]


def main() -> None:
    os.makedirs(os.path.join(TRAB, "raw"), exist_ok=True)
    os.makedirs(os.path.join(TRIB, "raw"), exist_ok=True)
    agora = datetime.datetime.now().isoformat(timespec="seconds")

    f1 = baixa(URL_LIVRO, os.path.join(TRAB, "raw/livro_sumulas_ojs_pns_tst.pdf"))
    vs = verbetes_tst(pdf_texto(os.path.join(RAIZ, f1["arquivo"])))
    f2 = baixa(URL_INDICE, os.path.join(TRAB, "raw/livro_precedentes_trabalhistas_v13112026.pdf"))
    ts = teses_tst(pdf_texto(os.path.join(RAIZ, f2["arquivo"])))
    f3 = baixa(URL_CARF, os.path.join(TRIB, "raw/carf_sumulas_consolidadas.html"))
    cs = sumulas_carf(open(os.path.join(RAIZ, f3["arquivo"]), encoding="utf-8").read())

    for nome, regs, fonte in [(os.path.join(TRAB, "tst_verbetes.jsonl"), vs, f1),
                              (os.path.join(TRAB, "tst_teses.jsonl"), ts, f2),
                              (os.path.join(TRIB, "carf_sumulas.jsonl"), cs, f3)]:
        with open(nome, "w", encoding="utf-8") as f:
            for r in regs:
                r.update({"fonte_url": fonte["url"], "fonte_sha256": fonte["sha256"],
                          "processado_em": agora})
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        viv = sum(r["vigente"] for r in regs)
        print(f"{os.path.relpath(nome, RAIZ)}: {len(regs)} registros, {viv} vigentes")
    import collections
    c = collections.Counter((r["tipo"], r["vigente"]) for r in vs)
    print("  TST por tipo (vigente):", sorted(c.items()))
    json.dump({"livro": f1, "indice": f2, "carf": f3},
              open(os.path.join(TRAB, "fontes.json"), "w"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
