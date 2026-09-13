"""
prompt_padrao.py — FONTE ÚNICA do prompt de resposta. Treino e avaliação importam daqui.

Motivo de existir: em 21/08/2026 medimos 11 prompts de system distintos nos datasets de
SFT (três jeitos de dizer "discursiva em prosa sem Markdown", quatro de dizer "peça com
estrutura formal") e o turno do usuário partido entre 5.913 exemplos com prefixo
"### CASO ###" e 10.951 crus. A avaliação, por sua vez, usava um décimo-segundo prompt,
genérico e igual para os dois gêneros. Ou seja: o modelo era treinado com uma instrução
e cobrado com outra, e dentro do treino via a mesma instrução em variantes sinônimas.

Isso é ruído em dois lugares. No treino, dilui o sinal de gênero entre variantes. Na
avaliação, remove a pista que ensinou o modelo a escolher o gênero — o que subestima o
efeito do SFT, e subestima de forma assimétrica entre discursiva e peça.

REGRA: nenhum script define prompt de resposta localmente. Quem gera dado de treino e
quem gera resposta para avaliação chamam `system_de()` e `usuario()` daqui. Se este
arquivo mudar, os datasets de SFT precisam ser renormalizados E os adapters retreinados,
porque adapter treinado num prompt não é comparável a avaliação em outro.

Nota de desenho: no gênero peça o system enuncia a estrutura formal. Isso vale para
TODAS as condições, inclusive o modelo base não treinado — e é o correto: sem isso, o
modelo treinado levava vantagem por saber o esqueleto que ao base ninguém contou, e o
ganho em critério formal ficava inflado. Com a pista dada a todos, o que sobra de
diferença é aprendizado, não conhecimento de formato vindo do prompt.
"""
from __future__ import annotations

VERSAO = "2026-08-21"

# Consolidados a partir das variantes dominantes medidas nos datasets, preservando toda
# restrição substantiva (prosa, ausência de Markdown, ausência de lacuna, citação inline).
SYSTEM: dict[str, str] = {
    "discursiva": (
        "Você é um advogado especialista respondendo questões discursivas da OAB 2ª fase.\n"
        "REGRAS: prosa técnica corrida, SEM Markdown (nunca ** ou ##), SEM placeholders "
        "entre colchetes, SEM cabeçalhos numerados; cite dispositivos legais inline "
        "(ex: 'conforme o art. 5º da CF')."
    ),
    "peca": (
        "Você é um advogado experiente redigindo peças jurídicas para a OAB 2ª fase.\n"
        "REGRAS: estrutura formal (endereçamento, qualificação, fatos, direito, pedidos, "
        "fecho); TEXTO PURO, SEM Markdown (sem ** ou ##); endereçamento e títulos de seção "
        "em CAIXA ALTA; pedidos em alíneas a) b) c).\n"
        "PROIBIDO deixar lacuna para preencher: nada de [Nome do Advogado], [Cidade], "
        "[Data], [OAB/UF nº], linha pontilhada ou XXX. A peça sai PRONTA — invente nome, "
        "cidade, data e número de inscrição plausíveis e escreva-os por extenso."
    ),
    "parecer": (
        "Você é advogado público redigindo parecer jurídico para consulta da administração.\n"
        "REGRAS: relatório da consulta, análise jurídica fundamentada e conclusão objetiva; "
        "TEXTO PURO, SEM Markdown, SEM placeholders entre colchetes."
    ),
    "sentenca": (
        "Você é magistrado redigindo sentença.\n"
        "REGRAS: relatório, fundamentação e dispositivo; TEXTO PURO, SEM Markdown, "
        "SEM placeholders entre colchetes."
    ),
}

# Rótulos equivalentes que circulam no repositório (dataset, benchmark, código do Rabula).
ALIAS: dict[str, str] = {
    "dissertacao": "discursiva", "dissertação": "discursiva", "discursive": "discursiva",
    "peça": "peca", "document_writing": "peca", "practical": "peca",
    "sentença": "sentenca",
}


def canonico(tipo: str) -> str:
    t = (tipo or "discursiva").strip().lower()
    return ALIAS.get(t, t)


def system_de(tipo: str) -> str:
    """System prompt do gênero. Gênero desconhecido cai em discursiva, o mais frequente."""
    return SYSTEM.get(canonico(tipo), SYSTEM["discursiva"])


def usuario(enunciado: str) -> str:
    """Turno do usuário: enunciado cru.

    Escolhido cru e não com prefixo "### CASO ###" porque cru era a maioria dos exemplos
    (10.951 contra 5.913) e já era o formato da avaliação — menos coisa para divergir.
    """
    return (enunciado or "").strip()


def mensagens(tipo: str, enunciado: str) -> list[dict]:
    return [{"role": "system", "content": system_de(tipo)},
            {"role": "user", "content": usuario(enunciado)}]
