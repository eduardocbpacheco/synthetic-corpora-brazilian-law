# Deposits

*[Versão em português: `LEIAME.md`](LEIAME.md)*

Four deposits, four identifiers. Separated by licence and lifecycle, not for tidiness: in a
single deposit the most restrictive licence would contaminate everything, and every code fix
would require versioning 3 GB of data.

| deposit | what it is | files | size |
|---|---|---:|---:|
| `corpus-treino` | the raw/card pair and the six fine-tuning blocks | 20 | 0.93 GB |
| `avaliacao-ablacao` | judgments of the 180 conditions plus the generated answers | 542 | 1.29 GB |
| `benchmark-juizes` | verdicts of 31 candidate judges plus the three lawyers' gold standard | 47,869 | 0.19 GB |
| `codigo` | snapshot of the pipeline at submission time | 163 | 1.5 MB |

[`DATASHEET.md`](DATASHEET.md) describes `corpus-treino` in datasheet form, with the known
defects and the measured cost of each.

## Freezing and verifying

```bash
python dataset/congela.py                 # all deposits
python dataset/congela.py corpus-treino   # one only
python dataset/congela.py --conferir      # revalidate against the stored manifest
python dataset/empacota.py                # build the archives, ready to upload
```

Each deposit's manifest lives in `manifestos/<name>.json`, with path, size, line count and
SHA-256 per file. That is what turns "the data is in the repository" into "these exact bytes
produced these results". `empacota.py` runs the same secret scan the repository assembly
uses, and refuses to write an archive that contains a credential.

## Why the generated answers travel with the judgments

The evaluation deposit carries two things: the judge's verdict for each criterion, and **the
text the model wrote**. Without the second, whoever downloads it inherits our choice of
grader without being able to contest it. With it, everything can be re-judged by another
grader, which is exactly what the companion paper argues should be possible.

The two collections are paired by condition and verified: 271 judgments, 271 generations,
no orphans on either side. Judgments under `avaliacao/resultados/_prompt_antigo/` were left
out; they come from a superseded prompt and publishing them beside the current ones would
hand the reader two incompatible sets without a label.

## Before depositing

- [x] Verify that examinations 39, 40 and 41 do not appear in `corpus-treino`
      (`dataset/confere_vazamento.py`, checked 13 Sep 2026)
- [ ] Run `--conferir` and attach the output
- [ ] Reserve the identifier and put it in both papers before publishing the record
- [ ] Check the teacher model's terms of service regarding redistribution of the layers
