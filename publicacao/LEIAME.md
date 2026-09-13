# Publicação e revisão

*[English version: `README.md`](README.md)*

## O que há aqui

| arquivo | o que é | páginas |
|---|---|---|
| `relatorio_ablacao.html` / `.pdf` | relatório interno do artigo 1, autônomo — abre offline, 8 diagramas embutidos | 73 |
| `relatorio_benchmark.html` / `.pdf` | relatório interno do artigo 2, idem, 2 diagramas | 28 |
| `artigo/artigo.html` / `.pdf` | **Artigo 1** · O que treinar — forma do corpus, volume de supervisão e escala | 13 |
| `artigo2/artigo.html` / `.pdf` | **Artigo 2** · Juiz não é ranking — o que a tabela de juízes não diz | 12 |

Os HTML dos relatórios carregam a biblioteca de diagramas de dentro do próprio arquivo: não
dependem de rede nem de CDN. Os artigos buscam as fontes no Google Fonts e caem numa pilha
de fallback se não houver rede.

## Como refazer

```bash
# relatório: corpo do artefato → html autônomo → pdf
juridico-env/bin/python publicacao/monta_standalone.py <corpo.html> publicacao/<nome>.html
juridico-env/bin/python publicacao/para_pdf.py publicacao/<nome>.html publicacao/<nome>.pdf

# artigo: tabelas recomputadas → montagem com os ids de bloco → pdf
juridico-env/bin/python publicacao/artigo/tabelas.py      # ou artigo2/
juridico-env/bin/python publicacao/artigo/monta_artigo.py
juridico-env/bin/python publicacao/para_pdf.py publicacao/artigo/artigo.html publicacao/artigo/artigo.pdf
```

As tabelas dos artigos **não são copiadas à mão** dos relatórios. `artigo/tabelas.py`
recomputa a partir dos arquivos de julgamento da ablação, via `avaliacao/nota.py`;
`artigo2/tabelas.py` recomputa o κ a partir dos julgamentos dos juízes, via
`avaliacao/kappa_por_classe.py`. Assim artigo e relatório não podem divergir numa revisão.

## A oficina de revisão

```bash
juridico-env/bin/python revisao/app.py     # http://127.0.0.1:7777
```

Sem login: roda só em `127.0.0.1`. O seletor na barra troca entre os dois artigos, e cada um
tem estado próprio. Clique em qualquer parágrafo para editar, `Esc` desfaz, `⌘/Ctrl+Enter`
fecha e salva. Selecione um trecho e clique em **comentar** para prender um comentário ali.
A barra conta alterações e comentários, e cada uma abre um painel com o antes e o depois.

O estado fica em JSON legível, um par por artigo: `revisao/dados/<slug>_edicoes.json` e
`<slug>_comentarios.json`. Para eu retomar o trabalho:

```bash
juridico-env/bin/python revisao/ler.py                # os dois artigos
juridico-env/bin/python revisao/ler.py juizes         # só um
juridico-env/bin/python revisao/ler.py treino --html  # o artigo com as edições aplicadas
```

Editar um bloco de volta ao texto original o remove da lista de alterações. Célula de tabela
não é editável de propósito — os números vêm do dado, não da digitação.
