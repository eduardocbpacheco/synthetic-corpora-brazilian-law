# Reproducing the paper

*[Versão em português: `REPRODUZIR.md`](REPRODUZIR.md)*

The work has five stages. They differ sharply in what they demand: the first three need
network access, a GPU and paid API keys, and together they cost roughly 400 GPU-hours. The
fourth needs none of that, and it is the one that produces **every number in the paper**
from the deposited judgments. If you want to check our results rather than rebuild the
experiment, go straight to stage 4.

Scripts carry Portuguese names and Portuguese comments; that is the working language of the
project. This file and the other documents are in both languages.

---

## Stage 4 · Analysis, from the deposited judgments

**Needs:** Python 3.11, `numpy`, `pandas`, `scipy`, `scikit-learn`. No GPU, no API key.
**Input:** the `avaliacao-ablacao` deposit, unpacked so that the judgment files sit in
`avaliacao/resultados/`.

```bash
python dataset/congela.py --conferir        # the files are the ones the manifest describes
python dataset/confere_vazamento.py         # the evaluation exams never entered training
python publicacao/artigo_en/tabelas.py      # recomputes Tables 1 to 4 of the paper
python avaliacao/contrastes_por_tarefa.py   # the paired contrasts of Section 4.3
python avaliacao/complementaridade.py       # criterion-level complementarity, Section 4.2
python avaliacao/kappa_por_classe.py        # judge agreement split into form and merit
```

`avaliacao/nota.py` is the single scoring function used by all of the above. It weights each
criterion by the points the examining board assigns to it, and it never aggregates the two
task genres. Every table in the paper comes from it; none is transcribed by hand.

---

## Stage 1 · Building the corpus

**Needs:** network access and an API key for the teacher model.

Collection, per source: `pipeline/recoleta_normas.py` (federal statutes),
`pipeline/coleta_stf_historico.py` and `augmentation/crawlers/stf_acordaos.py` (Supreme
Court decisions), `augmentation/crawlers/stj_acordaos.py`,
`augmentation/crawlers/enunciados.py` (summary opinions),
`pipeline/coleta_carreiras.py` (other career examinations),
`pipeline/parse_oab_pdfs.py` (Bar examinations and their rubrics).

Expansion into cards, which is what produces the structured arm:
`augmentation/expand_normas.py`, `expand_jurisprudencia.py`, `expand_casos.py`. They share
`augmentation/llm_client.py`, `prompts.py` and `sanitize.py`; `verify.py` checks the output
in layers.

Assembly: `pipeline/expande_cascata.py` produces the two-hop examples;
`pipeline/monta_benchmark_v2.py` builds the 105 questions and the 940 criteria, and is also
where the form/merit grouping of document-writing criteria is defined;
`aws/build_ablacao_regime.py` matches the two arms on token budget, which is the step that
makes the pair comparable.

`pipeline/diagnostico_corpus.py` runs the provenance checks whose findings are reported in
the datasheet's section on known defects.

---

## Stage 2 · Training and generation

**Needs:** a GPU. The 180 conditions ran on AWS EC2 instances with NVIDIA A10G.

Continued pre-training: `aws/cadeia_ablacao_tucano.sh` and `aws/cadeia_ablacao_qwen.sh`.
Fine-tuning of the 180 conditions: `aws/cadeia_sft_ablacao.sh`. This is where the protocol
the paper reports actually lives, `alpha 64` and `max_seq 3072` included.
Generation on the benchmark: `aws/sobe_vllm_ablacao.sh` raises a multi-adapter server and
`aws/gera_sft_ablacao.sh` (or `gera_ctrl_ablacao.sh` for the control arms) drives it;
`aws/gera_remoto.py` is the client.

---

## Stage 3 · Judging

**Needs:** API keys for the two judges.

`avaliacao/julga_rabula.py` judges each response against the official rubric, criterion by
criterion, producing the `*_partes.jsonl` files that stage 4 consumes. The judges are Kimi
K2.5 for discursive questions and GPT-OSS 120B for document writing, fixed before any
measurement. `avaliacao/judge.py` holds the client and `benchmark_schema.py` the contract of
the expected response.

`avaliacao/analisa_kappa_v4.py` is the statistical package that calibrates the judges
against the human gold standard; it imports `alignment.py` and `judge_llm.py`, inherited
from the source benchmark.

---

## Stage 5 · The manuscript

`publicacao/artigo_en/tabelas.py` recomputes the tables, `monta_artigo.py` assembles the
HTML, and `publicacao/jurix/para_tex_en.py` converts it to the IOS Press style used by the
conference. The Portuguese version lives in `publicacao/artigo/` and follows the same three
steps. Nothing in the manuscript is written twice: the tables come from the data and the
submission format is derived from the same source as the reading copy.

---

## What is deliberately absent

The project accumulated 108 entry-point scripts over several months, a number of them
superseded and some marked as such in their own headers. This repository contains only the
path that produced what is in the paper. Discarded material was discarded, not forgotten:
publishing the whole archive would leave the reader to guess which script produced a given
result, and the worst case is guessing the right name and the wrong version.

`publicacao/monta_repo.py` is what assembles this repository. It refuses to include a file
whose name or content matches a credential pattern, and it refuses to finish if any included
script imports a module that was left out.
