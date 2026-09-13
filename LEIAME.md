# Corpus sintético na adaptação de modelos de linguagem ao direito brasileiro

*[English version: `README.md`](README.md)*

Código e material de reprodução do artigo de mesmo nome, que mede três decisões que a
receita corrente de adaptação de domínio trata como uma só: **qual** texto entra no
pré-treino continuado, **em que forma** ele entra, e **quanta** supervisão vem depois.

O desenho é fatorial. Dois corpora de pré-treino pareados documento a documento, um de texto
jurídico bruto e outro em que o mesmo material foi reestruturado em fichas com camadas
geradas por um modelo-professor, mais um controle sem pré-treino, cruzados com seis blocos
de ajuste fino de composição distinta e quatro modelos-base de 1,5 a 14 bilhões de
parâmetros. São 180 condições treinadas, cada uma avaliada em 105 questões reais do Exame de
Ordem contra 940 critérios do espelho oficial das bancas, em dez execuções independentes.

**Eduardo Pacheco** · Instituto de Ciências Matemáticas e de Computação, Universidade de São Paulo.
Artigo em coautoria com Cibele Maria Russo.

## Comece por aqui

**[`REPRODUZIR.md`](REPRODUZIR.md)** percorre as cinco etapas e nomeia o script exato de cada
uma. Para conferir os resultados em vez de refazer o experimento, a etapa 4 não precisa de
GPU nem de chave de API: ela recomputa todos os números do artigo a partir dos julgamentos
depositados.

## O que há aqui

| diretório | o que guarda |
|---|---|
| `pipeline/` | coleta e montagem do corpus, construção do benchmark, diagnóstico de proveniência |
| `augmentation/` | geração das fichas estruturadas e os coletores das fontes |
| `aws/` | as cadeias que rodaram as 180 condições: pré-treino, ajuste fino, geração |
| `avaliacao/` | julgamento, nota, concordância por classe, contrastes pareados, complementaridade |
| `dataset/` | congelamento, manifestos com soma de verificação, a ficha do conjunto, empacotamento |
| `publicacao/` | as fontes do artigo, em português e em inglês, e a conversão para o IOS Press |
| `explorador/` | aplicação local para inspecionar os julgamentos ao lado das respostas geradas |

É uma seleção curada, não o acervo de trabalho. Só está aqui o caminho que produziu o que
está no artigo; o `REPRODUZIR.md` explica o que ficou de fora e por quê.

## Os dados

Os corpora e os julgamentos **não** estão neste repositório. Somam cerca de 3 GB e vivem em
depósitos separados, um por licença e ciclo de vida, cada um com identificador persistente.

| depósito | conteúdo | tamanho |
|---|---|---:|
| `corpus-treino` | o par bruto/ficha e os seis blocos de ajuste fino | 255 MB |
| `avaliacao-ablacao` | os julgamentos das 180 condições e as respostas que elas geraram | 119 MB |
| `benchmark-juizes` | os vereditos de 31 juízes candidatos e o padrão-ouro humano | 23 MB |

`dataset/manifestos/` traz, para cada arquivo de cada depósito, o caminho, o tamanho, a
contagem de linhas e o SHA-256. É isso que transforma "os dados estão disponíveis" em "estes
bytes exatos produziram estes resultados".

**[`dataset/DATASHEET.pt.md`](dataset/DATASHEET.pt.md)** descreve o corpus de treino em
formato de ficha de conjunto. Leia a seção de defeitos conhecidos antes de treinar nele:
esta é a versão que reproduz o estudo, não a recomendada para trabalho novo.

## Licença

Código sob MIT (`LICENSE`). Os dados depositados estão sob CC BY 4.0, com as ressalvas de
proveniência declaradas na ficha do conjunto.
