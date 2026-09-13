#!/usr/bin/env python3
"""empacota.py — monta o arquivo de cada depósito, pronto para subir.

O manifesto diz quais bytes são; este passo os reúne num `.tar.gz` com a estrutura de
diretórios que o depósito publica, acrescenta LICENÇA e LEIAME próprios, e confere ao final
que o que entrou é o que o manifesto previa. Sem essa conferência o pacote pode divergir do
manifesto que o acompanha, e aí a soma de verificação publicada deixa de valer.

    python dataset/empacota.py                 # todos
    python dataset/empacota.py corpus-treino   # um só
"""
from __future__ import annotations

import hashlib, json, sys, tarfile, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "publicacao"))
from depositos import DEPOSITOS, arquivos, RAIZ
from monta_repo import varre, NOMES_PROIBIDOS   # a mesma varredura da montagem do repositório

AQUI = Path(__file__).resolve().parent
PACOTES = AQUI / "pacotes"
MANI = AQUI / "manifestos"

LICENCAS = {
    "CC BY 4.0": """Creative Commons Attribution 4.0 International (CC BY 4.0)

Você pode compartilhar e adaptar este material para qualquer fim, inclusive comercial,
desde que dê o crédito apropriado. Texto integral em
https://creativecommons.org/licenses/by/4.0/legalcode.pt

CRÉDITO PEDIDO
  Pacheco, E.; Russo, C. M. {titulo}, v{versao}. {ano}.

SOBRE O MATERIAL DE ORIGEM
  No direito brasileiro, textos de lei e decisões judiciais não são protegidos por direito
  autoral (Lei 9.610/1998, art. 8º, incisos IV e V). Provas e espelhos de correção são
  publicados pelas bancas examinadoras. As camadas geradas por modelo de linguagem estão
  sujeitas aos termos do serviço usado na geração; quem redistribuir deve verificá-los.
""",
    "MIT": """MIT License

Copyright (c) {ano} Eduardo Pacheco

Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY.
""",
}


def leiame(dep: str, m: dict) -> str:
    d = DEPOSITOS[dep]
    linhas = [f"# {d['titulo']}", "", f"Versão {d['versao']} · congelada em {m['congelado_em']}",
              "", d["resumo"], "",
              f"**{m['arquivos']:,} arquivos · {m['bytes']/1e9:.2f} GB**".replace(",", "."), "",
              "## Conteúdo", ""]
    grupos: dict[str, list] = {}
    for it in m["itens"]:
        grupos.setdefault(it["caminho"].split("/")[0] if "/" in it["caminho"] else ".",
                          []).append(it)
    for g, itens in sorted(grupos.items()):
        b = sum(i["bytes"] for i in itens)
        ln = sum(i["linhas"] or 0 for i in itens)
        extra = f", {ln:,} linhas".replace(",", ".") if ln else ""
        linhas.append(f"- `{g}/` — {len(itens)} arquivo(s), {b/1e6:.1f} MB{extra}")
    linhas += ["", "## Integridade", "",
               "`MANIFESTO.json` traz caminho, tamanho, contagem de linhas e SHA-256 de cada",
               "arquivo. Para conferir, no diretório extraído:", "",
               "```bash", "python - <<'EOF'",
               "import hashlib, json",
               "m = json.load(open('MANIFESTO.json'))",
               "for it in m['itens']:",
               "    h = hashlib.sha256(open(it['caminho'],'rb').read()).hexdigest()",
               "    assert h == it['sha256'], it['caminho']",
               "print(len(m['itens']), 'arquivos conferidos')", "EOF", "```", "",
               "## Licença", "", d["licenca"], ""]
    if dep == "corpus-treino":
        linhas += ["## Defeitos conhecidos", "",
                   "`DATASHEET.md`, seção 6, lista os defeitos desta versão com o custo medido",
                   "de cada um. Leia antes de treinar: esta é a versão que reproduz o estudo,",
                   "não a recomendada para uso novo.", ""]
    return "\n".join(linhas)


def empacota(dep: str) -> Path:
    # A varredura roda ANTES de escrever o pacote. Um `.pem` já entrou num tar daqui uma
    # vez, e o empacotador não pode ser o único passo do caminho sem essa conferência.
    achados = []
    for destino, p in arquivos(dep):
        if NOMES_PROIBIDOS.search(p.name):
            achados.append(f"{destino}  nome proibido: arquivo de credencial")
        achados += varre(p, destino)
    if achados:
        print("  SEGREDO no depósito, empacotamento abortado:")
        for a in achados[:10]:
            print("   ", a)
        raise SystemExit(1)

    f = MANI / f"{dep}.json"
    if not f.exists():
        raise SystemExit(f"congele {dep} antes: python dataset/congela.py {dep}")
    m = json.loads(f.read_text("utf-8"))
    PACOTES.mkdir(parents=True, exist_ok=True)
    d = DEPOSITOS[dep]
    base = f"{dep}-v{d['versao']}"
    alvo = PACOTES / f"{base}.tar.gz"

    lic = LICENCAS["MIT" if dep == "codigo" else "CC BY 4.0"].format(
        titulo=d["titulo"], versao=d["versao"], ano=time.strftime("%Y"))

    vistos = set()
    with tarfile.open(alvo, "w:gz", compresslevel=6) as tar:
        def texto(nome: str, conteudo: str) -> None:
            import io
            dados = conteudo.encode("utf-8")
            info = tarfile.TarInfo(f"{base}/{nome}")
            info.size = len(dados)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(dados))

        texto("LEIAME.md", leiame(dep, m))
        texto("LICENCA.txt", lic)
        texto("MANIFESTO.json", json.dumps(m, ensure_ascii=False, indent=1))
        if dep == "corpus-treino":
            texto("DATASHEET.md", (AQUI / "DATASHEET.md").read_text("utf-8"))
        for i, (destino, p) in enumerate(arquivos(dep), 1):
            tar.add(p, arcname=f"{base}/{destino}")
            vistos.add(destino)
            if i % 5000 == 0:
                print(f"    {i}/{m['arquivos']}…", flush=True)

    faltando = {it["caminho"] for it in m["itens"]} - vistos
    if faltando:
        raise SystemExit(f"o pacote não bate com o manifesto: faltam {len(faltando)}")
    h = hashlib.sha256(alvo.read_bytes()).hexdigest() if alvo.stat().st_size < 3e9 else "—"
    print(f"  {alvo.name:34s} {alvo.stat().st_size/1e6:8.1f} MB  sha256 {h[:16]}…")
    return alvo


if __name__ == "__main__":
    for dep in ([a for a in sys.argv[1:] if not a.startswith("--")] or list(DEPOSITOS)):
        print(f"  empacotando {dep}…", flush=True)
        empacota(dep)
