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
from augmentation.connectors.lexml import texto_planalto, PLANALTO_BASE, HEADERS
import requests
from bs4 import BeautifulSoup


def texto_url(url: str) -> str:
    """Busca uma URL especifica do Planalto e devolve o texto limpo.

    Existe porque `texto_planalto` so conhece os padroes previsiveis
    (`/leis/L{numero}.htm`), e os diplomas mais antigos ou compilados moram fora deles:
    o Codigo Civil esta em `/leis/2002/L10406compilada.htm` e o Codigo Comercial em
    `/leis/LIM/LIM556.htm`. Foi por isso que os dois falharam na primeira passada.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if not r.ok:
            return ""
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        t = soup.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", t).strip()
    except Exception:
        return ""


# URLs fora do padrao previsivel, descobertas quando a primeira passada falhou.
URLS_ESPECIAIS = {
    "10406": [f"{PLANALTO_BASE}/leis/2002/L10406compilada.htm",
              f"{PLANALTO_BASE}/leis/2002/L10406.htm"],
    "556":   [f"{PLANALTO_BASE}/leis/LIM/LIM556.htm",
              f"{PLANALTO_BASE}/leis/LIM/LIM-556-1850.htm"],
    "8069":  [f"{PLANALTO_BASE}/leis/L8069.htm"],
}

SAIDA = os.path.join(RAIZ, "leis/recoleta_v2")
RELATORIO = os.path.join(RAIZ, "docs/RELATORIO_COLETA_V2.md")

# (rótulo, tipo, número, artigos esperados, o que havia antes)
ALVOS = [
    ("Código Civil",                    "lei", "10406",  2046, 57),
    ("Código Penal",                    "dl",  "2848",    361,  0),
    ("Estatuto da Criança e do Adolescente", "lei", "8069", 267,  9),
    ("Código Comercial",                "lei", "556",     913,  0),
]
# O separador de milhar importa: artigos acima de 999 se escrevem "Art. 1.045", e um
# regex que capture só `\d+` pega o "1" e colapsa os mil e tantos artigos finais num só.
# Foi o que fez o Codigo Civil aparecer com exatamente 1.000 artigos na primeira contagem.
RX_ART = re.compile(r"^\s*Art(?:igo)?\.?\s*([\d][\d.]*)", re.M)


def conta_artigos(texto: str) -> int:
    return len({m.group(1).replace(".", "").lstrip("0") or "0"
                for m in RX_ART.finditer(texto or "")})


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
    for rotulo, tipo, numero, esperado, antes in ALVOS:
        print(f"[{datetime.datetime.now():%H:%M}] baixando {rotulo} ({tipo} {numero})...", flush=True)
        t0 = time.time()
        try:
            texto = texto_planalto(tipo, numero) or ""
            if conta_artigos(texto) < 0.8 * esperado:
                for u in URLS_ESPECIAIS.get(numero, []):
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
        estado = ("ok" if esperado and n >= 0.8 * esperado else
                  "parcial" if n > antes else "falhou")
        if texto:
            caminho = os.path.join(SAIDA, f"{tipo}_{numero}.json")
            json.dump({"rotulo": rotulo, "tipo": tipo, "numero": numero,
                       "artigos": n, "esperado": esperado, "texto": texto},
                      open(caminho, "w", encoding="utf-8"), ensure_ascii=False)
        linhas.append({"rotulo": rotulo, "antes": antes, "artigos": n,
                       "esperado": esperado, "chars": len(texto), "estado": estado})
        print(f"    {n} artigos de {esperado} · {len(texto):,} chars · {estado} "
              f"({time.time()-t0:.0f}s)", flush=True)
        escreve_relatorio(linhas)
        time.sleep(1)
    print(f"\nrelatório: {os.path.relpath(RELATORIO, RAIZ)}")


if __name__ == "__main__":
    main()
