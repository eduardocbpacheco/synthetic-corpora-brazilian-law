# Ficha do conjunto · Corpus pareado de adaptação jurídica, v1.0

*[English version: `DATASHEET.md`](DATASHEET.md)*

Formato de *datasheet for datasets* (Gebru et al., 2021). Escrita em 13/09/2026, descrevendo
o estado exato que alimentou as 180 condições treinadas do estudo de ablação.

> **Aviso de versão.** Esta é a v1.0, congelada para reprodutibilidade, **não** a versão
> recomendada para uso novo. Ela tem defeitos conhecidos, medidos e listados na seção 6. A
> v2.0, em construção, corrige os quatro diplomas truncados, filtra a geração de casos por
> recuperação e verifica as referências processuais. Quem quiser treinar deve esperar a
> v2.0; quem quiser reproduzir o estudo precisa desta.

---

## 1 · Motivação

**Para que o conjunto foi criado.** Para responder uma pergunta que a literatura de
adaptação de domínio não separa: quanto do ganho vem do *conteúdo* do corpus e quanto vem da
*forma* em que ele entra no treino. Responder isso exige dois corpora que difiram só na
forma, e eles não existiam.

**Quem criou.** Eduardo Pacheco, no âmbito do mestrado no ICMC-USP, com orientação de Cibele
Maria Russo.

**Financiamento.** Recursos próprios do projeto; o treino rodou em instâncias AWS EC2
contratadas para este fim.

---

## 2 · Composição

O conjunto tem duas partes que servem a fases diferentes do treino.

### 2.1 · Pré-treino continuado: o par

Dois arquivos, **pareados documento a documento**. O mesmo acórdão que entra em um entra no
outro; o que muda é a forma.

| braço | documentos | tokens (Tucano) | tokens (Qwen) |
|---|---:|---:|---:|
| `bruto_completo.jsonl` | 39.856 | 50,58 M | 65,66 M |
| `expandido_completo.jsonl` | 41.900 | 59,43 M | 74,82 M |

No braço **bruto**, o documento entra como foi coletado e é cortado por tamanho quando
excede a janela. O corte é cego e cai onde calha, inclusive no meio de uma frase.

No braço **expandido**, o mesmo documento vira uma *ficha*: o texto original é preservado
intacto num campo próprio e recebe camadas geradas por um modelo-professor — síntese,
explicação, efeito prático, dispositivos relacionados, pares de pergunta e resposta. Cada
camada é um nó com identificador e filiação explícita, de modo que o corte respeita os nós:
cada pedaço leva o cabeçalho de identificação mais um subconjunto coerente das camadas.

Composição por categoria, em percentual de tokens:

| braço | caso julgado | norma | jurisprudência consolidada | enunciado |
|---|---:|---:|---:|---:|
| bruto | 78,3% | 8,9% | 9,1% | 3,7% |
| expandido | 35,5% | 36,3% | 19,9% | 8,3% |

**A diferença de composição é consequência da forma, não escolha.** Uma norma tem poucos
tokens no original e muitos depois de expandida; um acórdão integral já é longo e a expansão
acrescenta proporcionalmente menos. Isso é uma limitação do par e está declarado como tal:
parte do efeito atribuído à forma pode ser mistura de categoria.

Os quatro arquivos `casado_*` são os recortes efetivamente consumidos por cada família de
modelo, truncados para casar o orçamento de tokens do braço menor com o tokenizador daquela
família. O braço bruto roda uma época exata; o expandido é truncado em 0,851 época (Tucano)
e 0,877 (Qwen). **Nenhum braço repete documento.**

### 2.2 · Ajuste fino: os seis blocos

| bloco | exemplos | passos | composição |
|---|---:|---:|---|
| I | 1.007 | 189 | prova real da OAB, espelho oficial da banca como resposta |
| II | 1.182 | 222 | peça gerada (648) + primeira fase convertida (534) |
| III | 1.681 | 316 | bloco II + material a dois saltos (500) |
| IV | 2.687 | 504 | toda a OAB, oficial e gerada |
| VII | 223 | 42 | concursos de carreira e bancas fora da OAB |
| X | 2.909 | 546 | bloco IV + bloco VII |

Cada bloco vem com um `valid.jsonl` de ~5%. Os passos não são fixos: são calculados para
que todo bloco receba exatamente três épocas, por `passos = teto(3n / 16)`.

**Os blocos não são aninhados por construção.** II e III não contêm I; IV contém I e III; X
contém IV e VII. A tabela de composição real, contada nos metadados dos arquivos que
rodaram, está no relatório do estudo e é ela — não o desenho — que descreve o que cada
condição viu.

### 2.3 · O que **não** está aqui

O conjunto de avaliação — 105 questões da OAB, 940 critérios e o padrão-ouro de três
juristas — **não** faz parte deste depósito. Ele vem do benchmark Rabula e está no depósito
`benchmark-juizes`. A separação é deliberada: os exames de onde as questões de avaliação vêm
foram **excluídos de todo o corpus de treino**, e manter os dois em depósitos distintos torna
essa exclusão verificável em vez de prometida.

---

## 3 · Coleta

**Fontes.** Normas federais e estaduais paulistas dos sítios oficiais; acórdãos e enunciados
de súmula do STF, do STJ e do TJSP, por interfaces públicas e pelo DataJud; provas e espelhos
de correção publicados pelas bancas examinadoras.

**Período de coleta.** Agosto e setembro de 2026. Os acórdãos do STF cobrem 2010 em diante.

**Amostragem.** Não é amostra probabilística de nada. É o que as interfaces públicas
devolveram nos recortes pedidos, e os vieses de cobertura dessas interfaces são herdados sem
correção. Ver seção 6.

