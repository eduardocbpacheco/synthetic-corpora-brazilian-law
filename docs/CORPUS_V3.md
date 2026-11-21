# Corpus v3 — réplica no Tucano 3,7B (congelado + lacunas da auditoria de 14/11/2026)

Montado em 14/11/2026 por `pipeline/monta_corpus_v3.py`. Saída em `data/ablacao_regime_v3/`.
O corpus das 180 condições (`data/ablacao_regime/*_completo.jsonl`) **não foi tocado**: o
montador confere o sha256 contra `pipeline/congelado.sha256` antes de ler, e ele segue
`e43d20d3…` (bruto) e `34ccdbe9…` (expandido).

O v3 é o congelado **mais** o que faltava. Nada do congelado sai, exceto (a) o livro do TST
fatiado com verbetes cancelados e as fichas do TST feitas sobre ele, que foram substituídos,
e (b) os blocos brutos de nove diplomas com fonte truncada ou desatualizada, que foram
trocados pelo texto recoletado do mesmo diploma. Não houve rebalanceamento de área.

## 1. O que entrou, de onde

| item | o que | fonte e data | script |
|---|---|---|---|
| Split (furo 2) | 686 blocos brutos e 823 fichas que a montagem de 30/08 tinha mandado para a validação, inclusive lei, súmula e enunciado | `data/regimes/AB_{bruto,expandido}/valid.jsonl`: a validação gravada **na mesma montagem** do congelado (os `train.jsonl` de lá são byte a byte iguais ao congelado). Nada foi regerado | `monta_corpus_v3.base_congelada` |
| Fonte truncada (furo 1) | blocos brutos de CC, CP, ECA, Est. Pessoa Idosa, Desarmamento, Cheque e Duplicata, e também S.A. e LEP, que mesmo com a validação devolvida ficavam abaixo de 98% (o texto antigo de `leis_federais.jsonl` não trazia a redação atual inteira). 89 blocos saem, 254 entram | `leis/recoleta_v2/` (CC, CP, ECA, S.A., set/2026, Planalto) e `leis/recoleta_v3/` (Idoso, Desarmamento, Cheque, Duplicata, 14/11/2026, Planalto) | `monta_corpus_v3.blocos_lei` |
| Diplomas nunca coletados (furo 3) | os 32 da auditoria + Código de Ética e Disciplina da OAB (80º diploma da lista de referência): 303 blocos brutos | Planalto, 14/11/2026 19:34–19:39, pela escada de URLs de `recoleta_normas.py`; URL, data e sha256 em cada `leis/recoleta_v3/*.json`. CED-OAB: PDF de `oab.org.br/publicacoes/AbrirPDF` (caminho que o robots.txt não veda) | `pipeline/recoleta_v3.py` |
| LINDB | o DL 4.657/1942 de verdade (30 artigos, com os arts. 20–30 da Lei 13.655/2018) | Planalto, `decreto-lei/Del4657compilado.htm` | idem |
| LUG (Dec. 57.663/66), Anexo I | os 78 artigos da Lei Uniforme | o Planalto só tem o anexo como **PDF escaneado** (`decreto/1950-1969/anexo/an57663-66.pdf`, sem camada de texto). Câmara (legin) e Senado (legis) sondados: só o decreto promulgador. Texto por **OCR** (tesseract 5, `tessdata_best/por`, 400 dpi), cabeçalhos renumerados pela ordem com portão de contagem exata (78) | `pipeline/lug_anexo_ocr_v3.py` |
| TST (furo 4) | 766 súmulas/OJs/PNs **vigentes** (de 768 vigentes no livro), um verbete por documento, sem o "Histórico" (redação superada) e sem os itens cancelados das Súmulas 6 e 331; 220 teses de IRR/IAC com tese firmada. Total 986 documentos no bruto (2 PNs com extração quebrada, < 60 caracteres, ficaram de fora) | livro "Súmulas, OJs e PNs" do TST (edição de 26/09/2025, baixado 14/11/2026) e "Índice Temático — Precedentes Trabalhistas" (versão de 13/11/2026, CC BY-NC-SA 4.0); `www.tst.jus.br` permite robôs | `pipeline/coleta_trab_trib_v3.py` |
| CARF (furo 4) | 248 súmulas vigentes (6 revogadas fora); o efeito vinculante vai no status da ficha, não no enunciado | página oficial "Súmulas Consolidadas com os Acórdãos Precedentes" (gov.br/carf, atualizada em 09/10/2026, baixada 14/11/2026) | idem |
| Fichas novas | 4.875 fichas de artigo + 1.234 fichas de verbete TST/CARF → 8.958 documentos depois do corte por bloco | Mistral Large 3 (Bedrock), mesmo prompt e parâmetros das fichas existentes | `pipeline/gera_cards_v3.py` |

