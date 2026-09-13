#!/usr/bin/env python3
"""
enunciados.py — Coleta enunciados jurisprudenciais e de jornadas.

São textos curtos que orientam a solução de casos, o formato que melhor casa com o
card: enunciado + fundamentação + aplicação. Quatro fontes:

  tst      Livro de Súmulas, Orientações Jurisprudenciais e Precedentes Normativos.
           Tribunal superior, e fecha a lacuna trabalhista — hoje o corpus não tem
           NADA de trabalhista, nem lei nem jurisprudência.
  cjf      Enunciados das Jornadas de Direito Civil e Processual Civil do CJF. É o que
           a banca cita logo depois da lei seca em civil e processo civil.
  fonaje   Enunciados dos Juizados Especiais (cíveis, criminais e fazenda pública).
  fppc     Enunciados do Fórum Permanente de Processualistas Civis. Doutrina
           processual — coletado a pedido, para decidir inclusão depois.

Saída: data/enunciados/raw/ + data/enunciados/manifest.jsonl (mesmo esquema de campos
do manifest de doutrina, com caminho ABSOLUTO).

Uso:
    python augmentation/crawlers/enunciados.py
    python augmentation/crawlers/enunciados.py --fonte tst
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import urllib.request
from html import unescape
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
DESTINO  = _ROOT / "data" / "enunciados" / "raw"
MANIFEST = _ROOT / "data" / "enunciados" / "manifest.jsonl"
UA = {"User-Agent": "Mozilla/5.0 (pesquisa academica USP; corpus juridico)"}

CJF = ("https://www.cjf.jus.br/cjf/corregedoria-da-justica-federal/"
       "centro-de-estudos-judiciarios-1/publicacoes-1/jornadas-cej/")

# (chave, fonte, título, url, licença)
ALVOS = [
    ("tst", "TST", "Livro de Súmulas, OJs e Precedentes Normativos do TST",
     "https://www.tst.jus.br/documents/10157/63003/LivroInternet+(6).pdf/"
     "778cc371-66ec-6b88-8310-fabd1504f0a5?t=1691685168350", "obra_publica_gov"),

    ("cjf", "CJF - Jornadas", "Enunciados aprovados — Jornadas de Direito Civil I, III, IV e V",
     CJF + "EnunciadosAprovados-Jornadas-1345.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Civil",
     CJF + "i-jornada-de-direito-civil.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "III Jornada de Direito Civil",
     CJF + "iii-jornada-de-direito-civil-1.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "V Jornada de Direito Civil (2012)",
     CJF + "vjornadadireitocivil2012.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "VI Jornada de Direito Civil (2013)",
     CJF + "vijornadadireitocivil2013-web.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "VII Jornada de Direito Civil (2015)",
     CJF + "vii-jornada-direito-civil-2015.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "VIII Jornada de Direito Civil (2018)",
     CJF + "viii-enunciados-publicacao-site-com-justificativa.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "IX Jornada de Direito Civil (2022)",
     CJF + "enunciados-aprovados-2022-vf.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "Jornadas de Direito Civil — volume I",
     CJF + "volume_i.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "Jornadas de Direito Civil — volume II",
     CJF + "volume_ii.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Processual Civil — enunciados aprovados",
     "https://www.cjf.jus.br/cjf/corregedoria-da-justica-federal/"
     "centro-de-estudos-judiciarios-1/publicacoes-1/i-jornada-de-direito-processual-civil/"
     "i-jornada-de-direito-processual-civil-enunciados-aprovados/@@download/arquivo",
     "obra_publica_gov"),

    # Demais Jornadas. As páginas de Administrativo/Tributário/Seguridade são objetos
    # Plone que não servem o arquivo na raiz — o arquivo fica em <pasta>/<filho>/@@download/arquivo.
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Comercial — livreto",
     CJF.replace("jornadas-cej/", "jornadas-de-direito-comercial/")
     + "livreto-i-jornada-de-direito-comercial.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "II Jornada de Direito Comercial — enunciados aprovados",
     CJF.replace("jornadas-cej/", "jornadas-de-direito-comercial/")
     + "enunciados_aprovados-referencia_legislativa-justificativa_ii_jornada.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "III Jornada de Direito Comercial — enunciados aprovados",
     CJF.replace("jornadas-cej/", "jornadas-de-direito-comercial/")
     + "enunciados-aprovados-iii-jdc-revisados-2.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Administrativo — 40 enunciados aprovados",
     "https://www.cjf.jus.br/cjf/noticias/2020/08-agosto/"
     "i-jornada-de-direito-administrativo-aprova-40-enunciados/Enunciados_Aprovados_IJDA.pdf",
     "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Tributário — enunciados aprovados",
     CJF.replace("jornadas-cej/", "jornada-de-direito-tributario/")
     + "direito-tributario/@@download/arquivo", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada de Direito Desportivo",
     CJF.replace("jornadas-cej/", "") + "i-jornada-de-direito-desportivo.pdf", "obra_publica_gov"),
    ("cjf", "CJF - Jornadas", "I Jornada da Justiça Federal pela Equidade Racial",
     CJF.replace("jornadas-cej/", "")
     + "i-jornada-da-justica-federal-pela-equidade-racial.pdf", "obra_publica_gov"),

    ("fonaje", "FONAJE", "Enunciados do FONAJE — e-book consolidado",
     "https://fonaje.amb.com.br/wp-content/uploads/2025/07/EbookEnunciadosFonaje_Fev2020.pdf",
     "enunciado_publico"),
    ("fonaje", "FONAJE", "Enunciados Cíveis do FONAJE",
     "https://fonaje.amb.com.br/enunciados/", "enunciado_publico"),
    ("fonaje", "FONAJE", "Enunciados Criminais do FONAJE",
     "https://fonaje.amb.com.br/enunciados-criminais/", "enunciado_publico"),
    ("fonaje", "FONAJE", "Enunciados da Fazenda Pública do FONAJE",
     "https://fonaje.amb.com.br/enunciados-da-fazenda-publica/", "enunciado_publico"),

    # NÃO usar diarioprocessual.com: o domínio foi sequestrado e serve spam de cassino
    # (baixamos e o "PDF de enunciados" veio como página de apostas em indonésio).
    # Fonte de terceiro precisa de conferência de conteúdo, não só de status 200.
    ("fppc", "FPPC", "FPPC — Carta de Florianópolis",
     "https://institutodc.com.br/wp-content/uploads/2017/06/FPPC-Carta-de-Florianopolis.pdf",
     "enunciado_publico"),
]


def texto_de_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head|nav|footer)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</h\d>", "\n", html)
    texto = unescape(re.sub(r"<[^>]+>", " ", html))
    texto = re.sub(r"[ \t\xa0]+", " ", texto)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", texto).strip()


def baixar(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180).read()


def main() -> None:
    ap = argparse.ArgumentParser(description="Coleta enunciados (TST, CJF, FONAJE, FPPC).")
    ap.add_argument("--fonte", default="todas", choices=["todas", "tst", "cjf", "fonaje", "fppc"])
    args = ap.parse_args()

    DESTINO.mkdir(parents=True, exist_ok=True)
    ja = set()
    if MANIFEST.exists():
        for l in MANIFEST.read_text("utf-8").splitlines():
            try:
                ja.add(json.loads(l)["url"])
            except Exception:
                pass

    novas, erros = [], 0
    for chave, fonte, titulo, url, licenca in ALVOS:
        if args.fonte != "todas" and chave != args.fonte:
            continue
        if url in ja:
            log.info(f"  (já coletado) {titulo[:60]}")
            continue
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", titulo.lower())[:70]
        try:
            dados = baixar(url)
            if dados.startswith(b"%PDF"):
                arquivo = DESTINO / f"{chave}_{slug}.pdf"
                arquivo.write_bytes(dados)
            else:
                texto = texto_de_html(dados.decode("utf-8", "replace"))
                if len(texto) < 2_000:
                    raise ValueError(f"conteúdo curto demais ({len(texto)} chars)")
                arquivo = DESTINO / f"{chave}_{slug}.txt"
                arquivo.write_text(texto, "utf-8")
            log.info(f"  ✓ {titulo[:58]:58s} {len(dados)/1024:8.0f} KB")
        except Exception as e:
            erros += 1
            log.error(f"  ✗ {titulo[:58]}: {str(e)[:70]}")
            continue
        novas.append({
            "fonte": fonte, "categoria": "Enunciado", "titulo": titulo,
            "autor": fonte, "ano": "", "area": "Direito", "licenca": licenca,
            "url": url, "caminho": str(arquivo), "n_chars_aprox": len(dados),
        })

    if novas:
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST, "a", encoding="utf-8") as f:
            for d in novas:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
    log.info(f"✓ {len(novas)} documentos novos · {erros} erros → {MANIFEST}")


if __name__ == "__main__":
    main()
