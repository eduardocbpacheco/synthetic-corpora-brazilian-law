#!/usr/bin/env python3
"""
recoleta_v3.py — coleta os diplomas que os gabaritos citam e que o corpus nunca teve.

Etapa 2 da réplica (corpus v3). A auditoria de 14/11/2026 cruzou as citações dos gabaritos
da OAB com o que está nos dois braços congelados e achou 32 diplomas citados que NUNCA
foram coletados. A causa é de seleção, não de coleta: `leis/leis_federais.jsonl` foi
montado por `refs_casos` — quantas vezes o diploma aparece nos acórdãos —, e lei de ação
popular, de ADPF, de habeas data ou a LINDB quase não aparecem em acórdão do TJSP, mas
caem na prova toda edição.

Mesma escada de URLs de `recoleta_normas.py` (Planalto), e a mesma limpeza
(`lexml.texto_de_resposta`, que preserva o riscado como `<revogado>` e não adivinha a
codificação — ver A7). O que muda é o alvo e o destino: grava em `leis/recoleta_v3/`,
NUNCA em `recoleta_v2/` nem em `leis_federais.jsonl`, que alimentam o v4 de outras pessoas.

Cada arquivo leva URL de origem, data/hora da coleta e sha256 do texto, porque o artigo vai
precisar dizer DE ONDE e DE QUANDO veio cada diploma.

Também recoleta três que estavam lá com defeito:
  · Lei 10.826/2003 (Desarmamento): truncada, 2 de 37 artigos — item que a auditoria deixou
    "ainda aberto";
  · Lei 10.741/2003 (Idoso): a cópia de `recoleta_v2` veio da Câmara, PUBLICAÇÃO ORIGINAL de
    2003 — sem as 20 alterações posteriores, inclusive a que mudou o nome para "pessoa idosa";
  · LUG (Dec. 57.663/1966): o arquivo antigo é só o decreto promulgador. A lei uniforme mora
    no ANEXO I, que escreve "Artigo 1º" por extenso, e o divisor só lia "Art.".

Uso:  juridico-env/bin/python pipeline/recoleta_v3.py [--so CHAVE ...]
"""
from __future__ import annotations
import argparse, datetime, hashlib, json, os, re, sys, time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pipeline"))
from recoleta_normas import texto_url, urls_candidatas, conta_artigos   # noqa: E402
from augmentation.connectors.lexml import PLANALTO_BASE                 # noqa: E402

SAIDA = os.path.join(RAIZ, "leis/recoleta_v3")
P = PLANALTO_BASE

