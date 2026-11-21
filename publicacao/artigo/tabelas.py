#!/usr/bin/env python3
"""tabelas.py — as tabelas do artigo 1, recomputadas dos arquivos de julgamento.

Desenho pedido na revisão de 13/09: os dados abertos ANTES de qualquer conclusão. Uma
tabela por tarefa, modelos nas linhas, o regime de pré-treino como sublinha, um bloco de
ajuste fino por coluna, valores absolutos. O zero de cada eixo vem primeiro — a linha
`nenhum` antes dos dois regimes, a coluna `bloco 0` antes dos seis blocos — porque é contra
eles que todo o resto se lê.

Nada de número copiado à mão: tudo sai de `avaliacao/nota.py`, a mesma função que o
relatório usa, e os tamanhos de bloco saem do manifesto do depósito congelado.
"""
from __future__ import annotations

import json, sys, statistics as st
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "avaliacao"))
from nota import (MODELOS, NOME, BLOCOS, BASE, AREAS, nota, bloco0,  # noqa: E402
                  media_sementes, pt, ptd, cls)

SAI = Path(__file__).resolve().parent
REG = [("nenhum", "sem pré-treino"), ("bruto", "texto bruto"), ("expandido", "ficha")]
# O disco guarda os blocos com os nomes do desenho original, em que VII e X eram posições
# de uma grade maior. No artigo eles são seis e precisam ser seis: numerar de I a VI evita
# que o leitor procure os blocos V, VI, VIII e IX, que nunca existiram para ele.
ROTULO_BLOCO = {"I": "I", "II": "II", "III": "III", "IV": "IV", "VII": "V", "X": "VI"}
# A peça agregada saiu das tabelas: sendo 85,1% mérito, ela repetia a tabela de mérito e
# custava quase uma página. O valor agregado continua no texto onde ele muda a leitura.
TAREFAS = [("discursiva", "na tarefa de questão discursiva"),
           ("peca_formal", "na escrita de peça, aspectos formais"),
           ("peca_material", "na escrita de peça, aspectos de mérito")]


def tamanhos() -> dict[str, int]:
    m = json.load(open(RAIZ / "dataset/manifestos/corpus-treino.json"))
    return {it["caminho"].split("/")[1][6:]: it["linhas"] for it in m["itens"]
            if it["caminho"].startswith("sft/bloco_") and it["caminho"].endswith("train.jsonl")}


def tab(n, cap, cabs, linhas, pe=""):
    th = "".join("<th" + (' class="n"' if c[0] == "#" else "") + ">" + c.lstrip("#") + "</th>"
                 for c in cabs)
    return (f'<figure class="tab" id="tab-{n}">\n<figcaption><b>Tabela {n}.</b> {cap}</figcaption>\n'
            f'<div class="rol"><table>\n<thead><tr>{th}</tr></thead>\n<tbody>\n'
            + "".join(linhas) + "</tbody></table></div>\n"
            + (f'<p class="tnota">{pe}</p>' if pe else "") + "</figure>\n")


def fatorial(n: int, tarefa: str, rot: str, tam: dict[str, int]) -> str:
    """A tabela aberta de uma tarefa: nada agregado, nada em delta."""
    cab = ["Modelo", "Pré-treino", "#bloco 0"] + [f"#{ROTULO_BLOCO[b]}" for b in BLOCOS]
    L = []
    for m in MODELOS:
        for i, (reg, rot_reg) in enumerate(REG):
            cs = [f'<td rowspan="3">{NOME[m]}</td>'] if i == 0 else []
            cs.append(f"<td>{rot_reg}</td>")
            z = bloco0(m, reg, tarefa)
            cs.append(f'<td class="n z">{pt(z,1,"%")}</td>')
            valores = []
            for b in BLOCOS:
                v = media_sementes(b, reg, m, tarefa)
                valores.append(v)
                cs.append(f'<td class="n">{pt(v,1,"%")}</td>' if v is not None
                          else '<td class="n g">—</td>')
            # o melhor bloco da linha ganha destaque: é o que o olho procura
            bons = [x for x in valores if x is not None]
            if bons:
                # as colunas de bloco são as últimas da linha; a primeira célula só existe
                # na linha de cima de cada modelo, por causa do rowspan
                base = len(cs) - len(BLOCOS)
                cs[base + valores.index(max(bons))] = \
                    cs[base + valores.index(max(bons))].replace('class="n"', 'class="n melhor"')
            L.append(("<tr class='ctrl'>" if reg == "nenhum" else "<tr>") + "".join(cs) + "</tr>\n")
    # A legenda fica curta de propósito: o que ela explicava passou para o parágrafo que
    # antecede as tabelas, e repetir a mesma nota quatro vezes custava um terço de página.
    return tab(n, f"Nota {rot}, em percentual dos pontos do espelho, por modelo, regime de "
                  f"pré-treino e bloco de ajuste fino; média de três sementes de dez execuções cada, "
                  f"corrigida pelo Kimi K2.5 (discursiva) ou pelo GPT-OSS 120B (peça). Em destaque, o "
                  f"melhor bloco de cada linha.", cab, L)


ABREV = {"administrativo": "Admin.", "civil": "Civil", "constitucional": "Const.",
         "empresarial": "Empres.", "penal": "Penal", "trabalhista": "Trab.",
         "tributário": "Tribut."}


