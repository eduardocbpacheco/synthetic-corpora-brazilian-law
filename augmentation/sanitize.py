"""
sanitize.py — limpa markdown das expansões geradas por LLM.

O corpus espera texto puro: marcador `<<ID=...>>` numa linha, rótulo `[BLOCO]` na
linha seguinte, conteúdo abaixo. O gpt-4o-mini (gerador antigo) já entregava assim,
mas o Mistral L3 embrulha tudo em markdown — `**[NORMA]**`, `### **<<ID=...>>**`,
preâmbulo "Aqui está a expansão...", separadores `---`. Assim o rechunk_v3 não
reconhece bloco nenhum.

Uso:
    from sanitize import limpar_expansao
    texto_limpo = limpar_expansao(texto_bruto)
"""
from __future__ import annotations

import re

_NEGRITO   = re.compile(r"\*\*")
_HEADING   = re.compile(r"^\s{0,3}#{1,6}\s*")
_SEPARADOR = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_ITALICO   = re.compile(r"^\*(.+)\*$", re.DOTALL)
_ITALICO_MULTI = re.compile(r"\*(?!\s)([^*]{1,3000}?)(?<!\s)\*", re.DOTALL)


def limpar_expansao(texto: str) -> str:
    """Devolve a expansão sem markdown, começando no primeiro marcador <<ID=."""
    if not texto:
        return texto

    # Preâmbulo conversacional antes do primeiro marcador ("Aqui está a expansão...")
    i = texto.find("<<ID=")
    if i > 0:
        texto = texto[i:]

    texto = _NEGRITO.sub("", texto)
    # Itálico que atravessa linhas (o Mistral cita o caput como *"Artigo 1° ..."*).
    # Exige não-espaço colado aos asteriscos para não comer um `*` solto do texto.
    texto = _ITALICO_MULTI.sub(r"\1", texto)

    linhas = []
    for linha in texto.split("\n"):
        if _SEPARADOR.match(linha):
            continue
        linha = _HEADING.sub("", linha)
        despida = linha.strip()
        m = _ITALICO.match(despida)
        if m and "*" not in m.group(1):
            linha = m.group(1)
        linhas.append(linha.rstrip())

    # Colapsa as linhas em branco que sobraram dos separadores removidos
    saida, anterior_vazia = [], False
    for linha in linhas:
        vazia = not linha.strip()
        if vazia and anterior_vazia:
            continue
        saida.append(linha)
        anterior_vazia = vazia

    return normaliza_estrutura("\n".join(saida).strip())


REGRA_FORMATO = (
    "\nFORMATO DE SAÍDA (obrigatório): responda APENAS com os blocos, começando "
    "direto no primeiro marcador <<ID=...>>. Sem preâmbulo, sem comentário final. "
    "TEXTO PURO — proibido markdown: nada de **negrito**, nada de ### títulos, "
    "nada de --- separadores. O marcador <<ID=...>> e o rótulo [BLOCO] ficam cada "
    "um sozinho em sua linha, exatamente como no modelo.\n"
)


# ── Q8 · cabeçalho de nó e rótulo de bloco
#
# O cabeçalho canônico é `<<ID=…|DOC=…|TYPE=…|PARENT=…>>`, e 584 nós do corpus não o
# seguem. Nenhum deles perdeu conteúdo: o que falta no cabeçalho está codificado no
# PRÓPRIO ID, porque ele carrega a cadeia inteira. `CF88:ART:0208:QA:001` diz que o tipo é
# QA e que o pai é `CF88:ART:0208`. Reparar é melhor que recusar: recusar jogaria fora 584
# perguntas e respostas íntegras por causa de um separador.
#
#   534  ID=…|DOC=…                       sem TYPE nem PARENT
#    27  ID=…|DOC=…|PARENT=…              sem TYPE
#    22  ID=…|DOC=…|DOC=…|TYPE=…|PARENT=… DOC repetido
#     1  ID=…|DOC=…|TYPE=…|PAPIC=…        PARENT escrito errado pelo gerador
_CABECALHO = re.compile(r"<<(ID=[^>]{1,300})>>")
_CANONICO = re.compile(r"^ID=[^|]+\|DOC=[^|]+\|TYPE=[^|]+\|PARENT=[^|]+$")

# Tipo de nó fora do vocabulário. `Q` é QA truncado, `JUR` é JURIS, `CONTENT` é o rótulo
# em inglês do que o resto do corpus chama CONTEUDO.
_TIPO_CANONICO = {"Q": "QA", "JUR": "JURIS", "J": "JURIS", "CONTENT": "CONTEUDO",
                  "CONT": "CONTROV", "RE": "REL", "EFF": "EFFECT", "E": "EXPL"}

# Rótulo de bloco com erro de digitação do gerador. São 13 ocorrências em todo o corpus,
# mas um rótulo que aparece duas vezes ensina uma variante que não existe.
_ROTULO_CANONICO = {
    "PRINCÍPIOS RELACIONADAS": "PRINCÍPIOS RELACIONADOS",
    "PRINCÍPIOS RELACIONADADOS": "PRINCÍPIOS RELACIONADOS",
    "Q&A": "PERGUNTAS E RESPOSTAS",
    "PERGUNTAS E RESPOSTAS": "PERGUNTAS E RESPOSTAS",
}