### Correções de rótulo (sem mudar conteúdo)

* **`DOC=CP` → `CPM`** no expandido: as 444 fichas `CP:ART:*` do congelado (440 + 4 da validação)
  são do Código Penal **Militar** (413 dizem "Penal Militar" no texto; B4). Trocam-se só os
  marcadores `<<ID=`, `DOC=`, `PARENT=` e a linha `[NORMA]`; remissões no corpo da ficha ficam
  como estão, porque reescrevê-las seria adivinhar. `CP` passa a ser o Código Penal comum.
* **LC 107/2001** vinha batizada "Lei LINDB revisão" (1 bloco bruto, 5 fichas): é a lei que altera
  a LC 95/1998 (elaboração das leis). O rótulo passa a dizer isso. A LINDB real entrou à parte.
* **B2**: nota de informativo do STJ é `juris` nos dois braços (no expandido congelado estava em
  `caso`). Vale para o manifesto e para o par casado.
* **TST** passa a `juris` também no bruto (era `enunciado`, por ser o livro fatiado): súmula e OJ
  são consolidação de tribunal, a mesma natureza que o expandido já usava.

### Regra nova de validação (furo 2)

Norma, súmula, tese, OJ/PN e enunciado **nunca** vão para a validação. A validação é **por
documento** e só de jurisprudência decisória (acórdão, caso, nota de informativo): documento com
qualquer parte no treino vai inteiro para o treino. Da validação de 30/08 sobram 123 linhas no
bruto e **1** no expandido (as notas de informativo saem por número de informativo, e quase todo
informativo tem nota no treino). O bruto foi completado até 2% com 435 documentos de acórdão do
`pretrain_v4` cuja chave não aparece em parte nenhuma do treino v3 (641 linhas). No expandido não
há material decisório fora do treino; **recomendação: usar `bruto_valid.jsonl` como régua comum
dos dois braços** (texto jurídico natural, o mesmo para as duas condições).

## 2. Cobertura por diploma, antes e depois

"Vigentes": artigos que `expand_normas.dividir_em_artigos` encontra no texto da melhor fonte
depois de tirado o riscado, sem os só-revogação (a mesma definição que governa a geração de
ficha). Contagem por número-base (75, 75-A e 75-B contam como 75). "Antes" = congelado como
está, só com o `CP→CPM` aplicado. Portão: ≥ 98% nos dois braços — **passou para os 80**.

Agregado: 10.681 artigos vigentes; bruto 6.144 → 10.681; fichas 6.045 → 10.674. Antes, só 6 dos
80 diplomas passavam o portão. A Lei 8.666/1993 tem 1 artigo "vigente" porque foi revogada em
2023 (o texto recoletado marca o resto como riscado); os 121 artigos do congelado ficam.

