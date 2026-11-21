#!/usr/bin/env python3
"""
rechunk_v3.py — re-chunker que RESPEITA fronteiras (documento → bloco → Q&A).

Corrige os defeitos da auditoria (docs/AUDITORIA_CURADORIA_CPT.md):
  P1/P2  nunca corta no meio de bloco/frase; cada chunk começa por cabeçalho
  P3     Q&A é um bloco único (pergunta+resposta juntas) → nunca separadas
  P4     leis entram por ARTIGO INTEIRO com cabeçalho [NORMA] (nº+nome)
  P5     acórdão/tese carrega o bloco de IDENTIFICAÇÃO junto das Q&A
  P6     metadados ricos por chunk (categoria, proveniência, fonte, título)
  P7     chunk maior (TARGET_CHARS) → menos fragmentação

Gera uma AMOSTRA pequena por categoria para 2ª rodada de validação.
Uso:  ../.venv-dash/bin/python pipeline/rechunk_v3.py --por-categoria 6
"""
from __future__ import annotations
import argparse, json, re
from identificadores import chave_de_registro
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUG = ROOT / "augmentation" / "output"
OUT_DIR = ROOT / "data" / "pretrain_v3_sample"

# alvo de tamanho (em chars). ~8000 chars ≈ 2000 tokens reais → 3-4x o atual (~2185).
TARGET_CHARS = 8000
MAX_CHARS = 12000   # se um único bloco passar disso, fica inteiro mesmo (raro)
REEXPAND = False    # re-expandir jurisprudência com professor (flag --reexpand-juris)

# ── N13 · A RESERVA DE JURISPRUDÊNCIA FOI ABANDONADA (decisão do pesquisador, 18/09/2026)
#
# Havia 1.360 casos reservados em `data/holdout/holdout_test_ids.json`, com a intenção
# declarada de "nunca entram no CPT". A reserva era incoerente e, apurada, desnecessária:
#
#  · INCOERENTE: o filtro excluía por `juris_id`, campo que só existe nos arquivos de
#    EXPANSÃO. O braço bruto usa `id`, então a ficha do caso reservado era barrada e o
#    acórdão inteiro do mesmo caso entrava pela porta da frente. Barrava e deixava passar;
#  · DESNECESSÁRIA: **nada avalia sobre esses casos**. As nove referências de `avaliacao/`
#    apontam para `data/oab/benchmark.jsonl`, e o benchmark da OAB é feito de questões de
#    prova, não de julgados — não há sobreposição a proteger. Os únicos consumidores do
#    arquivo de reserva eram estes dois construtores, que dele só sabiam excluir.
#
# Manter custava ~34 M de caracteres (14,66 M já medidos no v4 e 19,68 M que a coleta nova
# do DJe trouxe) em troca de um rigor aparente. O artigo declara que a avaliação é o
# benchmark da OAB e que não há holdout de jurisprudência.
#
# Os arquivos FICAM em `data/holdout/`, junto com `mapa_holdout.json`, que reconstrói o elo
# ficha→julgado para 1.268 dos 1.360. Se a avaliação "dado o julgado, produza a ficha" for
# adiante, tudo que é preciso para religar a reserva está preservado — o que se removeu foi
# o filtro, não a informação.
def holdout_ids():
    return set()

BLOCK_RE = re.compile(r'(<<ID=[^>]*>>)')

# ── Re-expansão de cards de jurisprudência (professor Mistral L3) ─────────────
TEACHER = "mistral.mistral-large-3-675b-instruct"   # melhor professor do benchmark
REEXP_CACHE = ROOT / "data" / "pretrain_v3_sample" / "_reexp_juris_cache.json"
_reexp = None

def _load_reexp():
    global _reexp
    if _reexp is None:
        _reexp = json.loads(REEXP_CACHE.read_text("utf-8")) if REEXP_CACHE.exists() else {}
    return _reexp

def _save_reexp():
    REEXP_CACHE.parent.mkdir(parents=True, exist_ok=True)
    REEXP_CACHE.write_text(json.dumps(_reexp, ensure_ascii=False), "utf-8")

STUB_RE = re.compile(r'papel na fundamenta[çc][ãa]o|rela[çc][ãa]o e sentido|— rela[çc][ãa]o\.|relação\.')

REEXP_BLOCK_PROMPT = """Você é um jurista sênior. Reescreva APENAS o bloco abaixo de um card de jurisprudência para pré-treino.
Problema: as referências estão como STUBS soltos (ex.: "CF88:ART:0149 (Art. 149, CF) — papel na fundamentação." ou
"JURIS:STF:RG:TEMA0002 — relação e sentido"), sem explicação. Para CADA referência do bloco:
  (a) escreva-a por extenso e humana (ex.: "Art. 149 da CF/88 — competência da União para instituir contribuições sociais");
  (b) explique CONCRETAMENTE o vínculo (qual o papel na fundamentação; em que consiste a relação — superação, distinção, aplicação). 1-2 frases por item.
Não invente normas/precedentes que não estejam no bloco. NÃO use markdown (nada de **). Mantenha o marcador <<ID=...>> e o rótulo [ ... ] no início.
Contexto (identificação/tese do card, só para entender): {contexto}

BLOCO A REESCREVER:
{bloco}

Bloco reescrito:"""

