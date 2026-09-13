#!/usr/bin/env python3
"""monta_repo.py — monta a pasta que vai a público, e se recusa a levar segredo junto.

O repositório de trabalho tem chave privada, senha em texto puro e credencial de nuvem.
Publicar dele exigiria confiar numa lista de exclusão, e lista de exclusão erra em silêncio:
basta um arquivo novo com nome não previsto. Aqui a lógica é a inversa e tem duas travas.

  1. INCLUSÃO POR LISTA: só entra o que está declarado em CONTEUDO. O que não foi pensado
     fica de fora por omissão, que é o lado seguro do erro.
  2. VARREDURA DE SEGREDO: todo arquivo copiado é lido e comparado com um conjunto de
     padrões. Um acerto ABORTA a montagem inteira, em vez de pular o arquivo — pular
     deixaria a pasta pronta e o problema invisível.

    python publicacao/monta_repo.py            # monta e varre
    python publicacao/monta_repo.py --so-varrer  # só a varredura, sem copiar
"""
from __future__ import annotations

import re, shutil, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ.parent / "corpus-juridico-publicacao"

# Curadoria, não varredura. O projeto acumulou 108 scripts com ponto de entrada ao longo de
# meses, vários deles superados e alguns marcados como tal no próprio cabeçalho. Publicar o
# acervo inteiro entrega ao leitor a tarefa de adivinhar qual script produziu o resultado, e
# o pior caso é ele acertar o nome e errar a versão. Aqui entra APENAS o caminho que gerou o
# que está no artigo, etapa por etapa. O que ficou de fora não foi esquecido: foi descartado.
CONTEUDO: list[tuple[str, str]] = [
    # ── 1 · construção do corpus
    ("pipeline", "monta_benchmark_v2.py"),      # as 105 questões e os 940 critérios
    ("pipeline", "parse_oab_pdfs.py"),          # provas e espelhos a partir dos PDFs
    ("pipeline", "coleta_carreiras.py"),        # provas de concursos de carreira
    ("pipeline", "recoleta_normas.py"),         # coleta de leis federais
    ("pipeline", "coleta_stf_historico.py"),    # acórdãos do STF
    ("pipeline", "build_juris_bruto.py"),       # jurisprudência no braço bruto
    ("pipeline", "expande_cascata.py"),         # os exemplos a dois saltos
    ("pipeline", "diagnostico_corpus.py"),      # os defeitos que a ficha do conjunto reporta
    ("augmentation", "expand_normas.py"),       # fichas de norma
    ("augmentation", "expand_jurisprudencia.py"),
    ("augmentation", "expand_casos.py"),
    ("augmentation", "llm_client.py"), ("augmentation", "prompts.py"),
    ("augmentation", "sanitize.py"), ("augmentation", "verify.py"),
    ("augmentation/crawlers", "stf_acordaos.py"),
    ("augmentation/crawlers", "stj_acordaos.py"),
    ("augmentation/crawlers", "enunciados.py"),
    ("aws", "build_ablacao_regime.py"),         # o par casado em orçamento de tokens

    # ── 2 · treino e geração (as cadeias que rodaram as 180 condições)
    ("aws", "cadeia_ablacao_tucano.sh"), ("aws", "cadeia_ablacao_qwen.sh"),
    ("aws", "cadeia_sft_ablacao.sh"), ("aws", "gera_sft_ablacao.sh"),
    ("aws", "gera_ctrl_ablacao.sh"), ("aws", "sobe_vllm_ablacao.sh"),
    ("aws", "gera_remoto.py"), ("pipeline", "prompt_padrao.py"),

    # ── 3 · julgamento
    ("avaliacao", "julga_rabula.py"), ("avaliacao", "judge.py"),
    ("avaliacao", "benchmark_schema.py"),
    # Herdados do benchmark de origem e importados pela análise de concordância. Sem eles o
    # `kappa_por_classe.py` não roda, e é ele que produz a decomposição forma/mérito.
    ("rabula/consolidado/src", "alignment.py"),
    ("rabula/consolidado/src", "judge_llm.py"),
    ("rabula/consolidado/src", "prompts.py"),
    ("rabula/consolidado/src", "__init__.py"),

    # ── 4 · análise (roda só com os julgamentos depositados, sem GPU e sem credencial)
    ("avaliacao", "nota.py"),                   # a única função de nota do projeto
    ("avaliacao", "contrastes_por_tarefa.py"),
    ("avaliacao", "complementaridade.py"),
    ("avaliacao", "kappa_por_classe.py"),
    ("avaliacao", "analisa_kappa_v4.py"),
    ("avaliacao", "statistical_tests.py"),

    # ── 5 · manuscrito
    ("publicacao/artigo_en", "corpo_*.html"), ("publicacao/artigo_en", "tabelas.py"),
    ("publicacao/artigo_en", "monta_artigo.py"), ("publicacao/artigo_en", "estilo.css"),
    ("publicacao/artigo_en", "artigo.pdf"),
    ("publicacao/artigo", "corpo_*.html"), ("publicacao/artigo", "tabelas.py"),
    ("publicacao/artigo", "monta_artigo.py"), ("publicacao/artigo", "estilo.css"),
    ("publicacao/artigo", "artigo.pdf"),
    ("publicacao/jurix", "para_tex.py"), ("publicacao/jurix", "para_tex_en.py"),
    ("publicacao/jurix", "*.tex"), ("publicacao/jurix", "*.cls"),
    ("publicacao/jurix", "*.bst"), ("publicacao/jurix", "*.pdf"),

    # ── ferramentas
    ("dataset", "*.py"), ("dataset", "*.md"), ("dataset/manifestos", "*.json"),
    ("explorador", "*.py"), ("explorador/static", "*"),
    ("publicacao", "monta_repo.py"), ("publicacao", "para_pdf.py"),
    ("publicacao", "monta_standalone.py"), ("publicacao", "*.md"),
]

