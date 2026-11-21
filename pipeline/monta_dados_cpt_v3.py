#!/usr/bin/env python3
"""monta_dados_cpt_v3.py — diretórios de treino do CPT da réplica (etapa 2), Tucano 3,7B.

Lê data/ablacao_regime_v3/ e grava data/cpt_v3/<regime>/{train,valid}.jsonl no formato que o
aws/train_cpt_cuda.py espera, mais data/cpt_v3/cadeia.json com o orçamento e o fator de
aproveitamento de cada regime. Decisões do autor em 15/11/2026:

- grade (v3_bruto, v3_expandido): mesma regra das 180 condições. O arquivo vai inteiro e o
  trainer para no orçamento (o tamanho do bruto); no expandido, quem escolhe os ~75% vistos é
  o embaralhamento do próprio trainer, como no congelado.
- par casado a 22,35 M (casado_bruto, casado_expandido): composição idêntica, lido inteiro.
- mistura 50/50: metade do orçamento de cada braço, prefixos dos arquivos já embaralhados
  (semente 42), e a união embaralhada de novo.
- validação: bruto_valid.jsonl nos cinco. Só monitora; nada escolhe checkpoint.

O fator de aproveitamento (APROVEITAMENTO_SEQ) não é medida aqui, é parâmetro de cronograma.
O trainer põe max_steps = orçamento / (16 × 4.096 × fator) + 800, e o cosseno da LR corre sobre
esses passos. Com lote 1 não há padding, então o passo real treina 16 × (média do comprimento
truncado em 4.096). No congelado os fatores 0,425 e 0,5012 fizeram os dois braços pararem em
95,2% do cronograma (2.492 de 2.616 e 2.228 de 2.340 passos, conferido nos logs). Aqui o fator
de cada regime é escolhido para a parada cair no mesmo ponto do cosseno.

    juridico-env/bin/python pipeline/monta_dados_cpt_v3.py
"""
from __future__ import annotations

import json
import math
import os
import random
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
from transformers import AutoTokenizer  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
V3 = RAIZ / "data/ablacao_regime_v3"
SAIDA = RAIZ / "data/cpt_v3"
TOKENIZADOR = "Polygl0t/Tucano2-qwen-3.7B-Instruct"
MAX_SEQ, LOTE, MARGEM = 4096, 16, 800
FRACAO_PARADA = 0.952   # passo da parada / max_steps no congelado, nos dois braços
SEMENTE = 42


def le(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8")]


def comprimentos(textos: list[str], tok) -> list[int]:
    n = []
    for i in range(0, len(textos), 2000):
        n.extend(len(x) for x in tok(textos[i:i + 2000])["input_ids"])
    return n


def prefixo(docs: list[dict], n: list[int], orc: int) -> list[dict]:
    acc = 0
    for i, k in enumerate(n):
        if acc + k > orc:
            return docs[:i]
        acc += k
    return docs


def fator(orc: int, n: list[int], le_inteiro: bool) -> dict:
    """Fator que põe a parada em FRACAO_PARADA do cronograma.

    Na grade o trainer para no orçamento; num arquivo lido inteiro o orçamento é o próprio
    arquivo truncado, que é o que o contador de tokens do trainer vê.
    """
    trunc = [min(x, MAX_SEQ) for x in n]
    real = sum(trunc) / len(trunc) / MAX_SEQ
    passos = math.ceil(orc / (LOTE * MAX_SEQ * real))
    teto = math.ceil(passos / FRACAO_PARADA)
    f = orc / (LOTE * MAX_SEQ * (teto - MARGEM))
    return {"aproveitamento_real": round(real, 4), "passos_previstos": passos,
            "max_steps": teto, "fator": round(f, 4), "le_inteiro": le_inteiro}


def main() -> None:
    tok = AutoTokenizer.from_pretrained(TOKENIZADOR)
    man = json.load(open(V3 / "manifesto.json"))
    orc = man["familias"]["tucano"]["orcamento_tokens"]
    valid = (V3 / "bruto_valid.jsonl").read_text("utf-8")

    bruto, exp = le(V3 / "bruto_completo.jsonl"), le(V3 / "expandido_completo.jsonl")
    nb = comprimentos([d["text"] for d in bruto], tok)
    ne = comprimentos([d["text"] for d in exp], tok)

    metade = orc // 2
    mb, me = prefixo(bruto, nb, metade), prefixo(exp, ne, metade)
    mistura = mb + me
    random.Random(SEMENTE).shuffle(mistura)

    regimes = {
        "v3_bruto": (bruto, False),
        "v3_expandido": (exp, False),
        "casado_bruto": (le(V3 / "casado_tucano_bruto.jsonl"), True),
        "casado_expandido": (le(V3 / "casado_tucano_expandido.jsonl"), True),
        "mistura": (mistura, True),
    }
    cadeia = {}
    for nome, (docs, inteiro) in regimes.items():
        n = comprimentos([d["text"] for d in docs], tok)
        alvo = sum(min(x, MAX_SEQ) for x in n) if inteiro else orc
        # Num arquivo lido inteiro a marca fica 0,1% abaixo do total truncado: o contador do
        # trainer soma rótulos != -100, e o colator mascara todo token igual ao de padding
        # (que no Tucano é o EOS); com a marca exata, um token a menos e ela nunca dispara.
        alvo = int(alvo * 0.999) if inteiro else alvo
        d = SAIDA / nome
        d.mkdir(parents=True, exist_ok=True)
        with (d / "train.jsonl").open("w", encoding="utf-8") as f:
            for x in docs:
                f.write(json.dumps({"text": x["text"]}, ensure_ascii=False) + "\n")
        (d / "valid.jsonl").write_text(valid, "utf-8")
        cadeia[nome] = {"docs": len(docs), "tokens": sum(n), "orcamento": alvo,
                        "ckpt": f"ckpt_{alvo/1e6:.0f}M", **fator(alvo, n, inteiro)}
        if nome == "mistura":
            cadeia[nome]["docs_por_braco"] = {"bruto": len(mb), "expandido": len(me)}
            cadeia[nome]["tokens_por_braco"] = {"bruto": sum(nb[:len(mb)]),
                                                "expandido": sum(ne[:len(me)])}
        print(f"{nome:17s} docs {len(docs):6d} · {sum(n)/1e6:6.2f} M tokens · orçamento "
              f"{alvo/1e6:6.2f} M · fator {cadeia[nome]['fator']:.4f} · "
              f"max_steps {cadeia[nome]['max_steps']}", flush=True)
    (SAIDA / "cadeia.json").write_text(json.dumps(cadeia, ensure_ascii=False, indent=1), "utf-8")
    print(f"→ {SAIDA}/cadeia.json")


if __name__ == "__main__":
    main()