def _teacher_block(bloco: str, contexto: str) -> str:
    import boto3, os
    from botocore.config import Config
    br = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                      config=Config(read_timeout=120, retries={"max_attempts": 3}))
    r = br.converse(modelId=TEACHER,
                    messages=[{"role": "user", "content": [{"text": REEXP_BLOCK_PROMPT.format(contexto=contexto[:1200], bloco=bloco)}]}],
                    inferenceConfig={"maxTokens": 2500, "temperature": 0.2})
    out = r["output"]["message"]["content"][0]["text"].strip()
    p = out.find("<<ID=")
    if p > 0: out = out[p:]
    return out.replace("**", "")

REEXP_CACHE_ONLY = False   # no build final, só usa cache (não chama LLM p/ stragglers)

def reexpand_card(juris_id: str, expansao: str) -> str:
    """Re-expande, BLOCO A BLOCO, apenas os blocos com stub — preservando o resto do card."""
    if not STUB_RE.search(expansao):
        return expansao
    cache = _load_reexp()
    if juris_id in cache:
        return cache[juris_id]
    if REEXP_CACHE_ONLY:
        return expansao
    blocks = split_blocks(expansao)
    contexto = "\n".join(blocks[:2])  # identificação + enunciado/tese
    novo = []
    mudou = False
    for b in blocks:
        if STUB_RE.search(b):
            try:
                fb = _teacher_block(b, contexto)
                # sanidade do bloco: manteve marcador, sumiu o stub, não encolheu demais
                if fb.startswith("<<ID=") and not STUB_RE.search(fb) and len(fb) > 0.5 * len(b):
                    novo.append(fb); mudou = True; continue
            except Exception as e:
                print(f"  [reexp bloco falhou {juris_id}] {str(e)[:70]}")
        novo.append(b)
    fixed = "\n\n".join(novo)
    if mudou:
        cache[juris_id] = fixed; _save_reexp()
        return fixed
    return expansao

def split_blocks(expansao: str):
    """Divide a expansão em blocos, cada um começando por seu marcador <<ID=...>>.
    O 1º pedaço (antes de qualquer marcador) é ignorado se vazio."""
    parts = BLOCK_RE.split(expansao)
    blocks = []
    # parts = ['', '<<ID=..>>', 'texto', '<<ID=..>>', 'texto', ...]
    i = 1
    while i < len(parts):
        marker = parts[i]
        body = parts[i+1] if i+1 < len(parts) else ""
        blocks.append((marker + body).strip())
        i += 2
    if not blocks:  # sem marcadores → doc inteiro é um bloco
        blocks = [expansao.strip()]
    return blocks

def chunk_doc(header: str, blocks: list[str]):
    """Empacota blocos em chunks <= TARGET_CHARS, sem partir bloco.
    Repete `header` (bloco de identificação) no topo de cada chunk."""
    if not blocks:
        return []
    body_blocks = blocks[1:] if len(blocks) > 1 else []
    head = blocks[0]  # bloco de identificação ([NORMA]/[IDENTIFICAÇÃO])
    chunks, cur = [], []
    cur_len = len(head)
    for b in body_blocks:
        if cur and cur_len + len(b) + 2 > TARGET_CHARS:
            chunks.append(cur); cur = []; cur_len = len(head)
        cur.append(b); cur_len += len(b) + 2
    if cur or not chunks:
        chunks.append(cur)
    # monta texto: cabeçalho repetido + blocos; marca "continuação" quando k>0
    out = []
    n = len(chunks)
    for k, blist in enumerate(chunks):
        prefix = head
        if k > 0:
            prefix = head + f"\n[CONTINUAÇÃO {k+1}/{n}]"
        txt = prefix + "\n\n" + "\n\n".join(blist) if blist else prefix
        out.append(txt.strip())
    return out

def readjsonl(p: Path):
    if not p.exists(): return
    for line in p.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)

# ── Fontes BRUTAS de lei (texto original) e lookup nome→número ────────────────
LEIS = ROOT / "leis"

def _tabela_cp1250_para_cp1252() -> dict:
    """A recoleta veio decodificada como cp1250 quando as páginas do Planalto são cp1252.

    A assinatura é inconfundível e foi medida: `Presidęncia`, `LEI Nş 10.406`, `Lei de
    Introduçăo ŕs normas`. São os mesmos BYTES lidos pela tabela errada — 0xEA é `ê` em
    cp1252 e `ę` em cp1250; 0xBA é `º` e vira `ş`; 0xE3 é `ã` e vira `ă`; 0xF5 é `õ` e
    vira `ő`. Atingia 23.673 caracteres, e exatamente nos quatro diplomas da recoleta:
    Código Civil, Penal, Comercial e ECA — o Civil é o diploma mais citado do corpus.

    O conserto é a tabela de correspondência byte a byte entre as duas codificações, e não
    `texto.encode("cp1250").decode("cp1252")`: o texto traz marcas combinantes soltas
    (U+0301, U+0302) que cp1250 não representa, e a volta inteira levanta exceção por
    causa delas. A tabela troca só os 50 caracteres que DIFEREM entre as duas tabelas, e
    nenhum deles é letra do português — conferido —, de modo que aplicar a diploma já
    correto não muda nada e aplicar duas vezes dá o mesmo resultado.
    """
    tab = {}
    for b in range(0x80, 0x100):
        try:
            a, c = bytes([b]).decode("cp1250"), bytes([b]).decode("cp1252")
        except Exception:
            continue
        if a != c:
            tab[a] = c
    return tab


