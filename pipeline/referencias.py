#!/usr/bin/env python3
"""referencias.py — resolver e conferir citação de artigo dentro das fichas.

F6 · A conferência de integridade que o item pede, e a medição que ela permitiu.

O item Q3 registrava que "57% das 71.904 referências apontam para artigo ausente do
corpus", o que descreve fabricação em massa. Medido sobre o corpus: das 313.769 citações
por identificador, **82% resolvem sem tratamento nenhum e 93,8% resolvem depois de
normalizar**. O que a contagem antiga chamava de referência quebrada é, na maioria,
DIVERGÊNCIA DE ESCRITA do mesmo identificador:

  · a sigla varia — `CF`, `CF88`, `CRFB` são a Constituição; `CC`, `CC2002`, `CC-2002` são
    o Código Civil; `CPC`, `CPC2015`, `CPC-2015` e `LF13105-2015` são o mesmo CPC
  · o número varia no enchimento de zeros — `CF:ART:5`, `CF:ART:005`, `CF88:ART:0005`

O resíduo depois da normalização é, em boa parte, citação a artigo que o corpus NÃO TINHA
por truncamento na coleta: `CC:ART:0422`, `CC:ART:0927`, `CC:ART:0186` são artigos reais do
Código Civil, e o corpus trazia 57 dos 2.046 até o item A1 ser corrigido.

Isso não absolve o Q2, que é outro defeito: lá as citações de JULGADO são número-molde
("REsp 1.123.456/PR"), e nenhuma normalização as faz existir.
"""
from __future__ import annotations

import json, re, collections
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Apelidos do mesmo diploma. Cada linha custou uma medição errada antes de existir.
ALIAS = {
    "CF": "CF88", "CRFB": "CF88", "CFRB": "CF88", "CF/88": "CF88", "CFB": "CF88",
    "CC2002": "CC", "CC-2002": "CC", "LF10406-2002": "CC", "CCB": "CC",
    "CPC2015": "CPC", "CPC-2015": "CPC", "LF13105-2015": "CPC",
    "CP1940": "CP", "DL2848-1940": "CP",
    "CPP1941": "CPP", "DL3689-1941": "CPP",
    "CLT1943": "CLT", "DL5452-1943": "CLT",
    "CDC1990": "CDC", "LF8078-1990": "CDC",
    "CTN1966": "CTN", "LF5172-1966": "CTN",
}

# ── Q4 · a forma que o leitor procura ────────────────────────────────────────────────
#
# O índice `CF88:ART:0195` é o que o pipeline resolve; "art. 195 da Constituição Federal" é
# o que uma pessoa escreve e busca, e é a forma em que o modelo vai receber a pergunta na
# prova. Trazer só o índice não é erro de conteúdo, é referência numa língua que ninguém
# fala fora daqui.
#
# O nome sai da própria sigla, sem tabela de 1.887 entradas: as siglas de tipo (LF, LC, DL,
# MP, EC) já dizem a espécie e carregam número e ano, e só os códigos consagrados precisam
# de nome próprio. Este é o mesmo critério do `chave_diploma`: apelido quando consagrado,
# espécie mais número quando não.
NOME_CODIGO = {
    "CF88": "Constituição Federal", "CF": "Constituição Federal",
    "CRFB": "Constituição Federal", "ADCT": "Ato das Disposições Constitucionais Transitórias",
    "CC": "Código Civil", "CPC": "Código de Processo Civil",
    "CP": "Código Penal", "CPP": "Código de Processo Penal",
    "CLT": "Consolidação das Leis do Trabalho", "CTN": "Código Tributário Nacional",
    "CDC": "Código de Defesa do Consumidor", "CTB": "Código de Trânsito Brasileiro",
    "CE": "Código Eleitoral", "CM": "Código Civil", "CBA": "Código Brasileiro de Aeronáutica",
    "LPI": "Lei de Propriedade Industrial", "LEP": "Lei de Execução Penal",
    "CDM": "Código de Minas", "CF88ADCT": "Ato das Disposições Constitucionais Transitórias",
}
ESPECIE = {"LF": "Lei", "L": "Lei", "LEI": "Lei", "LC": "Lei Complementar",
           "LE": "Lei Estadual", "DL": "Decreto-Lei", "D": "Decreto", "DEC": "Decreto",
           "MP": "Medida Provisória", "EC": "Emenda Constitucional",
           "RES": "Resolução", "PORT": "Portaria"}
