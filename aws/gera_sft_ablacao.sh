#!/bin/bash
# Geracao das respostas do benchmark para as condicoes de SFT da etapa 2.  05/09
#
#   bash gera_sft_ablacao.sh <MODELO>      ex.: 1.5B
#
# Sobe UM vLLM com a base do modelo e TODOS os adapters de SFT daquele modelo, e gera
# tudo numa passada. O batching continuo mistura no mesmo passo requisicoes de adapters
# diferentes, entao as condicoes geram juntas em vez de em fila — que e a razao de o
# serve_vllm.sh existir com multi-LoRA.
#
# O juizo NAO roda aqui: e API, nao toca GPU, e roda no Mac em paralelo.
set -uo pipefail
cd ~/q5 || exit 1
MOD=${1:?informe o modelo: 1.5B, 3.7B, 8B ou 14B}
declare -A BASE=( [1.5B]=Polygl0t/Tucano2-qwen-1.5B-Instruct
                  [3.7B]=Polygl0t/Tucano2-qwen-3.7B-Instruct
                  [8B]=Qwen/Qwen3-8B  [14B]=Qwen/Qwen3-14B )

# espera o treino daquela maquina acabar
ALVO="train_""sft_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 180; done

DIR=peft_sft_$MOD
rm -rf $DIR; mkdir -p $DIR
n=0
for a in adapters/sft_*_${MOD}/final; do
  [ -d "$a" ] || continue
  nome=$(basename $(dirname "$a"))          # sft_I_bruto_s42_1.5B
  ln -sfn ~/q5/"$a" "$DIR/$nome"; n=$((n+1))
done
echo "$n adapters de $MOD em $DIR"
[ "$n" -eq 0 ] && exit 1

V="vl""lm"; ps -eo pid,args|grep -i -- "$V"|grep -v grep|awk '{print $1}'|xargs -r kill; sleep 20
cd ~/tucano 2>/dev/null || { echo "sem ~/tucano (vLLM) nesta maquina"; exit 1; }
BASE=${BASE[$MOD]} PEFTDIR=~/q5/$DIR nohup bash serve_vllm.sh > logs_vllm_sft_$MOD.txt 2>&1 &
for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && { touch ~/q5/VLLM_SFT_PRONTO; \
    echo "vLLM pronto com $n adapters $(date '+%H:%M')"; exit 0; }
  sleep 10
done
echo "vLLM nao respondeu"; exit 1