**Trabalho humano.** Nenhum, nesta parte. A anotação humana existe apenas no conjunto de
avaliação, que está em outro depósito.

---

## 4 · Pré-processamento

O braço bruto recebe limpeza mínima: normalização de espaços, remoção de cabeçalho e rodapé
de repositório, corte por janela de contexto.

O braço expandido é gerado com um modelo-professor comercial, a partir de um esquema fixo de
camadas por tipo de documento. O prompt de geração e o esquema estão no depósito de código.

Os dois braços preservam o texto original. No expandido ele fica num campo próprio e não é
reescrito — o que é gerado são as camadas ao redor.

---

## 5 · Usos

**Uso previsto.** Pré-treino continuado e ajuste fino de modelos de linguagem para tarefas
jurídicas em português, e — o uso para o qual o par foi construído — estudos que precisem
separar forma de conteúdo mantendo o acervo constante.

**Usos desaconselhados.** Este conjunto **não** serve como fonte de informação jurídica. As
camadas geradas contêm erro, inclusive referência processual inventada em escala medida
(seção 6). Um sistema que responda a consultas jurídicas a partir daqui, sem verificação
contra fonte oficial, vai citar processo que não existe.

**Uso em avaliação.** Não avalie neste corpus modelos treinados nele. E não avalie no
benchmark Rabula modelos treinados com os exames 39, 40 e 41 — que é justamente por que eles
foram excluídos daqui.

---

## 6 · Defeitos conhecidos, e o que cada um custa

Esta seção existe porque descobrimos os defeitos medindo, e porque o custo deles a jusante
foi quantificado. Publicá-los é mais útil do que corrigi-los em silêncio numa versão que
ninguém poderá comparar com esta.

**Quatro diplomas entraram truncados ou não entraram.** O coletor de leis federais parou
cedo em quatro arquivos.

| diploma | artigos no corpus | artigos no diploma | cobertura |
|---|---:|---:|---:|
| Código Civil | 57 | 2.046 | 3% |
| Estatuto da Criança e do Adolescente | 9 | 267 | 3% |
| Código Penal comum | 0 | 361 | ausente |
| Código Comercial | 0 | 913 | ausente |

Os outros quinze códigos têm cobertura entre 89% e 108% — valores acima de 100% vêm de
artigos com sufixo, como 5º-A, que a contagem nominal não prevê. **O custo medido:** a
análise por área do direito não encontrou prejuízo nas áreas afetadas; Direito Penal tem o
maior ganho de todas na questão discursiva. O que se sustenta é a negativa, não uma
afirmação sobre o mecanismo. A recoleta desses quatro já foi feita e entra na v2.0.

**Referência processual fabricada no braço expandido.** O modelo-professor não foi instruído
a verificar as referências que produzia. São **4.423 fichas** citando número de processo com
formato plausível e inexistente — metade de todas as que citam julgado. Das 21.912 citações
de julgado no corpus, 7 resolvem contra base real.

**O custo medido, e este é o que importa:** a fabricação chega à saída do modelo treinado.
A taxa de respostas que citam processo inexistente é de **0,512%** nas condições treinadas
com o braço expandido, contra 0,091% com o bruto e 0,072% no controle sem pré-treino — cerca
de sete vezes o controle. Em valor absoluto é baixa; em direção é sistemática.

**Identificadores colidentes.** Em 42 casos, duas fichas de artigos *diferentes* recebem o
mesmo identificador. A causa é dupla: artigos acima de 999 perdiam o separador de milhar
(`CPC:ART:0001` reunia os artigos 1, 1.000, 1.001 e 1.002) e artigos com sufixo perdiam o
sufixo (`CLT:ART:0075` reunia 75, 75-A e 75-B). São 42 de 12.781.

**Pareamento incompleto.** O par documento a documento não é perfeito em todos os conjuntos:
três deles ficam em 0,5%, 0% e 0,9% de correspondência verificável. Isso não invalida o par
no agregado — ele foi construído pela mesma tabela de origem — mas significa que a
afirmação "o mesmo documento nos dois braços" é verificável só em parte.

**Súmulas do STF sem número.** 778 linhas do braço bruto trazem `None` no lugar do número da
súmula. No braço expandido o número foi preservado nas 1.714 fichas. É mais uma assimetria
entre os braços e é candidata a explicar parte da vantagem do expandido.

**Fichas partidas.** 1.613 fichas do corpus de normas não cabem na janela e são partidas em
mais de uma linha, com **zero duplicatas**: nenhuma linha repete o conteúdo de outra. Isso é
comportamento desenhado, não defeito, e está aqui para explicar por que há mais linhas que
fichas.

---

## 7 · Distribuição e licença

**Compilação** sob CC BY 4.0.

**Material de origem.** No direito brasileiro, textos de lei e decisões judiciais não são
protegidos por direito autoral (Lei 9.610/1998, art. 8º, incisos IV e V), e as provas e
espelhos são publicados pelas bancas. **As camadas geradas** foram produzidas por um modelo
de linguagem comercial, e o uso delas está sujeito aos termos desse serviço no momento da
geração; quem redistribuir deve verificá-los.

**Verificação de integridade.** O manifesto `manifestos/corpus-treino.json` traz caminho,
tamanho, contagem de linhas e SHA-256 de cada arquivo. Confira com
`python dataset/congela.py corpus-treino --conferir`.

---

## 8 · Manutenção

Mantido por Eduardo Pacheco (edu@prysmo.com). A v1.0 é imutável: ela existe para reproduzir
um estudo e não receberá correção. As correções vão para a v2.0, que terá depósito e DOI
próprios, e esta ficha ganhará uma linha apontando para lá.