| diploma | área | vigentes | bruto antes | bruto v3 | fichas antes | fichas v3 |
|---|---|---:|---:|---:|---:|---:|
| CF/88 (corpo permanente) | todas | 248 | 243 (98.0%) | 248 (100.0%) | 242 (97.6%) | 248 (100.0%) |
| CPC/2015 | transv. | 1068 | 1017 (95.2%) | 1068 (100.0%) | 1039 (97.3%) | 1068 (100.0%) |
| LINDB (DL 4.657/42) | transv. | 29 | 0 (0.0%) | 29 (100.0%) | 0 (0.0%) | 29 (100.0%) |
| Estatuto da OAB (L 8.906/94) | ética | 87 | 87 (100.0%) | 87 (100.0%) | 87 (100.0%) | 87 (100.0%) |
| Código de Ética e Disciplina da OAB | ética | 80 | 0 (0.0%) | 80 (100.0%) | 0 (0.0%) | 80 (100.0%) |
| Lei 9.868/99 (ADI/ADC) | const | 30 | 30 (100.0%) | 30 (100.0%) | 27 (90.0%) | 30 (100.0%) |
| Lei 9.882/99 (ADPF) | const | 13 | 0 (0.0%) | 13 (100.0%) | 0 (0.0%) | 13 (100.0%) |
| Lei 12.016/09 (MS) | const/adm | 29 | 29 (100.0%) | 29 (100.0%) | 26 (89.7%) | 29 (100.0%) |
| Lei 4.717/65 (Ação Popular) | const/adm | 22 | 0 (0.0%) | 22 (100.0%) | 0 (0.0%) | 22 (100.0%) |
| Lei 7.347/85 (ACP) | const/adm | 23 | 23 (100.0%) | 23 (100.0%) | 22 (95.7%) | 23 (100.0%) |
| Lei 13.300/16 (MI) | const | 15 | 0 (0.0%) | 15 (100.0%) | 0 (0.0%) | 15 (100.0%) |
| Lei 9.507/97 (HD) | const | 21 | 0 (0.0%) | 21 (100.0%) | 0 (0.0%) | 21 (100.0%) |
| Lei 11.417/06 (SV) | const | 11 | 0 (0.0%) | 11 (100.0%) | 0 (0.0%) | 11 (100.0%) |
| Lei 8.112/90 | adm | 239 | 239 (100.0%) | 239 (100.0%) | 233 (97.5%) | 239 (100.0%) |
| Lei 14.133/21 | adm | 193 | 189 (97.9%) | 193 (100.0%) | 189 (97.9%) | 193 (100.0%) |
| Lei 8.666/93 (revogada em 2023) | adm | 1 | 1 (100.0%) | 1 (100.0%) | 1 (100.0%) | 1 (100.0%) |
| Lei 9.784/99 | adm | 70 | 70 (100.0%) | 70 (100.0%) | 68 (97.1%) | 70 (100.0%) |
| Lei 8.429/92 (LIA) | adm | 22 | 22 (100.0%) | 22 (100.0%) | 21 (95.5%) | 22 (100.0%) |
| Lei 8.987/95 (Concessões) | adm | 44 | 44 (100.0%) | 44 (100.0%) | 42 (95.5%) | 44 (100.0%) |
| Lei 11.079/04 (PPP) | adm | 30 | 0 (0.0%) | 30 (100.0%) | 0 (0.0%) | 30 (100.0%) |
| DL 3.365/41 (Desapropriação) | adm | 43 | 42 (97.7%) | 43 (100.0%) | 42 (97.7%) | 43 (100.0%) |
| Lei 12.846/13 (Anticorrupção) | adm | 31 | 0 (0.0%) | 31 (100.0%) | 0 (0.0%) | 31 (100.0%) |
| Lei 13.303/16 (Estatais) | adm | 96 | 0 (0.0%) | 96 (100.0%) | 0 (0.0%) | 96 (100.0%) |
| Lei 11.107/05 (Consórcios) | adm | 21 | 0 (0.0%) | 21 (100.0%) | 0 (0.0%) | 21 (100.0%) |
| Lei 10.257/01 (Estatuto da Cidade) | adm | 51 | 0 (0.0%) | 51 (100.0%) | 0 (0.0%) | 51 (100.0%) |
| Lei 13.019/14 (MROSC) | adm | 76 | 0 (0.0%) | 76 (100.0%) | 0 (0.0%) | 75 (98.7%) |
| LC 101/00 (LRF) | adm/fin | 73 | 73 (100.0%) | 73 (100.0%) | 71 (97.3%) | 73 (100.0%) |
| Código Civil | civ/emp | 1972 | 37 (1.9%) | 1972 (100.0%) | 55 (2.8%) | 1971 (99.9%) |
| CDC | civ | 108 | 103 (95.4%) | 108 (100.0%) | 101 (93.5%) | 108 (100.0%) |
| ECA | civ/pen | 265 | 8 (3.0%) | 265 (100.0%) | 8 (3.0%) | 264 (99.6%) |
| Lei 8.245/91 (Locações) | civ/emp | 88 | 88 (100.0%) | 88 (100.0%) | 82 (93.2%) | 88 (100.0%) |
| Lei 8.009/90 (Bem de família) | civ | 8 | 8 (100.0%) | 8 (100.0%) | 6 (75.0%) | 8 (100.0%) |
| Lei 5.478/68 (Alimentos) | civ | 26 | 0 (0.0%) | 26 (100.0%) | 0 (0.0%) | 26 (100.0%) |
| Lei 10.741/03 (Estatuto da Pessoa Idosa) | civ | 117 | 23 (19.7%) | 117 (100.0%) | 3 (2.6%) | 117 (100.0%) |
| Lei 13.146/15 (EPD) | civ | 125 | 125 (100.0%) | 125 (100.0%) | 120 (96.0%) | 125 (100.0%) |
| Lei 11.101/05 (Falências) | emp | 199 | 190 (95.5%) | 199 (100.0%) | 190 (95.5%) | 199 (100.0%) |
| Lei 6.404/76 (S.A.) | emp | 293 | 274 (93.5%) | 293 (100.0%) | 279 (95.2%) | 293 (100.0%) |
| LUG (Dec. 57.663/66) | emp | 78 | 0 (0.0%) | 78 (100.0%) | 0 (0.0%) | 78 (100.0%) |
| Lei 5.474/68 (Duplicata) | emp | 28 | 16 (57.1%) | 28 (100.0%) | 6 (21.4%) | 28 (100.0%) |
| Lei 7.357/85 (Cheque) | emp | 69 | 33 (47.8%) | 69 (100.0%) | 0 (0.0%) | 69 (100.0%) |
| Dec. 2.044/1908 (Letra/NP) | emp | 57 | 0 (0.0%) | 57 (100.0%) | 0 (0.0%) | 57 (100.0%) |
| Lei 9.279/96 (LPI) | emp | 244 | 244 (100.0%) | 244 (100.0%) | 244 (100.0%) | 244 (100.0%) |
| Lei 8.934/94 (Registro de Empresas) | emp | 61 | 0 (0.0%) | 61 (100.0%) | 0 (0.0%) | 61 (100.0%) |
| LC 123/06 (Simples) | emp/trib | 84 | 77 (91.7%) | 84 (100.0%) | 81 (96.4%) | 84 (100.0%) |
| Lei 4.886/65 (Representação comercial) | emp | 49 | 0 (0.0%) | 49 (100.0%) | 0 (0.0%) | 49 (100.0%) |
| Lei 9.307/96 (Arbitragem) | emp/civ | 44 | 44 (100.0%) | 44 (100.0%) | 43 (97.7%) | 44 (100.0%) |
| Código Penal (DL 2.848/40) | pen | 338 | 0 (0.0%) | 338 (100.0%) | 0 (0.0%) | 337 (99.7%) |
| CPP | pen | 776 | 765 (98.6%) | 776 (100.0%) | 758 (97.7%) | 776 (100.0%) |
| LEP (L 7.210/84) | pen | 200 | 192 (96.0%) | 200 (100.0%) | 192 (96.0%) | 200 (100.0%) |
| Lei 9.099/95 (Juizados) | pen/civ | 96 | 96 (100.0%) | 96 (100.0%) | 94 (97.9%) | 96 (100.0%) |
| Lei 11.343/06 (Drogas) | pen | 52 | 52 (100.0%) | 52 (100.0%) | 51 (98.1%) | 52 (100.0%) |
| Lei 8.072/90 (Hediondos) | pen | 17 | 17 (100.0%) | 17 (100.0%) | 17 (100.0%) | 17 (100.0%) |
| Lei 11.340/06 (Maria da Penha) | pen | 46 | 46 (100.0%) | 46 (100.0%) | 45 (97.8%) | 46 (100.0%) |
| Lei 12.850/13 (Organização criminosa) | pen | 28 | 0 (0.0%) | 28 (100.0%) | 0 (0.0%) | 28 (100.0%) |
| Lei 10.826/03 (Desarmamento) | pen | 37 | 13 (35.1%) | 37 (100.0%) | 2 (5.4%) | 37 (100.0%) |
| Lei 9.296/96 (Interceptação) | pen | 12 | 0 (0.0%) | 12 (100.0%) | 0 (0.0%) | 12 (100.0%) |
| Lei 8.137/90 (Crimes tributários) | pen/trib | 18 | 0 (0.0%) | 18 (100.0%) | 0 (0.0%) | 18 (100.0%) |
| Lei 9.605/98 (Crimes ambientais) | pen | 75 | 0 (0.0%) | 75 (100.0%) | 0 (0.0%) | 75 (100.0%) |
| Lei 9.613/98 (Lavagem) | pen | 15 | 0 (0.0%) | 15 (100.0%) | 0 (0.0%) | 15 (100.0%) |
| Lei 13.869/19 (Abuso de autoridade) | pen | 39 | 0 (0.0%) | 39 (100.0%) | 0 (0.0%) | 39 (100.0%) |
| CTB | pen | 323 | 323 (100.0%) | 323 (100.0%) | 322 (99.7%) | 322 (99.7%) |
| CLT (DL 5.452/43) | trab | 734 | 722 (98.4%) | 734 (100.0%) | 687 (93.6%) | 733 (99.9%) |
| Lei 8.036/90 (FGTS) | trab | 32 | 0 (0.0%) | 32 (100.0%) | 0 (0.0%) | 32 (100.0%) |
| Lei 5.584/70 (Processo do trabalho) | trab | 21 | 0 (0.0%) | 21 (100.0%) | 0 (0.0%) | 21 (100.0%) |
| Lei 7.783/89 (Greve) | trab | 19 | 0 (0.0%) | 19 (100.0%) | 0 (0.0%) | 19 (100.0%) |
| LC 150/15 (Doméstico) | trab | 47 | 0 (0.0%) | 47 (100.0%) | 0 (0.0%) | 47 (100.0%) |
| Lei 6.019/74 (Temporário/Terceirização) | trab | 20 | 0 (0.0%) | 20 (100.0%) | 0 (0.0%) | 20 (100.0%) |
| Lei 605/49 (RSR) | trab | 15 | 0 (0.0%) | 15 (100.0%) | 0 (0.0%) | 15 (100.0%) |
| Lei 8.213/91 (Benefícios) | trab | 131 | 130 (99.2%) | 131 (100.0%) | 127 (96.9%) | 131 (100.0%) |
| Lei 8.212/91 (Custeio) | trab/trib | 80 | 76 (95.0%) | 80 (100.0%) | 76 (95.0%) | 80 (100.0%) |
| CTN (L 5.172/66) | trib | 197 | 177 (89.8%) | 197 (100.0%) | 192 (97.5%) | 197 (100.0%) |
| LEF (L 6.830/80) | trib | 42 | 42 (100.0%) | 42 (100.0%) | 41 (97.6%) | 42 (100.0%) |
| LC 87/96 (Kandir/ICMS) | trib | 30 | 30 (100.0%) | 30 (100.0%) | 29 (96.7%) | 30 (100.0%) |
| LC 116/03 (ISS) | trib | 9 | 9 (100.0%) | 9 (100.0%) | 7 (77.8%) | 9 (100.0%) |
| Lei 8.397/92 (Cautelar fiscal) | trib | 20 | 0 (0.0%) | 20 (100.0%) | 0 (0.0%) | 20 (100.0%) |
| LC 24/75 (Convênios ICMS) | trib | 16 | 0 (0.0%) | 16 (100.0%) | 0 (0.0%) | 16 (100.0%) |
| Lei 9.430/96 | trib | 80 | 75 (93.8%) | 80 (100.0%) | 77 (96.2%) | 80 (100.0%) |
| LC 214/25 (IBS/CBS) | trib | 535 | 0 (0.0%) | 535 (100.0%) | 0 (0.0%) | 534 (99.8%) |

