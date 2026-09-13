"""
prompts.py — Prompts de expansão semântica para normas, jurisprudência e casos.

Cada prompt segue o DNA do hub semântico:
  - IDs estruturais <<ID=...|DOC=...|TYPE=...|PARENT=...>> para grafo futuro
  - Conteúdo íntegro (sem resumir o texto canônico)
  - 6-10 Q&A com 3 vias: direta / inversa / implícita
  - Aterramento factual: usa SOMENTE o que está no documento fornecido
"""

# ── NORMAS ─────────────────────────────────────────────────────────────────────
# Usado para: CF88, códigos, leis federais, leis SP
# Input: artigo isolado com texto completo

PROMPT_NORMA = """\
Quero produzir um corpus explicativo derivado de normas jurídicas brasileiras. \
Você receberá, entre ''', um artigo de lei e deverá escrever um texto de expansão \
no formato abaixo. A unidade semântica central (o "hub") é o ARTIGO; todos os \
demais blocos o circundam, criando múltiplas vias linguísticas de associação até ele.

<<ID={doc_id}:ART:{num_art:04d}|DOC={doc_id}|TYPE=ART|PARENT={doc_id}>>
[NORMA]
{identificacao}

[CONTEÚDO]
(Texto integral e literal do artigo — NUNCA resuma este bloco.)

<<ID={doc_id}:ART:{num_art:04d}:EXPL|DOC={doc_id}|TYPE=EXPL|PARENT={doc_id}:ART:{num_art:04d}>>
[EXPLICAÇÃO]
Detalhamento analítico do significado, elementos normativos, sujeitos, condutas \
obrigadas/proibidas/permitidas e princípios subjacentes.

<<ID={doc_id}:ART:{num_art:04d}:SYN|DOC={doc_id}|TYPE=SYN|PARENT={doc_id}:ART:{num_art:04d}>>
[SÍNTESE]
Núcleo normativo em 2-3 frases: o que o artigo determina e por quê importa.

<<ID={doc_id}:ART:{num_art:04d}:REL|DOC={doc_id}|TYPE=REL|PARENT={doc_id}:ART:{num_art:04d}>>
[RELAÇÃO COM OUTRAS NORMAS]
5 a 15 dispositivos relacionados, cada um com ID estrutural e explicação do vínculo:
- {doc_id}:ART:XXXX (Art. X) — tipo de relação e justificativa.
(Apenas relações fundamentadas; na dúvida, omita.)

<<ID={doc_id}:ART:{num_art:04d}:EFFECT|DOC={doc_id}|TYPE=EFFECT|PARENT={doc_id}:ART:{num_art:04d}>>
[EFEITO PRÁTICO]
Como o artigo é aplicado na prática: que condutas orienta, que consequências gera, \
como aparece em decisões judiciais e políticas públicas.

<<ID={doc_id}:ART:{num_art:04d}:JURIS|DOC={doc_id}|TYPE=JURIS|PARENT={doc_id}:ART:{num_art:04d}>>
[JURISPRUDÊNCIA]
3 a 8 decisões, súmulas ou teses que interpretam este artigo. Para cada uma:
- IDENTIFICADOR (ex: JURIS:STF:RG:TEMA0999): síntese do entendimento fixado.
REGRA CRÍTICA: cite APENAS precedentes de cuja existência você tem alta confiança. \
Na dúvida, omita — jamais invente número de ADI/RE/Súmula/Tema.

<<ID={doc_id}:ART:{num_art:04d}:QA:001|DOC={doc_id}|TYPE=QA|PARENT={doc_id}:ART:{num_art:04d}>>
[PERGUNTA]
(direta — cita o artigo explicitamente)
[RESPOSTA]
(resposta correspondente)

(Repita o bloco QA para 6 a 10 perguntas, garantindo:
 - ao menos 2 DIRETAS: a pergunta cita o artigo; a resposta traz o conteúdo/efeito
 - ao menos 2 INVERSAS: descreve a situação SEM citar o número; a resposta identifica o artigo
 - ao menos 2 IMPLÍCITAS: artigo dedutível pelo contexto, sem menção explícita)

---
Documento (artigo a expandir):
\'\'\'{documento}\'\'\'

Instruções:
1. Gere o texto de expansão seguindo exatamente o formato e a ordem dos blocos acima.
2. Em [CONTEÚDO], preserve o texto integral do artigo sem alterações.
3. Adapte os IDs ao documento real (ex: CF88, CDC, CP, CLT).
4. ATERRAMENTO FACTUAL: em [JURISPRUDÊNCIA] cite apenas precedentes de cuja existência \
você tem alta confiança. Na dúvida, omita.
5. Gere 6 a 10 pares Q&A com as três vias de associação.
"""


