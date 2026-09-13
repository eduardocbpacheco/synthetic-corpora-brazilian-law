#!/bin/bash
# Geracao das respostas do benchmark para a RODADA DE CONTROLES (regime `nenhum`).  11/09
#
#   bash gera_ctrl_ablacao.sh <MODELO>      ex.: 14B
#
# Igual ao gera_sft_ablacao.sh, com uma diferenca que importa: o glob e restrito a
# `sft_*_nenhum_s*_$MOD`. O script original casa `adapters/sft_*_${MOD}/final`, que na
# g5 sao os 36 adapters do fatorial mais os 4 controles novos. Servir 40 LoRAs num 14B
# em 4 bits e o cenario que derrubou o vLLM em 10/09: o pool de CPU de 36 adapters dava
# ~11 GB numa maquina de 15 GB. Aqui sao 2 a 6 adapters, e o pool cabe folgado.
set -uo pipefail
cd ~/q5 || exit 1
MOD=${1:?informe o modelo: 1.5B, 8B ou 14B}
declare -A BASE=( [1.5B]=Polygl0t/Tucano2-qwen-1.5B-Instruct
                  [8B]=Qwen/Qwen3-8B  [14B]=Qwen/Qwen3-14B )

ALVO="train_""sft_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 180; done

DIR=peft_ctrl_$MOD
rm -rf $DIR; mkdir -p $DIR
n=0
for a in adapters/sft_*_nenhum_s*_${MOD}/final; do
  [ -d "$a" ] || continue
  nome=$(basename $(dirname "$a"))
  ln -sfn ~/q5/"$a" "$DIR/$nome"; n=$((n+1))
done
echo "$n adapters de controle de $MOD em $DIR:"; ls $DIR
[ "$n" -eq 0 ] && { echo "nenhum adapter de controle pronto"; exit 1; }

V="vl""lm"; ps -eo pid,args|grep -i -- "$V"|grep -v grep|awk '{print $1}'|xargs -r kill; sleep 20
cd ~/tucano 2>/dev/null || { echo "sem ~/tucano (vLLM) nesta maquina"; exit 1; }
Q=""; [ "$MOD" = "14B" ] && Q="bnb"
BASE=${BASE[$MOD]} PEFTDIR=~/q5/$DIR QUANT=$Q nohup bash serve_vllm.sh > logs_vllm_ctrl_$MOD.txt 2>&1 &
for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && { touch ~/q5/VLLM_CTRL_PRONTO_$MOD; \
    echo "vLLM pronto com $n adapters de controle $(date '+%d/%m %H:%M')"; exit 0; }
  sleep 10
done
echo "vLLM nao respondeu"; exit 1
