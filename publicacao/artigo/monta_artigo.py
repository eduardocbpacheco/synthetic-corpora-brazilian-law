#!/usr/bin/env python3
"""monta_artigo.py — junta as partes do artigo e marca os blocos editáveis.

O editor de textos e os comentários precisam de uma âncora estável por bloco. Ela não pode
ser a posição no documento, que muda a cada parágrafo inserido, nem um hash do conteúdo,
que muda justamente quando o texto é editado. Aqui cada bloco recebe um `data-id`
sequencial gravado no próprio arquivo, de modo que ele sobrevive à edição e à remontagem —
desde que a ordem dos blocos não mude. Inserir um bloco no meio renumeraria os seguintes,
então blocos novos entram sempre com id fora da sequência (ver `proximo_id`).

    python publicacao/artigo/monta_artigo.py
"""
from __future__ import annotations

import re
from pathlib import Path

AQUI = Path(__file__).resolve().parent

# Blocos que o editor deixa clicar. Celula de tabela fica de fora de proposito: editar
# numero a mao é como o artigo e o dado se separam.
EDITAVEL = re.compile(r"<(h1|h2|h3|p|li|figcaption)(\s[^>]*)?>", re.I)


def tabelas() -> dict[str, str]:
    bruto = (AQUI / "tabelas.html").read_text("utf-8")
    fora, atual, rot = {}, [], None
    for linha in bruto.splitlines(keepends=True):
        m = re.search(r'<figure class="tab" id="tab-(\d+)"', linha)
        if m:
            if rot:
                fora[rot] = "".join(atual)
            rot, atual = m.group(1), [linha]
        elif rot:
            atual.append(linha)
    if rot:
        fora[rot] = "".join(atual)
    return fora


def marca(html: str) -> tuple[str, int]:
    """Insere data-id nos blocos editáveis, pulando o interior das tabelas."""
    pedacos = re.split(r"(<table\b.*?</table>)", html, flags=re.S | re.I)
    n = 0
    for k, ped in enumerate(pedacos):
        if ped.lower().startswith("<table"):
            continue

        def sub(m: re.Match) -> str:
            nonlocal n
            n += 1
            tag, atrs = m.group(1), m.group(2) or ""
            return f'<{tag} data-id="b{n:03d}"{atrs}>'

        pedacos[k] = EDITAVEL.sub(sub, ped)
    return "".join(pedacos), n


CABECA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>O que treinar</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400&display=swap">
<style>
*,*::before,*::after{box-sizing:border-box}
body{margin:0}
img,svg{max-width:100%;height:auto}
__CSS__
</style>
</head>
<body>
<article class="folha">
"""

RODAPE = """</article>
</body>
</html>
"""


def main() -> None:
    tabs = tabelas()
    corpo = "\n".join((AQUI / f"corpo_{i}.html").read_text("utf-8") for i in (1, 2, 3, 4))
    for rot, html in tabs.items():
        marca_texto = f"INSERIR_TABELA_{rot}"
        if marca_texto not in corpo:
            raise SystemExit(f"o corpo não tem lugar para a Tabela {rot}")
        corpo = corpo.replace(marca_texto, html)
    if "INSERIR_TABELA" in corpo:
        raise SystemExit("sobrou marcador de tabela no corpo")

    corpo, n = marca(corpo)
    css = (AQUI / "estilo.css").read_text("utf-8")
    saida = AQUI / "artigo.html"
    saida.write_text(CABECA.replace("__CSS__", css) + corpo + RODAPE, "utf-8")
    print(f"{saida.name} · {n} blocos editáveis · {saida.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
