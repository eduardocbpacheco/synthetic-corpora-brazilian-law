"""
Prompts do juiz LLM no estilo Rabula (paper LLM-as-Judge in BR Legal Domain).

Reproduz fielmente o template do `Experiment 1 - Judges.ipynb` cell 13 e 25:
- Uma única chamada por questão (não por critério)
- JSON estruturado de saída com `resultado` contendo todos critérios + acerto + raciocínio
- Persona: examinador e professor de direito com 10 anos de profissão
- Cache buster (token hex + soma trivial) para evitar cache hit do provedor
"""

PROMPT_DISCURSIVA = """Na segunda fase do exame da Ordem dos Advogados do Brasil o candidato deve responder a questões discursivas.

Você será o avaliador da resposta do candidato. Receberá 3 campos: 'gabarito', 'criterios' e 'resposta_candidato'.
O campo 'gabarito' é a referência oficial de resposta. O campo 'criterios' define os critérios objetivos para conferição de pontuação e o campo resposta_candidato contém a resposta do candidato.

A persona que irá adotar para avaliar é uma examinador e professor de direito experiente com 10 anos de profissão.

Instruções de resposta:
1. A resposta deve ser um json com o campo 'resultado' cujo conteúdo tem a mesma estrutura do JSON com os critérios mas com três campos a mais em cada linha: 'acerto', que pode ser 0 ou 1 a depender se o candidato satisfez o critério, 'raciocinio', que contém o motivo da decisão, resumidamente e 'cache_beaker' contém a soma entre {num1} e {num2} .
2. Os critérios de nota estão definidos no campo 'criterios'. Nele, há quanto cada cumprimento de critério confere de pontuação.
3. O critério contém referências às letras da questão (A, B, C) e a parte dessa mesma questão, que funciona como um pedaço da questão.

REGRAS IMPORTANTES DE AVALIAÇÃO (cumpra todas):
- Quando o critério contiver alternativas separadas por "ou" (ex.: "Art. X da CRFB/88 ou Súmula Vinculante nº Y"), QUALQUER UMA das alternativas é suficiente para acerto=1. NÃO exija que o candidato cite todas.
- Aceite paráfrases corretas e variações de redação do gabarito (ex.: "art. 71, III, da Constituição Federal" = "Art. 71, inciso III, da CRFB/88" = "artigo 71, III, CF").
- Avalie o CONCEITO jurídico, não o match literal. Se o candidato expressou a ideia certa com outras palavras, é acerto=1.
- Para critérios de citação legal: se o gabarito lista N referências como alternativas (com "ou"), basta o candidato citar 1 delas — mesmo que com formato ligeiramente diferente — para acerto=1.
- Se o gabarito lista N elementos COM "e" (cumulativos), aí sim exija TODOS.

A resposta final não deve ter '''json porque isso quebra a lógica.

{cache_buster}

RESPOSTA CANDIDATO
´´´ {resposta_candidato} ´´´

GABARITO
´´´ {gabarito} ´´´

CRITERIOS
´´´ {criterios} ´´´

JSON resposta: """


PROMPT_DOCUMENT_WRITING = """Na segunda fase do exame da Ordem dos Advogados do Brasil o candidato deve redigir uma peça processual para resolver um caso prático.

Você será o avaliador da resposta do candidato. Receberá 3 campos: 'gabarito', 'criterios' e 'resposta_candidato'.
O campo 'gabarito' é a referência oficial de resposta. O campo 'criterios' define os critérios objetivos para conferição de pontuação e o campo 'resposta_candidato' contém a resposta do candidato.

A persona que irá adotar para avaliar é uma examinador e professor de direito experiente com 10 anos de profissão.

Instruções de resposta:
1. A resposta deve ser um json com o campo 'resultado' cujo conteúdo tem a mesma estrutura do JSON com os critérios mas com três campos a mais em cada linha: 'acerto', que pode ser 0 ou 1 a depender se o candidato satisfez o critério, 'raciocinio', que contém o motivo da decisão, resumidamente e 'cache_beaker' contém a soma entre {num1} e {num2} .
2. Os critérios de nota estão definidos no campo 'criterios'. Há linhas com cada critério de correção e o ponto correspondente em caso de acerto.

REGRAS IMPORTANTES DE AVALIAÇÃO (cumpra todas):
- Quando o critério contiver alternativas separadas por "ou" (ex.: "Art. X da CRFB/88 ou Súmula Vinculante nº Y"), QUALQUER UMA das alternativas é suficiente para acerto=1. NÃO exija que o candidato cite todas.
- Aceite paráfrases corretas e variações de redação do gabarito.
- Avalie o CONCEITO jurídico, não o match literal. Se o candidato expressou a ideia certa com outras palavras, é acerto=1.
- Para critérios de citação legal alternativos (separados por "ou"): basta o candidato citar 1 das opções.
- Se o gabarito lista N elementos COM "e" (cumulativos), aí sim exija TODOS.

A resposta final não deve ter '''json porque isso quebra a lógica.

{cache_buster}

RESPOSTA CANDIDATO
´´´ {resposta_candidato} ´´´

GABARITO
´´´ {gabarito} ´´´

CRITERIOS
´´´ {criterios} ´´´

JSON resposta: """


PROMPT_ANSWER_DISCURSIVA = """Você receberá um exercício da segunda fase do exame da Ordem dos Advogados do Brasil (OAB).
Trata-se da questão discursiva, em que se pede que o candidato escreva a resposta para um problema jurídico.

Sua tarefa é escrever a resposta.

Instruções de resposta:
1. A resposta deve ser um json com 2 campos 'resposta' e 'raciocinio'.
2. Inclua no campo "raciocinio" o racional que levou à resposta.
3. O campo "resposta" deve conter a resposta à questão discursiva. Essa resposta é uma lista de json em que cada elemento tem como chave a letra da questão e o valor é a resposta.

A resposta final não deve ter '''json porque isso quebra a lógica.

QUESTÃO
´´´ {questao} ´´´
JSON resposta: """


PROMPT_ANSWER_DOCUMENT_WRITING = """Você receberá um exercício da segunda fase do exame da Ordem dos Advogados do Brasil (OAB).
Trata-se do exercício prático, em que se pede que o candidato escreva uma peça jurídica adequada para resolver o problema.

Sua tarefa é escrever a peça em si.

Instruções de resposta:
1. A resposta deve ser um json com 2 campos 'resposta' e 'raciocinio'.
2. Inclua no campo "raciocinio" um resumo da peça escolhida e os argumentos levantados.
3. O campo "resposta" deve conter diretamente a peça processual que responda adequadamente ao caso.

A resposta final não deve ter '''json porque isso quebra a lógica.

QUESTÃO
´´´ {questao} ´´´
JSON resposta: """
