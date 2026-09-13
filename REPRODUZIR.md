# Reproduzir o artigo

*[English version: `REPRODUCING.md`](REPRODUCING.md)*

O trabalho tem cinco etapas, e elas diferem muito no que exigem. As três primeiras precisam
de rede, de GPU e de chave de API paga, e somam cerca de 400 horas de GPU. A quarta não
precisa de nada disso, e é ela que produz **todos os números do artigo** a partir dos
julgamentos depositados. Se o objetivo é conferir o resultado em vez de refazer o
experimento, vá direto para a etapa 4.

Os scripts têm nome e comentário em português, que é a língua de trabalho do projeto. Este
arquivo e os demais documentos estão nas duas línguas.

---

## Etapa 4 · Análise, a partir dos julgamentos depositados

**Precisa de:** Python 3.11, `numpy`, `pandas`, `scipy`, `scikit-learn`. Sem GPU e sem
chave de API.
**Entrada:** o depósito `avaliacao-ablacao`, desempacotado de modo que os julgamentos
fiquem em `avaliacao/resultados/`.

```bash
python dataset/congela.py --conferir        # os arquivos são os que o manifesto descreve
python dataset/confere_vazamento.py         # os exames da avaliação nunca entraram no treino
python publicacao/artigo/tabelas.py         # recomputa as Tabelas 1 a 4 do artigo
python avaliacao/contrastes_por_tarefa.py   # os contrastes pareados da Seção 4.3
python avaliacao/complementaridade.py       # a complementaridade por critério, Seção 4.2
python avaliacao/kappa_por_classe.py        # a concordância do juiz separada em forma e mérito
```

`avaliacao/nota.py` é a única função de nota usada por todos eles. Ela pesa cada critério
pela pontuação que a banca lhe atribui, e nunca agrega os dois gêneros de tarefa. Toda
tabela do artigo sai dela; nenhuma é transcrita à mão.

---

## Etapa 1 · Construção do corpus

**Precisa de:** rede e chave de API do modelo-professor.

Coleta, por fonte: `pipeline/recoleta_normas.py` (leis federais),
`pipeline/coleta_stf_historico.py` e `augmentation/crawlers/stf_acordaos.py` (acórdãos do
STF), `augmentation/crawlers/stj_acordaos.py`, `augmentation/crawlers/enunciados.py`
(súmulas e enunciados), `pipeline/coleta_carreiras.py` (concursos de carreira),
`pipeline/parse_oab_pdfs.py` (provas da OAB e os espelhos de correção).

Expansão em fichas, que é o que produz o braço estruturado:
`augmentation/expand_normas.py`, `expand_jurisprudencia.py` e `expand_casos.py`. Os três
compartilham `augmentation/llm_client.py`, `prompts.py` e `sanitize.py`; o `verify.py`
confere a saída em camadas.

Montagem: `pipeline/expande_cascata.py` produz os exemplos a dois saltos;
`pipeline/monta_benchmark_v2.py` constrói as 105 questões e os 940 critérios, e é também
onde está definido o agrupamento dos critérios de peça em forma e mérito;
`aws/build_ablacao_regime.py` casa os dois braços em orçamento de tokens, que é o passo que
torna o par comparável.

`pipeline/diagnostico_corpus.py` roda as conferências de proveniência cujos achados a ficha
do conjunto reporta na seção de defeitos conhecidos.

---

## Etapa 2 · Treino e geração

**Precisa de:** GPU. As 180 condições rodaram em instâncias AWS EC2 com NVIDIA A10G.

Pré-treino continuado: `aws/cadeia_ablacao_tucano.sh` e `aws/cadeia_ablacao_qwen.sh`.
Ajuste fino das 180 condições: `aws/cadeia_sft_ablacao.sh`. É ali que o protocolo declarado
no artigo de fato vive, `alpha 64` e `max_seq 3072` inclusive.
Geração no benchmark: `aws/sobe_vllm_ablacao.sh` levanta um servidor multi-adaptador e
`aws/gera_sft_ablacao.sh` (ou `gera_ctrl_ablacao.sh`, para os braços de controle) o
conduz; `aws/gera_remoto.py` é o cliente.

---

## Etapa 3 · Julgamento

**Precisa de:** chave de API dos dois juízes.

`avaliacao/julga_rabula.py` julga cada resposta contra o espelho oficial, critério a
critério, produzindo os arquivos `*_partes.jsonl` que a etapa 4 consome. Os juízes são o
Kimi K2.5 para questão discursiva e o GPT-OSS 120B para peça, fixados antes de qualquer
medição. `avaliacao/judge.py` guarda o cliente e `benchmark_schema.py` o contrato da
resposta esperada.

`avaliacao/analisa_kappa_v4.py` é o pacote estatístico que calibra os juízes contra o
padrão-ouro humano; ele importa `alignment.py` e `judge_llm.py`, herdados do benchmark de
origem.

---

## Etapa 5 · O manuscrito

`publicacao/artigo/tabelas.py` recomputa as tabelas, `monta_artigo.py` monta o HTML, e
`publicacao/jurix/para_tex.py` converte para o estilo IOS Press usado pela conferência. A
versão em inglês está em `publicacao/artigo_en/` e segue os mesmos três passos. Nada do
manuscrito é escrito duas vezes: as tabelas vêm do dado e o formato de submissão é derivado
da mesma fonte que a cópia de leitura.

---

## O que está deliberadamente ausente

O projeto acumulou 108 scripts com ponto de entrada ao longo de meses, vários deles
superados e alguns marcados como tal no próprio cabeçalho. Este repositório contém apenas o
caminho que produziu o que está no artigo. O que ficou de fora foi descartado, não
esquecido: publicar o acervo inteiro entregaria ao leitor a tarefa de adivinhar qual script
gerou cada resultado, e o pior caso é ele acertar o nome e errar a versão.

`publicacao/monta_repo.py` é o que monta este repositório. Ele recusa arquivo cujo nome ou
conteúdo case com padrão de credencial, e recusa terminar se algum script incluído importar
módulo que ficou de fora.