## 3. Tamanho e orçamento de tokens

Tokenizadores do cache local: `Polygl0t/Tucano2-qwen-3.7B-Instruct` e `Qwen/Qwen3-8B` (o mesmo do
manifesto congelado). Regra de orçamento inalterada: o bruto roda uma época exata; o expandido é
o prefixo do embaralhamento (semente 42) que casa o mesmo número de tokens.

| | congelado | v3 | Δ |
|---|---:|---:|---:|
| registros bruto | 39.856 | 42.034 | +2.178 |
| registros expandido | 41.900 | 49.834 | +7.934 |
| Tucano · bruto (= orçamento) | 50.580.859 | 52.356.157 | +1,78 M (+3,5%) |
| Tucano · expandido disponível | 59.430.766 | 69.674.854 | +10,2 M (+17%) |
| Tucano · épocas do expandido | 0,851 | 0,751 | |
| Qwen3 · bruto (= orçamento) | 65.655.511 | 67.853.878 | +2,20 M (+3,3%) |
| Qwen3 · expandido disponível | 74.824.507 | 88.063.753 | +13,2 M (+18%) |
| Qwen3 · épocas do expandido | 0,877 | 0,771 | |
| validação | 809 / 824 linhas (por bloco) | 641 / 1 (por documento) | |