# Arquivos que vão para a RAIZ do repositório publicado. Ficam versionados aqui, em
# `publicacao/repo/`, e não direto no destino: o destino é reconstruído do zero a cada
# montagem, e o que só existisse lá seria apagado na passada seguinte.
RAIZ_REPO = ("README.md", "LEIAME.md", "REPRODUCING.md", "REPRODUZIR.md",
             "LICENSE", ".gitignore")

# Padrões de segredo. Preferem errar para o lado do alarme falso: um falso positivo custa
# uma inspeção, um falso negativo custa uma credencial publicada.
SEGREDOS: list[tuple[str, re.Pattern]] = [
    ("chave privada", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("credencial AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("segredo AWS", re.compile(r"aws_secret_access_key\s*[=:]\s*\S{20,}", re.I)),
    ("token GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")),
    ("chave de API genérica", re.compile(r"(api[_-]?key|secret|token)\s*[=:]\s*[\"'][A-Za-z0-9/+_-]{24,}[\"']", re.I)),
    ("senha atribuída", re.compile(r"(senha|password|passwd)\s*[=:]\s*[\"'][^\"']{4,}[\"']", re.I)),
]

# Nome de arquivo que não entra, seja qual for o conteúdo. É uma trava distinta da de
# conteúdo: um script que faz `ssh -i chave.pem` apenas CITA o caminho e é inofensivo; o
# que não pode viajar é o arquivo da chave em si.
NOMES_PROIBIDOS = re.compile(
    r"(\.pem|\.key|\.p12|\.pfx|id_rsa|id_ed25519|\.env.*|usuarios\.json|"
    r"\.netrc|credentials)$", re.I)

BINARIO = {".pdf", ".png", ".jpg", ".woff2", ".zip", ".gz"}


def varre(caminho: Path, rotulo: str) -> list[str]:
    if caminho.suffix.lower() in BINARIO:
        return []
    try:
        texto = caminho.read_text("utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    achados = []
    for nome, rx in SEGREDOS:
        for m in rx.finditer(texto):
            linha = texto[:m.start()].count("\n") + 1
            achados.append(f"{rotulo}:{linha}  {nome}  →  {m.group(0)[:60]}")
    return achados


# Módulos da biblioteca padrão e de terceiros que a curadoria não precisa conter.
EXTERNOS = {
    "os", "sys", "re", "json", "time", "math", "random", "shutil", "hashlib", "argparse",
    "collections", "itertools", "functools", "pathlib", "typing", "dataclasses", "glob",
    "statistics", "subprocess", "textwrap", "unicodedata", "urllib", "uuid", "html", "io",
    "tarfile", "csv", "datetime", "concurrent", "threading", "traceback", "warnings",
    "numpy", "pandas", "scipy", "sklearn", "matplotlib", "requests", "bs4", "flask",
    "boto3", "botocore", "tqdm", "yaml", "pyarrow", "playwright", "pypdf", "openai",
    "anthropic", "datasets", "transformers", "torch", "mlx", "mlx_lm", "peft", "vllm",
    "lxml", "dotenv", "tiktoken", "__future__", "logging", "types", "groq", "top2vec",
    "hdbscan", "umap", "sentence_transformers", "xml", "secrets", "json_repair",
}

IMPORTA = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)


def fecho(alvos: list[tuple[Path, str]]) -> list[str]:
    """Todo import local aponta para um arquivo que também entrou?

    É a diferença entre uma curadoria e um recorte arbitrário. Sem esta conferência o
    repositório publica um script que falha no primeiro `import` por causa de um módulo
    que ficou para trás, e o leitor descobre isso depois de clonar.
    """
    incluidos = {Path(rel).stem for _, rel in alvos if rel.endswith(".py")}
    quebras = []
    for p, rel in alvos:
        if not rel.endswith(".py"):
            continue
        try:
            texto = p.read_text("utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for m in IMPORTA.finditer(texto):
            mod = (m.group(1) or m.group(2) or "").split(".")[0]
            if not mod or mod in EXTERNOS or mod in incluidos:
                continue
            # só reclama do que existe no projeto: o resto é dependência externa
            if list(RAIZ.rglob(f"{mod}.py")):
                linha = texto[:m.start()].count("\n") + 1
                quebras.append(f"{rel}:{linha}  importa `{mod}`, que ficou de fora")
    return quebras


def itens() -> list[tuple[Path, str]]:
    fora = []
    for origem, padrao in CONTEUDO:
        base = RAIZ / origem
        if not base.exists():
            continue
        for p in sorted(base.glob(padrao)):
            if p.is_file() and "__pycache__" not in p.parts:
                fora.append((p, str(p.relative_to(RAIZ))))
    return fora


def main() -> None:
    # Os de raiz são varridos junto, mas copiados à parte: no laço comum eles virariam
    # arquivos chamados "(raiz) README.md", que foi o que aconteceu na primeira versão.
    raiz = [(RAIZ / "publicacao/repo" / n, n)
            for n in RAIZ_REPO if (RAIZ / "publicacao/repo" / n).exists()]
    corpo = itens()
    alvos = corpo + raiz
    print(f"  {len(alvos)} arquivo(s) na lista de inclusão")
    problemas = []
    for p, rel in alvos:
        if NOMES_PROIBIDOS.search(p.name):
            problemas.append(f"{rel}  nome proibido: arquivo de credencial")
        problemas += varre(p, rel)
    if problemas:
        print("\n  SEGREDO ENCONTRADO — montagem abortada:\n")
        for x in problemas:
            print("   ", x)
        raise SystemExit(1)
    print("  varredura de segredo: limpa")

    quebras = fecho(alvos)
    if quebras:
        print("\n  IMPORT SEM DESTINO — a curadoria não fecha:\n")
        for q in sorted(set(quebras)):
            print("   ", q)
        raise SystemExit(1)
    print("  fecho de imports: completo")

    if "--so-varrer" in sys.argv:
        return
    if DESTINO.exists():
        shutil.rmtree(DESTINO)
    for p, rel in corpo:
        d = DESTINO / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, d)
    for p, nome in raiz:
        shutil.copy2(p, DESTINO / nome)
    faltando = [n for n in RAIZ_REPO if not (RAIZ / "publicacao/repo" / n).exists()]
    if faltando:
        print("  aviso: falta em publicacao/repo/ →", ", ".join(faltando))
    print(f"  montado em {DESTINO}  ({len(corpo)} + {len(raiz)} na raiz)")


if __name__ == "__main__":
    main()