_CP1250 = str.maketrans(_tabela_cp1250_para_cp1252())


def _recoleta_v2() -> dict:
    """Os diplomas que chegaram truncados do Planalto e foram baixados de novo.

    Q3/A1 · `leis/codigos_especificos.parquet` é de fevereiro e traz o Código Civil com 57
    de 2.046 artigos, o Código Penal e o Comercial vazios, e o ECA com 8 de 267. A
    recoleta existe desde 12/09 em `leis/recoleta_v2/`, com 100% de cobertura nos quatro,
    e nunca foi ligada: o construtor continuava lendo o parquet truncado.

    A chave é o NÚMERO do diploma, não o apelido — "Código Civil" aparece escrito de
    quatro jeitos entre as fontes e o número não varia.
    """
    import json as _json
    tab = {}
    d = Path(LEIS) / "recoleta_v2"
    if not d.exists():
        return tab
    for arq in sorted(d.glob("*.json")):
        # `except Exception` aqui esconderia o que interessa. Quando este loader não
        # carregava nada, a causa era um import trocado — `_json` apontava para o módulo
        # `re` — e um except largo transformou AttributeError em "arquivo sem conteúdo".
        # JSONDecodeError é o único erro esperado de um arquivo malformado; o resto sobe.
        try:
            r = _json.loads(arq.read_text("utf-8"))
        except _json.JSONDecodeError:
            continue
        num = re.sub(r"[^0-9]", "", str(r.get("numero") or ""))
        if num and (r.get("texto") or "").strip():
            tab[num] = r["texto"].translate(_CP1250)
    return tab


# V6 · decisões do usuário em 16/09/2026, depois de ver os 122 diplomas marcados
# agrupados por quanto do texto está revogado.
#
# GRUPO A — o diploma inteiro foi substituído e o sucessor já está no corpus. Não entra.
# Não são duplicatas: `ISS (anterior LC 116)` é a LC 56/1987, `ISS anterior LC 116` é o
# DL 406/1968 e `ISS` é a LC 116/2003 — três diplomas distintos, dois superados. O mesmo
# vale para Drogas, CPC e Mandado de Segurança. Prevalece o recente, que já está aqui.
FORA_DO_BRUTO = {
    "BR-L-5869-1973":  "CPC 1973, substituído pela Lei 13.105/2015",
    "BR-L-8884-1994":  "CADE, substituída pela Lei 12.529/2011",
    "BR-L-6368-1976":  "Lei de Drogas, substituída pela Lei 11.343/2006",
    "BR-L-1533-1951":  "Mandado de Segurança, substituído pela Lei 12.016/2009",
    "BR-L-6367-1976":  "Acidente do Trabalho, substituída pela Lei 8.213/1991",
    "BR-L-8955-1994":  "Franquia, substituída pela Lei 13.966/2019",
    "BR-LC-56-1987":   "ISS, substituída pela LC 116/2003",
    "BR-DL-406-1968":  "ISS, substituído pela LC 116/2003",
}

# GRUPOS B, C e D — o diploma entra; sai o TEXTO revogado. Vale para todos, e a razão é
# medida: a etiqueta `<revogado>` não é anotação neutra num corpus de next-token
# prediction. Ela VIRA TEXTO — 8.351 delas já estão no bruto congelado, em 535 documentos,
# e 218 dos 227 blocos da CLT a levariam. Marcar ensinaria o modelo a escrever a etiqueta.
#
# A retirada acontece na MONTAGEM do bloco, não na carga: o texto carregado continua com a
# marca, que é o que permite ao lado expandido não gerar ficha sobre dispositivo revogado
# (V4) e ao V6 seguir medindo quanto havia. Tirar na carga apagaria essa informação.
def _tira_revogado(texto: str) -> str:
    return re.sub(r"\n{3,}", "\n\n",
                  re.sub(r"<revogado>.*?</revogado>", " ", texto or "", flags=re.S)).strip()