Composição por grupo (Tucano, % de tokens). O congelado do expandido está **com o B2 aplicado**,
para comparar igual com igual (sem o B2 era norma 36,3 · caso 35,5 · juris 19,9 · enunciado 8,3).

| braço | grupo | congelado | v3 |
|---|---|---:|---:|
| bruto | caso | 78,3 | 77,0 |
| bruto | juris | 9,1 | 9,5 |
| bruto | norma | 8,9 | 10,6 |
| bruto | enunciado | 3,7 | 3,0 |
| expandido | norma | 36,3 | 43,2 |
| expandido | juris | 38,3 | 34,7 |
| expandido | caso | 17,0 | 14,8 |
| expandido | enunciado | 8,4 | 7,3 |

No bruto, 95,6% dos tokens do v3 são o congelado tal como estava e 1,6% são os blocos devolvidos
da validação; no expandido, 82,0% congelado, 1,6% devolvido e 16,4% fichas novas. O enunciado do
bruto cai porque o TST saiu de `enunciado` e foi para `juris`.

### Atenção: a cobertura que o modelo VÊ no expandido é a do prefixo

O portão vale para os arquivos. Mas o expandido é cortado em 75% (Tucano) / 77% (Qwen) do que
existe, e o corte é aleatório: a cobertura de fichas **dentro do prefixo treinado** fica entre
56% (LC 24) e 96% (LPI), tipicamente 75–85% (CPC 76%, CC 79%, CP 79%, CLT 82%; tabela por
diploma em `manifesto.json → familias.*.cobertura_fichas_no_prefixo`). Isso já acontecia no
congelado (0,85 época) e piora porque o expandido cresceu 17% e o bruto 3,5%. O bruto é lido
inteiro, então ali a cobertura treinada é 100%. Decisão de desenho pendente para o autor:
manter o corte aleatório (comparável às 180 condições), ou garantir as fichas de norma da
lista de referência no prefixo (o que desloca a composição do prefixo para `norma`).