# (chave, rótulo, tipo, número, ano, artigos esperados, URLs sondadas antes da escada)
# O `esperado` é o maior número de artigo do diploma (contando revogados): o guarda de 80%
# pergunta "a página veio inteira?", como em recoleta_normas.
ALVOS = [
    ("L4717",  "Ação Popular",                       "lei", "4717",  "1965",  22, []),
    ("L9882",  "ADPF",                               "lei", "9882",  "1999",  14, []),
    ("L13300", "Mandado de Injunção",                "lei", "13300", "2016",  15, []),
    ("L11417", "Súmula Vinculante",                  "lei", "11417", "2006",  11, []),
    ("L9507",  "Habeas Data",                        "lei", "9507",  "1997",  23, []),
    # A LINDB é o DL 4.657/1942. O que o corpus chamava de LINDB era a LC 107/2001, que é
    # a lei sobre ELABORAÇÃO das leis (altera a LC 95) — o rótulo estava trocado.
    ("LINDB",  "LINDB (Lei de Introdução às normas do Direito Brasileiro)", "dl", "4657", "1942", 19,
     [f"{P}/decreto-lei/Del4657compilado.htm", f"{P}/decreto-lei/Del4657.htm"]),
    ("L12846", "Lei Anticorrupção",                  "lei", "12846", "2013",  31, []),
    ("L13303", "Lei das Estatais",                   "lei", "13303", "2016",  97, []),
    ("L13019", "Marco Regulatório das OSC (MROSC)",  "lei", "13019", "2014",  88, []),
    ("L11079", "Parcerias Público-Privadas",         "lei", "11079", "2004",  30, []),
    ("L11107", "Consórcios Públicos",                "lei", "11107", "2005",  20, []),
    ("L10257", "Estatuto da Cidade",                 "lei", "10257", "2001",  58,
     [f"{P}/leis/LEIS_2001/L10257.htm", f"{P}/leis/leis_2001/l10257.htm"]),
    # Decreto do Poder Legislativo de 1908: não é "decreto" do Executivo e mora em
    # `/decreto/historicos/dpl/`.
    ("D2044",  "Letra de Câmbio e Nota Promissória (Dec. 2.044/1908)", "d", "2044", "1908", 57,
     [f"{P}/decreto/historicos/dpl/DPL2044-1908.htm", f"{P}/decreto/historicos/dpl/dpl2044.htm"]),
    ("L8934",  "Registro Público de Empresas Mercantis", "lei", "8934", "1994", 67, []),
    ("L4886",  "Representantes Comerciais Autônomos", "lei", "4886", "1965",  47, []),
    ("L5478",  "Lei de Alimentos",                   "lei", "5478",  "1968",  29, []),
    ("L12850", "Organização Criminosa",              "lei", "12850", "2013",  27, []),
    ("L9296",  "Interceptação Telefônica",           "lei", "9296",  "1996",  12, []),
    ("L13869", "Abuso de Autoridade",                "lei", "13869", "2019",  45, []),
    ("L8137",  "Crimes contra a Ordem Tributária",   "lei", "8137",  "1990",  23, []),
    ("L9613",  "Lavagem de Dinheiro",                "lei", "9613",  "1998",  18, []),
    ("L9605",  "Crimes Ambientais",                  "lei", "9605",  "1998",  82, []),
    ("L8036",  "FGTS",                               "lei", "8036",  "1990",  32,
     [f"{P}/leis/L8036consol.htm"]),
    ("L5584",  "Normas de Direito Processual do Trabalho", "lei", "5584", "1970", 21, []),
    ("L7783",  "Lei de Greve",                       "lei", "7783",  "1989",  19, []),
    ("LC150",  "Empregado Doméstico",                "lc",  "150",   "2015",  47, []),
    ("L6019",  "Trabalho Temporário e Terceirização", "lei", "6019", "1974",  20, []),
    # Lei 605/1949: no Planalto o arquivo leva zero à esquerda.
    ("L605",   "Repouso Semanal Remunerado",         "lei", "605",   "1949",  16,
     [f"{P}/leis/l0605.htm", f"{P}/leis/L0605.htm"]),
    ("L8397",  "Medida Cautelar Fiscal",             "lei", "8397",  "1992",  30, []),
    ("LC24",   "Convênios de ICMS",                  "lc",  "24",    "1975",  15, []),
    ("LC214",  "IBS, CBS e Imposto Seletivo (reforma tributária)", "lc", "214", "2025", 544, []),
    # Recoletas de diplomas que já existiam com defeito (ver docstring).
    ("L10826", "Estatuto do Desarmamento",           "lei", "10826", "2003",  37,
     [f"{P}/leis/2003/L10.826compilado.htm", f"{P}/leis/2003/l10.826.htm"]),
    ("L10741", "Estatuto da Pessoa Idosa",           "lei", "10741", "2003", 118,
     [f"{P}/leis/2003/L10.741compilado.htm", f"{P}/leis/2003/l10.741.htm"]),
    ("D57663", "Lei Uniforme de Genebra (Letra de Câmbio e Nota Promissória)", "d", "57663", "1966", 78,
     [f"{P}/decreto/antigos/d57663.htm", f"{P}/decreto/1950-1969/D57663.htm"]),
    ("L7357",  "Lei do Cheque",                      "lei", "7357",  "1985",  71, []),
    ("L5474",  "Lei das Duplicatas",                 "lei", "5474",  "1968",  28, []),
]

# "Art . 36" (com espaço antes do ponto) e "Artigo 1º" por extenso: as duas formas que o
# contador de recoleta_normas não lê. Cheque, Duplicata e o Anexo I da LUG usam uma delas,
# e sem isto o guarda de 80% reprovaria página boa como truncada.
RX_ART_LARGO = re.compile(r"^\s*Art(?:igo)?\s*\.?\s*(\d{1,2}(?:\.\d{3})|\d{1,4})", re.M)


def conta(texto: str) -> int:
    t = re.sub(r"</?revogado>", "", texto or "")
    return max(conta_artigos(texto or ""),
               len({m.group(1).replace(".", "").lstrip("0") for m in RX_ART_LARGO.finditer(t)}))


