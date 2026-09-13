#!/usr/bin/env python3
"""
stf_acordaos.py — Crawler de acórdãos do STF via Playwright (headless browser).

O STF usa AWS WAF com challenge JavaScript — requests simples retornam 202 vazio.
Solução: Playwright com browser real headless.

Fontes:
  - jurisprudencia.stf.jus.br  (busca geral, requer JS)
  - Portal STF processos        (por classe processual)
  - controle_concentrado.jsonl  (já temos — usa como seed para busca de texto completo)

O que captura:
  - Acórdãos RE, ARE (repercussão geral)
  - ADI, ADPF, ADC (controle concentrado)
  - HC, RHC (liberdade)
  - MS, Rcl (mandamental/reclamação)

Saída: decisoes/stf/stf_acordaos.jsonl

Instalação:
    pip install playwright
    playwright install chromium

Uso:
    python augmentation/crawlers/stf_acordaos.py --limite 100
    python augmentation/crawlers/stf_acordaos.py --classe RE --limite 200
    python augmentation/crawlers/stf_acordaos.py --classe ADI --limite 500
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = _ROOT / "decisoes" / "stf"
OUTPUT     = OUTPUT_DIR / "stf_acordaos.jsonl"
STATE_FILE = OUTPUT_DIR / "stf_crawler_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DELAY = 2.0

# Classes processuais e volume estimado no STF
CLASSES_STF = {
    "RE":   "Recurso Extraordinário",
    "ARE":  "Agravo em Recurso Extraordinário",
    "ADI":  "Ação Direta de Inconstitucionalidade",
    "ADPF": "Arguição de Descumprimento de Preceito Fundamental",
    "ADC":  "Ação Declaratória de Constitucionalidade",
    "HC":   "Habeas Corpus",
    "MS":   "Mandado de Segurança",
    "Rcl":  "Reclamação",
    "AP":   "Ação Penal",
}


def verificar_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


def instalar_playwright():
    import subprocess
    log.info("Instalando Playwright...")
    subprocess.run(["pip", "install", "playwright", "-q"], check=True)
    subprocess.run(["playwright", "install", "chromium"], check=True)
    log.info("Playwright instalado.")


def carregar_estado() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"paginas_processadas": [], "processos_salvos": [], "total": 0}


def salvar_estado(estado: dict) -> None:
    STATE_FILE.write_text(json.dumps(estado, indent=2, ensure_ascii=False))


def parse_acordao_stf(html: str, classe: str, numero: str) -> dict | None:
    """Extrai campos de um acórdão STF a partir do HTML da página."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # Remove elementos de navegação
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        texto = soup.get_text(" ", strip=True)
        texto = re.sub(r"\s{3,}", " ", texto).strip()

        if len(texto) < 200:
            return None

        # Extrai ementa
        m_ementa = re.search(r"EMENTA[:\s]+(.*?)(?=ACÓRDÃO|RELATÓRIO|DECISÃO|$)", texto, re.DOTALL | re.IGNORECASE)
        ementa = m_ementa.group(1).strip()[:2000] if m_ementa else ""

        # Relator
        m_rel = re.search(r"Relator[a]?\s*[:\(]\s*([A-ZÁÉÍÓÚÂÊÔÃÕÜ][a-záéíóúâêôãõü\s\.]+?)(?:\n|,|\))", texto)
        relator = m_rel.group(1).strip() if m_rel else ""

        # Data
        m_data = re.search(r"Julgado?\s+em\s+([\d/]+)", texto, re.IGNORECASE)
        data = m_data.group(1) if m_data else ""

        # Órgão julgador
        m_org = re.search(r"(Primeira Turma|Segunda Turma|Plenário|Tribunal Pleno)", texto, re.IGNORECASE)
        orgao = m_org.group(1) if m_org else ""

        return {
            "fonte":    "stf_acordao",
            "classe":   classe,
            "numero":   numero,
            "processo": f"{classe} {numero}",
            "relator":  relator,
            "orgao":    orgao,
            "data":     data,
            "ementa":   ementa,
            "texto":    texto[:8000],
            "n_chars":  len(texto),
        }
    except Exception as e:
        log.error(f"Erro ao parsear {classe} {numero}: {e}")
        return None


