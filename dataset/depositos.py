#!/usr/bin/env python3
"""depositos.py — o que vai em cada depósito, e por que são quatro e não um.

Separar não é organização, é consequência de licença e de ciclo de vida. O corpus de treino
é derivado de fonte oficial e de geração por modelo comercial; os julgamentos são produção
nossa; o padrão-ouro humano é herdado de um trabalho publicado sob CC BY; e o código muda
num ritmo que nenhum dos três acompanha. Num depósito só, a licença mais restritiva
contaminaria tudo e cada correção de código exigiria versionar 3 GB de dados.

Cada depósito recebe DOI próprio. O artigo cita o que usou, não um pacote guarda-tudo.
"""
from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

DEPOSITOS: dict[str, dict] = {
    "corpus-treino": {
        "titulo": "Corpus pareado de adaptação jurídica: texto bruto e fichas estruturadas",
        "versao": "1.0",
        "resumo": "Dois corpora de pré-treino continuado pareados documento a documento — um "
                  "de texto jurídico como coletado, outro do mesmo material reestruturado em "
                  "fichas com camadas geradas — mais os seis blocos de ajuste fino da OAB.",
        "licenca": "CC BY 4.0 para a compilação; ver DATASHEET quanto ao material gerado",
        "itens": [
            ("cpt/bruto_completo.jsonl", "data/ablacao_regime/bruto_completo.jsonl"),
            ("cpt/expandido_completo.jsonl", "data/ablacao_regime/expandido_completo.jsonl"),
            ("cpt/casado_tucano_bruto.jsonl", "data/ablacao_regime/casado_tucano_bruto.jsonl"),
            ("cpt/casado_tucano_expandido.jsonl", "data/ablacao_regime/casado_tucano_expandido.jsonl"),
            ("cpt/casado_qwen_bruto.jsonl", "data/ablacao_regime/casado_qwen_bruto.jsonl"),
            ("cpt/casado_qwen_expandido.jsonl", "data/ablacao_regime/casado_qwen_expandido.jsonl"),
            ("cpt/manifesto_orcamento.json", "data/ablacao_regime/manifesto.json"),
            *[(f"sft/bloco_{b}/{a}.jsonl", f"data/finetune/blocos/{b}/{a}.jsonl")
              for b in ("I", "II", "III", "IV", "VII", "X") for a in ("train", "valid")],
            ("receita/build_ablacao_regime.py", "aws/build_ablacao_regime.py"),
        ],
    },
    "avaliacao-ablacao": {
        "titulo": "Julgamentos das 180 condições treinadas no benchmark OAB",
        "versao": "1.0",
        "resumo": "Um arquivo por condição, uma linha por (execução, questão, critério), com "
                  "o veredito do juiz, a pontuação da banca, a área e a classe do critério — "
                  "a evidência bruta de todas as tabelas do artigo de ablação. Junto vão as "
                  "respostas geradas pelos modelos, sem as quais o julgamento não pode ser "
                  "refeito com outro juiz: só com o veredito, o leitor herda a nossa escolha "
                  "de corretor sem poder contestá-la.",
        "licenca": "CC BY 4.0",
        "itens": [("julgamentos/", "avaliacao/resultados", "*_partes.jsonl", "no_topo"),
                  ("geracoes/", "avaliacao/resultados", ".cache_*/fase1_respostas.json",
                   "so_com_julgamento")],
    },
    "benchmark-juizes": {
        "titulo": "Régua de 31 juízes automáticos contra padrão-ouro humano",
        "versao": "1.0",
        "resumo": "Vereditos de 31 modelos candidatos a juiz sobre os 940 critérios do "
                  "padrão-ouro, em até cinco repetições sob código congelado, mais as "
                  "anotações dos três juristas.",
        "licenca": "CC BY 4.0; padrão-ouro herdado do benchmark Rabula, mesma licença",
        "itens": [
            ("vereditos/", "rabula/consolidado/data/evaluations_v4", "*.json"),
            ("golden/", "rabula/consolidado/data/annotations", "*"),
        ],
    },
    "codigo": {
        "titulo": "Código do pipeline: construção de corpus, treino, geração e julgamento",
        "versao": "1.0",
        "resumo": "Repositório instantâneo no momento da submissão. O depósito de código "
                  "existe para dar DOI a um estado exato; o desenvolvimento continua no "
                  "repositório de origem.",
        "licenca": "MIT",
        # Só `.py` e `.sh`. O glob `aws/*` que estava aqui levava junto
        # `aws/tucano-train-key.pem`, uma chave privada de SSH, e ela chegou a entrar num
        # pacote antes de a varredura pegá-la. Listar extensão em vez de tudo é o que
        # transforma o erro de "vazou" em "faltou".
        "itens": [
            ("avaliacao/", "avaliacao", "*.py"),
            ("pipeline/", "pipeline", "*.py"),
            ("augmentation/", "augmentation", "*.py"),
            ("aws/", "aws", "*.py"), ("aws/", "aws", "*.sh"),
            ("publicacao/", "publicacao", "*.py"),
            ("dataset/", "dataset", "*.py"), ("dataset/", "dataset", "*.md"),
            ("explorador/", "explorador", "*.py"),
            ("revisao/", "revisao", "*.py"),
        ],
    },
}


def _so_com_julgamento(base: Path):
    """Aceita a geração de uma condição só se o julgamento dela também for junto.

    O diretório de resultados acumulou caches de tentativas antigas — um `_prompt_antigo/`
    inteiro, entre outras. Varrer por padrão traria essas sobras para o depósito e o leitor
    encontraria respostas sem veredito correspondente, sem saber se foi descuido ou se a
    condição falhou. Parear pelo nome resolve: entra a geração que tem julgamento.
    """
    conds = {p.name[:-len("_partes.jsonl")] for p in base.glob("*_partes.jsonl")}
    minusc = {c.lower() for c in conds}

    def ok(p: Path) -> bool:
        if p.parent.parent != base:
            return False                      # cache aninhado em pasta de tentativa antiga
        return p.parent.name[len(".cache_"):].lower() in minusc
    return ok


def _no_topo(base: Path):
    """Só o nível de cima. `avaliacao/resultados/_prompt_antigo/` guarda julgamentos de um
    prompt superado; eles não foram descartados porque documentam a mudança, mas publicá-los
    junto dos correntes daria ao leitor dois conjuntos incompatíveis sem etiqueta."""
    return lambda p: p.parent == base


FILTROS = {"so_com_julgamento": _so_com_julgamento, "no_topo": _no_topo}


def arquivos(dep: str) -> list[tuple[str, Path]]:
    """[(caminho no depósito, caminho no disco)] já resolvido."""
    fora: list[tuple[str, Path]] = []
    for item in DEPOSITOS[dep]["itens"]:
        if len(item) == 2:
            destino, origem = item
            p = RAIZ / origem
            if p.exists():
                fora.append((destino, p))
            continue
        destino, origem, padrao = item[0], item[1], item[2]
        base = RAIZ / origem
        if not base.exists():
            continue
        aceita = FILTROS[item[3]](base) if len(item) > 3 else (lambda p: True)
        for p in sorted(base.rglob(padrao)):
            if p.is_file() and "__pycache__" not in p.parts and aceita(p):
                fora.append((destino + str(p.relative_to(base)), p))
    return fora
