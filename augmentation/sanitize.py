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

    return "\n".join(saida).strip()


REGRA_FORMATO = (
    "\nFORMATO DE SAÍDA (obrigatório): responda APENAS com os blocos, começando "
    "direto no primeiro marcador <<ID=...>>. Sem preâmbulo, sem comentário final. "
    "TEXTO PURO — proibido markdown: nada de **negrito**, nada de ### títulos, "
    "nada de --- separadores. O marcador <<ID=...>> e o rótulo [BLOCO] ficam cada "
    "um sozinho em sua linha, exatamente como no modelo.\n"
)