# ── JURISPRUDÊNCIA ─────────────────────────────────────────────────────────────
# Usado para: RG STF (teses), temas repetitivos STJ, súmulas STF/STJ
# Input: enunciado/tese + material de apoio fornecido

PROMPT_JURISPRUDENCIA = """\
Quero produzir um corpus explicativo derivado de jurisprudência de peso institucional: \
súmulas (vinculantes e não vinculantes), teses de repercussão geral (STF) e temas \
repetitivos (STJ). Você receberá, entre ''', o enunciado/tese e o material de apoio \
de um precedente e deverá escrever um texto de expansão no formato abaixo. \
A unidade semântica central (o "hub") é a TESE/PRECEDENTE.

<<ID={juris_id}|DOC={juris_id}|TYPE=PREC|PARENT=NULL>>
[IDENTIFICAÇÃO]
Tipo: {tipo} | Tribunal: {tribunal} | {identificador_label}: {identificador_valor} | \
Área: {area} | Status: {status_vinculante}.

[ENUNCIADO / TESE]
(Texto integral e literal da tese firmada / enunciado da súmula — NUNCA resuma.)

<<ID={juris_id}:CONTEXT|DOC={juris_id}|TYPE=CONTEXT|PARENT={juris_id}>>
[CONTEXTO / QUESTÃO RESOLVIDA]
Qual era a controvérsia jurídica e o que motivou a fixação da tese.

<<ID={juris_id}:RATIO|DOC={juris_id}|TYPE=RATIO|PARENT={juris_id}>>
[FUNDAMENTAÇÃO DETERMINANTE]
Os fundamentos que sustentam a tese — a ratio que a torna obrigatória.

<<ID={juris_id}:NORMREF|DOC={juris_id}|TYPE=NORMREF|PARENT={juris_id}>>
[NORMAS INTERPRETADAS]
5 a 15 dispositivos que o precedente interpreta/concretiza, com ID estrutural:
- CF88:ART:0005 (Art. 5º, CF) — papel na fundamentação.
(Apenas os efetivamente interpretados; na dúvida, omita.)

<<ID={juris_id}:SCOPE|DOC={juris_id}|TYPE=SCOPE|PARENT={juris_id}>>
[ALCANCE E EFEITOS]
Quem a tese vincula, abrangência objetiva, eventual modulação, hipóteses de não incidência. \
Explicite se é vinculante (art. 103-A CF / art. 927 CPC) ou apenas persuasivo.

<<ID={juris_id}:RELPREC|DOC={juris_id}|TYPE=RELPREC|PARENT={juris_id}>>
[PRECEDENTES RELACIONADOS]
Precedentes correlatos, de superação (overruling) ou distinção (distinguishing), com ID:
- JURIS:STF:RG:TEMA0XXX — relação e sentido.
REGRA CRÍTICA: inclua apenas precedentes citados no material fornecido ou de cuja \
existência você tem alta confiança. Na dúvida, omita.

<<ID={juris_id}:APPLIC|DOC={juris_id}|TYPE=APPLIC|PARENT={juris_id}>>
[APLICAÇÃO PRÁTICA]
Como instâncias inferiores devem aplicar a tese; situações típicas; consequências do descumprimento.

<<ID={juris_id}:QA:001|DOC={juris_id}|TYPE=QA|PARENT={juris_id}>>
[PERGUNTA]
(direta — cita o tema/súmula pelo número)
[RESPOSTA]
(resposta correspondente)

(Repita o bloco QA para 6 a 10 perguntas, garantindo:
 - ao menos 2 DIRETAS: cita o número do tema/súmula; resposta traz a tese
 - ao menos 2 INVERSAS: descreve a questão jurídica SEM citar o número; resposta identifica o precedente
 - ao menos 2 IMPLÍCITAS: precedente dedutível pelo contexto)

---
Tipo de jurisprudência: \'\'\'{tipo}\'\'\'
Documento (enunciado/tese + material de apoio):
\'\'\'{documento}\'\'\'

Instruções:
1. Gere o texto seguindo exatamente o formato e a ordem acima.
2. O [ENUNCIADO / TESE] deve ser literal ao documento — nunca altere a redação.
3. Adapte os IDs: súmula vinculante = JURIS:STF:SUM:VINC:XXXX; \
súmula comum STF = JURIS:STF:SUM:XXXX; STJ = JURIS:STJ:SUM:XXXX; \
RG STF = JURIS:STF:RG:TEMAXXX; tema STJ = JURIS:STJ:REP:TEMAXXX.
4. Em [NORMAS INTERPRETADAS] e [PRECEDENTES RELACIONADOS], cite apenas o que está \
no documento ou do que você tem alta confiança — jamais fabrique identificadores.
5. Deixe explícito em [ALCANCE E EFEITOS] se é vinculante ou persuasivo.
6. Gere 6 a 10 Q&A com as três vias de associação.
"""