def carregar_leis_brutas():
    """Retorna lista de {numero, nome, texto} das leis brutas + lookup nome→número."""
    import pandas as pd
    leis = []
    _rec = _recoleta_v2()

    def _texto(bruto, numero):
        """Prefere o texto recoletado, quando existe, e só então o da fonte antiga."""
        n = re.sub(r"[^0-9]", "", str(numero or "").split("/")[0])
        return _rec.get(n) or bruto
    # códigos (parquet): lei='Lei 10.406/2002', apelido='Código Civil'
    p = LEIS / "codigos_especificos.parquet"
    if p.exists():
        for _, r in pd.read_parquet(p).iterrows():
            # O código tem apelido consagrado ("Código Civil"), e é ele que o expandido
            # usa como sigla via `doc_id`. A chave canônica sai do número do diploma, que
            # é o que os dois lados têm em comum.
            leis.append({"numero": r.get("lei", ""), "nome": r.get("apelido") or r.get("lei", ""),
                         "texto": _texto(r.get("texto", ""), r.get("lei", "")), "cat": "Código",
                         "chave": chave_de_registro({"lei": r.get("lei", "")}, "BR")})
    # cf88 (parquet)
    p = LEIS / "cf88_adct.parquet"
    if p.exists():
        for _, r in pd.read_parquet(p).iterrows():
            # O ADCT é documento distinto da parte permanente, e dar a mesma chave aos
            # dois os faria parecer duplicata um do outro.
            nome_cf = str(r.get("lei", "CF88"))
            leis.append({"numero": "CF/1988", "nome": nome_cf, "texto": r.get("texto", ""),
                         "cat": "CF88",
                         "chave": "BR-ADCT-1988" if "ADCT" in nome_cf.upper() else "BR-CF-1988"})
    # leis federais (jsonl)
    for d in readjsonl(LEIS / "leis_federais.jsonl"):
        # A `url` da fonte viaja junto: é a testemunha mais confiável do TIPO do diploma,
        # melhor que o rótulo. "Bens Imóveis da União" está escrito "Decreto 9.760/1946" e
        # a norma é o DECRETO-LEI 9.760/1946 — quem diz isso é `/decreto-lei/Del9760.htm`.
        leis.append({"numero": d.get("lei", ""), "nome": d.get("apelido") or d.get("lei", ""),
                     "texto": _texto(d.get("texto", ""), d.get("lei", "")), "cat": "Lei Federal",
                     "url": d.get("url", ""),
                     "chave": chave_de_registro(d, "BR")})
    # A6 · Constituição do Estado de São Paulo. Faltava nos DOIS braços, e é a norma
    # fundamental do estado cujo tribunal fornece 21.381 dos documentos do braço bruto: o
    # modelo via a jurisprudência do TJSP sem nunca ter visto a constituição sob a qual ela
    # é julgada.
    for d in readjsonl(LEIS / "cesp.jsonl"):
        leis.append({"numero": d.get("lei", ""), "nome": d.get("apelido") or d.get("lei", ""),
                     "texto": d.get("texto", ""), "cat": "Constituição Estadual",
                     "chave": d.get("chave") or chave_de_registro(d, "SP")})
    # leis SP (jsonl)
    for d in readjsonl(LEIS / "leis_sp.jsonl"):
        leis.append({"numero": d.get("lei", ""), "nome": d.get("apelido") or d.get("lei", ""),
                     "texto": d.get("texto", ""), "cat": "Lei Estadual SP",
                     "chave": chave_de_registro(d, "SP")})
    # O MESMO diploma entrava por dois arquivos: o Estatuto da OAB, o Código de Trânsito,
    # o Código Florestal e a Lei de Propriedade Industrial estão em
    # `codigos_especificos.parquet` E em `leis_federais.jsonl`, com textos de tamanhos
    # diferentes porque vieram de coletas diferentes. São 568 mil caracteres, cerca de 142
    # mil tokens, gastos ensinando a mesma lei duas vezes em duas redações.
    #
    # Só ficou visível quando a chave canônica passou a existir; antes eram "Código de
    # Trânsito Brasileiro" e "CTB Código de Trânsito", dois nomes que nada ligava. Fica a
    # versão mais longa, que é a mais completa nos quatro casos.
    melhor: dict = {}
    for L in leis:
        k = L.get("chave") or L["nome"]
        if k not in melhor or len(L["texto"]) > len(melhor[k]["texto"]):
            melhor[k] = L
    if len(melhor) < len(leis):
        print(f"  diplomas duplicados removidos: {len(leis) - len(melhor)}")
    leis = list(melhor.values())

    # GRUPO A · o diploma inteiro sai, DEPOIS da deduplicação — que escolhe o texto mais
    # longo por chave e portanto precisa ver todos os candidatos antes.
    fora = [L for L in leis if L.get("chave") in FORA_DO_BRUTO]
    if fora:
        leis = [L for L in leis if L.get("chave") not in FORA_DO_BRUTO]
        print(f"  V6 · {len(fora)} diploma(s) substituído(s) fora do bruto: "
              + ", ".join(L["nome"][:26] for L in fora[:4]))

    lookup = {}
    for L in leis:
        if L["nome"]: lookup[L["nome"].strip().lower()] = L["numero"]
    return leis, lookup

_LEI_LOOKUP = None
def num_da_lei(nome: str) -> str:
    global _LEI_LOOKUP
    if _LEI_LOOKUP is None:
        _, _LEI_LOOKUP = carregar_leis_brutas()
    return _LEI_LOOKUP.get((nome or "").strip().lower(), "")

