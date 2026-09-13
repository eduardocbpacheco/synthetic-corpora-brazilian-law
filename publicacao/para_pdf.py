#!/usr/bin/env python3
"""para_pdf.py — imprime um HTML autonomo em PDF, esperando o mermaid desenhar.

`page.pdf()` dispara assim que a rede fica ociosa, e o mermaid so comeca a desenhar depois
disso: imprimir sem esperar produz um PDF com oito retangulos vazios no lugar das figuras.
A espera aqui e por evidencia — conta os <svg> que o mermaid criou e so imprime quando o
numero bate com o de blocos .mermaid da pagina.

    python publicacao/para_pdf.py <entrada.html> <saida.pdf>
"""
from __future__ import annotations

import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ent = Path(sys.argv[1]).resolve()
sai = Path(sys.argv[2]).resolve()

with sync_playwright() as pw:
    nav = pw.chromium.launch()
    pag = nav.new_page(viewport={"width": 1280, "height": 1600})
    erros: list[str] = []
    pag.on("pageerror", lambda e: erros.append(str(e)))
    pag.goto(ent.as_uri(), wait_until="networkidle", timeout=120_000)

    alvo = pag.evaluate("document.querySelectorAll('pre.mermaid, .mermaid').length")
    prontos = 0
    for _ in range(120):
        prontos = pag.evaluate("document.querySelectorAll('.mermaid svg').length")
        if alvo and prontos >= alvo:
            break
        time.sleep(1)
    pag.emulate_media(media="print")
    time.sleep(1)
    pag.pdf(path=str(sai), format="A4", print_background=True,
            margin={"top": "14mm", "bottom": "16mm", "left": "12mm", "right": "12mm"},
            display_header_footer=True,
            header_template="<div></div>",
            footer_template='<div style="width:100%;font:9px -apple-system,sans-serif;'
                            'color:#888;padding:0 12mm;text-align:right">'
                            '<span class="pageNumber"></span> / <span class="totalPages"></span></div>')
    nav.close()

print(f"diagramas: {prontos} de {alvo} desenhados")
if erros:
    print("erros de página:", erros[:3])
print(f"{sai}  ·  {sai.stat().st_size/1_048_576:.1f} MB")