# ── CASOS ──────────────────────────────────────────────────────────────────────
# Usado para: TJSP 2 grau, TJRJ acórdãos, decisões quaisquer
# Input: metadados + ementa/conteúdo da decisão

PROMPT_CASO = """\
Quero produzir um corpus explicativo derivado de decisões judiciais individuais \
(sentenças e acórdãos de casos concretos, de qualquer instância). Você receberá, \
entre ''', os metadados e o conteúdo de uma decisão e deverá escrever um texto de \
expansão no formato abaixo. A unidade semântica central (o "hub") é a DECISÃO.

<<ID={case_id}|DOC={case_id}|TYPE=CASE|PARENT=NULL>>
[IDENTIFICAÇÃO]
Tribunal/Órgão: {tribunal} | Instância: {instancia} | Tipo: {tipo_acao} | \
Processo: {processo} | Data: {data} | Área: {area}.

[CONTEÚDO]
(Ementa e trechos essenciais do inteiro teor — não resuma o que está aqui.)

<<ID={case_id}:FACTS|DOC={case_id}|TYPE=FACTS|PARENT={case_id}>>
[FATOS]
Síntese do quadro fático extraível da decisão: partes, o que ocorreu, qual o pedido.

<<ID={case_id}:ISSUE|DOC={case_id}|TYPE=ISSUE|PARENT={case_id}>>
[QUESTÃO JURÍDICA]
A controvérsia central que a decisão precisou resolver, formulada como pergunta jurídica.

<<ID={case_id}:RATIO|DOC={case_id}|TYPE=RATIO|PARENT={case_id}>>
[FUNDAMENTAÇÃO / RAZÃO DE DECIDIR]
Os fundamentos determinantes (ratio decidendi). Separe da ratio eventuais obiter dicta.

<<ID={case_id}:DISP|DOC={case_id}|TYPE=DISP|PARENT={case_id}>>
[DECISÃO / DISPOSITIVO]
O resultado: procedência/improcedência/provimento, condenações, valores, comando final.

<<ID={case_id}:NORMREF|DOC={case_id}|TYPE=NORMREF|PARENT={case_id}>>
[NORMAS APLICADAS]
Normas que fundamentaram a decisão, cada uma com ID estrutural:
- CF88:ART:0005 (Art. 5º, XXXII, CF) — papel na decisão.
REGRA CRÍTICA: inclua APENAS normas efetivamente citadas ou inequivocamente aplicadas \
na decisão. Nunca invente dispositivos não presentes no documento.

<<ID={case_id}:PRECREF|DOC={case_id}|TYPE=PRECREF|PARENT={case_id}>>
[PRECEDENTES APLICADOS]
Súmulas, teses RG ou temas repetitivos invocados, com ID estrutural:
- JURIS:STJ:SUM:0297 — aplicada para reconhecer relação de consumo.
REGRA CRÍTICA: apenas os efetivamente citados na decisão.

<<ID={case_id}:EFFECT|DOC={case_id}|TYPE=EFFECT|PARENT={case_id}>>
[EFEITO PRÁTICO]
O que esta decisão orienta em casos semelhantes. Deixe claro que é caso individual \
sem efeito vinculante — diferente de súmula/tese de RG.

<<ID={case_id}:QA:001|DOC={case_id}|TYPE=QA|PARENT={case_id}>>
[PERGUNTA]
(direta — referencia o caso ou processo)
[RESPOSTA]
(resposta correspondente)

(Repita o bloco QA para 6 a 10 perguntas, garantindo:
 - ao menos 2 DIRETAS: cita o caso/processo; resposta traz desfecho ou fundamento
 - ao menos 2 INVERSAS: descreve fatos/resultado SEM citar o número; resposta identifica norma/precedente
 - ao menos 2 IMPLÍCITAS: caso e fundamento dedutíveis pelo contexto)

---
Documento (metadados + decisão):
\'\'\'{documento}\'\'\'

Instruções:
1. Gere o texto de expansão seguindo exatamente o formato e a ordem acima.
2. Em [CONTEÚDO], preserve ementa e trechos essenciais sem resumir.
3. Adapte IDs ao tribunal e número do processo (ex: CASE:TJSP:2023.0012345-6).
4. ATERRAMENTO FACTUAL — REGRA CRÍTICA: use SOMENTE o que está no documento.
   Não invente número de processo, nome de relator, data, normas ou precedentes.
5. Distinga ratio decidendi de obiter dictum na [FUNDAMENTAÇÃO].
6. Gere 6 a 10 Q&A com as três vias de associação.
"""


