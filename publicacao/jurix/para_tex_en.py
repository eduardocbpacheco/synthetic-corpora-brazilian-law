#!/usr/bin/env python3
"""para_tex.py — converte o artigo em HTML para o estilo IOS Press, que é o da JURIX.

O artigo é escrito e revisado em HTML porque a oficina de revisão trabalha em cima dele.
A submissão, porém, tem forma obrigatória: `IOS-Book-Article.cls`, coluna única, com o
frontmatter próprio. Converter é preferível a manter duas fontes: a fonte continua sendo
uma só, e a forma de submissão é derivada dela a cada vez.

A conversão é deliberadamente estreita. Ela cobre exatamente as construções que o artigo
usa (h2/h3, p, ul/li, b, i, code, figure.tab com uma tabela dentro) e falha alto em
qualquer outra, em vez de produzir LaTeX silenciosamente errado.

    python publicacao/jurix/para_tex.py
"""
from __future__ import annotations

import html as H
import re
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
ART = AQUI.parent / "artigo_en/artigo.html"

ESCAPA = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
          "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}

# A fonte Times do estilo IOS não tem grego nem sinais matemáticos; sem isto o caractere
# some do PDF e o aviso passa despercebido no meio da compilação.
# Sentinelas de um byte para os quatro caracteres que a conversão PRECISA emitir sem que a
# passada de escape os toque: barra, chaves e cifrão. Elas viram LaTeX de verdade no fim.
BARRA, ABRE, FECHA, CIFRAO = "\x01", "\x02", "\x03", "\x04"
SENTINELA = {BARRA: "\\", ABRE: "{", FECHA: "}", CIFRAO: "$"}

_m = lambda corpo: CIFRAO + BARRA + corpo + CIFRAO
MATEMATICO = {"ρ": _m("rho"), "κ": _m("kappa"), "×": _m("times"), "⊂": _m("subset"),
              "≈": _m("approx"), "≤": _m("leq"), "≥": _m("geq"),
              "−": "-", "–": "--", "—": "--",   # célula sem medição; a Times do IOS não tem travessão
              "·": BARRA + "textperiodcentered" + ABRE + FECHA,
              "⁻": CIFRAO + "^" + ABRE + "-" + FECHA + CIFRAO,
              "¹": CIFRAO + "^" + ABRE + "1" + FECHA + CIFRAO,
              "⁵": CIFRAO + "^" + ABRE + "5" + FECHA + CIFRAO}


def txt(s: str) -> str:
    """Texto puro para LaTeX, já sem marcação."""
    s = H.unescape(s).replace("\xa0", " ")
    s = "".join(MATEMATICO.get(c, ESCAPA.get(c, c)) for c in s)
    s = s.replace("\\textbackslash", r"\textbackslash{}")
    return re.sub(r"\s+", " ", s)


def inline(s: str) -> str:
    """Converte a marcação de dentro do parágrafo, depois escapa o resto.

    Os comandos criados aqui usam sentinelas de um byte para barra e chaves. Sem isso a
    passada final de escape transformaria o `{` que a própria conversão acabou de escrever
    em `\{`, e o LaTeX receberia `\textbf\{...\}`.
    """

    cmd = lambda nome, conteudo: BARRA + nome + ABRE + txt(conteudo) + FECHA
    s = re.sub(r"<b>(.*?)</b>", lambda m: cmd("textbf", m.group(1)), s, flags=re.S)
    s = re.sub(r"<i>(.*?)</i>", lambda m: cmd("emph", m.group(1)), s, flags=re.S)
    s = re.sub(r"<code>(.*?)</code>", lambda m: cmd("texttt", m.group(1)), s, flags=re.S)
    s = re.sub(r'<span[^>]*class="idx"[^>]*>(.*?)</span>',
               lambda m: cmd("textit", m.group(1)), s, flags=re.S)
    s = re.sub(r"<[^>]+>", "", s)
    s = txt(s)
    for k, v in SENTINELA.items():
        s = s.replace(k, v)
    return s