### Par de composição casada (`casado_*`) — 32 M não é viável com o B2

O teto do par casado é a soma, por grupo, do mínimo entre os braços. Com o B2 a nota de
informativo sai de `caso` no expandido, e o `caso` do expandido cai para 10,29 M tokens (Tucano):
o teto vira **22,35 M** (caso 10,29 + juris 4,96 + norma 5,54 + enunciado 1,55). A 32 M algum
grupo de algum braço não teria material para a cota, e o código antigo encheria o braço curto
sem aviso e com composição diferente. Por isso o v3 monta o par **no teto viável, 22,35 M**, nas
duas famílias, com composição idêntica nos quatro arquivos: caso 46,1 · norma 24,8 · juris 22,2 ·
enunciado 6,9 (no congelado, sem B2: caso 65,8 · juris 14,3 · norma 14,1 · enunciado 5,8).

| arquivo | docs | tokens |
|---|---:|---:|
| `casado_tucano_bruto.jsonl` | 19.957 | 22.347.444 |
| `casado_tucano_expandido.jsonl` | 15.786 | 22.347.157 |
| `casado_qwen_bruto.jsonl` | 15.304 | 22.346.887 |
| `casado_qwen_expandido.jsonl` | 12.617 | 22.347.433 |

Para voltar a 32 M com composição casada seria preciso mais `caso` no expandido — ficha de
acórdão (a decisão D6 está em aberto) —, não mais norma.