# ── FICHA DE CONSOLIDAÇÃO DE JURISPRUDÊNCIA ────────────────────────────────────
# Metalayer: sintetiza múltiplas decisões sobre o mesmo tema.
# Seeds: IRDR, IAC, temas repetitivos STJ/STF, clusters de topic modeling.
# Captura: questão, divergência, variações factuais, normas, evolução + QA.

PROMPT_FICHA_CONSOLIDACAO = """\
Você é um jurista especializado em análise sistemática de jurisprudência brasileira.
Receberá um TEMA jurídico e um conjunto de DECISÕES sobre ele.
Sua tarefa é produzir uma FICHA DE CONSOLIDAÇÃO estruturada.

TEMA: {tema}
TIPO DE SEMENTE: {tipo_semente}

DECISÕES:
\'\'\'{decisoes}\'\'\'

Produza a ficha no formato abaixo:

<<ID=FICHA:{tema_id}|TYPE=CONSOLIDACAO|PARENT=NULL>>
[QUESTÃO JURÍDICA]
Formule a controvérsia central como uma pergunta jurídica precisa que qualquer
advogado reconheceria como o problema em debate.

<<ID=FICHA:{tema_id}:MAJ|TYPE=MAJ|PARENT=FICHA:{tema_id}>>
[POSIÇÃO MAJORITÁRIA]
Entendimento predominante: em quais tribunais/turmas prevalece e qual o fundamento normativo.

<<ID=FICHA:{tema_id}:DIV|TYPE=DIV|PARENT=FICHA:{tema_id}>>
[DIVERGÊNCIA / POSIÇÃO MINORITÁRIA]
Se houver: posição divergente, onde prevalece, fundamento.
Se não houver: "Jurisprudência consolidada — sem divergência relevante identificada."

<<ID=FICHA:{tema_id}:VAR|TYPE=VAR|PARENT=FICHA:{tema_id}>>
[VARIAÇÕES FACTUAIS]
Como diferenças nos fatos alteram o resultado (valor, tipo de relação, qualidade das partes).

<<ID=FICHA:{tema_id}:NORMREF|TYPE=NORMREF|PARENT=FICHA:{tema_id}>>
[NORMAS E PRINCÍPIOS]
5 a 15 dispositivos com ID estrutural e papel na questão:
- CF88:ART:0005 (art. 5º CF) — papel.
- CDC:ART:0006 (art. 6º CDC) — papel.
(Apenas os efetivamente citados nas decisões fornecidas.)

<<ID=FICHA:{tema_id}:EVOL|TYPE=EVOL|PARENT=FICHA:{tema_id}>>
[EVOLUÇÃO]
Como o entendimento mudou (overruling, superação, distinção, consolidação) com datas aproximadas.
Se estável: "Entendimento consolidado desde [período] sem alterações relevantes."

<<ID=FICHA:{tema_id}:QA:001|TYPE=QA|PARENT=FICHA:{tema_id}>>
[PERGUNTA]
(direta — cita o tema ou dispositivo)
[RESPOSTA]
(resposta correspondente)

(8 a 10 pares QA garantindo:
 - 3 DIRETAS: cita tema/dispositivo; resposta traz o entendimento
 - 3 INVERSAS: descreve o problema sem citar o tema; resposta identifica a tese
 - 2 IMPLÍCITAS: situação concreta; resposta aplica o entendimento
 - 1 sobre DIVERGÊNCIA se houver: "há posição contrária?"
 - 1 sobre VARIAÇÃO: "e se a situação fosse X?")

---
REGRAS CRÍTICAS:
1. Use APENAS o que está nas decisões fornecidas — não invente precedentes.
2. Se só há uma posição, não fabrique divergência.
3. Seja preciso: processos, datas, relatores e teses devem estar nas fontes.
4. Se as decisões forem insuficientes para um bloco, escreva
   "(informação insuficiente nas fontes fornecidas)" — nunca preencha com suposição.
"""