def _repara_cabecalho(m: "re.Match") -> str:
    campos = m.group(1).split("|")
    vistos: dict[str, str] = {}
    for c in campos:
        if "=" not in c:
            continue
        k, v = c.split("=", 1)
        k = k.strip().upper()
        if k == "PAPIC":            # erro de digitação do gerador
            k = "PARENT"
        if k not in vistos:         # o primeiro vence: o DOC repetido é o segundo
            vistos[k] = v.strip()
    ident = vistos.get("ID", "")
    partes = ident.split(":")
    if "TYPE" not in vistos and len(partes) >= 2:
        # O penúltimo segmento é o tipo quando o último é o índice do nó.
        cand = partes[-2] if partes[-1].isdigit() else partes[-1]
        vistos["TYPE"] = _TIPO_CANONICO.get(cand.upper(), cand.upper())
    if "PARENT" not in vistos and len(partes) >= 3:
        corte = -2 if partes[-1].isdigit() else -1
        vistos["PARENT"] = ":".join(partes[:corte]) or "NULL"
    vistos["TYPE"] = _TIPO_CANONICO.get(vistos.get("TYPE", "").upper(), vistos.get("TYPE", ""))
    vistos.setdefault("DOC", ident)
    vistos.setdefault("PARENT", "NULL")
    vistos.setdefault("TYPE", "")
    return (f"<<ID={vistos['ID']}|DOC={vistos['DOC']}"
            f"|TYPE={vistos['TYPE']}|PARENT={vistos['PARENT']}>>")


def normaliza_estrutura(texto: str) -> str:
    """Cabeçalho na forma canônica e rótulo de bloco sem variante."""
    if not texto:
        return texto
    texto = _CABECALHO.sub(
        lambda m: m.group(0) if _CANONICO.match(m.group(1)) else _repara_cabecalho(m), texto)
    for errado, certo in _ROTULO_CANONICO.items():
        if errado != certo:
            texto = texto.replace(f"[{errado}]", f"[{certo}]")
    return texto


# ── Q2 · citação de julgado fabricada ─────────────────────────────────────────────────
#
# Das 3.472 citações de julgado nas 14.794 fichas de norma, 1.205 trazem número-molde —
# `REsp 1.234.567` aparece 538 vezes, e há `987654`, `123456`, `HC 400.000`. O que prova
# invenção é o MOLDE do número, e não a ausência do julgado no corpus: para artigo de lei,
# ausente é defeito porque o corpus quer os códigos inteiros; para julgado não é, porque o
# corpus tem 5.181 de um universo de centenas de milhares.
#
# A remoção tem de respeitar a forma, porque as três que ocorrem pedem tratamentos
# diferentes — apagar só o número deixa prosa pendurada em duas delas:
#
#   item de lista     "- STJ: HC 456.789/SP — Entendimento: a suspensão do livramento..."
#                     o item existe para afirmar AQUELE caso; sem ele não sobra asserção,
#                     sobra um travessão. Sai o item inteiro.
#   parentético       "...impede a homologação (MS 12.345/DF)."
#                     o parêntese é o apoio; a proposição fica de pé sem ele. Sai o parêntese.
#   meio de frase     "Decisões judiciais, como a do STF na ADI 5.595, reforçam que..."
#                     sai a citação e a aposição que a introduz, quando dá para delimitá-la.
#
# Quando o bloco [JURISPRUDÊNCIA] fica sem nenhum item, ele sai junto: cabeçalho de bloco
# vazio ensina a forma de citar sem nada para citar.
_RX_ITEM = re.compile(r"(?m)^[ \t]*[-•*][ \t]*.*$")
_RX_PAREN = re.compile(r"\s*\([^()]{0,200}\)")
_RX_BLOCO_VAZIO = re.compile(r"(?m)^\[JURISPRUDÊNCIA\][ \t]*\n(?=\s*(?:\[|<<|$))")
_RX_APOSTO = re.compile(r",\s*(?:como|tal como|a exemplo de|ex\.?:|por exemplo,?)?\s*$")


def remove_julgado_inventado(texto: str, spans) -> str:
    """Tira do texto as citações que o detector apontou, por forma.

    `spans` é a lista de (início, fim) de `pipeline/referencias.py`; recebê-la pronta
    mantém a regra de detecção num lugar só — reimplementá-la aqui foi exatamente o erro
    que criou o `confere_corpus.py`. Os trechos saem da direita para a esquerda, senão a
    primeira remoção invalida as posições das seguintes.
    """
    for ini, fim in sorted(spans, reverse=True):
        ini_linha = texto.rfind("\n", 0, ini) + 1
        fim_linha = texto.find("\n", fim)
        fim_linha = len(texto) if fim_linha < 0 else fim_linha
        if _RX_ITEM.fullmatch(texto[ini_linha:fim_linha]):
            texto = texto[:ini_linha] + texto[fim_linha + 1:]
            continue
        ab = texto.rfind("(", ini_linha, ini)
        fe = texto.find(")", fim)
        if ab >= 0 and 0 <= fe < fim_linha and _RX_PAREN.fullmatch(texto[ab:fe + 1]):
            texto = texto[:ab].rstrip() + texto[fe + 1:]
            continue
        m = _RX_APOSTO.search(texto[:ini])
        corte = m.start() if m else ini
        depois = re.sub(r"^[\s,;/]*(?:[A-Z]{2}\b)?[\s,;.]*", " ", texto[fim:], count=1)
        texto = texto[:corte] + depois
    texto = _RX_BLOCO_VAZIO.sub("", texto)
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", texto)).strip()


