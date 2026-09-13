# Publication and revision

*[Versão em português: `LEIAME.md`](LEIAME.md)*

The manuscript is written and revised in HTML, because the revision workshop works on it
directly. Submission has a mandatory form, the IOS Press style used by the conference, and
it is derived from the same source rather than maintained separately.

| file | what it is | pages |
|---|---|---:|
| `artigo_en/artigo.pdf` | **the paper**, English, reading copy | 13 |
| `artigo/artigo.pdf` | the same in Portuguese, used for revision | 13 |
| `jurix/artigo_en.pdf` | the paper in IOS Press style, for submission | 11 |
| `jurix/artigo.pdf` | the Portuguese version in the same style | 10 |

The page limit is 10 excluding acknowledgements and references. The English body ends at 9.9
counted pages.

## Rebuilding

```bash
python publicacao/artigo_en/tabelas.py       # recompute the tables from the judgments
python publicacao/artigo_en/monta_artigo.py  # assemble the HTML with block identifiers
python publicacao/jurix/para_tex_en.py       # convert to the IOS Press style
cd publicacao/jurix && tectonic -X compile artigo_en.tex
```

The tables are **not** transcribed by hand from the report: `artigo_en/tabelas.py` recomputes
them from the judgment files through `avaliacao/nota.py`, the single scoring function of the
project. Article and report therefore cannot drift apart in a revision.

`para_tex_en.py` is a deliberately narrow converter. It covers exactly the constructs the
manuscript uses and fails loudly on anything else, rather than producing silently wrong
LaTeX.

## The revision workshop

```bash
python revisao/app.py     # http://127.0.0.1:7777
```

No login; it listens on the loopback interface only. The selector in the bar switches between
documents, and each keeps its own state. Click any paragraph to edit, `Esc` undoes,
`Cmd/Ctrl+Enter` closes and saves. Select a passage, or use the pencil in the margin, to
attach a comment.

A comment belongs to the version it was written against, because it speaks about a passage in
a given state of the text; after a rewrite it would point at a different sentence. Older
comments stay readable in the history of their own version.

The **versions** tab is the chain of custody: each version records its author, its timestamp
and the block-by-block difference against the previous one. Marking a version bakes the
pending edits into the text and clears the list, so the history is a sequence of complete
states rather than an ever-growing diary.
