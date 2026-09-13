#!/bin/bash
# Etapa 1 da ablacao de regime — braco Qwen, numa GPU.  30/08
#
#   bash cadeia_ablacao_qwen.sh <lista de jobs>
#   job = MODELO:REGIME:SEMENTE   ex.: 8B:bruto:42
#
# Orcamento: 65,66M tokens do tokenizador do Qwen — o braco MENOR (o bruto) inteiro.
# O bruto roda 1 epoca exata; o expandido e truncado ate casar o mesmo total.
#
# O harness dimensiona max_steps por um fator de aproveitamento de sequencia que foi
# MEDIDO a 2048 (0,64).  A 4096 ele superestima em ~60% e o treino passaria muito do
# orcamento.  Os fatores abaixo sao calculados do tamanho medio real dos documentos
# em tokens do Qwen (bruto 1.647, expandido 1.786) para que max_steps caia ~5% acima
# do necessario: a marca dispara com folga e a cosseno fecha quase inteira.
#
# expandable_segments: com vocabulario de 151k do Qwen, o tensor de logits de uma
# sequencia de 4096 pede 2,5 GB sozinho.  Na L4 (22,0 GiB uteis) isso estourou com
# 3,6 GiB reservados-mas-nao-alocados: fragmentacao pura.  O alocador expansivel
# devolve esse espaco.
#
# Laco de repeticao: o harness ja retoma do checkpoint mais recente (salvo a cada
# 200 passos), entao uma falha de memoria num documento longo custa minutos, nao a
# condicao inteira.  Sem isso a cadeia pularia o job e deixaria um buraco no desenho.
set -uo pipefail
cd ~/q5 || exit 1
ORC=65.66e6
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
TENTATIVAS=4

# Espera o treino que ja estiver rodando: assim da para trocar a LISTA de jobs sem
# descartar horas em curso — o job que terminar sozinho e pulado pelo teste de
# ckpt_66M logo abaixo.  O padrao e montado em duas partes de proposito: escrito
# inteiro, ele casaria com a propria linha de comando deste script.
ALVO="train""_cpt_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 120; done

for JOB in "$@"; do
  IFS=: read -r MOD REG SEED <<< "$JOB"
  case "$REG" in
    bruto)     APROV=0.5516 ;;
    expandido) APROV=0.6210 ;;
    *) echo "regime desconhecido: $REG"; exit 1 ;;
  esac
  # Liger so no 14B: com vocabulario de 151k, o tensor de logits de uma sequencia de
  # 4096 pede 2,5 GB e o 14B nao cabe em 22 GiB sem o kernel fundido (medido: estourou
  # nas 4 tentativas, com so 463 MiB de fragmentacao — faltava espaco de verdade).
  # O 8B cabe sem ele.  E reformulacao exata da entropia cruzada, nao aproximacao, e
  # os dois regimes de cada modelo usam a mesma configuracao, que e o que o contraste
  # exige.
  LIGER=""; [ "$MOD" = "14B" ] && LIGER="--liger"
  SAIDA="adapters/AB_${REG}_s${SEED}_qwen${MOD}"
  if [ -d "$SAIDA/ckpt_66M" ]; then
    echo "=== $JOB — ja existe, pulando ==="; continue
  fi
  echo "=== $JOB — inicio $(date '+%d/%m %H:%M') ==="
  for T in $(seq 1 $TENTATIVAS); do
    [ -d "$SAIDA/ckpt_66M" ] && break
    [ "$T" -gt 1 ] && echo "--- tentativa $T (retoma do ultimo checkpoint) $(date '+%H:%M')"
    APROVEITAMENTO_SEQ=$APROV .venv/bin/python train_cpt_cuda.py \
        --model "Qwen/Qwen3-${MOD}" \
        --data "data/AB_${REG}" \
        --output "$SAIDA" \
        --checkpoints-tokens "$ORC" \
        --max-seq 4096 --seed "$SEED" \
        --quant nf4 --lr-schedule cosine \
        --batch-size 1 --grad-accum 16 $LIGER \
        >> "logs_AB_${REG}_s${SEED}_${MOD}.txt" 2>&1 && break
  done
  echo "=== $JOB — fim $(date '+%d/%m %H:%M') · $(ls -d $SAIDA/ckpt_* 2>/dev/null || echo SEM-CHECKPOINT) ==="
done
echo "=== CADEIA CONCLUIDA $(date '+%d/%m %H:%M') ==="
