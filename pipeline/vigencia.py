#!/usr/bin/env python3
"""vigencia.py — o estado de vigência como CAMPO, e não como varredura de texto.

V5 · O critério é do usuário e é transversal: só entra no corpus o que já foi julgado e
está em vigor. Ensinar tese em discussão é como ensinar projeto de lei junto com lei.

Cada fonte grava esse estado de um jeito, e nenhuma chama a coluna do mesmo nome:

    súmula do STF     `situacao_sumula`        Aprovada · Cancelada · Superada · Alterada
    súmula do STJ     `situacao`               vigente
    IRDR do TJSP      `status`                 tese_firmada · revogado · admitido_pendente
    tema de RG        `ha_repercussao_geral`   Sim · Não · (vazio)
    artigo de lei     (nenhuma)                a marca está no corpo do texto
    enunciado         (nenhuma)                quem cancela é OUTRO verbete

Enquanto isso for descoberto caso a caso, cada leitor reimplementa a regra e erra de um
jeito diferente. Errei três vezes hoje, e as três merecem estar escritas aqui porque são o
motivo deste módulo existir:

  · procurei a marca de revogação ANTES do número do artigo, e em artigo vetado ela vem
    depois — conclui "54 artigos perdidos" quando era 1;
  · contei `revogado` como marca solta de texto e achei 1.038 fichas com dispositivo
    revogado, quando os artigos revogados POR INTEIRO são 44; o resto é artigo em vigor
    com um inciso revogado, que deve ficar;
  · varri a palavra `revogado` nos enunciados e marquei o CJF 595, que é o vivo, o que
    revogou o 499 — o morto não traz marca nenhuma, e a varredura ia excluir o certo e
    manter o errado.

Os três erros têm a mesma raiz: inferir estado a partir de texto. Aqui o estado é declarado.
"""
from __future__ import annotations

import re

# O vocabulário. Só `EM_VIGOR` entra no corpus; os demais são motivos distintos de exclusão
# e ficam separados porque a distinção é informação — o C8 mostrou que 136 temas sem tese
# são processo em curso e não falha de coleta, e isso só se sabe se os estados não se
# confundem.
EM_VIGOR = "em vigor"
REVOGADO = "revogado"
CANCELADO = "cancelado"
SUPERADO = "superado"
PENDENTE = "pendente de julgamento"
NAO_VINCULANTE = "não vinculante"      # existe, é final, mas não é precedente obrigatório
DESCONHECIDO = "desconhecido"

ENTRA = {EM_VIGOR, NAO_VINCULANTE}

# Por fonte: o campo que carrega o estado e como o valor dela se traduz. `None` no valor
# significa "trate como em vigor", que é o padrão das fontes que só listam o que vale.
MAPA = {
    "situacao_sumula": {"aprovada": EM_VIGOR, "alterada": EM_VIGOR,
                        "cancelada": CANCELADO, "superada": SUPERADO,
                        "publicação suspensa": SUPERADO},
    "situacao": {"vigente": EM_VIGOR, "cancelada": CANCELADO, "revogada": REVOGADO},
    "status": {"tese_firmada": EM_VIGOR, "revogado": REVOGADO, "cancelado": CANCELADO,
               "admitido_pendente": PENDENTE, "suspenso": PENDENTE},
}

# Artigo cujo corpo é só a nota de revogação ou de veto. Duas notações convivem: o
# parêntese e a etiqueta que a CF/88 usa. Ver o segundo erro citado no cabeçalho — a marca
# solta de texto NÃO serve, porque artigo em vigor cita inciso revogado o tempo todo.
_SO_REVOGACAO = re.compile(
    r"^\s*(?:Art\.?|Artigo)\s*[\d.]+\s*[ºo°]?\s*[\.\-–]?\s*"
    r"(?:[\(\[]?\s*(?:Revogad[oa]|VETADO)\b.{0,200}"
    r"|<\s*revogad[oa]\s*>\s*</\s*revogad[oa]\s*>"
    r"|<\s*vetado\s*>\s*</\s*vetado\s*>)\s*[\)\]]?\s*$",
    re.IGNORECASE | re.DOTALL)


def de_registro(d: dict) -> str:
    """O estado declarado pela fonte, traduzido para o vocabulário comum."""
    # Unidade que JÁ carrega o estado no vocabulário comum manda. É o ponto do V5: quem
    # colheu sabia mais do que o tradutor consegue inferir depois. O crawler do TJPR lê a
    # vigência da PÁGINA de procedência — `irdr-julgados` contra `irdr-em-andamento` — e
    # grava `situacao` como o tribunal escreveu, "TRANSITADO EM JULGADO". Sem esta linha o
    # tradutor não reconheceria essa frase, devolveria `desconhecido` e os 60 incidentes
    # seriam descartados por um filtro que existe para descartar o que está revogado.
    if d.get("vigencia") in ENTRA or d.get("vigencia") in (REVOGADO, CANCELADO, SUPERADO, PENDENTE):
        return d["vigencia"]
    for campo, traducao in MAPA.items():
        if campo in d and d.get(campo):
            return traducao.get(str(d[campo]).strip().lower(), DESCONHECIDO)
    return EM_VIGOR


def de_tema_rg(d: dict) -> str:
    """Tema de repercussão geral: três estados distintos, e confundi-los custou o B8.

    Sem tese publicada é processo EM CURSO. Com repercussão negada existe decisão final,
    ela só não gera precedente vinculante — e por isso entra, com rótulo próprio, em vez de
    ser descartada.
    """
    if not str(d.get("tese") or "").strip():
        return PENDENTE
    neg = str(d.get("ha_repercussao_geral", "")).strip().lower() in ("não", "nao", "no", "false")
    return NAO_VINCULANTE if neg else EM_VIGOR


def de_artigo(texto_artigo: str) -> str:
    return REVOGADO if _SO_REVOGACAO.match((texto_artigo or "").strip()) else EM_VIGOR


def entra_no_corpus(estado: str) -> bool:
    return estado in ENTRA


if __name__ == "__main__":
    import json
    from pathlib import Path
    RAIZ = Path(__file__).resolve().parent.parent
    print(f"{'fonte':28s} {'registros':>10s}  estados")
    for nome, arq in (("súmula do STF", "decisoes/stf/sumulas_nao_vinculantes.jsonl"),
                      ("súmula vinculante do STF", "decisoes/stf/sumulas_vinculantes.jsonl"),
                      ("súmula do STJ", "decisoes/stj/sumulas_stj.jsonl"),
                      ("IRDR do TJSP", "decisoes/irdr_iac/tjsp_irdrs_oficiais.jsonl")):
        p = RAIZ / arq
        if not p.exists():
            continue
        L = [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]
        import collections
        c = collections.Counter(de_registro(d) for d in L)
        print(f"{nome:28s} {len(L):10,d}  {dict(c)}")
    p = RAIZ / "decisoes/stf/repercussao_geral.jsonl"
    if p.exists():
        L = [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]
        import collections
        c = collections.Counter(de_tema_rg(d) for d in L if d.get("descricao"))
        print(f"{'tema de repercussão geral':28s} {sum(c.values()):10,d}  {dict(c)}")