# O padrão antigo, `\d+[ºo.\-A-Z]*`, lia o ponto do SEPARADOR DE MILHAR como parte do
# rótulo e parava ali: "Art. 1.089" virava `Art. 1.`. No Código Civil isso colapsava 1.064
# artigos acima de 999 — mais da metade do código — num único rótulo `Art. 1.`, repetido
# 1.132 vezes, e o cabeçalho `[ARTIGOS NESTE BLOCO]` do corpus anunciava faixas impossíveis
# como "Art. 993. a Art. 1.". 18,8% dos blocos de lei declaravam faixa descendente.
#
# O Q9 não pegava porque verifica o OUTRO divisor: `expand_normas.dividir_em_artigos`, do
# braço expandido, que sempre tratou o milhar corretamente. São dois divisores para a mesma
# tarefa, e só um estava sob verificação.
#
# A primeira alternativa, com milhar, vem antes por ser a mais longa; a segunda cobre
# "Art. 1º", "Art. 54" e "Art. 10-A". O ponto final da frase deixa de entrar no rótulo e
# volta ao corpo, que é reconstruído como `rot + corpo`.
ART_RE = re.compile(r'((?:Art\s*\.?|Artigo)\s*\d{1,3}(?:\.\d{3})+(?:-[A-Za-z])?'
                    r'|(?:Art\s*\.?|Artigo)\s*\d+\s*[ºo]?(?:-[A-Za-z])?)', re.IGNORECASE)

def _hard_split(texto: str, limite: int):
    """Quebra por parágrafos (fallback) quando um bloco excede o limite."""
    paras = texto.split("\n")
    out, cur, cl = [], [], 0
    for p in paras:
        if cur and cl + len(p) > limite:
            out.append("\n".join(cur)); cur = []; cl = 0
        cur.append(p); cl += len(p) + 1
    if cur: out.append("\n".join(cur))
    return out

# Um cabeçalho de artigo ABRE linha; "nos termos do art. 26" é citação dentro do corpo de
# outro artigo. `ART_RE.split` não distinguia os dois e cortava em ambos: de 34.462 pontos
# de corte, 15.918 (46,2%) estavam no meio de uma frase. Cada um partia o corpo do artigo
# em dois e batizava o pedaço com o número CITADO — o cabeçalho `[ARTIGOS NESTE BLOCO]`
# anunciava "art. 154 a art. 8º" porque a faixa saía de uma citação.
_INICIO_LINHA = re.compile(r"[\n\r][ \t]*$")


def _e_cabecalho(texto: str, i: int) -> bool:
    return i == 0 or texto[i - 1] in "\n\r" or bool(_INICIO_LINHA.search(texto[max(0, i - 12):i]))


def split_por_artigos(texto: str):
    """Divide o texto de uma lei em (rótulo_art, corpo) pelos CABEÇALHOS de artigo.

    Só conta como cabeçalho o "Art. N" que abre linha. As leis ALTERADORAS caem muito com
    essa regra — "Execução Civil CPC reforma" vai de 137 cortes para 10 — e isso está
    certo: o corpo delas é feito de citações dos artigos que alteram, não de artigos
    próprios. Dois diplomas ficam com zero cabeçalhos, a Lei do Cheque e a Lei Uniforme da
    Letra de Câmbio, porque escrevem `Art . 36`, com espaço antes do ponto; o padrão passou
    a tolerar esse espaço. Quando ainda assim não há cabeçalho, o texto entra inteiro num
    bloco só — nada se perde, só não há faixa a declarar.
    """
    cortes = [m for m in ART_RE.finditer(texto) if _e_cabecalho(texto, m.start())]
    itens = []
    for k, m in enumerate(cortes):
        fim = cortes[k + 1].start() if k + 1 < len(cortes) else len(texto)
        itens.append((m.group(1).strip(), texto[m.start():fim].strip()))
    return itens

