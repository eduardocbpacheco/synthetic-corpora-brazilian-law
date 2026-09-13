#!/usr/bin/env python3
"""monta_standalone.py — embrulha o corpo de um artefato num HTML que abre sozinho.

O artefato publicado vive dentro de um esqueleto que o host fornece: doctype, <head>, o
reset de CSS e o renderizador de mermaid. Salvo em disco, o mesmo arquivo abriria sem nada
disso — sem <head>, sem charset e, sobretudo, com os oito diagramas como texto cru. Aqui o
esqueleto é reconstruído e a biblioteca de mermaid vai embutida, para o arquivo não depender
de rede nem de CDN quando for aberto daqui a um ano.

    python publicacao/monta_standalone.py <corpo.html> <saida.html> "<título>"
"""
from __future__ import annotations

import re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
MERMAID = RAIZ / "assets/mermaid.min.js"

CABECA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titulo}</title>
<style>
/* Reset equivalente ao que o host do artefato injeta. */
*,*::before,*::after{{box-sizing:border-box}}
body{{margin:0}}
img,svg,video{{max-width:100%;height:auto}}
</style>
</head>
<body>
"""

# A folha de impressao vai no FIM do documento, nao no <head>. O corpo do artefato traz o
# proprio <style>, e ele entra depois do cabecalho: uma regra de impressao declarada la em
# cima perde para a regra de tela declarada mais abaixo, com a mesma especificidade. Foi
# assim que a primeira tentativa saiu com as tabelas ainda cortadas.
RODAPE = """
<style>
/* Impressão. Três coisas quebram aqui e nenhuma se resolve sozinha.

   A primeira é o recorte: na tela a tabela larga rola dentro do `overflow-x:auto`, mas o
   papel não rola — ele corta, e a coluna da direita simplesmente some do PDF. O overflow
   volta a `visible` e a tabela é obrigada a caber, com corpo menor e respiro apertado.

   A segunda é o desperdício: `break-inside:avoid` numa tabela de trinta linhas empurra a
   tabela inteira para a página seguinte e deixa meia página em branco. Tabela grande passa
   a poder partir; o que não parte é a LINHA, e o cabeçalho se repete em cada página por
   causa do `display:table-header-group`.

   A terceira é o rodapé do navegador, que ocupa espaço próprio: a margem inferior do PDF
   precisa contar com ele, e isso está no para_pdf.py, não aqui. */
@media print{{
  body{{background:#fff}}
  .page{{max-width:none;padding:0}}
  figure{{break-inside:avoid}}
  .tw{{overflow:visible;break-inside:auto;border-radius:0}}
  table{{font-size:9.5px;break-inside:auto}}
  thead{{display:table-header-group}}
  tr{{break-inside:avoid}}
  /* `anywhere` parte a palavra no meio — "Constituiç/ão" — porque autoriza a quebra antes
     de tentar alargar a coluna. `break-word` só quebra a palavra que sozinha não cabe, e a
     hifenização em pt-BR cuida do resto de forma legível. */
  th,td{{padding:4px 6px;overflow-wrap:break-word;hyphens:auto}}
  caption{{font-size:10.5px;break-after:avoid}}
  h2,h3,h4{{break-after:avoid}}
  .toc{{break-after:page}}
  .note,.spec,.stat{{break-inside:avoid}}
  a[href^="http"]::after{{content:" (" attr(href) ")";font-size:9px;color:#666}}
}}
</style>
<script>{mermaid}</script>
<script>
(function () {{
  var escuro = matchMedia('(prefers-color-scheme: dark)').matches
            || document.documentElement.dataset.theme === 'dark';
  mermaid.initialize({{
    startOnLoad: true,
    theme: escuro ? 'dark' : 'neutral',
    securityLevel: 'loose',
    flowchart: {{ htmlLabels: true, curve: 'basis' }},
  }});
}})();
</script>
</body>
</html>
"""


def main() -> None:
    corpo = Path(sys.argv[1]).read_text("utf-8")
    saida = Path(sys.argv[2])
    titulo = sys.argv[3] if len(sys.argv) > 3 else "Relatório"

    # O corpo do artefato pode trazer <title> proprio; aqui ele vira o do documento.
    m = re.search(r"<title>(.*?)</title>", corpo, re.S)
    if m:
        titulo = m.group(1).strip()
        corpo = corpo[:m.start()] + corpo[m.end():]

    js = MERMAID.read_text("utf-8") if MERMAID.exists() else ""
    if not js:
        print("aviso: mermaid.min.js ausente — os diagramas sairão como texto")
    # `</script>` dentro de uma string do proprio bundle fecharia a tag cedo.
    js = js.replace("</script>", "<\\/script>")

    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(CABECA.format(titulo=titulo) + corpo + RODAPE.format(mermaid=js), "utf-8")
    print(f"{saida}  ·  {saida.stat().st_size/1_048_576:.1f} MB  ·  título: {titulo!r}")


if __name__ == "__main__":
    main()