## 4. Fichas novas: professor, parâmetros e custo real

* Normas: `expand_normas.gerar_expansao` (PROMPT_NORMA + REGRA_FORMATO, temperatura 0,4, até 2.000
  tokens). Verbetes TST/CARF: PROMPT_JURISPRUDENCIA como em `gera_cards_enunciados.py` (0,35, até
  3.500), com status "Persuasivo (uniformização do TST)", "Vinculante (art. 896-C da CLT)" nas
  teses de IRR/IAC e, no CARF, "observância obrigatória pelos conselheiros" + "vinculante para a
  administração tributária federal" quando a súmula tem portaria de vinculação.
* Montagem igual à do `rechunk_v4`: artigo revogado por inteiro fora (1), citação de julgado com
  número-molde removida (Q2: **1.323**), forma natural da referência (Q4: 87), corte por bloco na
  faixa de ~1.650 tokens. Nas fichas novas o sufixo volta ao identificador (`:ART:0075-A`), que o
  prompt perdia.
* **Truncamento herdado**: 95% das fichas novas de norma batem o teto de 2.000 tokens de saída e
  terminam no meio de um bloco — a mesma taxa das fichas Mistral já existentes
  (`leis_federais_expandidas.jsonl`: 7.012 de 7.344). Mantido de propósito (mesmos parâmetros).
  Registro: as fichas de **código** do congelado (CC, CPC, CLT, CPP, CF…) foram geradas por
  gpt-4o-mini, não pelo Mistral; as novas do CC, CP e ECA são Mistral.
* Piloto: 50 artigos (US$ 0,183) + 10 verbetes (US$ 0,053) → US$ 0,0037/ficha de norma e
  US$ 0,0052/ficha de verbete → projeção US$ 24,29, abaixo do teto de US$ 150; seguiu.

| execução | chamadas | tokens entrada | tokens saída | US$ |
|---|---:|---:|---:|---:|
| piloto normas | 50 | 65.333 | 100.000 | 0,18 |
| piloto juris | 10 | 17.051 | 29.335 | 0,05 |
| completo | 6.049 | 8.468.629 | 13.209.091 | 24,05 |
| refação das 15 falhas de formato | 15 | 20.468 | 30.815 | 0,06 |
| **total** | **6.124** | **8.571.481** | **13.369.241** | **24,34** |

Preço: US$ 0,50 / 1M entrada e US$ 1,50 / 1M saída (Mistral Large 3, sob demanda, us-east-1).
Tokens medidos pelo `usage` do Bedrock (`llm_client.USO`), registro em
`data/ablacao_regime_v3/custo_api.jsonl`. O bruto não gerou chamada nenhuma: o cabeçalho
`[RESUMO DA LEI]` dos diplomas que já existiam vem do cache do N10, e o dos diplomas novos é a
**ementa da própria lei** (texto da fonte, não de modelo).