def chunk_lei_bruta(nome, numero, resumo, texto, chave=None):
    """Quebra o texto bruto por faixas de artigos; cada bloco carrega
    identificação (nome+número) + resumo da lei + os artigos do bloco."""
    # V6/B-C-D · o texto revogado sai AQUI, na montagem do bloco, e não na carga: o texto
    # carregado continua com a marca, que é o que permite ao lado expandido não gerar ficha
    # sobre dispositivo revogado (V4) e ao portão V6 seguir medindo quanto havia.
    texto = _tira_revogado(texto)
    itens = split_por_artigos(texto)
    if not itens:  # sem artigos detectáveis → 1 bloco
        itens = [("", texto.strip())]
    # C16 · o cabeçalho leva a chave canônica junto da forma humana. A forma humana é o
    # que se lê; a chave é o que casa com o braço expandido, que identifica o mesmo
    # diploma como `SP-LC-180-1978`. Antes o bruto dizia "LC SP 180/1978" e o expandido
    # "SP180-1978", e nada os ligava.
    # C16 · o identificador do cabeçalho é o APELIDO quando o diploma tem um, porque é ele
    # que o braço expandido usa e que as 313.846 citações do corpus escrevem: trocar `CC`
    # por `BR-L-10406-2002` quebraria a resolução de referência do F6 sem ganho nenhum. A
    # chave canônica entra ao lado, em campo próprio, que é o que torna o pareamento entre
    # os braços conferível — e era disso que o B1 reclamava.
    from identificadores import chave_de_registro          # noqa: F811
    try:
        from expand_normas import sigla_conhecida
        apelido = sigla_conhecida(nome)
    except Exception:
        apelido = None
    # Sem apelido consagrado, vale a chave canônica — nunca as iniciais do nome, que
    # colapsam diplomas distintos no mesmo identificador.
    ident = apelido or chave or numero
    header = (f"<<LEI|BRUTO|{ident}>>\n[LEI] {nome} ({numero})\n"
              + (f"[CHAVE] {chave}\n" if chave else "")
              + f"[RESUMO DA LEI] {resumo}")
    # espaço para artigos = TARGET - tamanho do header
    orc = TARGET_CHARS - len(header) - 100
    # quebra artigos individuais grandes demais (fallback por parágrafo)
    itens2 = []
    for rot, corpo in itens:
        if len(corpo) > orc:
            for j, sub in enumerate(_hard_split(corpo, orc)):
                itens2.append((rot if j == 0 else f"{rot} (cont.)", sub))
        else:
            itens2.append((rot, corpo))
    itens = itens2
    blocos, cur, cur_len = [], [], 0
    for rot, corpo in itens:
        if cur and cur_len + len(corpo) > orc:
            blocos.append(cur); cur = []; cur_len = 0
        cur.append((rot, corpo)); cur_len += len(corpo) + 2
    if cur: blocos.append(cur)
    out = []
    n = len(blocos)
    for k, bl in enumerate(blocos):
        faixa = f"{bl[0][0]} a {bl[-1][0]}" if bl[0][0] and n > 1 else (bl[0][0] or "íntegra")
        cab = header + f"\n[ARTIGOS NESTE BLOCO] {faixa}" + (f"  (parte {k+1}/{n})" if n > 1 else "")
        corpo = "\n\n".join(c for _, c in bl)
        out.append(cab + "\n\n" + corpo)
    return out

# (arquivo, categoria, proveniência, campo_expansao, fn(doc)->(doc_id, titulo))
# ── Resumo da lei (Bedrock, com fallback extrativo) ──────────────────────────
# O cache era só de MEMÓRIA, e por isso cada remontagem do v4 refazia até 196 chamadas
# pagas ao Bedrock — uma por diploma — para produzir exatamente os mesmos resumos. Agora
# persiste em disco. O resumo é dispositivo de CONTEXTO, não conteúdo: como o diploma é
# quebrado em vários blocos, o cabeçalho de cada um precisa dizer de que norma se trata,
# senão o modelo lê um trecho de articulado sem saber a que lei pertence. Por isso ele é
# estável entre execuções e cachear é seguro — muda só quando a lei muda.
_CACHE_RESUMO = Path(RAIZ) / "leis/resumos_lei.json" if "RAIZ" in dir() else None


def _carrega_cache() -> dict:
    p = Path(__file__).resolve().parent.parent / "leis/resumos_lei.json"
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return {}


def _grava_cache(c: dict) -> None:
    p = Path(__file__).resolve().parent.parent / "leis/resumos_lei.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")


_RESUMO_CACHE = _carrega_cache()


def resumo_lei(nome, numero, texto):
    key = numero or nome
    if key in _RESUMO_CACHE:
        return _RESUMO_CACHE[key]
    resumo = ""
    try:
        import boto3, os
        from botocore.config import Config
        br = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                          config=Config(read_timeout=60, retries={"max_attempts": 1}))
        prompt = (f"Em 1-2 frases objetivas, resuma o QUE a norma a seguir regula/faz como um todo "
                  f"(finalidade e âmbito). Não liste artigos. Norma: {nome} ({numero}).\n\n"
                  f"Trecho inicial:\n{texto[:3000]}")
        r = br.converse(modelId="zai.glm-5",
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={"maxTokens": 180, "temperature": 0.2})
        resumo = r["output"]["message"]["content"][0]["text"].strip()
    except Exception as e:
        # fallback: primeira frase significativa do preâmbulo
        m = re.search(r'(Institui|Disp[õo]e|Regula|Estabelece|Altera|Aprova)[^.]{0,300}\.', texto)
        resumo = (m.group(0).strip() if m else f"Norma {nome} ({numero}).")
    _RESUMO_CACHE[key] = resumo
    if resumo:                      # só grava o que valeu a chamada
        _grava_cache(_RESUMO_CACHE)
    return resumo

def _norma_rica(diploma, num_art, numero, doc_id):
    """Cabeçalho [NORMA] legível: 'Art. 2º da Lei nº 9.099/1995 (Juizados Especiais) | ref JE:ART:0002'."""
    numfmt = numero.replace("Lei ", "Lei nº ") if numero and numero.startswith("Lei ") else (numero or "")
    art = f"Art. {num_art}º" if str(num_art).strip() and str(num_art) != "?" else ""
    partes = [p for p in [art, f"da {numfmt}" if numfmt else "", f"({diploma})" if diploma else ""] if p]
    linha = " ".join(partes).strip()
    return f"{linha} | ref {doc_id}" if linha else f"{diploma} | ref {doc_id}"