def _parse_hit(hit: dict) -> dict | None:
    """Converte um hit da API Elasticsearch do STF em registro estruturado."""
    try:
        src    = hit.get("_source", {})
        doc_id = hit.get("_id", src.get("id", ""))

        classe  = src.get("processo_classe_processual_unificada_sigla", "")
        numero  = str(src.get("processo_numero", ""))
        ementa  = src.get("ementa_texto", "")
        relator = src.get("relator_acordao_nome", src.get("relator_processo_nome", ""))
        orgao   = src.get("orgao_julgador", "")
        data    = src.get("julgamento_data", src.get("publicacao_data", ""))

        # Monta texto completo a partir dos campos disponíveis
        partes = []
        if classe and numero:
            partes.append(f"PROCESSO: {classe} {numero}")
        if relator:
            partes.append(f"RELATOR: {relator}")
        if orgao:
            partes.append(f"ÓRGÃO: {orgao}")
        if data:
            partes.append(f"DATA JULGAMENTO: {data}")
        if src.get("partes_lista_texto"):
            partes.append(f"PARTES:\n{src['partes_lista_texto']}")
        if ementa:
            partes.append(f"EMENTA:\n{ementa}")
        if src.get("acordao_ata"):
            partes.append(f"ACÓRDÃO:\n{src['acordao_ata']}")
        if src.get("documental_tese_texto"):
            partes.append(f"TESE:\n{src['documental_tese_texto']}")
        if src.get("documental_tese_tema_texto"):
            partes.append(f"TEMA:\n{src['documental_tese_tema_texto']}")
        if src.get("documental_legislacao_citada_texto"):
            leis = src["documental_legislacao_citada_texto"]
            if isinstance(leis, list):
                leis = "\n".join(leis)
            partes.append(f"LEGISLAÇÃO CITADA:\n{leis}")
        if src.get("documental_indexacao_texto"):
            partes.append(f"INDEXAÇÃO:\n{src['documental_indexacao_texto']}")
        if src.get("documental_observacao_texto"):
            partes.append(f"OBSERVAÇÕES:\n{src['documental_observacao_texto']}")
        if src.get("inteiro_teor_url"):
            partes.append(f"INTEIRO TEOR URL: {src['inteiro_teor_url']}")

        texto = "\n\n".join(partes)

        if len(texto) < 100:
            return None

        return {
            "fonte":           "stf_acordao",
            "doc_id":          doc_id,
            "classe":          classe,
            "numero":          numero,
            "processo":        src.get("processo_codigo_completo", f"{classe} {numero}"),
            "relator":         relator,
            "orgao":           orgao,
            "data_julgamento": data,
            "is_repercussao_geral": src.get("is_repercussao_geral", False),
            "tema_rg":         src.get("documental_tese_tema_texto", ""),
            "ementa":          ementa[:3000],
            "texto":           texto[:10000],
            "n_chars":         len(texto),
            "inteiro_teor_url": src.get("inteiro_teor_url", ""),
        }
    except Exception as e:
        log.debug(f"Erro ao parsear hit: {e}")
        return None