_RX_SIGLA = re.compile(r"^([A-Z]+?)(\d+)(?:[-/](\d{4}))?$")


# Feminino ou masculino decide entre "da" e "do", e a lista e curta o bastante para ser
# explicita: errar a concordancia num corpus juridico e ruido que o modelo aprende.
_FEMININO = ("Constitui", "Lei", "Consolida", "Emenda", "Medida", "Resolu", "Portaria")


def forma_natural(sigla: str, artigo: str = "") -> str:
    """"CF88", "0195" -> "art. 195 da Constituicao Federal"."""
    s = (sigla or "").upper()
    nome = NOME_CODIGO.get(s) or NOME_CODIGO.get(ALIAS.get(s, ""))
    if not nome:
        m = _RX_SIGLA.match(s)
        if m and m.group(1) in ESPECIE:
            num = f"{int(m.group(2)):,}".replace(",", ".")
            nome = f"{ESPECIE[m.group(1)]} n\u00ba {num}"
            if m.group(3):
                nome += f"/{m.group(3)}"
    if not nome:
        return ""
    a = re.match(r"0*(\d+)([A-Z-]*)$", (artigo or "").upper())
    if not a:
        return nome
    de = "da" if nome.startswith(_FEMININO) else "do"
    # Do 1 ao 9 o artigo vai em ORDINAL ("art. 2\u00ba"), do 10 em diante em cardinal. E
    # regra de redacao legislativa, nao estilo: "art. 2" nao aparece em texto juridico
    # nenhum, e o corpus existe para ensinar a escrever como se escreve.
    num = a.group(1)
    if int(num) < 10:
        num += "\u00ba"
    suf = a.group(2)
    # "0041-XII" e artigo 41, inciso XII — o hifen e do identificador, nao da citacao.
    if suf.startswith("-") and re.fullmatch(r"-[IVXLC]+", suf):
        suf = f", {suf[1:]}"
    return f"art. {num}{suf} {de} {nome}"


REF = re.compile(r"\b([A-Z]{2,8}(?:\d+)?(?:-\d{4})?):ART:(\d{1,4}[A-Z-]*)")
CABECALHO = re.compile(r"<<ID=([^:|]+):ART:(\d{1,4}[A-Z-]*)")


# Zero a esquerda no NUMERO DO DIPLOMA, que e coisa diferente do zero no numero do artigo.
# `LF00978-1999` e `LF978-1999` sao a mesma lei e viravam chaves distintas; pior, o alias
# que leva `DL2848-1940` ao `CP` nao alcancava `DL002848-1940`, entao o Codigo Penal escrito
# com enchimento de zero simplesmente nao resolvia. Sao 120 identificadores recuperaveis so
# por isso.
_RX_DIPLOMA = re.compile(r"^([A-Z]+?)0+(\d+)((?:[-/]\d{4})?)$")


def _sem_zero(sigla: str) -> str:
    m = _RX_DIPLOMA.match(sigla)
    return f"{m.group(1)}{m.group(2)}{m.group(3)}" if m else sigla


def normaliza(sigla: str, numero: str) -> str:
    """Um identificador de artigo na forma canônica: `CC:ART:0422-A`."""
    s = sigla.upper()
    s = ALIAS.get(s) or ALIAS.get(_sem_zero(s)) or _sem_zero(s)
    m = re.match(r"0*(\d+)[-]?([A-Z]*)$", numero.upper())
    if not m:
        return f"{s}:ART:{numero.upper()}"
    suf = f"-{m.group(2)}" if m.group(2) else ""
    return f"{s}:ART:{int(m.group(1)):04d}{suf}"