# ── Q4 · a referência na língua que o leitor fala ─────────────────────────────────────
#
# 592 itens de lista (0,24% dos 242.859) trazem só o índice — `CF88:ART:0195` — sem nome de
# diploma nem "art. N". A cifra registrada no item era 5.176 e 7%; medida, é essa. A maioria
# dos itens já traz o nome entre parênteses e nunca foi defeito.
#
# O índice ENTRA junto, não sai. O F6 mede que 94,2% das 313.846 citações resolvem por
# identificador, e essa resolução é o que liga a ficha ao artigo no corpus: trocar o índice
# pela prosa consertaria a leitura humana quebrando a leitura de máquina. A forma natural é
# acrescentada, e o índice fica entre parênteses logo atrás.
# O indice tem de ABRIR o item. Essa e a forma do defeito — "- CF88:ART:0195 — Base
# constitucional..." — e restringir a ela evita estragar o que ja esta bom: em
# "- Devido processo legal (CF:ART:0005:LIV): Mobilizado para..." o item ja tem prosa
# propria, e prefixar "art. 5\u00ba da Constitui\u00e7\u00e3o Federal" duplicaria a referencia.
#
# O casamento vai ate o fim do indice INTEIRO, terceiro segmento incluido. Parar no artigo
# deixava ":LIV" solto depois do parentese que eu mesmo abria, e o item saia com pontuacao
# quebrada — conserto que estraga e pior que defeito que fica.
_RX_IDX_ABRE = re.compile(r"^([A-Z]{1,8}\d*(?:-\d{4})?):(?:ADCT:)?ART:(\d{1,5}[A-Z-]*)((?::[^\s)]+)*)")
_RX_TEM_NOME = re.compile(
    r"(Lei|Decreto|Emenda|Constitui[çc]|C[óo]digo|Estatuto|Consolida[çc]|Medida Provis"
    r"|Portaria|Resolu[çc]|S[úu]mula|\bart(?:igo)?s?\.?\s*\d)", re.I)
_RX_ITEM_LISTA = re.compile(r"(?m)^([ \t]*[-•*][ \t]*)(.*)$")


def acrescenta_forma_natural(texto: str, forma_natural) -> str:
    """Poe "art. N do Diploma" na frente do indice, nos itens que so trazem o indice.

    `forma_natural` vem de `pipeline/referencias.py` — a traducao mora junto do vocabulario
    de referencia, nao aqui.
    """
    def _item(m: "re.Match") -> str:
        marca, corpo = m.group(1), m.group(2)
        if _RX_TEM_NOME.search(corpo):
            return m.group(0)
        mi = _RX_IDX_ABRE.match(corpo)
        if not mi:
            return m.group(0)
        nat = forma_natural(mi.group(1), mi.group(2))
        if not nat or not nat.startswith("art."):
            return m.group(0)
        return f"{marca}{nat} ({mi.group(0)}){corpo[mi.end():]}"
    return _RX_ITEM_LISTA.sub(_item, texto)


# ── Q6 · a data que a ficha diz não ter ───────────────────────────────────────────────
#
# 19.070 das 23.530 fichas de precedente escrevem "Data: (informação insuficiente nas
# fontes fornecidas)". O modelo-professor não inventou nem se recusou: a semente que ele
# recebeu não trazia data nenhuma. A data está nos arquivos de coleta, e o que faltava era
# casar as duas pontas — `pipeline/datas_precedente.py` faz esse casamento e explica por
# que cada tribunal falha de um jeito diferente.
#
# Substituir em vez de apagar: um campo "Data:" sem valor ensina a ficha incompleta como se
# fosse a forma normal. Onde não há data recuperável — os 3.246 temas de repercussão geral,
# cuja coleta não tem campo de data — o texto original fica como está, porque ali a ficha
# está dizendo a verdade.
_RX_DATA_FALTA = re.compile(
    r"(Data[^:|\n]{0,18}:\s*)\(?\s*(?:informa[çc][ãa]o insuficiente|n[ãa]o (?:informad|consta"
    r"|especificad)|indispon)[^)|\n]{0,70}\)?", re.I)


def preenche_data(texto: str, data: str | None) -> str:
    """Troca a marca de data faltante pela data recuperada da coleta."""
    if not data:
        return texto
    return _RX_DATA_FALTA.sub(lambda m: f"{m.group(1)}{data}", texto, count=1)