# ── JURISPRUDÊNCIA — ENRIQUECIMENTO RICO ──────────────────────────────────────
# Task #1 do projeto: refaz o card de jurisprudência com os oito blocos pedidos
# pelo pesquisador. Os cards atuais já cobrem controvérsia, ratio, normas e QA;
# o que este prompt acrescenta é [TEMA], [PRINCÍPIOS RELACIONADOS] e
# [CASO PARADIGMÁTICO], mais o MODO da relação em cada norma e exemplos concretos
# de aplicação. Input: o card já expandido (material de apoio).

PROMPT_JURIS_RICO = """\
Você é um jurista sênior montando um corpus de pré-treino sobre jurisprudência brasileira.
Receberá, entre ''', um CARD já existente sobre um precedente. Reescreva-o completo, no
formato de blocos abaixo, aprofundando o que já existe e acrescentando o que falta.

<<ID={juris_id}|DOC={juris_id}|TYPE=PREC|PARENT=NULL>>
[IDENTIFICAÇÃO]
Tipo, tribunal, órgão julgador, número/identificador, data e área do direito.

[TEMA]
O tema jurídico em uma frase nominal, do jeito que um advogado o procuraria
(ex.: "dosimetria da pena — consequências do crime — orfandade da vítima").

<<ID={juris_id}:CONTROV|DOC={juris_id}|TYPE=CONTROV|PARENT={juris_id}>>
[CONTROVÉRSIA]
A questão em disputa formulada como pergunta jurídica precisa, com as duas posições
que estavam em jogo e o que cada uma sustentava.

<<ID={juris_id}:RATIO|DOC={juris_id}|TYPE=RATIO|PARENT={juris_id}>>
[RATIO DECIDENDI]
A razão determinante da decisão — a proposição jurídica sem a qual o resultado seria
outro. Separe do que é obiter dictum. 3 a 6 frases.

<<ID={juris_id}:NORMREF|DOC={juris_id}|TYPE=NORMREF|PARENT={juris_id}>>
[NORMAS RELACIONADAS]
3 a 10 dispositivos, cada um com ID estrutural, nome por extenso e O MODO da relação
(fundamenta, é interpretado conforme, é afastado, é lido em conjunto com, tem eficácia
limitada por):
- CP:ART:0059 (art. 59 do Código Penal — circunstâncias judiciais) — fundamenta a
  exasperação: é nele que "consequências do crime" opera como vetor.

<<ID={juris_id}:PRINC|DOC={juris_id}|TYPE=PRINC|PARENT={juris_id}>>
[PRINCÍPIOS RELACIONADOS]
2 a 6 princípios efetivamente mobilizados (individualização da pena, proporcionalidade,
proteção integral, segurança jurídica...), cada um com uma frase dizendo COMO pesou no
raciocínio — não basta nomear.

<<ID={juris_id}:PARAD|DOC={juris_id}|TYPE=PARAD|PARENT={juris_id}>>
[CASO PARADIGMÁTICO]
Resumo do caso concreto que gerou a tese: partes (genéricas), fatos relevantes, o que
foi pedido, o que decidiram as instâncias e o desfecho. 4 a 8 frases.

<<ID={juris_id}:APLIC|DOC={juris_id}|TYPE=APLIC|PARENT={juris_id}>>
[APLICAÇÃO]
Como a tese é aplicada na prática, e 2 a 5 exemplos sintéticos de casos que a aplicaram,
cada um em uma ou duas frases dizendo a situação e o resultado. Marque CADA exemplo:
"(caso real, conforme a fonte)" quando o caso estiver no card, "(exemplo hipotético)"
quando você o construiu para ilustrar a incidência. Nunca deixe um exemplo sem marca —
o corpus não pode ensinar hipótese como se fosse precedente.

<<ID={juris_id}:QA:001|DOC={juris_id}|TYPE=QA|PARENT={juris_id}>>
[PERGUNTA]
(direta — cita o tema ou o identificador)
[RESPOSTA]
(resposta correspondente)

(Repita o bloco QA para 6 a 10 perguntas, garantindo:
 - 2 DIRETAS: citam o tema/identificador; a resposta traz a tese
 - 2 INVERSAS: descrevem o problema sem citar o tema; a resposta identifica a tese
 - 2 IMPLÍCITAS: situação concreta; a resposta aplica o entendimento
 - 1 sobre os LIMITES: "e se a situação fosse X, muda?")

---
Card existente (material de apoio):
\'\'\'{card}\'\'\'

REGRAS CRÍTICAS:
1. Use APENAS o que está no card. NÃO invente processo, data, relator, número de
   Súmula/Tema/RE/REsp nem caso posterior.
2. Se o card não tiver material para um bloco, escreva nele
   "(informação insuficiente nas fontes fornecidas)" — nunca preencha com suposição.
   Isso vale especialmente para [CASO PARADIGMÁTICO]: enunciado de súmula ou tese de
   repetitivo em geral NÃO traz os fatos, e nesse caso é o que se deve escrever.
3. Mantenha os marcadores <<ID=...>> e os rótulos [BLOCO] exatamente como no modelo.
"""