def crawl_stf_playwright(
    classe: str = "RE",
    limite: int = 100,
    estado: dict | None = None,
    desde: str | None = None,
    ate: str | None = None,
) -> list[dict]:
    """
    Usa Playwright para contornar o AWS WAF do STF.
    Intercepta as chamadas à API Elasticsearch interna (/api/search/search)
    e coleta os dados diretamente do JSON — sem precisar parsear HTML.
    """
    from playwright.sync_api import sync_playwright

    if estado is None:
        estado = carregar_estado()

    ja_feitos  = set(estado.get("processos_salvos", []))
    resultados = []
    PAGE_SIZE  = 10

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="pt-BR",
        )
        page = ctx.new_page()

        # ── Passo 1: abre o portal para obter cookies/token WAF ──────────────
        log.info(f"Abrindo portal STF (classe={classe})...")
        page.goto("https://jurisprudencia.stf.jus.br/pages/search",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)

        # ── Passo 2: usa page.evaluate para chamar a API via fetch interno ───
        # O browser já tem os cookies/tokens do WAF — as chamadas fetch funcionam
        pagina_api = 1
        while len(resultados) < limite:
            log.info(f"  Página {pagina_api} (acumulado: {len(resultados)})")

            # Payload Elasticsearch real (interceptado do portal STF)
            from_idx = (pagina_api - 1) * PAGE_SIZE
            payload  = {
                "query": {
                    "bool": {
                        "filter": [
                            # Filtro de data. Sem ele a consulta ordena por julgamento
                            # decrescente e para no limite, o que faz o arquivo ser uma
                            # JANELA dos ultimos meses e nao uma amostra do acervo: em
                            # 12/09/2026 as 464 acoes penais colhidas eram todas de 2026
                            # e as 1.358 reclamacoes, todas de 2025-2026.
                            *([{"range": {"julgamento_data": {
                                **({"gte": desde} if desde else {}),
                                **({"lte": ate} if ate else {}),
                            }}}] if (desde or ate) else []),
                            {
                                "query_string": {
                                    "default_operator": "AND",
                                    "fields": [
                                        "processo_codigo_completo.plural",
                                        "ementa_texto.plural^3",
                                        "documental_tese_texto.plural^2",
                                    ],
                                    "query": classe,
                                    "type": "phrase",
                                }
                            }
                        ]
                    }
                },
                "_source": [
                    "id", "processo_codigo_completo", "processo_numero",
                    "processo_classe_processual_unificada_sigla",
                    "relator_acordao_nome", "relator_processo_nome",
                    "orgao_julgador", "julgamento_data", "publicacao_data",
                    "ementa_texto", "acordao_ata", "partes_lista_texto",
                    "documental_tese_texto", "documental_tese_tema_texto",
                    "documental_legislacao_citada_texto",
                    "documental_indexacao_texto", "documental_observacao_texto",
                    "is_repercussao_geral", "inteiro_teor_url",
                ],
                "size":  PAGE_SIZE,
                "from":  from_idx,
                "sort":  [{"julgamento_data": {"order": "desc"}}],
                "track_total_hits": True,
            }

            try:
                resposta = page.evaluate(
                    """async (payload) => {
                        const r = await fetch('https://jurisprudencia.stf.jus.br/api/search/search', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
                            credentials: 'include',
                            body: JSON.stringify(payload),
                        });
                        return r.ok ? await r.json() : null;
                    }""",
                    payload,
                )
            except Exception as e:
                log.warning(f"  fetch falhou: {e}")
                break

            if not resposta:
                log.warning("  API retornou null.")
                break

            hits = resposta.get("result", {}).get("hits", {}).get("hits", [])
            if not hits:
                log.info("  Sem mais resultados.")
                break

            novos = 0
            for hit in hits:
                if len(resultados) >= limite:
                    break
                doc_id = hit.get("_id", "")
                if doc_id in ja_feitos:
                    continue
                r = _parse_hit(hit)
                if r:
                    resultados.append(r)
                    ja_feitos.add(doc_id)
                    novos += 1

            log.info(f"    {novos} novos hits | total: {len(resultados)}")
            pagina_api += 1
            page.wait_for_timeout(int(DELAY * 1000))

        browser.close()

    return resultados


