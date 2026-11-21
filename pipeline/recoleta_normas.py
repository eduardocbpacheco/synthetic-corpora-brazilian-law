#!/usr/bin/env python3
"""
recoleta_normas.py — recoleta os diplomas que chegaram truncados do Planalto.

Quatro códigos entraram no corpus incompletos ou vazios porque a extração parou cedo. O
texto de origem em `leis/codigos_especificos.parquet` já chega truncado, então reprocessar
não resolve: é preciso baixar de novo.

  Código Civil        26.278 chars na fonte · 57 de 2.046 artigos
  Código Penal           617 chars · zero artigos, para na promulgação
  ECA                  9.565 chars · 9 de 267 artigos
  Código Comercial       277 chars · zero artigos

O script NÃO sobrescreve nada do corpus atual. Grava em `leis/recoleta_v2/` e escreve um
relatório de progresso em `docs/RELATORIO_COLETA_V2.md`, atualizado a cada diploma, para
poder ser lido enquanto roda.

A verificação é a mesma que revelou o defeito: contar artigos distintos no texto baixado e
comparar com o número conhecido de artigos do diploma. Um download que traga menos de 80%
é reportado como falha, não como sucesso.

Uso:  juridico-env/bin/python pipeline/recoleta_normas.py
"""
from __future__ import annotations
import json, os, re, sys, time, datetime

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
from augmentation.connectors.lexml import (texto_planalto, texto_de_resposta,
                                           PLANALTO_BASE, HEADERS)
import requests
from bs4 import BeautifulSoup