# ── ENUNCIADO DOUTRINÁRIO ─────────────────────────────────────────────────────
# Enunciado de Jornada (CJF), FONAJE ou FPPC NÃO é súmula. Súmula é consolidação da
# jurisprudência do próprio tribunal, com autoridade institucional e casos julgados
# atrás dela — a vinculante chega a obrigar. Enunciado é aprovado por assembleia de
# juristas em evento científico ou fórum: vale como doutrina qualificada, é persuasivo,
# e o que existe atrás dele é consenso, não julgado.
#
# Por isso os blocos são outros. Forçar o card de súmula aqui produziria "informação
# insuficiente" em metade deles (não há caso paradigmático nem precedente originário),
# e — pior — ensinaria o modelo a tratar opinião qualificada como norma obrigatória.

PROMPT_ENUNCIADO_DOUTRINARIO = """\
Você é um jurista sênior preparando corpus de pré-treino. Receberá, entre ''', um
ENUNCIADO aprovado em jornada de estudos ou fórum de juristas ({fonte}). Ele NÃO é
súmula de tribunal: não vincula, vale como doutrina qualificada.

Escreva o card no formato abaixo.

<<ID={enun_id}|DOC={enun_id}|TYPE=ENUN|PARENT=NULL>>
[IDENTIFICAÇÃO]
Fonte, número do enunciado e área. Diga explicitamente a natureza e a força: enunciado
doutrinário aprovado em {fonte}, de eficácia PERSUASIVA, sem força vinculante.

[TEXTO DO ENUNCIADO]
O enunciado na íntegra e literal. NUNCA parafraseie este bloco.

<<ID={enun_id}:NORMA|DOC={enun_id}|TYPE=NORMA|PARENT={enun_id}>>
[NORMA INTERPRETADA]
O dispositivo que o enunciado interpreta, por extenso, e COMO ele o interpreta —
ampliando, restringindo, resolvendo ambiguidade do texto, ou colmatando lacuna.

<<ID={enun_id}:DIVERG|DOC={enun_id}|TYPE=DIVERG|PARENT={enun_id}>>
[DIVERGÊNCIA QUE MOTIVOU]
Enunciado existe porque havia dúvida ou dissenso. Explique qual era a controvérsia e
quais leituras concorriam antes dele. Se o material não permitir reconstruir isso,
escreva "(a fonte não descreve a controvérsia anterior)".

<<ID={enun_id}:JUSTIF|DOC={enun_id}|TYPE=JUSTIF|PARENT={enun_id}>>
[JUSTIFICATIVA DOUTRINÁRIA]
O fundamento pelo qual a posição foi adotada: interpretação sistemática, teleológica,
princípio invocado, coerência com o restante do sistema. 3 a 6 frases.

<<ID={enun_id}:APLIC|DOC={enun_id}|TYPE=APLIC|PARENT={enun_id}>>
[APLICAÇÃO]
Em que situações concretas o enunciado orienta a solução, com 2 a 4 exemplos, cada um
marcado "(exemplo hipotético)". E diga qual o peso argumentativo: como doutrina
qualificada, é invocável em petição e decisão, mas NÃO obriga o julgador.

<<ID={enun_id}:QA:001|DOC={enun_id}|TYPE=QA|PARENT={enun_id}>>
[PERGUNTA]
(direta — cita o enunciado ou o dispositivo)
[RESPOSTA]
(resposta correspondente)

(Repita para 4 a 8 pares, garantindo:
 - 2 DIRETAS: citam o enunciado ou a norma; a resposta traz a orientação
 - 2 INVERSAS: descrevem o problema sem citar; a resposta identifica a orientação
 - 1 sobre a FORÇA: "esse entendimento vincula o juiz?" — a resposta deve deixar claro
   que não, é doutrina persuasiva)

---
REGRAS CRÍTICAS:
1. Use APENAS o que está no enunciado e no que você sabe com alta confiança sobre a norma
   citada. NÃO invente número de dispositivo, de precedente ou de outro enunciado.
2. NUNCA descreva o enunciado como vinculante, obrigatório ou como súmula.
3. Texto puro, sem markdown. Mantenha os marcadores <<ID=...>> e os rótulos [BLOCO].

ENUNCIADO ({fonte}, nº {numero}):
\'\'\'{texto}\'\'\'
{norma}"""