def crawl_stf_via_controle_concentrado(limite: int = 500) -> list[dict]:
    """
    Usa controle_concentrado.jsonl como seed.
    Para cada ADI/ADPF/ADC com ID, tenta recuperar texto via redir.stf.

    Fallback quando o portal principal está protegido por WAF.
    """
    import requests, urllib3
    urllib3.disable_warnings()

    cc_path = OUTPUT_DIR / "controle_concentrado.jsonl"
    if not cc_path.exists():
        log.error(f"Arquivo não encontrado: {cc_path}")
        return []

    estado  = carregar_estado()
    ja_feitos = set(estado.get("processos_salvos", []))

    itens = [json.loads(l) for l in cc_path.read_text().splitlines() if l.strip()]
    itens = [i for i in itens if i.get("id") and i.get("id") not in ja_feitos][:limite]
    log.info(f"Seeds do controle concentrado: {len(itens)}")

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Macintosh) Chrome/120.0"})
    s.verify = False

    resultados = []
    for i, item in enumerate(itens, 1):
        doc_id = item.get("id", "")
        classe = item.get("classe", "ADI")
        numero = item.get("numero", "")

        # Tenta recuperar texto via paginador do STF
        url = f"https://redir.stf.jus.br/paginadorpub/paginador.jsp?docTP=AC&docID={doc_id}"
        try:
            r = s.get(url, timeout=20)
            if r.ok and len(r.text) > 500:
                acordao = parse_acordao_stf(r.text, classe, numero)
                if acordao:
                    acordao["doc_id_stf"] = doc_id
                    resultados.append(acordao)
                    log.info(f"  [{i}/{len(itens)}] {classe} {numero}: {acordao['n_chars']} chars")
                else:
                    log.debug(f"  [{i}/{len(itens)}] {classe} {numero}: sem conteúdo útil")
            else:
                log.debug(f"  [{i}/{len(itens)}] {classe} {numero}: {r.status_code}")
        except Exception as e:
            log.debug(f"  [{i}/{len(itens)}] {classe} {numero}: {e}")

        time.sleep(DELAY)

    return resultados


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawler de acórdãos STF")
    parser.add_argument("--classe",   default="RE",
                        choices=list(CLASSES_STF.keys()) + ["todas"],
                        help="Classe processual (default: RE)")
    parser.add_argument("--limite",   type=int, default=200,
                        help="Máximo de acórdãos por classe (default: 200)")
    parser.add_argument("--desde", default=None,
                        help="Data mínima de julgamento, AAAA-MM-DD")
    parser.add_argument("--ate", default=None,
                        help="Data máxima de julgamento, AAAA-MM-DD")
    parser.add_argument("--metodo",
                        choices=["playwright", "controle_concentrado", "auto"],
                        default="auto",
                        help="Método de coleta (default: auto)")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    estado = carregar_estado()

    # Decide método
    if args.metodo == "auto":
        metodo = "playwright" if verificar_playwright() else "controle_concentrado"
        log.info(f"Método automático selecionado: {metodo}")
    else:
        metodo = args.metodo

    if metodo == "playwright" and not verificar_playwright():
        log.warning("Playwright não instalado. Instalando...")
        instalar_playwright()

    classes = list(CLASSES_STF.keys()) if args.classe == "todas" else [args.classe]
    total   = 0

    with open(OUTPUT, "a", encoding="utf-8") as f_out:
        for classe in classes:
            log.info(f"\n=== Coletando {CLASSES_STF.get(classe, classe)} ===")

            if metodo == "playwright":
                resultados = crawl_stf_playwright(classe, args.limite, estado, args.desde, args.ate)
            else:
                # controle_concentrado só faz sentido para ADI/ADPF/ADC
                if classe in ("ADI", "ADPF", "ADC", "ADO"):
                    resultados = crawl_stf_via_controle_concentrado(args.limite)
                else:
                    log.warning(f"Método controle_concentrado só funciona para ADI/ADPF/ADC. Pulando {classe}.")
                    continue

            for r in resultados:
                f_out.write(json.dumps(r, ensure_ascii=False) + "\n")
            f_out.flush()

            total += len(resultados)
            estado["processos_salvos"].extend(
                f"{r['classe']}_{r['numero']}" for r in resultados
            )
            estado["total"] = total
            salvar_estado(estado)

            log.info(f"  {len(resultados)} acórdãos coletados para {classe}")

    log.info(f"\n✓ Total: {total} acórdãos | Saída: {OUTPUT}")


if __name__ == "__main__":
    main()