def texto_url(url: str) -> str:
    """Busca uma URL especifica do Planalto e devolve o texto limpo.

    Existe porque `texto_planalto` so conhece os padroes previsiveis
    (`/leis/L{numero}.htm`), e os diplomas mais antigos ou compilados moram fora deles:
    o Codigo Civil esta em `/leis/2002/L10406compilada.htm` e o Codigo Comercial em
    `/leis/LIM/LIM556.htm`. Foi por isso que os dois falharam na primeira passada.

    A limpeza NAO mora mais aqui. Ela era uma copia da que existe em `texto_planalto`, e
    as duas carregavam os mesmos dois defeitos — `apparent_encoding` adivinhando cp1250
    (A7) e `get_text` achatando o riscado (V6). Consertar uma e esquecer a outra e o
    padrao que o N8 registrou: duas implementacoes da mesma tarefa, so uma verificada.
    Agora ha uma so, `lexml.texto_de_resposta`.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        return texto_de_resposta(r) if r.ok else ""
    except Exception:
        return ""


# URLs fora do padrao previsivel, descobertas quando a primeira passada falhou.
URLS_ESPECIAIS = {
    "10406": [f"{PLANALTO_BASE}/leis/2002/L10406compilada.htm",
              f"{PLANALTO_BASE}/leis/2002/L10406.htm"],
    "556":   [f"{PLANALTO_BASE}/leis/LIM/LIM556.htm",
              f"{PLANALTO_BASE}/leis/LIM/LIM-556-1850.htm"],
    "8069":  [f"{PLANALTO_BASE}/leis/L8069.htm"],
    # `texto_planalto` nao conhece o tipo "decreto"; o RPS entra pela URL direta.
    "3048":  [f"{PLANALTO_BASE}/decreto/d3048.htm",
              f"{PLANALTO_BASE}/decreto/D3048compilado.htm"],
    # V6 · sete diplomas em que `/leis/L{n}.htm` da 404. As URLs abaixo foram SONDADAS uma
    # a uma, nao deduzidas: o Planalto usa tres esquemas conviventes — `L{n}compilada.htm`
    # para os anteriores a 1990, `L{n}cons.htm` para a faixa seguinte, e
    # `_ato{periodo}/{ano}/lei/l{n}.htm` a partir de 2004, com o nome do arquivo em
    # minuscula. Ainda ha `L8112compilado.htm` ao lado de `L8112cons.htm`, com 343 kB
    # contra 563 kB: fica o `cons`, que e o que traz o historico riscado.
    "6015":  [f"{PLANALTO_BASE}/leis/L6015compilada.htm"],
    "6404":  [f"{PLANALTO_BASE}/leis/L6404compilada.htm"],
    "8112":  [f"{PLANALTO_BASE}/leis/L8112cons.htm"],
    "8213":  [f"{PLANALTO_BASE}/leis/L8213cons.htm"],
    "8212":  [f"{PLANALTO_BASE}/leis/L8212cons.htm"],
    "11977": [f"{PLANALTO_BASE}/_ato2007-2010/2009/lei/l11977.htm"],
    "12546": [f"{PLANALTO_BASE}/_ato2011-2014/2011/lei/l12546.htm"],
}

def urls_candidatas(tipo: str, numero: str, ano: str = "") -> list[str]:
    """A escada de URLs do Planalto, em ordem de preferencia.

    Nasceu de sondagem, nao de deducao: sete diplomas davam 404 no padrao `/leis/L{n}.htm`
    e cada URL boa teve de ser descoberta a mao. O Planalto usa TRES esquemas conviventes,
    e a diferenca entre eles nao e o tipo da norma, e a EPOCA:

      · `/leis/L{n}compilada.htm` — anteriores a 1990 (Registros Publicos, S/A);
      · `/leis/L{n}cons.htm`      — faixa seguinte (Estatuto do Servidor, LBPS, CUSTEIO);
      · `/_ato{periodo}/{ano}/lei/l{n}.htm` — a partir de 2004, com o arquivo em MINUSCULA.

    As versoes `compilada`/`cons` vem primeiro de proposito: sao as que trazem o historico
    riscado, que e o que o V6 precisa. Onde as duas existem, fica a maior — o Estatuto do
    Servidor tem `L8112compilado.htm` com 343 kB ao lado de `L8112cons.htm` com 563 kB.
    """
    n, a = str(numero), str(ano or "")
    tipo = (tipo or "lei").lower()
    fora = []
    if tipo in ("lc", "lei_complementar"):
        fora += [f"{PLANALTO_BASE}/leis/lcp/Lcp{n}.htm"]
    elif tipo in ("dl", "decreto_lei"):
        fora += [f"{PLANALTO_BASE}/decreto-lei/Del{n}.htm",
                 f"{PLANALTO_BASE}/decreto-lei/Del{n}compilado.htm"]
    elif tipo in ("d", "decreto"):
        fora += [f"{PLANALTO_BASE}/decreto/D{n}compilado.htm",
                 f"{PLANALTO_BASE}/decreto/d{n}.htm",
                 f"{PLANALTO_BASE}/decreto/D{n}.htm",
                 f"{PLANALTO_BASE}/decreto-lei/Del{n}.htm"]
    else:
        fora += [f"{PLANALTO_BASE}/leis/L{n}compilada.htm",
                 f"{PLANALTO_BASE}/leis/L{n}compilado.htm",
                 f"{PLANALTO_BASE}/leis/L{n}cons.htm",
                 f"{PLANALTO_BASE}/leis/L{n}.htm"]
        # Quarto esquema, descoberto quando a Lei 10.522/2002 falhou em todos os outros:
        # a faixa 1999-2003 mora em pasta por ANO, antes de as pastas `_ato` existirem. E
        # a mesma forma do Codigo Civil, `/leis/2002/L10406compilada.htm`, que ja estava em
        # URLS_ESPECIAIS sem que eu tivesse reparado que era um PADRAO e nao uma excecao.
        if a.isdigit() and 1999 <= int(a) <= 2003:
            fora += [f"{PLANALTO_BASE}/leis/{a}/L{n}compilada.htm",
                     f"{PLANALTO_BASE}/leis/{a}/L{n}.htm"]
    # As pastas `_ato` NAO sao blocos uniformes de quatro anos: a primeira cobre tres
    # (2004-2006) e as seguintes quatro. Calcular por divisao produzia `_ato2004-2007`,
    # que nao existe. A lista vai explicita porque foi lida do site, nao deduzida.
    PERIODOS = [(2004, 2006), (2007, 2010), (2011, 2014),
                (2015, 2018), (2019, 2022), (2023, 2026)]
    if a.isdigit() and int(a) >= 2004:
        per = next((f"_ato{x}-{y}" for x, y in PERIODOS if x <= int(a) <= y), "")
        sub = {"lc": "lcp", "d": "decreto", "decreto": "decreto"}.get(tipo, "lei")
        pre = {"lc": "lcp", "d": "d", "decreto": "d"}.get(tipo, "l")
        if per:
            fora += [f"{PLANALTO_BASE}/{per}/{a}/{sub}/{pre}{n}.htm"]
    return fora


SAIDA = os.path.join(RAIZ, "leis/recoleta_v2")
RELATORIO = os.path.join(RAIZ, "docs/RELATORIO_COLETA_V2.md")

# (rotulo, tipo, numero, ano, artigos esperados, o que havia antes)
# O ANO entrou na tupla por causa do V6: as URLs do Planalto a partir de 2004 moram em
# pasta por periodo (`_ato2011-2014/2011/lei/l12546.htm`) e sem o ano nao ha como monta-las.
ALVOS = [
    # Primeira leva, Q3/A1: diplomas TRUNCADOS na coleta antiga.
    ("Código Civil",                     "lei", "10406", "2002", 2046,  57),
    ("Código Penal",                     "dl",  "2848",  "1940",  361,   0),
    ("Estatuto da Criança e do Adolescente", "lei", "8069", "1990", 267,  9),
    ("Código Comercial",                 "lei", "556",   "1850",  913,   0),
    # Segunda leva, V6. Nao entram por estarem truncados — entram porque a coleta antiga
    # ACHATAVA o riscado, e sao os diplomas em que mais texto de redacao superada convive
    # com a vigente. O `esperado` de cada um e o que o corpus JA tem, medido, e nao um
    # numero de fora: aqui o guarda de 80% pergunta "a pagina veio inteira?".
    ("CLT",                              "dl",  "5452",  "1943",  922, 922),
    ("RPS Previdência",                  "d",   "3048",  "1999",  382, 382),
    ("Lei Registros Públicos",           "lei", "6015",  "1973",  307, 307),
    ("S/A",                              "lei", "6404",  "1976",  299, 299),
    ("Estatuto Servidor",                "lei", "8112",  "1990",  251, 251),
    ("LBPS",                             "lei", "8213",  "1991",  156, 156),
    ("CUSTEIO Previdência",              "lei", "8212",  "1991",  105, 105),
    ("Simples Nacional ME EPP",          "lc",  "123",   "2006",   89,  89),
    ("IRPJ/CSLL",                        "lei", "9430",  "1996",   88,  88),
    ("Minha Casa Minha Vida",            "lei", "11977", "2009",   83,  83),
    ("Desoneração Folha",                "lei", "12546", "2011",   52,  52),
    # Terceira leva, V6: os federais que restavam entre os 18 com mais repeticao. Os tres
    # paulistas da mesma lista ficam de fora — sao da ALESP, outra fonte, outro crawler.
    ("Lei de Falências",                 "lei", "11101", "2005",  201, 201),
    ("Bens Imóveis da União",            "d",   "9760",  "1946",  197, 197),
    ("Licitações",                       "lei", "8666",  "1993",  126, 126),
    ("Condomínios Incorporações",        "lei", "4591",  "1964",   70,  70),
    ("Sistema Financeiro Nacional",      "lei", "4595",  "1964",   65,  65),
    ("IRPF",                             "lei", "7713",  "1988",   58,  58),
    ("Alienação Fiduciária",             "lei", "9514",  "1997",   42,  42),
    ("LOAS",                             "lei", "8742",  "1993",   42,  42),
    ("Planos de Saúde",                  "lei", "9656",  "1998",   36,  36),
    ("ICMS Kandir",                      "lc",  "87",    "1996",   36,  36),
    ("Cadastro Dívida Ativa",            "lei", "10522", "2002",   40,  40),
    ("Improbidade Administrativa",       "lei", "8429",  "1992",   25,  25),
    ("PIS/COFINS Base",                  "lei", "9718",  "1998",   18,  18),
    ("PNMA",                             "lei", "6938",  "1981",   17,  17),
]
# O separador de milhar importa: artigos acima de 999 se escrevem "Art. 1.045", e um
# regex que capture só `\d+` pega o "1" e colapsa os mil e tantos artigos finais num só.
# Foi o que fez o Codigo Civil aparecer com exatamente 1.000 artigos na primeira contagem.
RX_ART = re.compile(r"^\s*Art(?:igo)?\.?\s*([\d][\d.]*)", re.M)


def conta_artigos(texto: str, so_vigentes: bool = False) -> int:
    """Artigos distintos do texto.

    O criterio de aceitacao pergunta "baixei a pagina inteira?", e nao "quantos artigos
    seguem em vigor" — sao perguntas diferentes e a segunda nao serve de guarda contra
    truncamento. Por isso a contagem padrao IGNORA a marca `<revogado>`: sem isso o Codigo
    Comercial cairia de 913 para 478 artigos so por a fonte passar a ser lida direito, e o
    guarda de 80% acusaria truncamento onde houve conserto. Os 478 sao verdade e valem ser
    relatados — o de 1850 teve a Parte Primeira revogada pelo Codigo Civil de 2002 —, mas
    pela chamada com `so_vigentes`.
    """
    t = texto or ""
    if not so_vigentes:
        t = re.sub(r"</?revogado>", "", t)
    else:
        t = re.sub(r"<revogado>.*?</revogado>", " ", t, flags=re.S)
    return len({m.group(1).replace(".", "").lstrip("0") or "0"
                for m in RX_ART.finditer(t)})


def escreve_relatorio(linhas: list[dict]) -> None:
    ok = sum(1 for x in linhas if x["estado"] == "ok")
    md = [
        "# Relatório de coleta — corpus v2", "",
        f"Atualizado em {datetime.datetime.now():%d/%m/%Y %H:%M}. Gerado por "
        "`pipeline/recoleta_normas.py`, atualizado a cada diploma enquanto roda.", "",
        "Nada aqui sobrescreve o corpus atual: a saída vai para `leis/recoleta_v2/`.", "",
        f"**{ok} de {len(ALVOS)} diplomas recoletados com sucesso.**", "",
        "## Normas", "",
        "| diploma | artigos antes | artigos agora | esperado | cobertura | chars | estado |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for x in linhas:
        cob = f"{100*x['artigos']/x['esperado']:.0f}%" if x["esperado"] else "—"
        md.append(f"| {x['rotulo']} | {x['antes']} | **{x['artigos']}** | {x['esperado']} | "
                  f"{cob} | {x['chars']:,} | {x['estado']} |")
    md += ["", "## Critério de aceitação", "",
           "Um download só conta como bom se trouxer **80% ou mais** dos artigos conhecidos do",
           "diploma. Foi exatamente essa contagem que revelou o defeito original: os arquivos",
           "antigos existiam, tinham tamanho plausível e estavam truncados.", "",
           "## O que ainda falta baixar", "",
           "Ver `docs/PLANO_COLETA_V2.md`. Em ordem: ementa dos 2.309 acórdãos do STF que já têm",
           "inteiro teor, Constituição do Estado de São Paulo, inteiro teor do controle",
           "concentrado do STF (4.046), acórdãos do STJ (4.102), informativo do STF, e os",
           "enunciados numerados de CJF, FONAJE e FPPC.", ""]
    os.makedirs(os.path.dirname(RELATORIO), exist_ok=True)
    open(RELATORIO, "w", encoding="utf-8").write("\n".join(md))


def main() -> None:
    os.makedirs(SAIDA, exist_ok=True)
    linhas = []
    for rotulo, tipo, numero, ano, esperado, antes in ALVOS:
        print(f"[{datetime.datetime.now():%H:%M}] baixando {rotulo} ({tipo} {numero})...", flush=True)
        t0 = time.time()
        try:
            texto = texto_planalto(tipo, numero) or ""
            if conta_artigos(texto) < 0.8 * esperado:
                # Pausa ENTRE as tentativas, e nao so entre diplomas: a escada pode ter
                # seis URLs e 29 diplomas, e sem isso a recoleta dispara uma centena de
                # requisicoes sem intervalo nenhum.
                for u in URLS_ESPECIAIS.get(numero, []) + urls_candidatas(tipo, numero, ano):
                    time.sleep(2)
                    alt = texto_url(u)
                    if conta_artigos(alt) > conta_artigos(texto):
                        texto = alt
                        print(f"    via URL especial: {u}", flush=True)
                    if conta_artigos(texto) >= 0.8 * esperado:
                        break
        except Exception as e:
            texto = ""
            print(f"    erro: {type(e).__name__}: {e}", flush=True)
        n = conta_artigos(texto)
        n_vig = conta_artigos(texto, so_vigentes=True)
        estado = ("ok" if esperado and n >= 0.8 * esperado else
                  "parcial" if n > antes else "falhou")
        if texto:
            caminho = os.path.join(SAIDA, f"{tipo}_{numero}.json")
            json.dump({"rotulo": rotulo, "tipo": tipo, "numero": numero,
                       "artigos": n, "artigos_vigentes": n_vig,
                       "esperado": esperado, "texto": texto},
                      open(caminho, "w", encoding="utf-8"), ensure_ascii=False)
        linhas.append({"rotulo": rotulo, "antes": antes, "artigos": n,
                       "esperado": esperado, "chars": len(texto), "estado": estado})
        print(f"    {n} artigos de {esperado} · {len(texto):,} chars · {estado} "
              f"({time.time()-t0:.0f}s)", flush=True)
        escreve_relatorio(linhas)
        time.sleep(2)
    print(f"\nrelatório: {os.path.relpath(RELATORIO, RAIZ)}")


if __name__ == "__main__":
    main()
