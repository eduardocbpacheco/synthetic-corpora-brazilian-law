#!/bin/bash
# Sobe o vLLM na L4 assim que o treino em curso terminar, servindo a base do Tucano 1,5B
# com os adapters da ablacao. Usa a FOLGA da L4 (ela fecha 03/09 contra 04/09 da maquina
# critica) para entregar o primeiro contraste sem atrasar nada.
set -uo pipefail
cd /home/ubuntu/tucano || exit 1
ALVO="train""_cpt_cuda"
while ps -eo args | grep -- "$ALVO" | grep -qv grep; do sleep 120; done
echo "treino encerrado $(date '+%d/%m %H:%M') — subindo vLLM"
sleep 20
BASE=Polygl0t/Tucano2-qwen-1.5B-Instruct PEFTDIR=peft_ab nohup bash serve_vllm.sh > logs_vllm_ab.txt 2>&1 &
for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && { touch /home/ubuntu/tucano/VLLM_PRONTO; \
    echo "vLLM pronto $(date '+%H:%M')"; curl -s http://127.0.0.1:8000/v1/models | head -c 600; exit 0; }
  sleep 10
done
echo "vLLM nao respondeu em 15 min"; exit 1