## 5. O que ficou de fora, e por quê

* **Acórdãos do TST**: `jurisprudencia.tst.jus.br` tem `robots.txt` com `Disallow: /` e não há
  conjunto aberto de inteiro teor com termos de uso. Pulado.
* **Acórdãos do CARF**: os "dados abertos" do CARF são gerenciais (estoque, produtividade); o
  acervo de acórdãos só existe como sistema de busca, sem licença nem exportação em lote.
  Pulado.
* **Verbetes TST cancelados** (162 súmulas, 224 OJs da SBDI-I…) e **súmulas CARF revogadas** (6):
  fora por definição. PN 42 e PN 116: extração do PDF quebrada (< 60 caracteres), fora.
* **Validação do expandido**: só 1 documento cumpre a regra nova; ver a recomendação na seção 1.
* **Súmulas do STF com `None` no número (A5)** e a repetição RESUMO/TEXTO (B3) continuam como no
  congelado — não eram objeto desta correção, e mexer nelas tiraria a comparabilidade.
* `leis/recoleta_v3/raw/lug_anexo_I_transcricao.txt` (deixado por uma tentativa anterior, sem
  proveniência registrada e com metade do tamanho esperado) **não** foi usado; a LUG veio do OCR
  do PDF oficial.

## 6. Ajustes de código feitos no caminho

* `pipeline/referencia_v3.py`: o detector de artigo no bruto passou a aceitar NBSP ("Art.\xa01º") e
  o número na linha seguinte ("Art.\n135"); sem isso a Lei 8.112 media 47 de 239 e a 14.133, 7 de
  193, quando estavam completas.
* `pipeline/monta_corpus_v3.py`: CRLF do Planalto normalizado antes do divisor ("Art.\r\n18" não
  abria linha e a Lei 8.137 perdia 8 de 18 artigos); grupo de ficha com cerca de markdown antes do
  marcador (1 ficha do CTB) e de enunciado do CJF com identificador longo (8) reconhecido; aborta se
  algum documento ficar sem grupo.
* Nenhum script antigo foi alterado (o `rechunk_v4.py` segue com o split antigo; a regra nova mora
  em `monta_corpus_v3.elegivel_validacao` / `completa_validacao`).

## 7. Como reproduzir

```bash
cd "Artigo Treino Juridico"
# 1. coletas (já feitas em 14/11/2026; idempotentes, pulam o que existe)
juridico-env/bin/python pipeline/recoleta_v3.py
juridico-env/bin/python pipeline/lug_anexo_ocr_v3.py          # requer tesseract e pdftoppm
juridico-env/bin/python pipeline/coleta_trab_trib_v3.py       # requer pdftotext
# 2. medir o que falta (não grava nada)
juridico-env/bin/python pipeline/monta_corpus_v3.py --cobertura
# 3. fichas: piloto, estimativa, completo (retomável; para se passar do teto)
juridico-env/bin/python pipeline/gera_cards_v3.py --piloto 50 --piloto-juris 10
juridico-env/bin/python pipeline/gera_cards_v3.py --estima
juridico-env/bin/python pipeline/gera_cards_v3.py --completo --workers 16 --teto-usd 150
# 4. montagem, portão, tokens, par casado e manifesto (~1 min; tokenizadores do cache HF)
juridico-env/bin/python pipeline/monta_corpus_v3.py
```

Arquivos: `data/ablacao_regime_v3/{bruto,expandido}_completo.jsonl` (campos `text`, `grupo`,
`origem`), `{bruto,expandido}_valid.jsonl`, `casado_{tucano,qwen}_{bruto,expandido}.jsonl`
(só `text`), `cards_v3.jsonl` (fichas geradas, com texto de origem e modelo), `custo_api.jsonl`,
`manifesto.json` (orçamento, composição, origem, cobertura antes/depois/no prefixo e sha256 de
cada arquivo).