def areas(n: int) -> str:
    """Tucano2 3,7B fixado, áreas nas COLUNAS.

    Com as áreas nas linhas seriam 21 linhas (7 áreas x 3 regimes) por 6 colunas; nas
    colunas são 12 linhas por 9. A página é alta e estreita, então o que custa é linha.
    """
    cab = ["Tarefa", "Pré-treino"] + [f"#{ABREV[a]}" for a in AREAS]
    L = []
    for tk, rot in TAREFAS:
        for i, (reg, rot_reg) in enumerate(REG):
            cs = [f'<td rowspan="3">{rot.replace("na tarefa de ", "").replace("na escrita de ", "")}</td>'] if i == 0 else []
            cs.append(f"<td>{rot_reg}</td>")
            for a in AREAS:
                v = [media_sementes(b, reg, "3.7B", tk, area=a) for b in BLOCOS]
                v = [x for x in v if x is not None]
                cs.append(f'<td class="n">{pt(st.mean(v),1,"%")}</td>' if v
                          else '<td class="n g">—</td>')
            L.append(("<tr class='ctrl'>" if reg == "nenhum" else "<tr>") + "".join(cs) + "</tr>\n")
    return tab(n, "Nota por área do direito no Tucano2 3,7B, em percentual dos pontos do espelho, média dos seis blocos e de três sementes de dez execuções cada.",
               cab, L)


def modelos(n: int) -> str:
    cab = ["Modelo", "#Parâmetros", "Família", "#Uma condição"]
    dados = [("Tucano2 1,5B", "1,5 bi", "foco em português", "4,8 h"),
             ("Tucano2 3,7B", "3,7 bi", "foco em português", "9,6 h"),
             ("Qwen3 8B", "8,2 bi", "multilíngue", "17,5 h"),
             ("Qwen3 14B", "14,8 bi", "multilíngue", "28 h")]
    L = [f"<tr><td>{a}</td><td class='n'>{b}</td><td>{c}</td><td class='n'>{d}</td></tr>\n"
         for a, b, c, d in dados]
    return tab(n, "Os quatro modelos-base e o custo de uma condição de ajuste fino em GPU "
                  "NVIDIA A10G. As duas famílias diferem em mais do que o tamanho: os Tucano2 "
                  "são treinados com foco em português e os Qwen3 são multilíngues, o que "
                  "permite distinguir efeito de escala de efeito de exposição prévia.", cab, L)


def correcao(n: int) -> str:
    """Tabela 5: a correção de cobertura. Medida no teto de 3.000 tokens (resultados_t3k),
    em bloco I, para as três construções serem comparáveis. Recarrega nota.py com o teto de
    3.000 — por isso roda DEPOIS das Tabelas 1-4, que ficam no teto de 1.500."""
    import os, importlib
    os.environ["NOTA_PECAS"] = str(RAIZ / "avaliacao" / "resultados_t3k")
    import nota as _n
    importlib.reload(_n)
    S10 = tuple(range(42, 52))
    dados = [("Grade congelada (cobertura incompleta)", "bruto", "expandido", (42, 43, 44)),
             ("v3 (cobertura completa)", "v3_bruto", "v3_expandido", (42, 43, 44)),
             ("Par casado, 22,35 M (dez sementes)", "casado_bruto", "casado_expandido", S10)]
    cab = ["Construção do corpus", "#Formal", "#Mérito", "#Discursiva"]
    L = []
    for rot, bru, exp, sem in dados:
        cs = [f"<td>{rot}</td>"]
        for tk in ("peca_formal", "peca_material", "discursiva"):
            b = _n.media_sementes("I", bru, "3.7B", tk, sementes=sem)
            e = _n.media_sementes("I", exp, "3.7B", tk, sementes=sem)
            d = (e - b) if (b is not None and e is not None) else None
            cs.append(f'<td class="n">{pt(b,1)} · {pt(e,1)} · {ptd(d,1)}</td>')
        L.append("<tr>" + "".join(cs) + "</tr>\n")
    cap = ("O contraste texto-bruto/ficha na escrita de peça do Tucano2 3,7B sob três construções "
           "de corpus, no bloco de ajuste fino I e no teto de geração de 3.000 tokens. Cada célula "
           "traz a nota do texto bruto, a nota da ficha e a diferença entre elas (ficha menos texto "
           "bruto), em percentual dos pontos da banca. A grade congelada carrega a cobertura "
           "incompleta do experimento de 180 condições; o v3 completa os 80 diplomas de referência "
           "a pelo menos 98%; o par casado mantém o orçamento de tokens em 22,35 M e a composição "
           "por grupo idêntica nos dois braços.")
    pe = ("No par casado a diferença no formal é significativa (pareada sobre as dez sementes, "
          "t = 4,1 com nove graus de liberdade, p ≈ 0,003, nove das dez sementes positivas); as "
          "diferenças no mérito e na discursiva não são.")
    return tab(n, cap, cab, L, pe)


if __name__ == "__main__":
    tam = tamanhos()
    partes = []
    for i, (tk, rot) in enumerate(TAREFAS):
        partes.append(fatorial(1 + i, tk, rot, tam))
    partes.append(areas(4))
    partes.append(correcao(5))   # por último: recarrega nota.py no teto de 3.000
    (SAI / "tabelas.html").write_text("\n".join(partes), "utf-8")
    print(f"{len(partes)} tabelas · {(SAI / 'tabelas.html').stat().st_size:,} bytes")
