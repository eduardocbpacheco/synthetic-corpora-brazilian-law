#!/bin/bash
# Semente 44 do braco Tucano, na AWS.  03/09
#
#   bash cadeia_ablacao_tucano.sh <jobs>     job = TAM:REGIME:SEMENTE  ex.: 3.7B:bruto:44
#
# Por que aqui e nao no Mac: o Mac era o gargalo (09/09) e duas GPUs ficariam ociosas
# cinco dias. Plataforma passa a ser confundida com a semente 44 — mas cada PAR
# bruto/expandido continua inteiro numa so plataforma, semente e fator de ruido, e a
# replicacao mlx contra CUDA foi medida em +0,0pp (p=0,908, achado 25).
#
# Orcamento: 50,58M tokens do tokenizador do Tucano — o mesmo do Mac.
# Sem quantizacao: o 3,7B em bf16 sao 7,4 GB, cabe folgado nos 24 GB.
# Sem Liger: vocabulario de 49k da logits de 0,8 GB, nao ha aperto (o 14B do Qwen
# precisava porque 151k dao 2,5 GB).
#
# APROV recalibrado do tamanho medio real dos documentos em tokens do Tucano
# (bruto 1.269, expandido 1.418), para max_steps cair ~5% acima do necessario.
set -uo pipefail
cd ~/q5 || exit 1
ORC=50.58e6
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
TENTATIVAS=4

ALVO="train""_cpt_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 120; done

for JOB in "$@"; do
  IFS=: read -r TAM REG SEED <<< "$JOB"
  case "$REG" in
    bruto)     APROV=0.4250 ;;
    expandido) APROV=0.5012 ;;
    *) echo "regime desconhecido: $REG"; exit 1 ;;
  esac
  SAIDA="adapters/AB_${REG}_s${SEED}_tucano${TAM}"
  if [ -d "$SAIDA/ckpt_51M" ]; then echo "=== $JOB — ja existe, pulando ==="; continue; fi
  echo "=== $JOB — inicio $(date '+%d/%m %H:%M') ==="
  for T in $(seq 1 $TENTATIVAS); do
    [ -d "$SAIDA/ckpt_51M" ] && break
    [ "$T" -gt 1 ] && echo "--- tentativa $T (retoma do ultimo checkpoint) $(date '+%H:%M')"
    APROVEITAMENTO_SEQ=$APROV .venv/bin/python train_cpt_cuda.py \
        --model "Polygl0t/Tucano2-qwen-${TAM}-Instruct" \
        --data "data/AB_${REG}" \
        --output "$SAIDA" \
        --checkpoints-tokens "$ORC" \
        --max-seq 4096 --seed "$SEED" \
        --quant none --lr-schedule cosine \
        --batch-size 1 --grad-accum 16 \
        >> "logs_AB_${REG}_s${SEED}_tucano${TAM}.txt" 2>&1 && break
  done
  echo "=== $JOB — fim $(date '+%d/%m %H:%M') · $(ls -d $SAIDA/ckpt_* 2>/dev/null || echo SEM-CHECKPOINT) ==="
done
echo "=== CADEIA TUCANO CONCLUIDA $(date '+%d/%m %H:%M') ==="