def _reescreve_norma(exp, diploma, num_art, numero, doc_id):
    """Substitui a 1ª linha do bloco [NORMA] pela versão rica."""
    rica = _norma_rica(diploma, num_art, numero, doc_id)
    return re.sub(r'(\[NORMA\]\s*\n)([^\n]+)', lambda m: m.group(1) + rica, exp, count=1)

def _titulo_lei(d):
    dip = d.get("diploma", "?"); art = d.get("num_art", "?")
    num = num_da_lei(dip)
    nome_num = f"{dip} ({num})" if num else dip
    return d.get("id") or d.get("doc_id") or dip, f"{nome_num} — Art. {art}"
def _titulo_juris(d):
    return d.get("juris_id", "?"), f"{d.get('tipo','?')} {d.get('tribunal','')} — {d.get('identificador','')}".strip()
def _titulo_caso(d):
    return d.get("case_id", "?"), f"Caso TJSP — {d.get('area','')} / {d.get('tipo_acao','')}".strip(" -/")
def _titulo_oab(d):
    return d.get("id", "?"), f"OAB 1ª fase — {d.get('id','')}"

FONTES = [
    ("cf88_expandida.jsonl",            "CF88",           "expandido", "expansao", _titulo_lei),
    ("codigos_expandidos.jsonl",        "Código",         "expandido", "expansao", _titulo_lei),
    ("leis_federais_expandidas.jsonl",  "Lei Federal",    "expandido", "expansao", _titulo_lei),
    ("leis_sp_expandidas.jsonl",        "Lei Estadual SP","expandido", "expansao", _titulo_lei),
    ("sumulas_stf_expandida.jsonl",     "Súmula STF",     "expandido", "expansao", _titulo_juris),
    ("rg_stf_expandida.jsonl",          "Repercussão Geral STF","expandido","expansao", _titulo_juris),
    ("temas_stj_expandida.jsonl",       "Tema STJ",       "expandido", "expansao", _titulo_juris),
    ("stj_acordaos_expandida.jsonl",    "Acórdão/Info STJ","expandido","expansao", _titulo_juris),
    ("stf_acordaos_expandida.jsonl",    "Acórdão STF",    "expandido", "expansao", _titulo_juris),
    ("casos_tjsp_expandidos.jsonl",     "Caso TJSP",      "expandido", "expansao", _titulo_caso),
]

def build_oab(d):
    """OAB 1ª fase: transforma múltipla escolha em QA DISSERTATIVA autocontida.
    A pergunta vira autocontida e a resposta disserta com base na alternativa correta."""
    ident = f"OAB 1ª fase — Exame {d.get('exame','?')} · Questão {d.get('id','')} · Área: {d.get('area','')}"
    pergunta = d.get("pergunta", ""); corr = d.get("alternativa_correta") or d.get("resposta", "")
    q_diss, r_diss = pergunta, corr
    try:
        import boto3, os
        from botocore.config import Config
        br = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                          config=Config(read_timeout=60, retries={"max_attempts": 1}))
        prompt = (
            "Transforme a questão de múltipla escolha da OAB abaixo em um par PERGUNTA/RESPOSTA "
            "dissertativo e AUTOCONTIDO, para pré-treino de um modelo jurídico. Regras: (1) a PERGUNTA "
            "deve fazer sentido sozinha, sem alternativas; (2) a RESPOSTA deve dissertar brevemente "
            "(2-4 frases) explicando o porquê, com base na alternativa correta e fundamento jurídico. "
            "Responda em JSON {\"pergunta\":\"...\",\"resposta\":\"...\"}.\n\n"
            f"Área: {d.get('area','')}\nEnunciado: {pergunta}\nAlternativa correta: {corr}")
        r = br.converse(modelId="zai.glm-5",
                        messages=[{"role": "user", "content": [{"text": prompt}]}],
                        inferenceConfig={"maxTokens": 500, "temperature": 0.3})
        raw = r["output"]["message"]["content"][0]["text"]
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            j = json.loads(m.group(0)); q_diss = j.get("pergunta", pergunta); r_diss = j.get("resposta", corr)
    except Exception:
        pass
    txt = (f"<<ID=OAB:{d.get('id','')}|DOC=OAB|TYPE=QA|PARENT=NULL>>\n[IDENTIFICAÇÃO]\n{ident}\n\n"
           f"[PERGUNTA]\n{q_diss}\n\n[RESPOSTA]\n{r_diss}")
    return d.get("id", "?"), ident, txt

