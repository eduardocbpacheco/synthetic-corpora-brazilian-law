#!/bin/bash
# Etapa 2 — ablacao de fine-tuning.  05/09
#
#   bash cadeia_sft_ablacao.sh <jobs>
#   job = MODELO:REGIME:BLOCO:SEMENTE     ex.: 1.5B:bruto:I:42
#   REGIME = bruto | expandido | nenhum   (nenhum = SFT sobre o base, sem CPT)
#
# Constantes do protocolo, iguais ao yaml_sft do Mac: rank 32, alpha 64, ultimas 24
# camadas, 7 modulos, LR 1e-5 cosseno, lote efetivo 16, max_seq 3072, MASCARA DE
# ENUNCIADO (treina so na resposta), retomada do adapter de CPT.
#
# EPOCAS FIXAS em 3, nao iteracoes fixas: os blocos diferem 13x em tamanho e iters=1200
# daria 6,7 epocas no X contra 87 no VII, que e memorizacao. O iters vem do arquivo.
#
# Todo o SFT roda em CUDA, inclusive o dos Tucano cujo CPT foi em mlx. Assim a plataforma
# do SFT e CONSTANTE entre os 9 pontos de partida, em vez de confundir plataforma com
# modelo. A conversao mlx->PEFT foi verificada com erro relativo 0,0.
set -uo pipefail
cd ~/q5 || exit 1
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
TENTATIVAS=3

declare -A BASE=( [1.5B]=Polygl0t/Tucano2-qwen-1.5B-Instruct
                  [3.7B]=Polygl0t/Tucano2-qwen-3.7B-Instruct
                  [8B]=Qwen/Qwen3-8B  [14B]=Qwen/Qwen3-14B )
declare -A QUANT=( [1.5B]=none [3.7B]=none [8B]=none [14B]=nf4 )
# O 8B entrou no liger em 06/09: na L4 de 22 GiB ele estourava pedindo 1,74 GiB, que e
# exatamente o tamanho dos logits de uma sequencia de 3072 no vocabulario de 151k do Qwen
# (3072 x 151669 x 2 bytes x 2 pelo upcast). O liger funde a linear com a entropia cruzada
# e nunca materializa esse tensor. Doze condicoes falharam antes de a causa aparecer.
declare -A LIGER=( [1.5B]="" [3.7B]="" [8B]="--liger" [14B]="--liger" )
# O diretorio do adapter de CPT traz a familia no nome: tucano1.5B, qwen8B.
declare -A FAM=( [1.5B]=tucano1.5B [3.7B]=tucano3.7B [8B]=qwen8B [14B]=qwen14B )

ALVO="train_""sft_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 120; done

for JOB in "$@"; do
  IFS=: read -r MOD REG BL SEED <<< "$JOB"
  DADOS="data/blocos/$BL"
  [ -d "$DADOS" ] || { echo "bloco $BL ausente"; continue; }
  N=$(wc -l < "$DADOS/train.jsonl")
  ITERS=$(( (3*N + 15) / 16 ))            # teto de 3 epocas, lote efetivo 16
  SAIDA="adapters/sft_${BL}_${REG}_s${SEED}_${MOD}"
  if [ -d "$SAIDA/final" ]; then echo "=== $JOB — ja existe, pulando ==="; continue; fi
  if [ "$REG" = "nenhum" ]; then CPT=""; else CPT="--cpt-adapter peft_cpt/AB_${REG}_s42_${FAM[$MOD]}"; fi
  echo "=== $JOB · $N exemplos · $ITERS iters — inicio $(date '+%d/%m %H:%M') ==="
  for T in $(seq 1 $TENTATIVAS); do
    [ -d "$SAIDA/final" ] && break
    [ "$T" -gt 1 ] && echo "--- tentativa $T $(date '+%H:%M')"
    .venv/bin/python train_sft_cuda.py \
        --model "${BASE[$MOD]}" --data "$DADOS" --output "$SAIDA" \
        $CPT --iters "$ITERS" --seed "$SEED" \
        --quant "${QUANT[$MOD]}" ${LIGER[$MOD]} \
        >> "logs_sft_${BL}_${REG}_s${SEED}_${MOD}.txt" 2>&1 && break
  done
  echo "=== $JOB — fim $(date '+%d/%m %H:%M') · $([ -d $SAIDA/final ] && echo OK || echo FALHOU) ==="
done
echo "=== CADEIA SFT CONCLUIDA $(date '+%d/%m %H:%M') ==="