def indice(caminho: Path) -> set[str]:
    """Os artigos que EXISTEM no corpus, na forma canônica."""
    fora = set()
    for linha in open(caminho, encoding="utf-8"):
        m = CABECALHO.match(json.loads(linha)["text"])
        if m:
            fora.add(normaliza(m.group(1), m.group(2)))
    return fora


def confere(caminho: Path, piso: float = 0.90) -> dict:
    """Quanto das citações resolve. Abaixo do piso, é para recusar a ingestão.

    O piso existe porque a alternativa — ingerir e medir depois — foi o que produziu um
    corpus em que 19 mil citações apontam para lugar nenhum sem que nada reclamasse.
    """
    existe = indice(caminho)
    cita: collections.Counter = collections.Counter()
    for linha in open(caminho, encoding="utf-8"):
        for m in REF.finditer(json.loads(linha)["text"]):
            cita[normaliza(m.group(1), m.group(2))] += 1
    total = sum(cita.values())
    resolve = sum(v for k, v in cita.items() if k in existe)
    frac = resolve / total if total else 1.0
    quebradas = collections.Counter({k: v for k, v in cita.items() if k not in existe})
    return {"artigos_no_corpus": len(existe), "citacoes": total,
            "distintas": len(cita), "resolvem": resolve, "fracao": frac,
            "passa": frac >= piso, "piores": quebradas.most_common(12),
            "por_diploma": collections.Counter(k.split(":")[0] for k in quebradas).most_common(10)}


# ── Q2 · citação de JULGADO inventada
#
# Aqui a regra do artigo NÃO serve, e confundir as duas produz medição errada. O corpus
# pretende conter os códigos inteiros, então artigo citado e ausente é defeito. Já os
# julgados são amostra de um universo de centenas de milhares: o corpus tem 5.181 distintos,
# e um REsp real que não esteja nele não prova invenção nenhuma.
#
# O que PROVA invenção é o número. Medido nas 14.794 fichas de norma: das 3.472 citações de
# julgado, 1.205 (34,7%) trazem número com padrão de dígito — `REsp 1.234.567` sozinho
# aparece 538 vezes, e há `987654`, `1.845.678`, `1.823.456`, `123456`. Nenhum tribunal
# numera assim; são o molde que o gerador usa quando não tem o dado.
CIT_JULGADO = re.compile(
    r"\b(REsp|AREsp|RE|ARE|HC|RHC|MS|AI|Rcl|ADI|ADC|ADPF|EREsp|AgRg)\s*"
    r"n?[ºo°]?\s*([\d][\d.]{2,})", re.IGNORECASE)


def numero_molde(numero: str) -> bool:
    """O número é sequência de dígitos, e não um número de processo.

    Quatro dígitos consecutivos subindo ou descendo (1234, 4321), ou o número inteiro
    feito de no máximo dois algarismos distintos (111222). É deliberadamente estreito:
    um processo real pode ter dois dígitos em sequência por acaso, quatro não.
    """
    d = re.sub(r"\D", "", numero)
    if len(d) < 4:
        return False
    for i in range(len(d) - 3):
        j = d[i:i + 4]
        if all(int(j[k + 1]) - int(j[k]) == 1 for k in range(3)):
            return True
        if all(int(j[k]) - int(j[k + 1]) == 1 for k in range(3)):
            return True
    return len(set(d)) <= 2


def julgados_inventados(texto: str) -> list[str]:
    """As citações de julgado com número-molde dentro de um documento."""
    return [f"{m.group(1).upper()} {m.group(2)}"
            for m in CIT_JULGADO.finditer(texto) if numero_molde(m.group(2))]