def coleta(alvo) -> dict:
    chave, rotulo, tipo, numero, ano, esperado, especiais = alvo
    melhor, url_melhor = "", ""
    vistos = set()
    for u in especiais + urls_candidatas(tipo, numero, ano):
        if u in vistos:
            continue
        vistos.add(u)
        time.sleep(2)            # pausa por requisição, não por diploma (ver recoleta_normas)
        t = texto_url(u)
        if conta(t) > conta(melhor):
            melhor, url_melhor = t, u
        if conta(melhor) >= 0.8 * esperado:
            break
    n = conta(melhor)
    estado = "ok" if n >= 0.8 * esperado else ("parcial" if n else "falhou")
    return {"chave": chave, "rotulo": rotulo, "tipo": tipo, "numero": numero, "ano": ano,
            "lei": f"{ {'lei': 'Lei', 'lc': 'LC', 'dl': 'Decreto-Lei', 'd': 'Decreto'}[tipo] } "
                   f"{int(numero):,}/{ano}".replace(",", ".").strip(),
            "url": url_melhor, "coletado_em": datetime.datetime.now().isoformat(timespec="seconds"),
            "artigos": n, "esperado": esperado, "estado": estado,
            "sha256": hashlib.sha256(melhor.encode()).hexdigest(), "texto": melhor}


URL_CED = "https://www.oab.org.br/publicacoes/AbrirPDF?LivroId=0000004085"


def coleta_ced() -> dict:
    """Código de Ética e Disciplina da OAB (Res. CFOAB 02/2015), o 80º diploma da lista.

    Não está no Planalto: é norma do Conselho Federal. O PDF vem do link que a própria
    página "Código de Ética e Disciplina (CED)" do portal da OAB publica, em
    `/publicacoes/AbrirPDF` — caminho que o robots.txt da OAB NÃO veda (vedados são
    `/arquivos/` e `/Content/`, por isso não usei o PDF do Regulamento Geral).

    O texto começa no ANEXO ÚNICO: a Resolução que aprova o código tem os seus próprios
    arts. 1º e 2º, e deixá-los colaria dois "Art. 1º" de normas diferentes no mesmo
    diploma — o divisor ficaria com o mais longo e o do código poderia sumir.
    """
    import subprocess, tempfile, requests
    from augmentation.connectors.lexml import HEADERS
    r = requests.get(URL_CED, headers=HEADERS, timeout=60)
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "ced.pdf")
        open(pdf, "wb").write(r.content)
        os.makedirs(os.path.join(SAIDA, "raw"), exist_ok=True)
        open(os.path.join(SAIDA, "raw", "ced_oab.pdf"), "wb").write(r.content)
        txt = subprocess.run(["pdftotext", pdf, "-"], capture_output=True, text=True).stdout
    i = txt.find("ANEXO ÚNICO")
    txt = txt[i:] if i >= 0 else txt
    # cabeçalho corrido de página e número de página soltos
    txt = re.sub(r"\n\s*CÓDIGO DE ÉTICA E DISCIPLINA – Resolução n\. 02/2015\s*\n", "\n", txt)
    txt = re.sub(r"\n\s*\d{1,2}\s*\n", "\n", txt)
    n = conta(txt)
    return {"chave": "CED-OAB", "rotulo": "Código de Ética e Disciplina da OAB",
            "tipo": "res", "numero": "2", "ano": "2015", "lei": "Resolução CFOAB 02/2015",
            "url": URL_CED, "coletado_em": datetime.datetime.now().isoformat(timespec="seconds"),
            "artigos": n, "esperado": 80, "estado": "ok" if n >= 64 else "parcial",
            "sha256": hashlib.sha256(txt.encode()).hexdigest(), "texto": txt.strip()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so", nargs="*", help="só estas chaves")
    ap.add_argument("--refaz", action="store_true", help="recoleta mesmo o que já existe")
    a = ap.parse_args()
    os.makedirs(SAIDA, exist_ok=True)
    for alvo in ALVOS:
        if a.so and alvo[0] not in a.so:
            continue
        cam = os.path.join(SAIDA, f"{alvo[0]}.json")
        if os.path.exists(cam) and not a.refaz:
            r = json.load(open(cam, encoding="utf-8"))
            if r.get("estado") == "ok":
                print(f"  {alvo[0]:7} já coletado ({r['artigos']} artigos)")
                continue
        r = coleta(alvo)
        json.dump(r, open(cam, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {alvo[0]:7} {r['artigos']:>4}/{r['esperado']:<4} {r['estado']:8} "
              f"{len(r['texto']):>8,} chars  {r['url']}", flush=True)
    if not a.so or "CED-OAB" in a.so:
        cam = os.path.join(SAIDA, "CED-OAB.json")
        if a.refaz or not os.path.exists(cam):
            r = coleta_ced()
            json.dump(r, open(cam, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  CED-OAB {r['artigos']:>4}/80   {r['estado']}", flush=True)


if __name__ == "__main__":
    main()
