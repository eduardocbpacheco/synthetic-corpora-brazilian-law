#!/bin/bash
# Geração e juízo das condições da etapa 2 (corpus v3, Tucano 3,7B).  18/11
#
# Mesmos tetos da regeração: discursivas a 1.500 tokens, peças a 3.000, 10 runs, em
# avaliacao/resultados_t3k/ (o nota.py lê as duas dali quando NOTA_PECAS aponta para lá).
# Primeiro gera todas as condições, até PARALELO por vez; depois desliga a instância
# (PARAR=<instance-id>, opcional), porque o juízo é API e não precisa da GPU; por fim julga.
#
#   PORTA=8201 PARAR=i-0adb87b55589693cd bash pipeline/gera_v3_t3k.sh sft_I_v3_bruto_s42_3.7B ... AB_v3_bruto_S42_T37
#
# O vLLM tem de estar servindo os adapters com esses nomes, e o túnel aberto na PORTA.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
set -a; . ./.env.aws.shared; set +a
PY=juridico-env/bin/python
PORTA=${PORTA:-8201}
PARALELO=${PARALELO:-3}
WORKERS=${WORKERS:-8}
export GERA_TIMEOUT=${GERA_TIMEOUT:-7200}
RAIZ=avaliacao/resultados_t3k
mkdir -p "$RAIZ" logs

gera() {
  c=$1
  for i in 1 2 3; do   # o cache retoma por questão; nova tentativa só refaz o que faltou
    $PY -u aws/gera_remoto.py --host 127.0.0.1 --porta "$PORTA" --conds "$c" --tipo discursiva \
        --max-tokens 1500 --n-runs 10 --raiz-cache "$RAIZ" --workers "$WORKERS" >> "logs/v3_${c}.log" 2>&1
    $PY -u aws/gera_remoto.py --host 127.0.0.1 --porta "$PORTA" --conds "$c" --tipo peca \
        --max-tokens 3000 --n-runs 10 --raiz-cache "$RAIZ" --workers "$WORKERS" >> "logs/v3_${c}.log" 2>&1
    completa "$c" && break
  done
  completa "$c" && echo "$(date '+%d/%m %H:%M') gerada $c" || echo "$(date '+%d/%m %H:%M') INCOMPLETA $c"
}

completa() {  # 105 questões × 10 runs no cache
  $PY - "$RAIZ/.cache_$1/fase1_respostas.json" <<'EOF'
import json, sys
try:
    c = json.load(open(sys.argv[1]))
except (OSError, ValueError):
    sys.exit(1)
sys.exit(0 if len(c) >= 105 and all(len(v) >= 10 for v in c.values()) else 1)
EOF
}

for c in "$@"; do   # nome com espaço = lista não separada (zsh), e aí nada roda
  case "$c" in *" "*) echo "condição com espaço: '$c'"; exit 1;; esac
done

n=0
for c in "$@"; do
  gera "$c" &
  n=$((n+1))
  [ $((n % PARALELO)) -eq 0 ] && wait
done
wait
echo "=== geração concluída $(date '+%d/%m %H:%M')"

faltam=0
for c in "$@"; do completa "$c" || faltam=$((faltam+1)); done
if [ "$faltam" -gt 0 ]; then
  echo "=== $faltam condições incompletas — instância fica ligada, nada é julgado"; exit 1
fi
if [ -n "${PARAR:-}" ]; then
  aws ec2 stop-instances --region us-east-1 --instance-ids "$PARAR" --output text >/dev/null \
    && echo "=== $PARAR desligada $(date '+%d/%m %H:%M')"
fi

n=0
for c in "$@"; do
  { $PY -u avaliacao/julga_rabula.py --model-id "$c" --n-runs 10 --workers 8 --res "$RAIZ" \
      >> "logs/v3_${c}.log" 2>&1; echo "$(date '+%d/%m %H:%M') julgada $c"; } &
  n=$((n+1))
  [ $((n % 4)) -eq 0 ] && wait
done
wait
echo "=== v3 concluído $(date '+%d/%m %H:%M')"