def spans_julgados_inventados(texto: str) -> list[tuple[int, int]]:
    """As mesmas citações, como (início, fim) no texto.

    `julgados_inventados` devolve o rótulo NORMALIZADO — "RESP 1.234.567" em maiúsculas —
    que serve para contar e agrupar e não para achar no texto: a ficha escreve "REsp
    1.123.456", e `texto.find` do rótulo falha. Quem for REMOVER a citação precisa da
    posição, e ela sai daqui para a regra de deteccão continuar num lugar só.
    """
    return [m.span() for m in CIT_JULGADO.finditer(texto) if numero_molde(m.group(2))]


def confere_julgados(caminho: Path) -> dict:
    total = inventadas = docs = docs_ruins = 0
    quais: collections.Counter = collections.Counter()
    for linha in open(caminho, encoding="utf-8"):
        texto = json.loads(linha)["text"]
        if "TYPE=ART" not in texto[:200] and ":ART:" not in texto[:120]:
            continue
        docs += 1
        achadas = julgados_inventados(texto)
        total += sum(1 for _ in CIT_JULGADO.finditer(texto))
        if achadas:
            docs_ruins += 1
            inventadas += len(achadas)
            quais.update(re.sub(r"[^0-9A-Z ]", "", a.upper()) for a in achadas)
    return {"fichas": docs, "fichas_com_invencao": docs_ruins, "citacoes": total,
            "inventadas": inventadas, "distintos": len(quais),
            "sobrevivem": _sobrevivem_a_montagem(caminho),
            "piores": quais.most_common(10)}


def _sobrevivem_a_montagem(caminho: Path) -> int:
    """Quantas citações fabricadas ainda estariam no corpus DEPOIS da montagem.

    Existe porque as duas perguntas são diferentes e confundi-las dá uma resposta falsa nos
    dois sentidos. O artefato congelado de `data/ablacao_regime/` guarda 1.205, e não pode
    ser mexido: ele é a entrada das 162 condições já medidas. O que importa para o próximo
    treino é o que `rechunk_v4.py` entrega, e lá a citação sai. Relatar só o primeiro número
    faz a correção parecer não ter acontecido; relatar só o segundo esconde o que está
    gravado no disco hoje.
    """
    import sys as _s
    _s.path.insert(0, str(RAIZ / "augmentation"))
    try:
        from sanitize import remove_julgado_inventado
    except ImportError:
        return -1
    resto = 0
    for linha in open(caminho, encoding="utf-8"):
        texto = json.loads(linha)["text"]
        if "TYPE=ART" not in texto[:200] and ":ART:" not in texto[:120]:
            continue
        sp = spans_julgados_inventados(texto)
        if sp:
            resto += len(spans_julgados_inventados(remove_julgado_inventado(texto, sp)))
    return resto


if __name__ == "__main__":
    import sys
    alvo = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "data/ablacao_regime/expandido_completo.jsonl"
    r = confere(alvo)
    print(f"{alvo.name}")
    print(f"  artigos no corpus: {r['artigos_no_corpus']:,}")
    print(f"  citações: {r['citacoes']:,} ({r['distintas']:,} distintas)")
    print(f"  resolvem: {r['resolvem']:,} ({r['fracao']:.1%})  {'PASSA' if r['passa'] else 'ABAIXO DO PISO'}")
    print(f"  não resolvem: {r['citacoes'] - r['resolvem']:,}")
    print(f"  por diploma: {dict(r['por_diploma'])}")
    print(f"  mais citados que não existem: {[k for k, _ in r['piores'][:6]]}")
    j = confere_julgados(alvo)
    print(f"\n  citação de julgado nas fichas de norma:")
    print(f"    fichas varridas: {j['fichas']:,} · com citação inventada: {j['fichas_com_invencao']:,}")
    print(f"    citações {j['citacoes']:,} · com número-molde {j['inventadas']:,} "
          f"({100*j['inventadas']/max(j['citacoes'],1):.1f}%) em {j['distintos']} identificadores")
    print(f"    piores: {[k for k, _ in j['piores'][:6]]}")
