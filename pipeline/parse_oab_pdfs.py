"""
Parser de PDFs do Exame de Ordem OAB (2ª fase).

Extrai de cada par (caderno + gabarito definitivo):
  - Enunciado da peça profissional
  - 4 questões discursivas com suas partes A/B
  - Gabarito comentado de cada questão
  - Critérios de avaliação (Distribuição dos Pontos)

ATENÇÃO — NÃO é mais a fonte do benchmark. Use pipeline/monta_benchmark_v2.py.
Este parser fazia uma SEGUNDA extração dos espelhos, pior que a do Rabula: perdia as
24 discursivas do exame 39 (cabeçalho antigo "QUESTÃO 1"), perdia 4 questões cujo
rótulo era "A)" e não "A.", truncava o texto do critério na coluna de pontuação e
fundia as partes de um item num critério só (tudo-ou-nada). Segue válido para o
corpus de TREINO (--only train).

Saída (legado): data/oab/benchmark.jsonl — exames 39/40/41
       data/oab/sft.jsonl         — questões dos demais exames (treino)

Uso:
    cd "Artigo Treino Juridico"
    source juridico-env/bin/activate
    python pipeline/parse_oab_pdfs.py

    # Apenas benchmark:
    python pipeline/parse_oab_pdfs.py --only benchmark

    # Apenas treino:
    python pipeline/parse_oab_pdfs.py --only train
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import pdfplumber

# ── Caminhos base ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
PDF_DIR = BASE_DIR / "data" / "oab" / "pdfs"
OUTPUT_DIR = BASE_DIR / "data" / "oab"

# Exames benchmark (Rabula) → vai para benchmark.jsonl
BENCHMARK_EXAMES = {39, 40, 41}

# Mapeamento nome de área (pasta) → nome canônico
AREA_MAP = {
    "administrativo": "Direito Administrativo",
    "civil": "Direito Civil",
    "constitucional": "Direito Constitucional",
    "trabalho": "Direito do Trabalho",
    "trabalhista": "Direito do Trabalho",
    "empresarial": "Direito Empresarial",
    "penal": "Direito Penal",
    "tribut": "Direito Tributário",
    "tributario": "Direito Tributário",
    "tributário": "Direito Tributário",
}


# ── Extração de texto raw ─────────────────────────────────────────────────────

def _pdf_pages(path: Path) -> list[str]:
    """Retorna lista de textos por página do PDF."""
    try:
        with pdfplumber.open(path) as pdf:
            return [pg.extract_text() or "" for pg in pdf.pages]
    except Exception as e:
        print(f"  [AVISO] Falha ao ler {path.name}: {e}")
        return []


# O caderno do exame 38 usa CAPITULAR: o "Q" de QUESTÃO é um glifo separado, e o
# extrator devolve "Q 1\nUESTÃO" em vez de "QUESTÃO 1". Sem normalizar, o exame
# rendia só a peça — 7 itens de 35 — e nenhum aviso era emitido, porque a peça
# extraía normalmente. Mesma causa do "P\nROVA\nP\nRÁTICO" no cabeçalho.
_CAPITULAR = re.compile(r"\bQ\s*(\d+)\s*\n\s*UEST[ÃA]O\b")
_CAPITULAR2 = re.compile(r"\bQ\s*\n\s*UEST[ÃA]O\s*(\d+)\b")


def _normaliza_capitular(texto: str) -> str:
    texto = _CAPITULAR.sub(lambda m: f"QUESTÃO {m.group(1)}", texto)
    return _CAPITULAR2.sub(lambda m: f"QUESTÃO {m.group(1)}", texto)


def _clean(texto: str) -> str:
    """Remove cabeçalhos repetitivos, rodapés e instruções institucionais."""
    texto = _normaliza_capitular(texto)
    # Remove cabeçalho OAB padrão
    texto = re.sub(
        r"ORDEM DOS ADVOGADOS DO BRASIL\n.*?Exame de Ordem Unificado\n.*?\n.*?\n",
        "",
        texto,
        flags=re.DOTALL,
    )
    # Remove linha de rodapé
    texto = re.sub(r"Padrão de Resposta.*?Página \d+ de \d+", "", texto)
    # Remove linhas de número de página de caderno
    texto = re.sub(r"PROVA PRÁTICO-PROFISSIONAL – PÁGINA \d+", "", texto)
    texto = re.sub(r"QUESTÃO \d+ – PÁGINA \d+", "", texto)

    # NOVO: Remove blocos de instruções institucionais da capa do PDF
    # Padrão típico: "TEMPO", "NÃO SERÁ PERMITIDO", "SUA PROVA", etc.
    # Removemos qualquer bloco do começo da página até o primeiro "QUESTÃO N" ou "PEÇA"
    # se contiver palavras-chave de instruções
    indicadores_instrucao = [
        "fiscal de sala", "fiscal da sala",
        "caderno para transcrição", "caderno de textos definitivos",
        "FGV realizará identificação", "identificação datiloscópica",
        "NÃO SERÁ PERMITIDO", "Confira seus dados pessoais",
        "5 (cinco) horas é o tempo", "tempo disponível para a realização",
        "será possível retirar-se da sala", "rascunho",
        "Assinale seu nome", "caneta esferográfica transparente",
    ]
    # Se uma página tem 2+ indicadores antes da primeira QUESTÃO/PEÇA, remove o cabeçalho
    primeiro_marcador = re.search(r"(QUEST[ÃA]O\s+\d+|PEÇA\s+PRÁTICO|PEÇA\s+JUR[ÍI]DICA)", texto, re.IGNORECASE)
    if primeiro_marcador:
        cabecalho = texto[:primeiro_marcador.start()]
        n_indicadores = sum(1 for ind in indicadores_instrucao if ind.lower() in cabecalho.lower())
        if n_indicadores >= 2:
            texto = texto[primeiro_marcador.start():]

    # Normaliza espaços excessivos
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def _limpar_enunciado_residual(enunciado: str) -> str:
    """
    Limpa ruído residual em enunciados extraídos.
    Lida com layout multi-coluna fragmentado onde instruções da capa OAB
    aparecem entre o título e o enunciado real.
    """
    # Lista expandida de palavras-chave que indicam instruções institucionais
    KW_INSTRUCAO = [
        "fiscal da sala", "fiscal de sala", "fiscal de aplicação",
        "fiscal de aplicação", "caderno de textos definitivos",
        "caderno para transcrição", "caderno de rascunho",
        "será possível retirar-se", "caneta esferográfica",
        "fgv realizará identificação", "identificação datiloscópica",
        "lista de presença", "tempo disponível para a realização",
        "agenda eletrônica", "telefone celular", "máquina fotográfica",
        "walkman", "controle de alarme", "pendrive",
        "examinandos por meio da coleta", "impressões digitais",
        "qualquer tipo de comunicação", "levantar da cadeira",
        "termo desistindo", "portar aparelhos", "horário de realização",
        "padrão de resposta", "(cid:", "página", "XXXIII", "XXXIV", "XXXV",
        "exame de ordem unificado", "prova prático", "verifique se a disciplina",
        "ordem dos advogados do brasil",
    ]

    # Remove linhas com indicadores de instrução
    linhas_limpas = []
    for linha in enunciado.split("\n"):
        linha_low = linha.lower().strip()
        if not linha_low:
            linhas_limpas.append(linha)
            continue
        if any(kw.lower() in linha_low for kw in KW_INSTRUCAO):
            continue
        # Linhas curtas (< 10 chars) que são fragmentos de instruções de capa
        if len(linha_low) < 10 and re.match(r"^[•·\-\*•]?\s*[a-z]", linha_low):
            continue
        # Linhas que começam com bullet e contêm "examinando"
        if re.search(r"examinando(?!\s+deve)", linha_low):
            continue
        linhas_limpas.append(linha)
    enunciado = "\n".join(linhas_limpas)

    # Remove caracteres de PDF problemáticos
    enunciado = re.sub(r"\(cid:\d+\)", "", enunciado)
    enunciado = re.sub(r"\s*•\s*$", "", enunciado, flags=re.MULTILINE)

    # Normaliza espaços
    enunciado = re.sub(r"\n{3,}", "\n\n", enunciado)
    enunciado = re.sub(r" {2,}", " ", enunciado)
    return enunciado.strip()


# ── Parser do caderno de provas ───────────────────────────────────────────────

def _is_writing_page(texto: str) -> bool:
    """Retorna True se a página é apenas linhas de escrita (numeradas 1-60)."""
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
    if len(linhas) < 3:
        return True
    nums = sum(1 for l in linhas if re.match(r"^\d+$", l))
    return nums / len(linhas) > 0.7


def _is_instruction_page(texto: str) -> bool:
    """
    Retorna True se a página é a capa/instruções institucionais (sem questões reais).
    Heurística: forte presença de indicadores institucionais E ausência de questão real.
    """
    texto_low = texto.lower()

    # Conta indicadores de capa institucional
    indicadores = [
        "sua prova", "informações gerais", "fiscal de sala", "fiscal da sala",
        "não será permitido", "caneta esferográfica", "caderno de textos definitivos",
        "fgv realizará identificação", "identificação datiloscópica",
        "5 (cinco) horas", "2 (duas) horas", "tempo disponível para a realização",
        "termo desistindo",
        "portar aparelhos", "agenda eletrônica", "controle de alarme",
        "atenção", "elaboração dos textos", "incluir todos os dados",
    ]
    n_instrucao = sum(1 for ind in indicadores if ind in texto_low)

    # Se tem 3+ indicadores institucionais, é capa
    if n_instrucao >= 3:
        return True

    # Procura por marcadores REAIS de questão (numeração)
    # "QUESTÃO 1" / "QUESTÃO 2" — não apenas "PROVA PRÁTICO-PROFISSIONAL" do header
    tem_questao = bool(re.search(r"quest[ãa]o\s+\d+\b", texto_low))
    # Ou tem o enunciado da peça (não apenas o header)
    tem_peca_real = bool(re.search(r"peça\s+prático-profissional\s*[\n\r].{200,}", texto_low, re.DOTALL))

    return n_instrucao >= 2 and not (tem_questao or tem_peca_real)


def extrair_questoes_caderno(path_caderno: Path) -> dict:
    """
    Extrai peça e questões discursivas do caderno de provas.

    Returns:
        {
          "peca": str,             # texto do enunciado da peça
          "discursivas": [         # lista de 4 questões
            {
              "numero": int,       # 1-4
              "enunciado": str,    # texto completo da questão
              "parte_a": str,      # apenas o texto da parte A
              "parte_b": str,      # texto da parte B (se houver)
              "valor_a": float,    # pontuação da parte A
              "valor_b": float,    # pontuação da parte B
            }
          ]
        }
    """
    paginas = _pdf_pages(path_caderno)
    if not paginas:
        return {}

    # Concatena páginas não-rasunho E não-instrucionais
    blocos: list[str] = []
    for p in paginas:
        if _is_writing_page(p):
            continue
        if _is_instruction_page(p):
            continue
        blocos.append(_clean(p))
    texto_total = "\n\n".join(blocos)

    resultado: dict = {"peca": "", "discursivas": []}

    # ── Extrai peça profissional ──────────────────────────────────────────────
    m_peca = re.search(
        r"PEÇA PRÁTICO-PROFISSIONAL\s*(.*?)(?=QUESTÃO\s+1\b|$)",
        texto_total,
        re.DOTALL | re.IGNORECASE,
    )
    if m_peca:
        # Remove parágrafo ATENÇÃO se presente
        peca_txt = m_peca.group(1)
        peca_txt = re.sub(r"^ATENÇÃO\n.*?identificação\.\n", "", peca_txt, flags=re.DOTALL)
        resultado["peca"] = _limpar_enunciado_residual(peca_txt)

    # ── Extrai questões discursivas ───────────────────────────────────────────
    partes_questao = re.split(r"\n(?=QUESTÃO\s+\d+\b)", texto_total, flags=re.IGNORECASE)

    for bloco in partes_questao:
        m_num = re.match(r"QUESTÃO\s+(\d+)\b\s*", bloco, re.IGNORECASE)
        if not m_num:
            continue

        num = int(m_num.group(1))
        corpo = bloco[m_num.end():].strip()

        # Extrai pontuação de A e B
        val_a = val_b = 0.0
        for m in re.finditer(r"Valor:\s*(\d+[,\.]\d+)\)", corpo):
            v = float(m.group(1).replace(",", "."))
            if val_a == 0.0:
                val_a = v
            else:
                val_b = v

        # Separa partes A e B
        m_ab = re.search(r"\nB\)", corpo, re.IGNORECASE)
        if m_ab:
            parte_a = corpo[: m_ab.start()].strip()
            parte_b = corpo[m_ab.start():].strip()
        else:
            parte_a = corpo
            parte_b = ""

        resultado["discursivas"].append(
            {
                "numero": num,
                "enunciado": _limpar_enunciado_residual(corpo),
                "parte_a": _limpar_enunciado_residual(parte_a),
                "parte_b": _limpar_enunciado_residual(parte_b) if parte_b else "",
                "valor_a": val_a,
                "valor_b": val_b,
            }
        )

    resultado["discursivas"].sort(key=lambda x: x["numero"])
    return resultado


# ── Parser do gabarito/padrão de respostas ────────────────────────────────────

def _parse_criterios(texto_distribuicao: str) -> list[dict]:
    """
    Extrai critérios individuais do bloco "Distribuição dos Pontos".

    Returns lista de {"id": str, "texto": str, "pontuacao_max": float}
    """
    criterios: list[dict] = []
    linhas = texto_distribuicao.split("\n")

    # Padrão: "N. Descrição do critério (0,XX)" seguido de pontuações
    padrao_item = re.compile(
        r"^([A-Z\d]+[\.\d]*)\.\s+(.*?)(?:\((\d+[\.,]\d+)\))?$",
        re.DOTALL,
    )

    buffer_id: Optional[str] = None
    buffer_texto: list[str] = []
    buffer_pontuacao = 0.0

    def flush():
        if buffer_id and buffer_texto:
            texto = " ".join(buffer_texto).strip()
            # Extrai pontuação máxima: padrões "0,00/0,10/0,60" ou "(0,50)"
            # Só aceita valores ≤ 5.0 (notas OAB típicas: 0,10 a 0,65 por critério)
            pts: list[float] = []
            # Padrão: sequência de pontuações "0,XX/0,YY"
            for m in re.finditer(r"(?<!\d)(\d{1,2}[,\.]\d{2})(?!\d)", texto):
                v = float(m.group(1).replace(",", "."))
                if 0 < v <= 5.0:
                    pts.append(v)
            pontuacao = max(pts) if pts else buffer_pontuacao
            # Remove trailing pontuação da descrição "0,00/0,10/0,60"
            texto_limpo = re.sub(r"\s+\d+[,\.]\d+(?:/\d+[,\.]\d+)+\s*$", "", texto).strip()
            # Remove pontuação inline entre parênteses no final "(0,50)"
            texto_limpo = re.sub(r"\s+\(\d+[,\.]\d+\)\s*$", "", texto_limpo).strip()
            criterios.append({
                "id": buffer_id,
                "texto": texto_limpo,
                "pontuacao_max": round(pontuacao, 2),
            })

    for linha in linhas:
        linha = linha.strip()
        if not linha or linha.startswith("ITEM") or linha.startswith("PONTUAÇÃO"):
            continue

        # Detecta início de novo item: "1." ou "A." ou "5.1"
        m_inicio = re.match(r"^([A-Z\d]+(?:\.\d+)?)\.\s+(.+)", linha)
        if m_inicio:
            flush()
            buffer_id = m_inicio.group(1)
            buffer_texto = [m_inicio.group(2)]
            # Pontuação inline
            m_pts = re.search(r"\((\d+[,\.]\d+)\)", m_inicio.group(2))
            try:
                buffer_pontuacao = float(m_pts.group(1).replace(",", ".")) if m_pts else 0.0
            except (ValueError, AttributeError):
                buffer_pontuacao = 0.0
        elif buffer_id and not re.match(r"^0[,\.]\d+", linha):
            # Continuação de item anterior (não é linha de pontuação)
            buffer_texto.append(linha)

    flush()
    return criterios


def extrair_gabarito(path_gabarito: Path) -> dict:
    """
    Extrai gabaritos e critérios do PDF de padrão de respostas definitivo.

    Returns:
        {
          "peca": {
            "gabarito_comentado": str,
            "criterios": [{"id", "texto", "pontuacao_max"}]
          },
          "discursivas": [
            {
              "numero": int,
              "gabarito_comentado": str,
              "criterios": [...]
            }
          ]
        }
    """
    paginas = _pdf_pages(path_gabarito)
    if not paginas:
        return {}

    resultado: dict = {"peca": {}, "discursivas": []}

    # Varre páginas identificando cada seção.
    # ATENÇÃO: para questões discursivas, o cabeçalho, gabarito e critérios
    # ficam TODOS na mesma página, por isso não se usa `continue` após
    # detectar o cabeçalho — processamos linha a linha dentro da mesma página.
    questao_atual: Optional[int] = None
    gab_comentado: list[str] = []
    dist_pontos: list[str] = []
    modo = ""  # "gab" ou "dist"

    def flush_questao():
        gab = "\n".join(gab_comentado).strip()
        crits = _parse_criterios("\n".join(dist_pontos))
        enunc = "\n".join(enunciado_buf).strip()
        if gab or crits:
            if questao_atual is None:
                resultado["peca"] = {
                    "gabarito_comentado": gab,
                    "criterios": crits,
                    "enunciado_inline": enunc,  # formato antigo inclui enunciado
                }
            else:
                resultado["discursivas"].append(
                    {
                        "numero": questao_atual,
                        "gabarito_comentado": gab,
                        "criterios": crits,
                        "enunciado_inline": enunc,
                    }
                )

    # Flag de enunciado: formato antigo inclui o enunciado no PDF do gabarito
    enunciado_buf: list[str] = []
    # Exames 13 e 14 usam um terceiro formato: blocos "QUESTÃO: QUESTÃO DISCURSIVA" e
    # "QUESTÃO: PEÇA PRÁTICO-PROFISSIONAL", com a questão identificada por código
    # ("QUESTÃO Nº: B002081") em vez de número 1..4. Sem isto os dois exames rendiam
    # só a peça — 7 itens em vez de 35 — e o parser não avisava.
    seq_discursiva = 0

    for pg in paginas:
        limpo = _clean(pg)
        linhas = limpo.split("\n")

        for linha in linhas:
            linha_strip = linha.strip()
            if not linha_strip:
                continue

            # ── Detecta mudança de seção de questão ─────────────────────────

            # Formato novo: "PADRÃO DE RESPOSTA – PEÇA PROFISSIONAL"
            if re.search(r"PADRÃO DE RESPOSTA.*PEÇA", linha_strip, re.IGNORECASE):
                if gab_comentado or dist_pontos:
                    flush_questao()
                questao_atual = None
                gab_comentado = []
                dist_pontos = []
                enunciado_buf = []
                modo = ""
                continue

            # Formato dos exames 13/14: "QUESTÃO: QUESTÃO DISCURSIVA"
            if re.match(r"(TIPO\s+DE\s+)?QUEST[ÃA]O\s*:\s*QUEST[ÃA]O\s+DISCURSIVA\s*$", linha_strip, re.I):
                if gab_comentado or dist_pontos:
                    flush_questao()
                seq_discursiva += 1
                questao_atual = seq_discursiva
                gab_comentado = []
                dist_pontos = []
                enunciado_buf = []
                modo = ""
                continue

            # Formato antigo: "PEÇA PRÁTICO-PROFISSIONAL", com ou sem "QUESTÃO:" antes
            if re.match(r"((TIPO\s+DE\s+)?QUEST[ÃA]O\s*:\s*)?PEÇA PRÁTICO-PROFISSIONAL\s*$", linha_strip, re.IGNORECASE):
                if gab_comentado or dist_pontos:
                    flush_questao()
                questao_atual = None
                gab_comentado = []
                dist_pontos = []
                enunciado_buf = []
                modo = ""
                continue

            # Formato novo: "PADRÃO DE RESPOSTA – QUESTÃO 0N"
            m_q_novo = re.search(r"PADRÃO DE RESPOSTA.*QUESTÃO\s+0?(\d+)", linha_strip, re.IGNORECASE)
            if m_q_novo:
                if gab_comentado or dist_pontos:
                    flush_questao()
                questao_atual = int(m_q_novo.group(1))
                gab_comentado = []
                dist_pontos = []
                enunciado_buf = []
                modo = ""
                continue

            # Formato antigo: linha "QUESTÃO N" sozinha (sem mais texto)
            m_q_antigo = re.match(r"^QUESTÃO\s+(\d+)\s*$", linha_strip, re.IGNORECASE)
            if m_q_antigo:
                if gab_comentado or dist_pontos:
                    flush_questao()
                questao_atual = int(m_q_antigo.group(1))
                gab_comentado = []
                dist_pontos = []
                enunciado_buf = []
                modo = ""
                continue

            # ── Detecta sub-seções dentro da questão ────────────────────────
            if re.match(r"(Gabarito Comentado|GABARITO COMENTADO)\s*$", linha_strip, re.IGNORECASE):
                modo = "gab"
                continue
            if re.match(r"(Distribuição dos Pontos|DISTRIBUIÇÃO DOS PONTOS)\s*$", linha_strip, re.IGNORECASE):
                modo = "dist"
                continue
            # Enunciado: no formato antigo contém o texto da questão
            if re.match(r"(Enunciado|ENUNCIADO|ENUNCIADO DA QUESTÃO DISCURSIVA)\s*$", linha_strip, re.IGNORECASE):
                modo = "enunciado"
                continue

            # ── Acumula conteúdo ─────────────────────────────────────────────
            if modo == "gab":
                gab_comentado.append(linha_strip)
            elif modo == "dist":
                dist_pontos.append(linha_strip)
            elif modo == "enunciado":
                enunciado_buf.append(linha_strip)

    # Flush final
    flush_questao()

    resultado["discursivas"].sort(key=lambda x: x["numero"])
    return resultado


# ── Montagem do benchmark JSONL ───────────────────────────────────────────────

def _area_from_filename(nome: str) -> str:
    """Extrai área jurídica canônica do nome do arquivo."""
    nome_lower = nome.lower()
    for slug, nome_canonico in AREA_MAP.items():
        if slug in nome_lower:
            return nome_canonico
    return "Desconhecida"


def _encontrar_par(pasta: Path, tipo_caderno: bool = True) -> dict[str, Path]:
    """
    Para um diretório de exame, retorna dicionário {area: path} para
    cadernos ou gabaritos definitivos.
    """
    resultado: dict[str, Path] = {}
    for pdf in pasta.glob("*.pdf"):
        nome = pdf.name.lower()
        if tipo_caderno and "caderno" in nome:
            area = _area_from_filename(nome)
            if area not in resultado or len(nome) < len(resultado[area].name):
                resultado[area] = pdf
        elif not tipo_caderno and "gabarito_def" in nome:
            area = _area_from_filename(nome)
            if area not in resultado or "prelim" in resultado[area].name.lower():
                resultado[area] = pdf
    # O exame 32 só tem gabarito PRELIMINAR publicado — sete áreas, caderno e gabarito
    # completos em disco, e mesmo assim rendia zero porque a busca exigia "definitivo".
    # O preliminar é aceito apenas onde não existe definitivo, nunca em vez dele.
    if not tipo_caderno:
        for pdf in pasta.glob("*.pdf"):
            nome = pdf.name.lower()
            if "gabarito" in nome and "prelim" in nome and "2fase" in nome:
                area = _area_from_filename(nome)
                if area and area not in resultado:
                    resultado[area] = pdf
    return resultado


def processar_exame(pasta: Path, num_exame: int, split: str) -> list[dict]:
    """
    Processa um diretório de exame e retorna lista de entradas JSONL.

    Returns lista de dicts representando questões do benchmark.
    """
    entradas: list[dict] = []

    cadernos = _encontrar_par(pasta, tipo_caderno=True)
    gabaritos = _encontrar_par(pasta, tipo_caderno=False)

    areas_comuns = set(cadernos.keys()) & set(gabaritos.keys())

    if not areas_comuns:
        print(f"  [AVISO] Exame {num_exame}: nenhum par caderno+gabarito encontrado em {pasta}")
        return entradas

    for area in sorted(areas_comuns):
        path_cad = cadernos[area]
        path_gab = gabaritos[area]

        print(f"  {area}: {path_cad.name} + {path_gab.name}")

        questoes_cad = extrair_questoes_caderno(path_cad)
        questoes_gab = extrair_gabarito(path_gab)

        if not questoes_cad or not questoes_gab:
            print(f"    [AVISO] Extração incompleta para {area}")
            continue

        # ── Peça profissional ─────────────────────────────────────────────────
        peca_enunc = questoes_cad.get("peca", "")
        peca_gab = questoes_gab.get("peca", {})

        # Formato antigo: enunciado está no próprio PDF do gabarito
        if not peca_enunc and peca_gab.get("enunciado_inline"):
            peca_enunc = peca_gab["enunciado_inline"]

        if peca_enunc and peca_gab:
            entradas.append({
                "tipo": "peca",
                "id": f"{num_exame}-peca-{area.split()[-1].lower()[:5]}",
                "exame": str(num_exame),
                "area": area,
                "split": split,
                "enunciado": peca_enunc,
                "tipo_peca": _inferir_tipo_peca(peca_gab.get("gabarito_comentado", "")),
                "gabarito": peca_gab.get("gabarito_comentado", ""),
                "criterios": peca_gab.get("criterios", []),
            })

        # ── Questões discursivas ──────────────────────────────────────────────
        gab_por_num = {d["numero"]: d for d in questoes_gab.get("discursivas", [])}

        # Tenta usar discursivas do caderno primeiro; cai para gabarito se caderno vazio
        discursivas_cad = questoes_cad.get("discursivas", [])
        if not discursivas_cad:
            # Formato antigo: usa enunciado_inline do gabarito
            discursivas_cad = [
                {
                    "numero": d["numero"],
                    "enunciado": d.get("enunciado_inline", ""),
                }
                for d in questoes_gab.get("discursivas", [])
                if d.get("enunciado_inline")
            ]

        for disc in discursivas_cad:
            num = disc["numero"]
            enunc = disc.get("enunciado", "")
            gab_disc = gab_por_num.get(num)
            if not gab_disc:
                continue
            # Formato antigo: pega enunciado do gabarito se caderno não extraiu
            if not enunc and gab_disc.get("enunciado_inline"):
                enunc = gab_disc["enunciado_inline"]
            if not enunc:
                continue

            entradas.append({
                "tipo": "discursiva",
                "id": f"{num_exame}-disc-{area.split()[-1].lower()[:5]}-{num}",
                "exame": str(num_exame),
                "area": area,
                "split": split,
                "enunciado": enunc,
                "gabarito": gab_disc.get("gabarito_comentado", ""),
                "criterios": gab_disc.get("criterios", []),
            })

    return entradas


def _inferir_tipo_peca(gabarito_comentado: str) -> str:
    """Infere o tipo de peça a partir do gabarito comentado."""
    gc = gabarito_comentado.lower()
    tipos = [
        ("mandado de segurança", "Mandado de Segurança"),
        ("habeas corpus", "Habeas Corpus"),
        ("apelação", "Recurso de Apelação"),
        ("recurso de apelação", "Recurso de Apelação"),
        ("ação direta de inconstitucionalidade", "ADI"),
        ("ação civil pública", "Ação Civil Pública"),
        ("ação popular", "Ação Popular"),
        ("mandado de injunção", "Mandado de Injunção"),
        ("recurso especial", "Recurso Especial"),
        ("embargos", "Embargos"),
        ("contestação", "Contestação"),
        ("agravo", "Agravo"),
    ]
    for padrao, nome in tipos:
        if padrao in gc:
            return nome
    return "Peça Processual"


# ── CLI principal ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Parser de PDFs OAB → JSONL benchmark.")
    parser.add_argument(
        "--only",
        choices=["benchmark", "train", "all"],
        default="all",
        help="Processa apenas o split especificado (default: all).",
    )
    parser.add_argument(
        "--output-benchmark",
        default="data/oab/benchmark.jsonl",
        help="Arquivo de saída do benchmark (default: data/oab/benchmark.jsonl).",
    )
    parser.add_argument(
        "--output-sft",
        default="data/oab/sft_oab.jsonl",
        help="Arquivo de saída SFT/treino (default: data/oab/sft_oab.jsonl).",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    todas_entradas_benchmark: list[dict] = []
    todas_entradas_sft: list[dict] = []

    # ── Processa exames benchmark ─────────────────────────────────────────────
    if args.only in ("benchmark", "all"):
        print("\n=== Processando exames BENCHMARK (39, 40, 41) ===")
        for num_exame in sorted(BENCHMARK_EXAMES):
            pasta = PDF_DIR / f"benchmark_exame{num_exame}"
            if not pasta.exists():
                print(f"  [AVISO] Pasta não encontrada: {pasta}")
                continue
            print(f"\nExame {num_exame}:")
            entradas = processar_exame(pasta, num_exame, split="benchmark")
            todas_entradas_benchmark.extend(entradas)
            print(f"  → {len(entradas)} questões")

        if todas_entradas_benchmark:
            path_out = BASE_DIR / args.output_benchmark
            with open(path_out, "w", encoding="utf-8") as f:
                for e in todas_entradas_benchmark:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            print(f"\n✓ Benchmark: {len(todas_entradas_benchmark)} questões → {path_out}")

    # ── Processa exames de treino ─────────────────────────────────────────────
    if args.only in ("train", "all"):
        print("\n=== Processando exames de TREINO ===")

        for pasta in sorted(PDF_DIR.iterdir()):
            if not pasta.is_dir():
                continue
            if "benchmark" in pasta.name:
                continue  # já processado acima

            # Extrai número do exame do nome da pasta
            m_num = re.search(r"exame(\d+)", pasta.name)
            if not m_num:
                continue
            num_exame = int(m_num.group(1))

            if num_exame in BENCHMARK_EXAMES:
                continue  # segurança extra

            print(f"\nExame {num_exame}:")
            entradas = processar_exame(pasta, num_exame, split="train")
            todas_entradas_sft.extend(entradas)
            print(f"  → {len(entradas)} questões")

        if todas_entradas_sft:
            path_out = BASE_DIR / args.output_sft
            with open(path_out, "w", encoding="utf-8") as f:
                for e in todas_entradas_sft:
                    f.write(json.dumps(e, ensure_ascii=False) + "\n")
            print(f"\n✓ SFT treino: {len(todas_entradas_sft)} questões → {path_out}")

    # ── Resumo final ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"Total benchmark: {len(todas_entradas_benchmark)} questões")
    print(f"Total SFT treino: {len(todas_entradas_sft)} questões")

    # Distribuição por tipo
    for nome, lista in [("benchmark", todas_entradas_benchmark), ("treino", todas_entradas_sft)]:
        if lista:
            disc = sum(1 for e in lista if e["tipo"] == "discursiva")
            peca = sum(1 for e in lista if e["tipo"] == "peca")
            print(f"  {nome}: {disc} discursivas + {peca} peças")


if __name__ == "__main__":
    main()
