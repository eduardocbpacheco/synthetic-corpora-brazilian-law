#!/bin/bash
# Etapa 2 da réplica (15/11/2026): CPT do Tucano 3,7B no corpus v3 e, sobre cada CPT, as SFT
# dos blocos I e VI (X no disco) nas sementes 42, 43 e 44.
#
# Cada job é REGIME:ORCAMENTO:FATOR:CKPT, gerado de data/cpt_v3/cadeia.json
# (pipeline/monta_dados_cpt_v3.py). Os dados vão em ~/q5/data/cpt_v3/<regime>/.
#
#   nohup bash cadeia_v3.sh v3_bruto:52356157:0.4074:ckpt_52M ... > cadeia_v3.log 2>&1 &
#
# Hiperparâmetros idênticos à cadeia_ablacao_tucano.sh (a das 180 condições): seq 4.096,
# lote 1 × 16, LR do protocolo com cosseno, sem quantização, semente 42 no CPT. O que muda
# é o corpus, o orçamento e o fator, que põe a parada no mesmo ponto do cosseno que no
# congelado. O controle `nenhum` não depende do corpus e é reaproveitado da grade.
set -uo pipefail
cd ~/q5 || exit 1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
TAM=3.7B
FAM=tucano3.7B
TENTATIVAS=4
ALVO="train""_cpt_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 120; done

for JOB in "$@"; do
  IFS=: read -r REG ORC APROV CKPT <<< "$JOB"
  SAIDA="adapters/AB_${REG}_s42_${FAM}"
  echo "=== CPT $REG · $ORC tokens · fator $APROV — inicio $(date '+%d/%m %H:%M') ==="
  for T in $(seq 1 $TENTATIVAS); do
    [ -d "$SAIDA/$CKPT" ] && break
    [ "$T" -gt 1 ] && echo "--- tentativa $T (retoma do ultimo checkpoint) $(date '+%H:%M')"
    APROVEITAMENTO_SEQ=$APROV .venv/bin/python train_cpt_cuda.py \
        --model "Polygl0t/Tucano2-qwen-${TAM}-Instruct" \
        --data "data/cpt_v3/$REG" \
        --output "$SAIDA" \
        --checkpoints-tokens "$ORC" \
        --max-seq 4096 --seed 42 \
        --quant none --lr-schedule cosine \
        --batch-size 1 --grad-accum 16 \
        >> "logs_AB_${REG}_s42_${FAM}.txt" 2>&1 && break
  done
  if [ ! -d "$SAIDA/$CKPT" ]; then
    echo "=== CPT $REG FALHOU $(date '+%d/%m %H:%M') — pulando as SFT ==="; continue
  fi
  echo "=== CPT $REG — fim $(date '+%d/%m %H:%M') ==="
  rm -rf "peft_cpt/AB_${REG}_s42_${FAM}"
  cp -r "$SAIDA/$CKPT" "peft_cpt/AB_${REG}_s42_${FAM}"

  SFT=()
  for BL in I X; do for S in 42 43 44; do SFT+=("$TAM:$REG:$BL:$S"); done; done
  bash cadeia_sft_ablacao.sh "${SFT[@]}"
done
echo "=== CADEIA V3 CONCLUIDA $(date '+%d/%m %H:%M') ==="