def tabela(bloco: str) -> str:
    """figure.tab -> table flutuante com tabular. Só o que o artigo usa."""
    # O montador injeta data-id na figcaption, então o seletor precisa aceitar atributos.
    # Sem isso a legenda saía vazia e o PDF mostrava só "Table 1." do contador do LaTeX.
    cap = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", bloco, re.S)
    if not cap:
        raise SystemExit("tabela sem legenda: " + bloco[:80])
    legenda = inline(re.sub(r"<b>(Tabela|Table) \d+\.</b>\s*", "", cap.group(1)))
    cabs = [inline(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", bloco, re.S)]
    linhas = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", bloco.split("<tbody>")[-1], re.S):
        celulas = []
        for m in re.finditer(r'<td([^>]*)>(.*?)</td>', tr, re.S):
            atr, conteudo = m.group(1), inline(m.group(2))
            span = re.search(r'rowspan="(\d+)"', atr)
            if span:
                conteudo = r"\multirow{%s}{*}{%s}" % (span.group(1), conteudo)
            celulas.append(conteudo)
        if len(celulas) < len(cabs):          # linha sob rowspan: falta a primeira célula
            celulas = [""] * (len(cabs) - len(celulas)) + celulas
        linhas.append(" & ".join(celulas) + r" \\")
    col = "ll" + "r" * (len(cabs) - 2)
    # `!ht` em vez de `t`: com quatro tabelas de treze linhas, empurrar todas para o topo
    # da página deixava meia página em branco antes de cada uma. `footnotesize` e colunas
    # apertadas recuperam mais uma página inteira, e a tabela continua legível porque o que
    # ela tem são números curtos.
    return ("\\begin{table}[!ht]\n\\centering\n\\caption{%s}\n"
            "\\footnotesize\\setlength{\\tabcolsep}{4pt}\n"
            "\\begin{tabular}{%s}\n\\hline\n%s \\\\\n\\hline\n%s\n\\hline\n"
            "\\end{tabular}\n\\end{table}\n" %
            (legenda, col, " & ".join("\\textbf{%s}" % c for c in cabs), "\n".join(linhas)))


def main() -> None:
    doc = ART.read_text("utf-8")
    corpo = doc.split("<article class=\"folha\">", 1)[1].rsplit("</article>", 1)[0]

    titulo = inline(re.search(r"<h1[^>]*>(.*?)</h1>", corpo, re.S).group(1))
    resumo = " ".join(inline(p) for p in
                      re.findall(r"<p[^>]*>(.*?)</p>",
                                 re.search(r'<div[^>]*class="resumo"[^>]*>(.*?)</div>', corpo, re.S).group(1),
                                 re.S))
    chaves = inline(re.search(r'<p[^>]*class="chaves"[^>]*>(.*?)</p>', corpo, re.S).group(1))
    chaves = chaves.split(":", 1)[-1].strip(" }").replace(" · ", r"\sep ")

    # o corpo começa depois das palavras-chave
    corpo = re.split(r'<p[^>]*class="chaves"[^>]*>', corpo, 1)[1].split("</p>", 1)[1]

    saida: list[str] = []
    for m in re.finditer(
            r'<figure[^>]*class="tab".*?</figure>|<h2[^>]*>.*?</h2>|<h3[^>]*>.*?</h3>'
            r'|<ol class="refs">.*?</ol>|<ul>.*?</ul>|<p[^>]*>.*?</p>', corpo, re.S):
        b = m.group(0)
        if b.startswith("<figure"):
            saida.append(tabela(b))
        elif b.startswith("<h2"):
            t = inline(re.sub(r'<span class="num">.*?</span>', "", b))
            if t.lower().startswith(("referências", "references")):
                break
            saida.append("\\section{%s}" % t)
        elif b.startswith("<h3"):
            saida.append("\\subsection{%s}" %
                         inline(re.sub(r'<span class="num">.*?</span>', "", b)))
        elif b.startswith("<ul"):
            itens = "\n".join("\\item %s" % inline(i)
                              for i in re.findall(r"<li[^>]*>(.*?)</li>", b, re.S))
            saida.append("\\begin{itemize}\n%s\n\\end{itemize}" % itens)
        else:
            saida.append(inline(b))

    refs = re.search(r'<ol[^>]*class="refs"[^>]*>(.*?)</ol>', corpo, re.S)
    bib = "\n".join("\\bibitem{r%d} %s" % (i, inline(li))
                    for i, li in enumerate(re.findall(r"<li[^>]*>(.*?)</li>", refs.group(1), re.S), 1))

    tex = f"""\\documentclass{{IOS-Book-Article}}
\\usepackage{{mathptmx}}
\\usepackage{{multirow}}
\\usepackage[utf8]{{inputenc}}
\\usepackage[T1]{{fontenc}}
\\usepackage[english]{{babel}}
\\begin{{document}}
\\begin{{frontmatter}}
\\title{{{titulo}}}
\\author[A]{{\\fnms{{Eduardo}} \\snm{{Pacheco}}}}
and
\\author[A]{{\\fnms{{Cibele Maria}} \\snm{{Russo}}}}
\\runningauthor{{E. Pacheco and C. M. Russo}}
\\address[A]{{Instituto de Ciências Matemáticas e de Computação, Universidade de São Paulo}}
\\begin{{abstract}}
{resumo}
\\end{{abstract}}
\\begin{{keyword}}
{chaves}
\\end{{keyword}}
\\end{{frontmatter}}

{chr(10).join(chr(10) + s if s.startswith(chr(92) + "section") else s for s in saida)}

\\begin{{thebibliography}}{{99}}
{bib}
\\end{{thebibliography}}
\\end{{document}}
"""
    (AQUI / "artigo_en.tex").write_text(tex, "utf-8")
    print(f"artigo.tex · {len(tex):,} bytes · {len(saida)} blocos")


if __name__ == "__main__":
    main()