def gerar_amostra(por_categoria: int, full: bool = False, out_dir: Path = None):
    OD = out_dir or OUT_DIR
    OD.mkdir(parents=True, exist_ok=True)
    todos = []
    resumo = []
    for arq, cat, prov, campo, ftit in FONTES:
        p = AUG / arq
        if not p.exists():
            resumo.append((cat, arq, "AUSENTE", 0, 0)); continue
        docs = []
        for d in readjsonl(p):
            if not full and len(docs) >= por_categoria: break
            docs.append(d)
        n_chunks_cat = 0
        for d in docs:
            exp = d.get(campo, "") or ""
            if not exp.strip(): continue
            # NUNCA inclui no CPT casos reservados para avaliação (held-out)
            if d.get("juris_id") in holdout_ids():
                continue
            doc_id, titulo = ftit(d)
            # leis: reescreve o cabeçalho [NORMA] no formato humano legível
            if ftit is _titulo_lei:
                exp = _reescreve_norma(exp, d.get("diploma", ""), d.get("num_art", ""),
                                       num_da_lei(d.get("diploma", "")), doc_id)
            # jurisprudência: re-expande stubs soltos com o professor Mistral L3
            if ftit is _titulo_juris and REEXPAND:
                exp = reexpand_card(d.get("juris_id", doc_id), exp)
            blocks = split_blocks(exp)
            chunks = chunk_doc(titulo, blocks)
            for k, txt in enumerate(chunks):
                todos.append({
                    "id": f"{doc_id}#{k}",
                    "categoria": cat,
                    "proveniencia": prov,
                    "fonte_arquivo": arq,
                    "doc_id": doc_id,
                    "titulo": titulo,
                    "chunk_ix": k,
                    "n_chunks": len(chunks),
                    "n_chars": len(txt),
                    "text": txt,
                })
                n_chunks_cat += 1
        resumo.append((cat, arq, "ok", len(docs), n_chunks_cat))

    # OAB 1ª fase (estrutura própria)
    p = AUG / "oab_1fase_expandida.jsonl"
    if p.exists():
        docs = []
        for d in readjsonl(p):
            if not full and len(docs) >= por_categoria: break
            docs.append(d)
        n_chunks_cat = 0
        for d in docs:
            doc_id, titulo, txt = build_oab(d)
            todos.append({"id": f"{doc_id}#0", "categoria": "OAB 1ª fase", "proveniencia": "expandido",
                          "fonte_arquivo": "oab_1fase_expandida.jsonl", "doc_id": doc_id, "titulo": titulo,
                          "chunk_ix": 0, "n_chunks": 1, "n_chars": len(txt), "text": txt})
            n_chunks_cat += 1
        resumo.append(("OAB 1ª fase", "oab_1fase_expandida.jsonl", "ok", len(docs), n_chunks_cat))

    # LEIS BRUTAS (texto original, ao lado dos cards) — quebra por artigo c/ id+resumo
    leis, _ = carregar_leis_brutas()
    por_fonte = {}
    for L in leis:
        por_fonte.setdefault(L["cat"], []).append(L)
    for cat, lst in por_fonte.items():
        n_chunks_cat = 0; ndocs = 0
        _lim = lst if full else lst[:max(2, por_categoria // 2)]
        for L in _lim:   # leis brutas (grandes)
            if not (L.get("texto") or "").strip(): continue
            ndocs += 1
            res = resumo_lei(L["nome"], L["numero"], L["texto"])
            chunks = chunk_lei_bruta(L["nome"], L["numero"], res, L["texto"],
                                     L.get("chave"))
            for k, txt in enumerate(chunks):
                todos.append({
                    "id": f"BRUTO:{L.get('chave') or L['numero']}#{k}", "categoria": cat, "proveniencia": "bruto",
                    "fonte_arquivo": "leis/ (texto original)", "doc_id": L["numero"],
                    "titulo": f"{L['nome']} ({L['numero']}) — texto bruto",
                    "chunk_ix": k, "n_chunks": len(chunks), "n_chars": len(txt), "text": txt,
                })
                n_chunks_cat += 1
        resumo.append((f"{cat} (BRUTO)", "leis/", "ok", ndocs, n_chunks_cat))

    out = OD / ("train.jsonl" if full else "sample.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for r in todos:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # manifest
    (OD / "manifest.json").write_text(json.dumps({
        "target_chars": TARGET_CHARS, "max_chars": MAX_CHARS,
        "por_categoria": por_categoria, "total_chunks": len(todos),
        "categorias": [{"categoria": c, "arquivo": a, "status": s, "docs": nd, "chunks": nc}
                       for c, a, s, nd, nc in resumo],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"AMOSTRA v3 → {out}  ({len(todos)} chunks de {sum(1 for _ in todos)} — {por_categoria}/categoria)")
    print(f"{'categoria':22s} {'docs':>5s} {'chunks':>7s}  status")
    for c, a, s, nd, nc in resumo:
        print(f"  {c:22s} {nd:5d} {nc:7d}  {s if s!='ok' else ''}")
    import statistics
    tam = [t["n_chars"] for t in todos]
    if tam:
        print(f"\nTamanho chunk (chars): mediana={int(statistics.median(tam))} média={int(statistics.mean(tam))} máx={max(tam)}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--por-categoria", type=int, default=6, help="nº de documentos por categoria na amostra")
    ap.add_argument("--reexpand-juris", action="store_true", help="re-expande cards de jurisprudência com Mistral L3")
    ap.add_argument("--full", action="store_true", help="corpus COMPLETO (todos os docs) → data/pretrain_v3/train.jsonl")
    args = ap.parse_args()
    REEXPAND = args.reexpand_juris
    if args.full:
        REEXP_CACHE_ONLY = True
        gerar_amostra(args.por_categoria, full=True, out_dir=ROOT/"data"/"pretrain_v3")
    else:
        gerar_amostra(args.por_categoria)
