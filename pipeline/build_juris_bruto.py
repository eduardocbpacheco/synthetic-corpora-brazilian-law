#!/usr/bin/env python3
"""
build_juris_bruto.py — Jurisprudência BRUTA padronizada para o CPT.

O corpus só tinha a versão CARD da jurisprudência (texto gerado por LLM). O acórdão
original — a linguagem que o tribunal de fato escreve — estava em `decisoes/` e nunca
tinha entrado. Este script traz esse material com o mesmo desenho semi-bruto das leis:
cabeçalho de identificação e resumo REPETIDOS em cada parte do documento.

DOIS ESTRATOS, e a diferença é do pesquisador:

  CONSOLIDAÇÃO — súmulas (STF, STJ, TJSP), teses de repercussão geral, temas
  repetitivos, IRDR e IAC. **Entra INTEIRA, sem seleção nenhuma.** Enunciado de
  consolidação é único por definição: não há redundância a cortar, e descartar um
  deles é perder entendimento, não repetição.

  ACÓRDÃO — decisões individuais (STF, controle concentrado, informativos do STJ).
  Aqui sim há repetição, e vale o procedimento:
    1. descarta o que não tem questão de fato ou de direito — texto curto demais e
       acórdãos do STF que são só cabeçalho processual (lista de partes, sem ementa);
    2. modelagem de tópicos (--metodo lsa | bertopic | top2vec);
    3. dentro de cada tópico olha os N primeiros e mantém os distintos entre si;
    4. o resto do tópico fica de fora, por ser variação do mesmo entendimento.

O resumo do cabeçalho é a EMENTA oficial quando existe — não uma paráfrase de LLM.

Saída: data/juris_bruto/juris_bruto_chunks.jsonl
Uso:   python pipeline/build_juris_bruto.py [--k 800] [--por-cluster 5] [--limiar 0.6]
"""
from __future__ import annotations

import time as _t
import numpy as np
import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from vigencia import (de_registro as _vig_registro, de_tema_rg as _vig_rg,
                      entra_no_corpus as _vig_entra)   # V5
SAIDA = ROOT / "data" / "juris_bruto" / "juris_bruto_chunks.jsonl"

# Corpo de ~5.000 chars: com o cabeçalho repetido, o chunk fecha perto de 1.600 tokens
# e cabe nos 2.048 do treino sem truncar. Chunk maior perderia o fim de cada parte.
ALVO_CHARS = 5000

CAB_RE = re.compile(r"RELATOR:|PARTES:|ADV\.\(A/S\)|LEG-FED|LEG FED", re.I)
SUBST_RE = re.compile(r"ementa|decis[ãa]o|ac[óo]rd[ãa]o|tese|inconstitucional|"
                      r"recurso (?:conhecid|provid)|vistos|relat[óo]rio", re.I)

STOP = """a o e de da do das dos em no na nos nas um uma uns umas para por com sem sob sobre ao aos que se como
mais menos ja nao não ou entre ate até pelo pela pelos pelas seu sua seus suas este esta estes estas esse essa
esses essas aquele aquela isso isto ser foi sao são tem ter havia haver quando onde qual quais cujo cuja art
artigo inciso paragrafo parágrafo caput lei n nº num numero número acordao acórdão ementa relator ministro
ministra turma seção secao julgado julgamento unanimidade maioria processo recurso stf stj tribunal federal
superior justica justiça direito""".split()


def _limpa(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


# G1 · o CSV do TJSP de 1º grau vem de extração de PDF, e traz o carimbo de autenticidade
# do processo digital dentro do corpo da decisão. Medido em 18/09 sobre as 5.214 sentenças
# com texto: 4,23 M de 39,8 M caracteres, **10,6% do material**, em cinco moldes que se
# repetem palavra por palavra entre documentos.
#
# Não é só desperdício de token. Andaime formular idêntico entre documentos distintos é
# exatamente o que fez a deduplicação por LSH descartar decisão diferente quando o limiar
# estava em 0,5: o que os pares tinham em comum era o carimbo, não a matéria.
#
# No 2º grau o mesmo teste dá 2,3%, quase tudo o nome do tribunal em cabeçalho de página —
# mais brando, e limpo pelo mesmo passe.
_TRIB_TJSP = r"T\s?R\s?I\s?B\s?U\s?N\s?A\s?L(?:\s?\w)*?\s?P\s?A\s?U\s?L\s?O"
_RUIDO_TJSP = [
    # o carimbo de autenticidade do processo digital, em quatro moldes
    re.compile(r"(?i)para\s+conferir\s+o\s+original.{0,400}?liberado\s+nos\s+autos\s+em\s+"
                r"\d{2}/\d{2}/\d{4}\s*às\s*\d{2}:\d{2}\s*\.?"),
    re.compile(r"(?i)para\s+conferir\s+o\s+original.{0,300}?e\s+c[oó]digo\s+\w+\s*\."),
    re.compile(r"(?i)este\s+documento\s+(?:é|foi)\s+c[oó]pia\s+do\s+original.{0,250}?"
                r"(?:\d{2}:\d{2}\s*\.?|\.)"),
    re.compile(r"(?i)documento\s+assinado\s+digitalmente.{0,150}?\."),
    # o papel timbrado, até a abertura do ato. `SENTENÇA` é o terminador confiável: vem
    # logo depois do timbre em todos os moldes vistos, e é estrutura, não padrão adivinhado.
    re.compile(rf"{_TRIB_TJSP}.{{0,600}}?"
                r"(?=SENTEN[ÇC]A\b|CONCLUS[ÃA]O\b|DECIS[ÃA]O\b|VISTOS\b)", re.S),
    re.compile(rf"{_TRIB_TJSP}.{{0,400}}?(?:@tjsp\.jus\.br|lauda\s+\d+|CEP:?\s*\d{{5}}-?\d{{3}})",
                re.S),
    # a quebra de página injeta o timbre NO MEIO da frase; tirado o bloco principal, sobra
    # a cauda de endereço encalhada entre duas orações. Removê-la RECOMPÕE a frase.
    re.compile(r"(?i),?\s*Fone:\s*\(?\d{2}\)?[^A-ZÀ-Ú]{0,90}?E-?mail:\s*\S+@tjsp\.jus\.br"),
    re.compile(r"(?i)\bCONCLUS[ÃA]O\s+Aos?\s+.{0,300}?\bdigitei\."),
    re.compile(r"(?i)\b(?:lauda\s+\d+|fls?\.\s*\d+)\b"),
]


def _tira_ruido_tjsp(t: str) -> str:
    """Tira o papel timbrado e o carimbo digital, que não são a decisão.

    Medido em 18/09/2026: no 1º grau cai de 39,8 M para 30,4 M de caracteres, **23,5%**;
    no 2º grau, 1,1% — o 1º grau vem de extração de PDF e o 2º não.

    Sobram 9,1% dos documentos com alguma marca de timbre, em moldes que este passe não
    cobre. Fica declarado em vez de arredondado: o passe não é completo.

    A verificação que importa não é quanto saiu, e sim se saiu texto a mais. Um documento
    cujo texto limpo começa em minúscula perdeu uma maiúscula para o regex; a primeira
    versão deste passe mutilava 25 documentos assim, e esta mutila 1 em 5.214.
    """
    for rx in _RUIDO_TJSP:
        t = rx.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


# G1 · o RESUMO de uma sentença é o DISPOSITIVO, e ele é citação literal da fonte.
#
# Sentença de 1º grau não tem ementa: 0 das 5.778 linhas do CSV trazem o campo. O código
# caía nos primeiros 1.200 caracteres, que numa sentença é o "Vistos. Trata-se de ação..."
# — a parte que menos informa o que foi decidido. O dispositivo diz.
#
# Medido: 58,9% das sentenças trazem marcador explícito de abertura do dispositivo, na
# mediana a 79% do texto, e 97,8% trazem verbo de julgamento. Extrair em vez de gerar
# mantém o braço bruto não-gerado — que é a definição dele — e não custa chamada de LLM.
_RX_DISPOSITIVO = re.compile(
    r"(?i)\b(ante\s+o\s+exposto|isto\s+posto|isso\s+posto|posto\s+isso|diante\s+do\s+exposto|"
    r"pelo\s+exposto|do\s+exposto|em\s+face\s+do\s+exposto|por\s+todo\s+o\s+exposto)\b")


def _dispositivo(texto: str, teto: int = 600) -> str:
    """O trecho a partir da última abertura de dispositivo. Vazio se não houver.

    A ÚLTIMA ocorrência, e não a primeira: a fundamentação costuma citar "ante o exposto"
    ao resumir precedente alheio, e é o fecho da própria sentença que interessa.
    """
    ms = list(_RX_DISPOSITIVO.finditer(texto))
    if not ms:
        return ""
    trecho = texto[ms[-1].start():][:teto]
    ponto = trecho.rfind(". ")
    return (trecho[:ponto + 1] if ponto > 200 else trecho).strip()


# A nota do informativo do STJ abre com a identificação do julgado, em linha corrida:
# "Processo REsp 1.234.567-SP, Rel. Min. Nancy Andrighi, Terceira Turma, por unanimidade,
# julgado em 12/03/2024, DJe 15/03/2024". Relator e órgão saem daí.
_RX_RELATOR = re.compile(
    r"Rel\.?\s*(?:Min(?:istr[ao])?\.?|Minª\.?|Des(?:embargador[ao])?\.?\s*Convocad[ao])\s*"
    r"([A-ZÁÂÃÉÊÍÓÔÕÚÇ][\wÁÂÃÉÊÍÓÔÕÚÇáâãéêíóôõúç'.\- ]{3,48}?)"
    r"(?=\s*,|\s*\(|\s+por\s|\s+julgad|\s+Rel\.|\s*$)", re.M)
_RX_ORGAO = re.compile(
    r"\b((?:Primeira|Segunda|Terceira|Quarta|Quinta|Sexta)\s+(?:Turma|Seção)|Corte Especial)\b")


def shingles64(texto: str, n: int = 10) -> set[int]:
    """As shingles de `n` tokens do texto, como inteiros de 64 bits estáveis.

    Extraída de `_flui_sem_quase_duplicata` para ser UMA implementação só. A medida lexical
    passou a ser usada também fora da deduplicação — no experimento que combina semelhança
    semântica com lexical —, e duas cópias do mesmo cálculo divergem sem avisar: bastaria
    uma normalizar acento e a outra não para os dois números deixarem de ser comparáveis.

    `blake2b` e não `hash`: o `hash` de string é salgado por processo, e com ele a
    deduplicação devolvia conjunto diferente a cada execução do mesmo arquivo (N18).
    """
    import hashlib as _hl
    import unicodedata as _u
    s = _u.normalize("NFKD", (texto or "").lower())
    tk = re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if not _u.combining(c))).split()
    return {int.from_bytes(_hl.blake2b(" ".join(tk[i:i + n]).encode("utf-8"),
                                       digest_size=8).digest(), "big", signed=True)
            for i in range(max(0, len(tk) - n + 1))}


def _flui_sem_quase_duplicata(docs, limite: float = 0.8,
                              registro: list | None = None,
                              total: int | None = None):
    """Tira o que repete o que já entrou, por sobreposição de shingles de 10 tokens.

    FLUXO, e isto é o que torna o acervo do DJe tratável em 24 GB. A forma anterior recebia
    uma LISTA e devolvia outra: para as monocráticas isso seria segurar ~10 G caracteres de
    texto em memória ao mesmo tempo que os ~10 GB de vetores de shingle, e a execução morre
    antes do primeiro sinal de progresso — foi o que aconteceu em 18/09. Aqui o documento é
    ENTREGUE assim que passa, quem chama o grava e o texto é solto; do que já entrou fica em
    memória só o vetor de shingles, que é o que a comparação precisa, mais três campos por
    documento para o registro de descartes poder nomear o vencedor. O resultado é idêntico:
    `_sem_quase_duplicata` é esta mesma função consumida em lista.

    Medido em dois dias inteiros do DJe, a quase-duplicação não é a mesma em todo lugar —
    e é isso que responde se "saber que algo NÃO é" vale a pena. A proporção de pares com
    sobreposição acima de 0,5:

        acórdão              0,3%      sobra 90% depois de deduplicar
        Concedendo           0,3%      sobra 95%
        Negando              1,4%      sobra 93%
        Não Conhecendo      25,7%      sobra 53%

    A decisão que CONHECE e nega mérito se comporta como acórdão: é o tribunal dizendo o
    que o direito é, e quase não se repete. A que NÃO CONHECE também é direito — de
    admissibilidade, que é metade da prática recursal —, mas quase metade dela repete outra
    do mesmo dia, sobretudo a fórmula da Súmula 7. O problema nunca foi a matéria, foi a
    repetição; e para repetição a ferramenta é deduplicar, não excluir.

    Vale também para os acórdãos: 10% deles são quase-duplicata de outro, e isso ninguém
    tinha medido.
    """
    import hashlib as _hl
    import unicodedata as _u

    import numpy as _np
    # LSH por FAIXAS, e não por shingle solta. A versão por shingle — mesmo com esboço de
    # hash mínimo — ainda junta candidatos demais: uma shingle sozinha é compartilhada por
    # muitos documentos, a lista de postagem cresce e a deduplicação de 45 mil documentos
    # não termina. Na faixa, dois documentos só viram candidatos se coincidirem em TODAS as
    # 4 posições de alguma das 12 faixas, o que é seletivo o bastante para o conjunto de
    # candidatos ficar pequeno e sensível o bastante para não perder par acima de 0,5.
    # 20 faixas de 3 linhas, e os números não são gosto: com `b` faixas de `r` linhas, a
    # chance de um par de semelhança `s` virar candidato é 1-(1-s^r)^b. Com 12×4 ela é de
    # só 54% em s=0,5 — e a deduplicação passou a deixar 86% em pé onde a comparação
    # exaustiva deixava 78%, ou seja, perdia quase metade dos pares no limiar. Com 20×3 a
    # detecção em 0,5 vai a 93%, em 0,6 a 99% e acima disso é praticamente certa.
    # HASH ESTÁVEL, e isto é correção de REPRODUTIBILIDADE, não otimização.
    #
    # A versão anterior ordenava as shingles por `hash(tupla_de_strings)` para montar o
    # esboço min-hash. O `hash` de string no Python é SALGADO por processo, então o esboço
    # mudava a cada execução e a deduplicação devolvia um conjunto diferente do mesmo
    # arquivo. Medido em 18/09 sobre 8.000 monocráticas, três execuções idênticas:
    # **6.268, 6.259 e 6.269 documentos**. O corpus não era reconstruível a partir do
    # próprio código — defeito grave para dissertação, e o mesmo que já havia sido corrigido
    # no `random_state` do UMAP, aqui despercebido.
    #
    # `blake2b` de 8 bytes é estável entre execuções e entre máquinas. Custa 23 minutos
    # contra 11 para 2,1 M de documentos; a alternativa `crc32` empata em velocidade com o
    # `hash` salgado, mas dá 32 bits em vez de 64.
    #
    # MEMÓRIA, na mesma passagem. Guardar cada shingle como tupla de 10 strings custava
    # **269.460 bytes por documento** — medido, não estimado —, o que para os ~2,1 M de
    # monocráticas projetados daria 566 GB. Guardando o conjunto como vetor `int64`
    # ordenado, cai para **15.070 B/doc**, ou ~32 GB no total, e a deduplicação fica mais
    # rápida (17 s contra 23 s em 20.000 documentos). Sobre a mesma entrada e o mesmo seed,
    # as duas formas devolvem **exatamente os mesmos documentos**.
    #
    # A alternativa que NÃO serve é janelar. Medida: com janela de 10.000, a perda de pares
    # é de 2,2% com 2 janelas, 4,4% com 4 e 5,5% com 6 — cresce cerca de 1 ponto por
    # janela, e 2,1 M de documentos dariam 210 janelas.
    def _h64(g: tuple) -> int:
        return int.from_bytes(
            _hl.blake2b(" ".join(g).encode("utf-8"), digest_size=8).digest(),
            "big", signed=True)

    # PROGRESSO, porque o silêncio custou caro. A deduplicação do acervo do DJe ficou
    # cinquenta minutos sem dizer nada sobre 669.925 acórdãos, e não havia como saber se
    # faltavam dois minutos ou seis horas — nem se estava presa. Um trabalho que leva mais
    # que alguns minutos tem de dizer em que ponto está; sem isso, a única escolha é esperar
    # às cegas ou matar e perder tudo.
    import time as _t
    FAIXAS, LINHAS = 20, 3
    idx: dict[tuple, list[int]] = {}
    # Só o necessário para o registro de descartes nomear o vencedor: quem é, de que
    # processo e de que tamanho. O texto do vencedor já foi entregue e não volta.
    fica: list[tuple] = []
    conj: list = []
    _t0, _prox = _t.time(), 60.0
    _n = total if total is not None else len(docs)
    for _i, d in enumerate(docs):
        if _n > 50_000 and _t.time() - _t0 > _prox:
            _dt = _t.time() - _t0
            _resta = _dt * (_n - _i) / max(1, _i)
            print(f"    dedup {_i:,}/{_n:,} ({_i/_n:.0%}) · ficam {len(fica):,} · "
                  f"{_dt/60:.0f} min · faltam ~{_resta/60:.0f} min", flush=True)
            _prox += 60.0
        sh_h = shingles64(d.get("texto") or d.get("text") or "")
        if not sh_h:
            continue
        sh = _np.array(sorted(sh_h), dtype=_np.int64)
        esboco = sorted(sh_h)[:FAIXAS * LINHAS]
        if len(esboco) < FAIXAS * LINHAS:
            esboco = (esboco * FAIXAS * LINHAS)[:FAIXAS * LINHAS]
        bandas = [tuple(esboco[b * LINHAS:(b + 1) * LINHAS]) for b in range(FAIXAS)]
        cand = {i for b in bandas for i in idx.get(b, ())}
        # ETAPA 3 da cadeia de custódia · o descarte precisa deixar RASTRO.
        #
        # Até aqui a deduplicação rodava em memória e o que ela tirava sumia sem registro:
        # dava para saber quantos caíram, nunca QUAIS nem por semelhança a quem. Era isso
        # que impedia a CORPORA-FASE-2 de existir como artefato auditável, e não é detalhe
        # de log — o limiar já esteve em 0,5, e nessa faixa 65% dos pares removidos de
        # espelho eram decisões DISTINTAS que só compartilhavam o andaime formular do
        # acórdão. Sem o par gravado, não havia como ver isso a não ser reexecutando.
        #
        # Grava-se o vencedor, o descartado e a semelhança medida — o suficiente para
        # refazer a escolha do limiar sem recoletar nem reconstruir.
        _melhor, _s = None, 0.0
        for i in cand:
            _inter = _np.intersect1d(sh, conj[i], assume_unique=True).size
            _si = _inter / max(sh.size, conj[i].size, 1)
            if _si > _s:
                _melhor, _s = i, _si
        if _s >= limite:
            if registro is not None and _melhor is not None:
                _venc_ref, _venc_proc, _venc_chars = fica[_melhor]
                # `id` no acervo montado, `seq` no acervo cru do DJe: o registro tem de
                # nomear o descartado nos dois, senão grava None e não serve para auditar.
                registro.append({
                    "descartado": d.get("id") or d.get("seq"),
                    "processo": d.get("processo"),
                    "fonte": d.get("fonte"), "chars": len(d.get("texto") or ""),
                    "duplica": _venc_ref,
                    "duplica_processo": _venc_proc,
                    "duplica_chars": _venc_chars,
                    "semelhanca": round(_s, 4),
                })
            continue
        for b in bandas:
            idx.setdefault(b, []).append(len(fica))
        conj.append(sh)
        fica.append((d.get("id") or d.get("seq"), d.get("processo"),
                     len(d.get("texto") or d.get("text") or "")))
        yield d


def _sem_quase_duplicata(docs: list[dict], limite: float = 0.8,
                         registro: list | None = None) -> list[dict]:
    """A forma em LISTA do `_flui_sem_quase_duplicata` — mesma implementação, um consumidor
    diferente. Quem já cabe em memória continua chamando esta; quem não cabe (o DJe) consome
    o fluxo e grava documento a documento."""
    return list(_flui_sem_quase_duplicata(docs, limite, registro, total=len(docs)))


def carregar_monocraticas(teto: int, semente: int = 42) -> list[dict]:
    """G2 · a decisão monocrática do STJ, que estava em disco sem caminho até o corpus.

    Vem de `dje_monocraticas_sel.jsonl`, que o `dedup_dje.py` já entregou resolvido por
    `seq` e deduplicado por semelhança, com os teores escolhidos em 18/09: entram
    **Concedendo e Negando**, fica de fora **Não Conhecendo**. A razão foi medida, não
    estética — em amostra de 30.000 de cada teor, deduplicando a 0,8, o Não Conhecendo é
    48,6% redundante e 46% dele invoca a Súmula 7, que é uma matéria só dita um milhão de
    vezes; o Negando é 8,5% e o Concedendo 4,2%, o material menos repetitivo do acervo
    inteiro. Entre os ACÓRDÃOS a proporção se inverte — 81% do volume é Negando e 13% Não
    Conhecendo —, o que diz onde cada coisa mora: admissibilidade na monocrática, mérito no
    colegiado.

    O TETO é obrigatório e não tem valor padrão generoso de propósito. O acervo selecionado
    são ~9 G caracteres, e a montagem carrega texto em memória: pô-lo inteiro ao lado dos
    7,5 G dos acórdãos não cabe em 24 GB, e o corpus de treino inteiro tem hoje 1,6 GB. A
    escolha de quanto entra é decisão de COMPOSIÇÃO, do pesquisador, e por isso é parâmetro
    de linha de comando e não constante escondida aqui dentro.

    A amostra é sorteada com semente fixa, e isso é requisito de reprodutibilidade, não
    capricho: é a mesma lição do `random_state` do UMAP e do hash salgado do N18 — o corpus
    tem de ser reconstruível a partir do próprio código. Sorteio, e não "os primeiros N",
    porque o arquivo sai do dedup ordenado por teor e depois por data, então cortar pelo
    começo daria só Negando dos primeiros anos.
    """
    p = ROOT / "decisoes/stj/dje_monocraticas_sel.jsonl"
    if teto <= 0 or not p.exists():
        return []
    # Duas passagens: a primeira conta as linhas, a segunda lê só as sorteadas. Carregar
    # tudo para depois amostrar seria justamente o que não cabe.
    n = sum(1 for _ in open(p, "rb"))
    escolhidas: set[int] | None = None
    if teto < n:
        import random as _r
        escolhidas = set(_r.Random(semente).sample(range(n), teto))
    docs = []
    for i, l in enumerate(open(p, errors="replace")):
        if escolhidas is not None and i not in escolhidas:
            continue
        d = json.loads(l)
        txt = _limpa(d.get("texto"))
        if len(txt) < 200:
            continue
        proc = d.get("processo") or ""
        # Prefixo próprio no identificador: `DJEM` contra o `DJE` do acórdão. Os dois saem
        # do mesmo espaço de `SeqDocumento` do portal, e o N23 já mostrou o que acontece
        # quando o tipo do documento se perde no caminho.
        docs.append(dict(id=f"BRUTO:STJ:DJEM:{d.get('seq')}",
                         fonte="STJ — decisão monocrática", tribunal="STJ",
                         classe=(proc.split() or [""])[0],
                         numero=str(d.get("registro") or ""), processo=proc,
                         relator=d.get("relator") or "", orgao="",
                         data=d.get("data") or "", ementa="", texto=txt))
    print(f"  monocráticas: {n:,} no acervo selecionado · {len(docs):,} sorteadas "
          f"(semente {semente})", flush=True)
    return docs


def carregar_acordaos() -> list[dict]:
    """Decisões individuais — sujeitas à seleção por tópico."""
    docs = []
    # C17 · Dois arquivos, e o segundo nunca foi lido. `stf_acordaos.jsonl` e uma janela de
    # 2025–2026: a consulta ordenava por data decrescente e batia no teto de paginacao de
    # 10.000 do indice, entao parava no ano corrente sem dizer nada. O fatiamento por data
    # que resolveu o C2 e o C4 tambem foi rodado aqui e gerou
    # `stf_acordaos_historico.jsonl`, com 25.984 registros de 2010 a 2026 — que ficaram
    # colhidos e fora do corpus porque ninguem ligou o arquivo ao construtor.
    #
    # Dos 25.984, so 9.461 sao decisao: 16.523 sao DESPACHO, com mediana de 955 caracteres
    # e nenhuma ementa. Despacho nao decide questao de direito — e "cite-se", "manifeste-se",
    # o expediente que move o processo. Ensina-lo junto com acordao e o mesmo defeito do B6,
    # tratar igual o que tem naturezas diferentes. O `elegivel` ja derruba 96% deles pelo
    # teste de cabecalho sem substancia; o `doc_id` diz isso de frente e sem depender de
    # heuristica sobre o texto.
    vistos_ac = set()
    _stf_ac: dict[str, dict] = {}
    for arq in ("stf_acordaos.jsonl", "stf_acordaos_historico.jsonl"):
        p_ac = ROOT / "decisoes/stf" / arq
        if not p_ac.exists():
            continue
        for l in open(p_ac, errors="replace"):
            d = json.loads(l)
            if str(d.get("doc_id") or "").startswith("despacho"):
                continue
            # O `doc_id` do indice e a chave; os dois arquivos se sobrepoem no ano corrente.
            ident = str(d.get("doc_id") or "") or f"{d.get('processo')}|{d.get('data_julgamento')}"
            if ident in vistos_ac:
                continue
            vistos_ac.add(ident)
            # O identificador tem de ser a MESMA coisa que a chave de deduplicação logo
            # acima. Ele usava só o processo, e a chave usa `doc_id` ou processo+data: por
            # isso dois acórdãos do mesmo processo — `AP 477 AgR` julgado em 2010 e de novo
            # em 2013 — passavam pela deduplicação e depois disputavam o mesmo id. Um
            # processo rende vários acórdãos ao longo do tempo; o número dele não
            # identifica julgado.
            _stf_ac[ident] = dict(id=f"BRUTO:STF:{ident}",
                             fonte="STF — acórdão", tribunal="STF",
                             classe=d.get("classe") or "",
                             numero=str(d.get("numero") or ""),
                             processo=d.get("processo") or "",
                             relator=d.get("relator") or "", orgao=d.get("orgao") or "",
                             data=d.get("data_julgamento") or "",
                             ementa=_limpa(d.get("ementa")),
                             texto=_limpa(d.get("texto")))
    # C2 · O inteiro teor do controle concentrado, quando existe. O arquivo antigo grava
    # `texto=ementa`, porque a coleta anterior só tinha a ementa; a URL de inteiro teor que
    # ela guardava aponta para um endpoint que responde 202 vazio a qualquer acesso
    # automatizado. O texto vem da própria API de busca, no campo `inteiro_teor_texto`, e
    # está em `stf_inteiro_teor_concentrado.jsonl`. Casa por `id`, que os dois arquivos
    # trazem na forma `sjurNNNNNN`.
    #
    # Cobertura medida na API: 4.402 dos 7.712 acórdãos têm inteiro teor digitalizado —
    # 100% do ADPF e do ADO, 52,5% do ADI. A falta é do acervo do STF, não da coleta.
    inteiro: dict[str, dict] = {}
    p_it = ROOT / "decisoes/stf/stf_inteiro_teor_concentrado.jsonl"
    if p_it.exists():
        for l in open(p_it, errors="replace"):
            d = json.loads(l)
            if d.get("id"):
                inteiro[str(d["id"])] = d

    vistos_cc = set()
    for l in open(ROOT / "decisoes/stf/controle_concentrado.jsonl", errors="replace"):
        d = json.loads(l)
        em = _limpa(d.get("ementa_texto"))
        rel = d.get("relator_acordao_nome")
        it = inteiro.get(str(d.get("id") or ""))
        corpo = _limpa(it.get("inteiro_teor_texto")) if it else ""
        vistos_cc.add(str(d.get("id") or ""))
        docs.append(dict(id=f"BRUTO:STF:CC:{d.get('processo') or d.get('id')}",
                         fonte="STF — controle concentrado", tribunal="STF",
                         classe=d.get("classe") or "", numero=str(d.get("numero") or ""),
                         processo=d.get("processo") or "", relator=rel if rel not in (None, "None") else "",
                         orgao="", data=d.get("julgamento_data") or "",
                         ementa=em, texto=corpo or em))

    # O arquivo novo cobre acórdãos que o antigo não tinha: são 7.712 na API contra 4.053
    # no arquivo de janeiro. Os que sobram entram por aqui.
    for ident, d in inteiro.items():
        if ident in vistos_cc:
            continue
        corpo = _limpa(d.get("inteiro_teor_texto"))
        if not corpo:
            continue
        docs.append(dict(id=f"BRUTO:STF:CC:{d.get('titulo') or ident}",
                         fonte="STF — controle concentrado", tribunal="STF",
                         classe=d.get("classe") or "",
                         numero=str(d.get("processo_numero") or ""),
                         processo=d.get("titulo") or "",
                         relator=d.get("relator_acordao_nome") or "",
                         orgao=d.get("orgao_julgador") or "",
                         data=d.get("julgamento_data") or "",
                         ementa=_limpa(d.get("ementa_texto")), texto=corpo))
    # B1 · Os acórdãos que o braço expandido fichava e o bruto não tinha. Sem eles a regra
    # D4 fica insatisfeita pelo lado errado: há ficha sem o texto que ela ficha. Buscados um
    # a um, e não por classe inteira — as classes a que pertencem somam 187.576 documentos
    # para uma lacuna de 1.567, e encheriam o corpus de agravo regimental.
    p_falt = ROOT / "decisoes/stf/stf_faltantes.jsonl"
    if p_falt.exists():
        for l in open(p_falt, errors="replace"):
            d = json.loads(l)
            corpo = _limpa(d.get("inteiro_teor_texto"))
            if len(corpo) < 200:
                continue
            classe = d.get("processo_classe_processual_unificada_sigla") or ""
            num = str(d.get("processo_numero") or "")
            # `stf_faltantes.jsonl` SE SOBREPÕE ao `stf_acordaos.jsonl` em 1.243
            # documentos: o `id` daqui é o `doc_id` de lá. As duas cargas rotulavam ambos
            # como "STF — acórdão" e cada uma tinha o seu próprio conjunto de vistos, de
            # modo que o mesmo julgado entrava DUAS vezes — uma como extrato de 4 mil
            # caracteres e outra como íntegra de 31 mil. Ninguém via porque os ids eram
            # montados de formas diferentes, um pelo processo e outro pelo `id`.
            # Agora as duas alimentam o mesmo acumulador, e fica o texto MAIOR, que é a
            # íntegra — foi para isso que este arquivo foi colhido.
            _novo = dict(id=f"BRUTO:STF:{d.get('id')}", fonte="STF — acórdão",
                             tribunal="STF", classe=classe, numero=num,
                             # `classe numero`, e não o `titulo`: o título vem como
                             # "ADPF 1058 MC-Ref", com o número no MEIO, e a conferência de
                             # pareamento exige que a cadeia termine em dígito.
                             processo=f"{classe} {num}".strip(),
                             relator=d.get("relator_acordao_nome") or d.get("relator_processo_nome") or "",
                             orgao=d.get("orgao_julgador") or "",
                             data=str(d.get("julgamento_data") or "")[:10],
                             ementa=_limpa(d.get("ementa_texto")), texto=corpo)
            _ant = _stf_ac.get(str(d.get("id")))
            if not _ant or len(_ant.get("texto") or "") < len(corpo):
                _stf_ac[str(d.get("id"))] = _novo

    # N17 · A MESMA decisão entrava duas vezes, sob dois rótulos, e a deduplicação não
    # tinha como ver.
    #
    # Achado em 18/09 ao fechar o T5 (truncagem na gravação). O `doc_id` de
    # `stf_acordaos*.jsonl` é o mesmo `sjurNNNNNN` do inteiro teor: 11.371 dos 30.504
    # acórdãos o trazem nessa forma, e **1.736 deles também estão em
    # `stf_inteiro_teor_concentrado.jsonl`**. O extrato entrava como "STF — acórdão" e a
    # íntegra como "STF — controle concentrado" — 9,2 M de caracteres de extrato ao lado da
    # íntegra completa do mesmo julgado. No primeiro caso conferido, `sjur370637`, são
    # 10.000 caracteres (o teto exato do `texto[:10000]`) contra 142.530.
    #
    # A deduplicação por LSH não alcança isso por duas razões somadas: ela roda POR FONTE, e
    # estes estão em fontes distintas; e mesmo na mesma fonte, um texto 14 vezes menor que o
    # outro não atinge similaridade 0,8.
    #
    # Fica a ÍNTEGRA, que entra pelo caminho do controle concentrado com o texto inteiro, e
    # sai o extrato. É a mesma decisão do N12, reaparecida por outra porta.
    _dup_it = [k for k in _stf_ac if k in inteiro]
    for k in _dup_it:
        del _stf_ac[k]
    if _dup_it:
        print(f"  N17 · {len(_dup_it)} extratos do STF descartados: a íntegra do mesmo "
              f"julgado entra como controle concentrado")

    # O acumulador dos acórdãos do STF é despejado aqui, depois das DUAS cargas que o
    # alimentam, e não no fim de cada uma.
    docs.extend(_stf_ac.values())

    # C4 · Informativo do STF, uma nota por julgado. O tribunal já entrega a tese
    # rotulada em `resumo_noticia` e a fundamentação em `conteudo_noticia`, com a
    # legislação e a jurisprudência citadas em campo próprio. É o material mais limpo do
    # corpus: compare com o Q1, que aponta que as fichas de precedente GERADAS não dizem o
    # que foi decidido. Aqui quem diz é o STF.
    p_inf = ROOT / "decisoes/stf/stf_inteiro_teor_informativo.jsonl"
    if p_inf.exists():
        for l in open(p_inf, errors="replace"):
            d = json.loads(l)
            resumo = _limpa(d.get("resumo_noticia"))
            corpo = _limpa(d.get("conteudo_noticia"))
            if len(resumo) + len(corpo) < 200:
                continue
            classe = d.get("processo_classe_processual_unificada_classe_sigla") or ""
            num = str(d.get("processo_numero") or "")
            partes = [f"[QUESTÃO] {_limpa(d.get('titulo_noticia'))}" if d.get("titulo_noticia") else "",
                      f"[TESE] {resumo}" if resumo else "",
                      f"[FUNDAMENTAÇÃO] {corpo}" if corpo else "",
                      f"[LEGISLAÇÃO CITADA] {_limpa(d.get('documental_legislacao_citada_texto'))}"
                      if d.get("documental_legislacao_citada_texto") else "",
                      f"[JURISPRUDÊNCIA CITADA] {_limpa(d.get('documental_jurisprudencia_citada_texto'))}"
                      if d.get("documental_jurisprudencia_citada_texto") else ""]
            texto = "\n".join(x for x in partes if x)
            docs.append(dict(id=f"BRUTO:STF:INF:{d.get('id')}",
                             fonte="STF — informativo", tribunal="STF", classe=classe,
                             numero=num, processo=(f"{classe} {num}".strip() or d.get("titulo") or ""),
                             relator=d.get("relator_processo_nome") or "",
                             orgao=d.get("orgao_julgador") or "",
                             data=str(d.get("julgamento_data") or "")[:10],
                             ementa=resumo, texto=texto))

    # C1 · acórdãos do STJ pelo portal de DADOS ABERTOS do tribunal, sob CC-BY. O sistema
    # de consulta segue bloqueado por desafio anti-automação e não foi tocado; o acervo,
    # não — o STJ publica as íntegras do Diário da Justiça em `dadosabertos.web.stj.jus.br`.
    # É a íntegra mesmo: mediana de 16 mil caracteres, com ementa, relatório e voto.
    # O DJe REPUBLICA o mesmo documento em mais de um dia — 223 dos 22.875 `SeqDocumento`
    # aparecem em duas datas, e nos 223 o texto é IDÊNTICO, conferido. Não é colisão de
    # identificador: é a mesma decisão publicada de novo. Fica a publicação mais ANTIGA,
    # que é a data em que a decisão veio a público. Sem isso o F4 reprovaria.
    # A acumulação é por DICIONÁRIO e não por varredura da lista a cada registro: a versão
    # que filtrava `docs` a cada linha era quadrática e levava 75 s só neste trecho.
    p_dje = ROOT / "decisoes/stj/dje_acordaos.jsonl"
    if p_dje.exists():
        por_seq: dict[str, dict] = {}
        for l in open(p_dje, errors="replace"):
            d = json.loads(l)
            txt = _limpa(d.get("texto"))
            if len(txt) < 200:
                continue
            seq = str(d.get("seq"))
            ant = por_seq.get(seq)
            # `str(...)` dos dois lados: o campo chega ora string ora epoch conforme o
            # ano do Diário (ver `_data_iso` no coletor). A normalização certa é na origem
            # e já está lá; esta é a rede de segurança, porque um acervo já gravado com o
            # formato antigo não deve derrubar a montagem inteira.
            if ant and str(ant.get("data") or "") <= str(d.get("data") or ""):
                continue
            proc = d.get("processo") or ""
            por_seq[seq] = dict(id=f"BRUTO:STJ:DJE:{seq}", fonte="STJ — acórdão",
                                tribunal="STJ", classe=(proc.split() or [""])[0],
                                numero=str(d.get("registro") or ""), processo=proc,
                                relator=d.get("relator") or "", orgao="",
                                data=d.get("data") or "", ementa="", texto=txt)
        # A deduplicação NÃO roda aqui. Ela custa 74 s a cada 8 mil documentos, e
        # `carregar_acordaos` é chamado pela montagem e por cada execução da conferência —
        # pagar isso toda vez é desperdício. É passo próprio, uma vez só, em
        # `pipeline/dedup_dje.py`, que reescreve o arquivo de coleta.
        docs.extend(por_seq.values())
        _dje_reg = {str(x["numero"]) for x in por_seq.values() if x.get("numero")}
    else:
        _dje_reg = set()

    # C1 · espelhos de acórdão, o segundo conjunto do portal aberto. O espelho é o registro
    # que a Secretaria de Jurisprudência produz sobre o acórdão — e é o que o sistema de
    # consulta bloqueado serve: ementa, decisão, jurisprudência citada e referências
    # legislativas, que a íntegra do DJe traz soltas no corpo, sem estrutura.
    #
    # Quem tem íntegra no DJe NÃO entra de novo: medido, a ementa do espelho já está DENTRO
    # da íntegra em 92% dos casos casados, e repeti-la é o defeito do B3. São 3.882 casos.
    # O resto — a grande maioria, porque os espelhos cobrem período bem mais largo que os
    # 141 dias colhidos do DJe — entra como documento próprio.
    p_esp = ROOT / "decisoes/stj/espelhos_acordaos.jsonl"
    if p_esp.exists():
        vistos_esp = set()
        for l in open(p_esp, errors="replace"):
            d = json.loads(l)
            reg = str(d.get("numeroRegistro") or "").strip()
            if reg and reg in _dje_reg:
                continue
            ident = str(d.get("id") or "")
            if not ident or ident in vistos_esp:
                continue
            vistos_esp.add(ident)
            partes = [f"[EMENTA] {_limpa(d.get('ementa'))}" if d.get("ementa") else "",
                      f"[DECISÃO] {_limpa(d.get('decisao'))}" if d.get("decisao") else "",
                      f"[TESE] {_limpa(d.get('teseJuridica'))}" if d.get("teseJuridica") else "",
                      f"[LEGISLAÇÃO CITADA] {_limpa(' · '.join(d.get('referenciasLegislativas') or []))}"
                      if d.get("referenciasLegislativas") else "",
                      f"[JURISPRUDÊNCIA CITADA] {_limpa(d.get('jurisprudenciaCitada'))}"
                      if d.get("jurisprudenciaCitada") else ""]
            corpo = "\n".join(x for x in partes if x)
            if len(corpo) < 200:
                continue
            cl = d.get("siglaClasse") or ""
            docs.append(dict(id=f"BRUTO:STJ:ESP:{ident}", fonte="STJ — espelho",
                             tribunal="STJ", classe=cl,
                             numero=str(d.get("numeroProcesso") or ""),
                             processo=f"{cl} {d.get('numeroProcesso') or ''}".strip(),
                             relator=d.get("ministroRelator") or "",
                             orgao=d.get("nomeOrgaoJulgador") or "",
                             data=str(d.get("dataDecisao") or ""), ementa="", texto=corpo))

    for i, l in enumerate(open(ROOT / "decisoes/stj/stj_informativos_acordaos.jsonl", errors="replace")):
        d = json.loads(l)
        txt = _limpa(d.get("texto"))
        proc = d.get("processo") or ""
        m = re.search(r"((?:REsp|AREsp|HC|RHC|CC|MS|AgInt|EDcl)[\s\.\d\-/A-Z]{4,25})", txt)
        if not proc and m:
            proc = m.group(1).strip()
        # C1 · o relator vinha VAZIO nos 4.093 documentos, e o órgão em 3.281 deles: o
        # arquivo não traz os campos, mas a nota do informativo os escreve na primeira
        # linha — "Rel. Min. Nancy Andrighi, Terceira Turma, por unanimidade, julgado em".
        # Ninguém reclamava porque campo vazio não levanta erro. Extraídos daqui: relator
        # em 99,1% (59 ministros distintos, todos do STJ) e órgão em 87,6%.
        # Isto NÃO substitui o C1, que é o inteiro teor e segue bloqueado pelo desafio
        # anti-automação do tribunal — melhora o que já está em mãos, colhido do
        # Informativo de Jurisprudência, que o STJ publica aberto.
        mr = _RX_RELATOR.search(txt)
        mo = _RX_ORGAO.search(txt)
        docs.append(dict(id=f"BRUTO:STJ:INFJ:{d.get('informativo')}:{i}", fonte="STJ — informativo",
                         tribunal="STJ", classe="", numero=str(d.get("informativo") or ""),
                         processo=proc,
                         relator=(d.get("relator") or "").strip()
                                 or (re.sub(r"\s+", " ", mr.group(1)).strip(" .,") if mr else ""),
                         orgao=(d.get("orgao") or "").strip()
                               or (re.sub(r"\s+", " ", mo.group(1)) if mo else ""),
                         data=d.get("data") or "", ementa="", texto=txt))

    # Quase-duplicata sai POR FONTE, e não só do acervo do STJ. A pergunta que levou a isto
    # era sobre monocráticas, e a resposta apareceu noutro lugar: quando medi as outras
    # fontes, o acórdão do STF também repetia. Medido, antes da montagem:
    #
    #     STJ — DJe                24% quase-duplicata   (já tirado em `dedup_dje.py`)
    #     STF — acórdão histórico   9%
    #     STF — informativo         9%
    #     STF — acórdão            15%
    #     STJ — espelho             2%
    #     STJ — informativo         1%
    #
    # Por FONTE e não sobre o todo: comparar 230 mil documentos entre si custaria minutos a
    # cada execução, e duplicata entre fontes distintas é outra pergunta — a do espelho
    # contra a íntegra, que já foi respondida por `numeroRegistro` e não por semelhança.
    #
    # E o que JÁ FOI deduplicado não é deduplicado de novo. Medido na montagem de 19/09: o
    # passe sobre os 558.307 acórdãos do DJe levou 32 minutos e removeu **zero** documentos,
    # porque o `dedup_dje.py` já os havia tirado, com o mesmo algoritmo e o mesmo limiar de
    # 0,8. Não era só tempo perdido: o passe guarda o vetor de shingles de tudo que já
    # entrou, e com meio milhão de documentos isso põe a máquina de 24 GB a comprimir
    # memória — o RSS mostrava 3 GB enquanto o compressor segurava 29,7 G comprimidos em
    # 11,5 de física, e a fase de tópicos, que vem logo depois, é justamente a que precisa
    # do espaço. O acervo do DJe chega ao construtor pronto, por desenho: a deduplicação
    # dele é passo próprio, uma vez só, e não trabalho de toda montagem.
    JA_DEDUPLICADAS = {"STJ — acórdão", "STJ — decisão monocrática"}
    por_fonte: dict[str, list[dict]] = {}
    for d in docs:
        por_fonte.setdefault(d["fonte"], []).append(d)
    for _f in sorted(JA_DEDUPLICADAS & set(por_fonte)):
        print(f"  {_f}: {len(por_fonte[_f]):,} — quase-duplicata já tirada em dedup_dje.py, "
              f"não se repete aqui", flush=True)
    saida, cortados = [], {}
    _reg: list[dict] = []
    for f, g in por_fonte.items():
        if f in JA_DEDUPLICADAS:
            saida.extend(g)
            continue
        lim = _sem_quase_duplicata(g, registro=_reg)
        if len(lim) < len(g):
            cortados[f] = len(g) - len(lim)
        saida.extend(lim)
    if cortados:
        print("  quase-duplicatas fora: " + " · ".join(f"{k} {v}" for k, v in cortados.items()))
    # CORPORA-FASE-2: o registro do que a etapa 3 tirou, e por semelhança a quê.
    p_reg = ROOT / "data/juris_bruto/dedup_descartados.jsonl"
    p_reg.parent.mkdir(parents=True, exist_ok=True)
    with open(p_reg, "w", encoding="utf-8") as fh:
        for r in _reg:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    if _reg:
        _ch = sum(r["chars"] for r in _reg)
        _med = sorted(r["semelhanca"] for r in _reg)[len(_reg) // 2]
        print(f"  → {p_reg.relative_to(ROOT)}: {len(_reg)} descartes · "
              f"{_ch/1e6:.1f} M chars · semelhança mediana {_med:.3f}")
    return saida


# A "tese" que não é tese: texto de navegação do portal e aviso de que o acórdão ainda não
# saiu. O campo vem preenchido, então a regra de exigir tese não o barra, e o corpus passa
# a ensinar "Clique aqui para ter acesso a todas as teses firmadas neste tema" como se
# fosse o entendimento firmado. São poucos — 4 no bruto — e são exatamente o tipo de ruído
# que um modelo reproduz com confiança.
_TESE_FALSA = re.compile(
    r"(clique\s+aqui|acessar?\s+a\s+tese|consulte\s+o\s+inteiro\s+teor|veja\s+a\s+tese"
    r"|aguardando\s+public|não\s+divulgad|em\s+elabora|pendente\s+de\s+public)", re.I)


def tese_utilizavel(tese: str) -> bool:
    tese = (tese or "").strip()
    return len(tese) >= 40 and not _TESE_FALSA.search(tese[:160])


def numero_limpo(numero: str, classe: str, tribunal: str) -> str:
    """Remove a classe e o tribunal que a fonte já embutiu no número.

    B10 · `iac_teses.jsonl` grava `numero` como "IAC STJ 1", e o rótulo é montado como
    `{classe} {numero} do {tribunal}`. O resultado era "IAC IAC STJ 1 do STJ", com a sigla
    três vezes.
    """
    n = str(numero or "").strip()
    for prefixo in (f"{classe} {tribunal}", f"{classe}", f"{tribunal}"):
        if prefixo and n.upper().startswith(prefixo.upper()):
            n = n[len(prefixo):].strip(" -–:")
    return n or str(numero or "").strip()


# Fontes de tese de IRDR/IAC, uma linha por arquivo. É CONSTANTE DE MÓDULO, e não
# literal dentro do laço, para que `confere_corpus.py` confira a lista real em vez de
# manter uma cópia: acrescentar fonte aqui e esquecer lá é perda silenciosa, que é o
# modo de falha que mais apareceu neste corpus.
FONTES_IRDR = [("tjsp_irdrs_oficiais.jsonl", "TJSP — IRDR", "IRDR"),
    ("tjpr_nugep.jsonl", "TJPR — IRDR", "IRDR"),
    ("trf4_nugep.jsonl", "TRF4 — IRDR", "IRDR"),
    ("tjrs_nugep.jsonl", "TJRS — IRDR", "IRDR"),
    ("trf1_nugep.jsonl", "TRF1 — IRDR", "IRDR"),
    ("trf2_nugep.jsonl", "TRF2 — IRDR", "IRDR"),
    ("tjsc_nugep.jsonl", "TJSC — IRDR", "IRDR"),
    ("tjrj_nugep.jsonl", "TJRJ — precedente", "IRDR"),
    ("tjmg_nugep.jsonl", "TJMG — precedente", "IRDR"),
    ("iac_teses.jsonl", "IAC — tese", "IAC")]

def carregar_consolidacao() -> list[dict]:
    """Súmulas, teses de RG, temas repetitivos, IRDR e IAC. NUNCA passam por seleção."""
    docs = []

    def add(id_, fonte, tribunal, classe, numero, texto, orgao=""):
        texto = _limpa(texto)
        if len(texto) < 30:
            return
        # F4 · identificador nulo falha alto. As 799 súmulas do STF colapsaram em dois ids
        # porque o número vinha de um campo que a fonte não tem, e nada reclamou: o corpus
        # saiu com "Súmula None" em 716 linhas. Um identificador sem número não é um
        # documento, é um agrupamento acidental.
        if numero in (None, "", "None") or "None" in str(id_):
            raise SystemExit(f"identificador sem número em {fonte}: id={id_!r} numero={numero!r}")
        numero = numero_limpo(numero, classe, tribunal)
        rotulo = f"{classe} {numero}".strip()
        docs.append(dict(id=id_, fonte=fonte, tribunal=tribunal, classe=classe,
                         numero=str(numero or ""), processo=f"{rotulo} do {tribunal}".strip(),
                         relator="", orgao=orgao, data="", ementa=texto, texto=texto))

    # V3 · só entra o que está em vigor. "Alterada" permanece: a súmula vale na redação
    # nova. "Cancelada", "Superada" e "Publicação suspensa" não são direito vigente, e
    # ensiná-las é o equivalente a ensinar um dispositivo revogado.
    FORA_DE_VIGOR = {"Cancelada", "Superada", "Publicação suspensa"}
    for arq, fonte, classe in [("sumulas_vinculantes.jsonl", "STF — súmula vinculante", "Súmula Vinculante"),
                               ("sumulas_nao_vinculantes.jsonl", "STF — súmula", "Súmula")]:
        p = ROOT / "decisoes/stf" / arq
        if not p.exists():
            continue
        for l in open(p, errors="replace"):
            d = json.loads(l)
            if not _vig_entra(_vig_registro(d)):      # V5 · a mesma regra para todas as fontes
                continue
            # A fonte do STF chama o campo de `sumula_numero`; `numero` é o nome usado nas
            # fontes do STJ e do TJSP. Ler o errado era o defeito A5.
            numero = d.get("sumula_numero") or d.get("numero")
            add(f"BRUTO:STF:{classe.upper().replace(' ', '')}:{numero}", fonte, "STF",
                classe, numero, d.get("sumula_texto"))

    for l in open(ROOT / "decisoes/stj/sumulas_stj.jsonl", errors="replace"):
        d = json.loads(l)
        if not _vig_entra(_vig_registro(d)):          # V5
            continue
        add(f"BRUTO:STJ:SUM:{d.get('numero')}", "STJ — súmula", "STJ", "Súmula",
            d.get("numero"), d.get("texto"), d.get("orgao_julgador") or "")

    # C14 · O arquivo OFICIAL manda, e o antigo entra só pelo que ele não tiver. Os 1.007
    # temas que o corpus usava vinham de `informativos.trilhante.com.br`, um agregador
    # comercial: quatro campos, sem situação, sem órgão, sem questão submetida, e sem
    # garantia de fidelidade ao que a corte decidiu nem licença da fonte. O oficial traz
    # 1.416 temas, 1.133 com tese, e a situação escrita pelo próprio STJ — que é o que
    # permite excluir os 190 cancelados e os 154 ainda em julgamento por CAMPO (V5), e não
    # por leitura da prosa.
    vistos_tema = set()
    for arq, fonte_t in (("temas_stj_oficial.jsonl", "STJ — tema repetitivo"),
                         ("temas_stj.jsonl", "STJ — tema repetitivo")):
        p_t = ROOT / "decisoes/stj" / arq
        if not p_t.exists():
            continue
        for l in open(p_t, errors="replace"):
            d = json.loads(l)
            num = d.get("tema") or d.get("numero")
            if num in vistos_tema:
                continue
            if not _vig_entra(_vig_registro(d)):      # V5 · cancelado e pendente ficam fora
                continue
            tese = _limpa(d.get("tese"))
            if not tese_utilizavel(tese):
                continue
            vistos_tema.add(num)
            # A questão submetida só existe no oficial, e é ela que diz o que se perguntou.
            corpo = (f"[QUESTÃO] {_limpa(d.get('questao'))}\n[TESE FIXADA] {tese}"
                     if d.get("questao") else tese)
            add(f"BRUTO:STJ:TEMA:{num}", fonte_t, "STJ", "Tema repetitivo", num, corpo,
                _limpa(d.get("orgao")))

    # C12 · o IAC do STJ, da pesquisa de precedentes qualificados do proprio tribunal.
    p_iac = ROOT / "decisoes/stj/iac_stj_oficial.jsonl"
    if p_iac.exists():
        for l in open(p_iac, errors="replace"):
            d = json.loads(l)
            if not _vig_entra(_vig_registro(d)):      # V5
                continue
            tese = _limpa(d.get("tese"))
            if not tese_utilizavel(tese):
                continue
            corpo = (f"[QUESTÃO] {_limpa(d.get('questao'))}\n[TESE FIXADA] {tese}"
                     if d.get("questao") else tese)
            add(f"BRUTO:STJ:IAC:{d['numero']}", "STJ — IAC", "STJ", "IAC",
                d["numero"], corpo, _limpa(d.get("orgao")))

    p = ROOT / "decisoes/stf/repercussao_geral.jsonl"
    if p.exists():
        for l in open(p, errors="replace"):
            d = json.loads(l)
            tese = _limpa(d.get("tese"))
            if not tese_utilizavel(tese):
                continue
            # SEM TESE FIXADA = tema com repercussão reconhecida mas ainda NÃO JULGADO.
            # São 716 dos 2.000. Entram só título e descrição, ou seja, a PERGUNTA sem a
            # resposta — o modelo aprenderia a controvérsia como se fosse entendimento.
            if not tese:
                continue
            corpo = f"[QUESTÃO] {_limpa(d.get('titulo'))} {_limpa(d.get('descricao'))}\n[TESE FIXADA] {tese}"
            # `numero_tema` entra na cadeia de alternativas: os temas recoletados pela API
            # (C8) trazem número e tese mas não o campo `tema`, e sem isto a trava do F4
            # derrubava a montagem inteira com `BRUTO:STF:RG:None`. Foi ela que pegou.
            num_rg = d.get("tema") or d.get("numero_tema") or d.get("numero")
            add(f"BRUTO:STF:RG:{num_rg}", "STF — repercussão geral", "STF",
                "Tema de repercussão geral", num_rg, corpo)

    p = ROOT / "decisoes/tjsp/sumulas_tjsp.jsonl"
    if p.exists():
        for l in open(p, errors="replace"):
            d = json.loads(l)
            # V3/V5 · o estado vem do campo, como nas demais fontes. O TJSP publica um
            # consolidado só do que está em vigor — 89 súmulas numeradas de 1 a 89 sem
            # lacuna, e nenhuma marca de cancelamento no PDF oficial — então as 89 entram.
            # `pipeline/vigencia_tjsp.py` grava esse estado em vez de deixá-lo implícito.
            if not _vig_entra(_vig_registro(d)):
                continue
            add(f"BRUTO:TJSP:SUM:{d.get('numero')}", "TJSP — súmula", "TJSP", "Súmula",
                d.get("numero"), d.get("texto"))

    # C13 · O TJPR foi o unico dos dez tribunais cuja pagina de NUGEP responde por caminho
    # adivinhavel; o agregador nacional do CNJ (BNPR) esta em 503 e a pagina do Pangea em
    # 404. Os 60 incidentes vem com a vigencia lida da PAGINA de procedencia, entao o
    # filtro logo abaixo os le pelo campo em vez de tentar traduzir "TRANSITADO EM JULGADO".
    # C12 · `iac_teses.jsonl` e uma MISTURA, e foi isso que o item viu pela metade quando
    # anotou "sao do STJ, nao do TJSP": das 22 linhas, 16 sao IAC do STJ, 5 sao IAC do
    # TJSP — que tem numeracao propria, separada da do IRDR, e por isso o "Tema 1" de la
    # (Pinheirinho) nao e o tema 1 do `tjsp_irdrs_oficiais.jsonl` (garantia do FGC) — e 1
    # e um registro do STJ que nao casa nem com o IAC nem com o tema repetitivo de mesmo
    # numero. Cinco numeros apareciam DUAS vezes no arquivo, com teses diferentes, porque
    # as duas numeracoes colidiam num campo so.
    #
    # O lado do STJ passa a vir do arquivo oficial (22 IAC, 17 com tese, contra 16 aqui, e
    # com situacao, ramo e orgao); o lado do TJSP continua vindo daqui, que e onde ele
    # existe. O identificador ja carrega o tribunal desde o C13, entao os dois IAC 1 nao
    # disputam mais a mesma chave.
    for arq, fonte, classe_arq in FONTES_IRDR:
        p = ROOT / "decisoes/irdr_iac" / arq
        if not p.exists():
            continue
        for i, l in enumerate(open(p, errors="replace")):
            d = json.loads(l)
            tese = _limpa(d.get("tese"))
            # Não basta existir: precisa SER uma tese. Ver `tese_utilizavel`.
            if not tese_utilizavel(tese):
                continue
            # V1/V3 · o estado do incidente decide, e não a presença do texto. `revogado`
            # saiu de vigor; `admitido_pendente` ainda está em julgamento, e uma tese em
            # discussão não é entendimento firmado.
            if not _vig_entra(_vig_registro(d)):      # V5
                continue
            corpo = (f"[QUESTÃO] {_limpa(d.get('nome_tema'))} {_limpa(d.get('questao'))}\n"
                     f"[TESE FIXADA] {tese}")
            # O identificador carrega o TRIBUNAL, e nao so a classe e o numero. Sem isso
            # o IRDR 4 do TJSP e o IRDR 4 do TJPR disputam `BRUTO:IRDR:4` e um apaga o
            # outro — foi o que o F4 pegou no minuto em que o TJPR entrou. E a mesma raiz
            # do B1: numero sem tribunal nao identifica precedente nenhum.
            trib = (d.get("tribunal") or ("TJSP" if "TJSP" in fonte else "")).upper()
            # O arquivo do TJRJ traz os TRÊS tipos de precedente — IRDR, IAC e Grupo de
            # Representativos —, porque a busca do tribunal devolve os três juntos. A
            # classe sai do registro quando ele a declara, e do rótulo do arquivo quando
            # não: fixá-la pelo arquivo marcaria 26 IACs e GRs como IRDR.
            classe = (d.get("tipo") or classe_arq).upper()
            # O STJ deste arquivo e substituido pelo oficial, logo abaixo.
            if arq == "iac_teses.jsonl" and trib == "STJ":
                continue
            num = d.get("tema") or d.get("numero") or i
            # O rotulo diz o tribunal. "IAC — tese" servia aos dois e escondia justamente
            # a distincao que o C12 apontou: ha IAC do STJ e IAC do TJSP, com numeracoes
            # proprias, e quem le a fonte precisa saber de qual se trata.
            rot = f"{trib} — {classe}" if trib and "—" not in fonte.split()[0] else fonte
            add(f"BRUTO:{trib}:{classe}:{num}" if trib else f"BRUTO:{classe}:{num}",
                rot if classe == "IAC" else fonte, trib or "TJSP", classe, num, corpo)

    # C1 · registro oficial do Sistema de Gestão de Precedentes do STJ, em dados abertos.
    # Bloco próprio porque não é IRDR nem mora em `decisoes/irdr_iac/`. Cobre CINCO tipos, e
    # três deles — PUIL, SIRDR e Controvérsia — o corpus não tinha por nenhum outro caminho:
    # o crawler anterior trouxe 1.416 registros, todos de um tipo só.
    vistos_id = {d["id"] for d in docs}
    p_pq = ROOT / "decisoes/stj/precedentes_qualificados.jsonl"
    if p_pq.exists():
        for l in open(p_pq, errors="replace"):
            d = json.loads(l)
            tese = _limpa(d.get("tese"))
            if not tese_utilizavel(tese):
                continue
            if not _vig_entra(_vig_registro(d)):                  # V5
                continue
            tipo = (d.get("tipo") or "TEMA").upper().replace("Ó", "O")
            num = d.get("numero") or ""
            ident = f"BRUTO:STJ:{tipo}:{num}"
            # O registro oficial REPETE os temas repetitivos que já entram por
            # `temas_stj_oficial.jsonl`, e com o mesmo identificador: dos 1.159 Temas com
            # tese, só 46 são novos. Sem esta guarda entravam 1.141 duplicatas e o F4
            # reprovava. O que este conjunto acrescenta de fato são os TIPOS que faltavam —
            # PUIL, SIRDR e Controvérsia — mais os 46 temas que a outra coleta não tinha.
            if ident in vistos_id:
                continue
            vistos_id.add(ident)
            corpo = (f"[QUESTÃO] {_limpa(d.get('questao'))}\n[TESE FIXADA] {tese}")
            add(ident, f"STJ — {d.get('tipo')}", "STJ", tipo, num, corpo)

    return docs


def carregar_tjsp(grau: str) -> list[dict]:
    """Acórdãos do TJSP. O CSV local já traz o CONTEÚDO INTEGRAL da decisão — não é
    extrato, ao contrário do que o crawler das superiores havia guardado.

    2º grau: 21.353 decisões, 97% com ementa (que vira o resumo do cabeçalho).
    1º grau: 5.778 sentenças, SEM ementa — o resumo tem de ser gerado (ver
    `pipeline/resume_sentencas_tjsp.py`), e só para as selecionadas.
    """
    p = ROOT / "decisoes/tjsp" / f"tjsp_{grau}.csv"
    if not p.exists():
        return []
    csv.field_size_limit(sys.maxsize)
    docs = []
    with open(p, encoding="utf-8", errors="replace") as f:
        for i, row in enumerate(csv.DictReader(f)):
            corpo = _tira_ruido_tjsp(_limpa(row.get("conteudo")))
            if len(corpo) < 200:
                continue
            nup = (row.get("nup") or "").strip()
            classe = _limpa(row.get("classe"))
            docs.append(dict(
                id=f"BRUTO:TJSP:{grau}:{nup or i}", fonte=f"TJSP — {grau.replace('_', 'º ')}",
                tribunal="TJSP", classe=classe, numero=nup, processo=nup or f"{classe} {i}",
                relator=_limpa(row.get("magistrado")),
                orgao=_limpa(row.get("orgao_julgador")) or _limpa(row.get("vara")),
                data=_limpa(row.get("data_julgamento")) or _limpa(row.get("data_publicacao")),
                ementa=_limpa(row.get("ementa")), texto=corpo,
                assunto=_limpa(row.get("assunto")), comarca=_limpa(row.get("comarca"))))
    return docs


def elegivel(d: dict) -> bool:
    t = d["texto"]
    if len(t) < 200:
        return False
    # Acórdão do STF cujo texto é só o cabeçalho processual não tem questão de direito
    return not (len(CAB_RE.findall(t[:1500])) >= 2 and not SUBST_RE.search(t))


def _topicos(textos: list[str], metodo: str, k: int):
    """Devolve o rótulo de tópico de cada documento. -1 = não coube em tópico nenhum.

    Comparação medida em 18/08/2026 sobre os 10.178 acórdãos elegíveis, no espaço de
    embeddings (neutro para os três métodos):

        método               tópicos  coesão  silhueta   seleciona
        LSA + k-means K=800      800   0,857    -0,159       3.434
        BERTopic                 193   0,901     0,056         844 (+4.371 outliers)
        Top2Vec                  149   0,818    -0,090         655

    BERTopic vence nas duas medidas de qualidade e é a única com silhueta positiva —
    o k-means com K=800 força fronteiras onde não há. Por isso é o padrão.
    """
    if metodo == "bertopic":
        from bertopic import BERTopic
        from sentence_transformers import SentenceTransformer
        from umap import UMAP
        import time as _t
        modelo = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
        # A fase de tópicos era a última cega da montagem. Com 558 mil acórdãos do DJe ela
        # deixou de ser questão de minutos, e sem relato não há como distinguir "demorando"
        # de "presa" — o mesmo problema que a deduplicação tinha, e que já custou uma
        # espera de cinquenta minutos no escuro.
        _t0 = _t.time()
        print(f"    tópicos · embeddings de {len(textos):,} textos...", flush=True)
        E = modelo.encode([t[:1500] for t in textos], batch_size=64, convert_to_numpy=True,
                          show_progress_bar=len(textos) > 50_000)
        print(f"    tópicos · embeddings em {(_t.time()-_t0)/60:.0f} min · "
              f"UMAP e HDBSCAN agora (esta parte não relata progresso)", flush=True)
        # random_state fixo no UMAP: sem ele o BERTopic é estocástico e o mesmo comando
        # devolvia 5.425 acórdãos numa rodada e 5.089 na seguinte. Para dissertação, o
        # corpus precisa ser reprodutível.
        umap = UMAP(n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42)
        rot, _ = BERTopic(language="multilingual", calculate_probabilities=False, min_topic_size=8,
                          umap_model=umap).fit_transform([t[:1500] for t in textos], embeddings=E)
        return list(rot)
    if metodo == "top2vec":
        from top2vec import Top2Vec
        m = Top2Vec(documents=[t[:1500] for t in textos], speed="learn", workers=8, min_count=10)
        return list(m.doc_top)
    from sklearn.decomposition import TruncatedSVD
    from sklearn.preprocessing import Normalizer
    from sklearn.pipeline import make_pipeline
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer
    X = TfidfVectorizer(max_features=60000, ngram_range=(1, 2), min_df=5, max_df=0.35,
                        sublinear_tf=True, strip_accents="unicode", stop_words=STOP).fit_transform(textos)
    Z = make_pipeline(TruncatedSVD(200, random_state=42), Normalizer(copy=False)).fit_transform(X)
    return list(KMeans(n_clusters=k, random_state=42, n_init=3).fit_predict(Z))


def selecionar_por_copia(docs: list[dict], limiar: float = 0.85,
                         m_termos: int = 20, teto_df: int = 2000) -> list[int]:
    """Entra tudo, MENOS o que for quase-cópia de algo que já entrou.

    Substitui a regra antiga, que decidia por tópico, e a razão é que aquela regra não era
    um critério. Na montagem de 19/09, **229.181 dos 338.280 documentos selecionados
    entraram só por serem outliers do HDBSCAN** — ou seja, o tamanho e a composição do corpus
    eram efeito colateral da densidade do agrupamento. Do outro lado, `por_cluster=5` jogava
    fora nuance: um tópico com 500 casos distintos contribuía com cinco. A regra nova tem um
    botão só, e ele significa alguma coisa.

    COMO SE MEDE "cópia", e por que não é por embedding nem por shingle. Medido em 50.000
    monocráticas, com os pares inspecionados um a um:

      · **embedding** vê assunto e gênero e é cego a nome, número e valor. Os pares acima de
        0,99 eram CASOS DISTINTOS com o mesmo molde — dois agravos do INSS de tribunais
        diferentes, dois habeas corpus de réus, crimes e penas diferentes. Pior: como
        RECUPERAÇÃO ele também falha, porque há centenas de documentos igualmente próximos e
        o gêmeo verdadeiro não se destaca — 61% de recall com 20 vizinhos, 79% com 50;
      · **shingle** de 10 tokens vê a literalidade, e decisão em série com o nome trocado
        quebra janelas suficientes para cair a 0,48 e escapar do corte de 0,8. Dos 148.574
        pares candidatos do experimento, um ÚNICO passava de 0,8 — a camada lexical que já
        roda em `dedup_dje.py` está esgotada;
      · **TF-IDF** pesa cada termo pelo inverso da frequência: a fórmula está em tudo e pesa
        pouco, o que é do caso é raro e pesa muito. Foi o único que separou. O par decisivo
        são dois AREsp da CREFISA com shingle de 0,48 e TF-IDF de 1,00.

    O limiar 0,85 é decisão do pesquisador em 19/09, tomada com os pares na mão: em
    0,70–0,75 os pares eram casos diferentes (INPI contra DEXCO); em 0,85–0,90 eram produção
    em série com só o nome mudando (dois REsp do INSS sobre o mesmo ponto).

    A BUSCA é por índice invertido sobre os `m_termos` de maior peso de cada documento, que
    são justamente os do caso. Medido: **100% de recall** contra a busca exaustiva, tanto em
    10.000 quanto em 50.000 documentos, com 40 s contra 265 s no segundo caso. Um banco
    vetorial ao lado não acrescenta nada — o método já está no teto —, e por isso não entra.

    A ORDEM é fixada e declarada, porque a regra é gulosa e o resultado depende dela: por
    DATA, do mais antigo para o mais novo, de modo que a decisão original fique e as cópias
    posteriores saiam. Sem isso o corpus não é reconstruível, que é a lição do N18.
    """
    import collections

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    ordem = sorted(range(len(docs)),
                   key=lambda i: (str(docs[i].get("data") or ""), str(docs[i].get("id") or "")))
    # GERADOR e não lista: 650 mil recortes de 6.000 caracteres são ~3,9 GB parados só para
    # serem consumidos uma vez. E `float32` em vez do `float64` padrão, que com 860 termos
    # por documento é a diferença entre 6,7 e 3,4 GB só na matriz.
    def _corpus():
        for i in ordem:
            yield (docs[i].get("texto") or docs[i].get("ementa") or "")[:6000]

    X = normalize(TfidfVectorizer(max_features=200_000, ngram_range=(1, 2), min_df=3,
                                  sublinear_tf=True, strip_accents="unicode",
                                  dtype=np.float32).fit_transform(_corpus()),
                  copy=False).tocsr()
    topo = []
    for r in range(X.shape[0]):
        a, b = X.indptr[r], X.indptr[r + 1]
        idx, val = X.indices[a:b], X.data[a:b]
        topo.append(idx[np.argsort(-val)[:m_termos]] if len(idx) > m_termos else idx)

    inv: dict[int, list[int]] = collections.defaultdict(list)
    df: collections.Counter = collections.Counter()
    fica: list[int] = []
    t0, prox = _t.time(), 60.0
    for r in range(X.shape[0]):
        if _t.time() - t0 > prox:
            _dt = _t.time() - t0
            print(f"    cópia {r:,}/{X.shape[0]:,} ({r/X.shape[0]:.0%}) · ficam {len(fica):,} "
                  f"· faltam ~{_dt*(X.shape[0]-r)/max(1,r)/60:.0f} min", flush=True)
            prox += 60.0
        cand: set[int] = set()
        for t in topo[r]:
            if df[t] <= teto_df:
                cand.update(inv[t])
        if cand:
            cs = np.fromiter(cand, dtype=np.int64)
            if np.asarray((X[r] @ X[cs].T).todense()).ravel().max() >= limiar:
                continue
        # Só quem FICA entra no índice: o descartado não serve de representante, e mantê-lo
        # fora encurta as listas de postagem, que é o que domina o custo.
        for t in topo[r]:
            inv[t].append(r)
            df[t] += 1
        fica.append(r)
    print(f"  quase-cópia (TF-IDF ≥ {limiar}): {len(docs):,} → {len(fica):,} "
          f"({1-len(fica)/max(1,len(docs)):.1%} fora) · {_t.time()-t0:.0f}s", flush=True)
    return sorted(ordem[r] for r in fica)


def selecionar(docs: list[dict], k: int, por_cluster: int, limiar: float, metodo: str = "bertopic"):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    textos = [(d["ementa"] or d["texto"])[:4000] for d in docs]
    X = TfidfVectorizer(max_features=60000, ngram_range=(1, 2), min_df=5, max_df=0.35,
                        sublinear_tf=True, strip_accents="unicode", stop_words=STOP).fit_transform(textos)
    lab = _topicos(textos, metodo, k)

    escolhidos, avaliados = [], 0
    porc = {}
    for i, c in enumerate(lab):
        porc.setdefault(int(c), []).append(i)
    # Documento que não coube em tópico nenhum (-1) é o caso singular por definição:
    # entra INTEIRO, sem teto. Amostramos e são ementas completas, não ruído — mediana
    # de 2.577 chars contra 2.534 dos agrupados.
    escolhidos += porc.pop(-1, [])
    for c, idx in porc.items():
        idx = idx[:por_cluster]
        avaliados += len(idx)
        S = cosine_similarity(X[idx])
        mant = []
        for a in range(len(idx)):
            if all(S[a][b] < limiar for b in mant):
                mant.append(a)
        escolhidos += [idx[a] for a in mant]
    return escolhidos, lab, avaliados


_RESUMOS_SENTENCA = None


def resumo_de(d: dict) -> str:
    """Ementa oficial quando existe; senão o DISPOSITIVO, que é literal; senão o gerado."""
    global _RESUMOS_SENTENCA
    if d["ementa"]:
        return d["ementa"][:1200]
    disp = _dispositivo(d["texto"])
    if disp:
        return disp
    if _RESUMOS_SENTENCA is None:
        p = ROOT / "data/juris_bruto/resumos_sentencas_tjsp.json"
        _RESUMOS_SENTENCA = json.loads(p.read_text("utf-8")) if p.exists() else {}
    gerado = _RESUMOS_SENTENCA.get(d["id"])
    if gerado:
        return gerado[:1200]
    corte = d["texto"][:1200]
    ponto = corte.rfind(". ")
    return corte[:ponto + 1] if ponto > 300 else corte


def cabecalho(d: dict) -> str:
    ident = " · ".join(x for x in [
        d["processo"] or f"{d['classe']} {d['numero']}".strip(),
        d["tribunal"] + (f" ({d['orgao']})" if d["orgao"] else ""),
        f"Rel. {d['relator']}" if d["relator"] else "",
        f"j. {d['data']}" if d["data"] else "",
    ] if x)
    return (f"<<JURIS|BRUTO|{d['tribunal']}|{d['processo'] or d['id']}>>\n"
            f"[DECISÃO] {ident}\n"
            f"[RESUMO DA DECISÃO] {resumo_de(d)}")



def sem_repetir_resumo(d: dict) -> str:
    """O texto a partir de onde o resumo termina.

    B3 · A ementa de um acórdão É o começo do acórdão, e `resumo_de` devolve os primeiros
    1.200 caracteres quando não há ementa. Nos dois casos o bloco `[RESUMO DA DECISÃO]` e o
    começo de `[TEXTO — parte 1/N]` eram o mesmo parágrafo, literal. Medido no corpus
    atual: 5.277 documentos, 4,79 M caracteres, cerca de 1,20 M tokens gastos repetindo.

    O resumo fica, porque é o trecho ROTULADO e é ele que ensina o que é uma ementa; o que
    sai é a segunda cópia. Se nada sobra, o documento era só o resumo, e é o que se grava.
    """
    resumo, texto = resumo_de(d).strip(), d["texto"].lstrip()
    n = 0
    while n < min(len(resumo), len(texto)) and resumo[n] == texto[n]:
        n += 1
    # Exige que o resumo seja quase todo prefixo do texto: um resumo que apenas COMEÇA
    # igual, e depois diverge, é conteúdo distinto e fica.
    if n >= 200 and n >= 0.9 * len(resumo):
        restante = texto[n:].lstrip(" .;:\n\t")
        return restante if len(restante) >= 200 else ""
    return d["texto"]

def partir(texto: str, alvo: int) -> list[str]:
    if len(texto) <= alvo:
        return [texto]
    partes, atual = [], ""
    for frase in re.split(r"(?<=[.;:])\s+", texto):
        if atual and len(atual) + len(frase) > alvo:
            partes.append(atual.strip())
            atual = ""
        atual += frase + " "
    if atual.strip():
        partes.append(atual.strip())
    return partes


def _grava(out, d: dict, seq: int) -> int:
    """Escreve os chunks de UMA decisão e devolve quantos foram.

    Era o laço final da montagem, sobre a lista inteira do que foi selecionado. Virou função
    porque a regra de seleção nova faz entrar quase tudo: com a antiga eram 338 mil decisões
    acumuladas em memória antes da primeira linha ser gravada, com a nova seriam ~950 mil, e
    isso é cerca de 10 GB de texto parado esperando o fim. Agora cada acervo é gravado assim
    que é escolhido e liberado em seguida.

    O `seq` é sufixo sequencial: decisões distintas do MESMO processo (ex.: acórdão e
    embargos) geravam id igual e colidiam, o que atrapalharia qualquer dedup posterior.
    """
    cab = cabecalho(d)
    corpo = sem_repetir_resumo(d)
    comum = {"categoria": f"Jurisprudência bruta — {d['tribunal']}",
             "proveniencia": "semi_bruto", "fonte_arquivo": d["fonte"],
             "titulo": d["processo"] or d["id"], "licenca": "obra_publica_gov", "url": ""}
    if not corpo:
        # O documento é só o resumo: súmula, tese e verbete têm ementa igual ao texto.
        # Repetir o mesmo parágrafo sob dois rótulos ensina a repetir.
        out.write(json.dumps({"id": f"{d['id']}~{seq}#0", **comum, "chunk_ix": 0,
                              "n_chunks": 1, "n_chars": len(cab), "text": cab},
                             ensure_ascii=False) + "\n")
        return 1
    partes = partir(corpo, ALVO_CHARS)
    for k, pt in enumerate(partes):
        texto = f"{cab}\n[TEXTO — parte {k+1}/{len(partes)}]\n{pt}"
        out.write(json.dumps({"id": f"{d['id']}~{seq}#{k}", **comum, "chunk_ix": k,
                              "n_chunks": len(partes), "n_chars": len(texto), "text": texto},
                             ensure_ascii=False) + "\n")
    return len(partes)


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta a jurisprudência bruta padronizada.")
    ap.add_argument("--k", type=int, default=800)
    ap.add_argument("--por-cluster", type=int, default=5)
    ap.add_argument("--limiar", type=float, default=0.6)
    ap.add_argument("--metodo", default="bertopic", choices=["bertopic", "top2vec", "lsa"])
    # A REGRA DE SELEÇÃO, trocada em 19/09. `topico` é a antiga, que decidia por agrupamento
    # e cujo número dominante era o de outliers do HDBSCAN entrando inteiros — 229.181 de
    # 338.280 na última montagem com ela. `copia` é a nova: entra tudo menos quase-cópia,
    # medida por TF-IDF, com o limiar auditado par a par. A antiga fica disponível porque o
    # corpus do experimento das 162 condições foi montado com ela e tem de ser reprodutível.
    ap.add_argument("--selecao", default="copia", choices=["copia", "topico"],
                    help="como escolher o que entra (ver selecionar_por_copia)")
    ap.add_argument("--limiar-copia", type=float, default=0.85,
                    help="TF-IDF acima disto é quase-cópia e não entra (G3, decidido em 19/09)")
    # G1 · o default era `2_grau`, e com ele as 5.778 sentenças de 1º grau ficaram em disco
    # desde fevereiro sem entrar em lugar nenhum. É o ÚNICO material de primeiro grau do
    # corpus — todo o resto é recursal, e a sentença é exatamente o que a peça ataca.
    ap.add_argument("--tjsp", default="ambos", choices=["nenhum", "2_grau", "1_grau", "ambos"],
                    help="quais decisões do TJSP incluir (cada grau tem espaço de tópicos próprio)")
    # G2 · quanto de monocrática entra. Zero é o default porque o acervo é maior que tudo o
    # mais junto e a escolha é de composição: ver `carregar_monocraticas`.
    # G2b · decisão do pesquisador em 18/09/2026: entram **300.000**. A sequência de
    # números que a sustenta: a seleção por tópicos guarda ~40% do que recebe (medido em
    # amostras de 5 a 40 mil, com 28% a 33% caindo como singulares que entram inteiros), a
    # mediana da monocrática é ~10 mil caracteres, então 300 mil sorteadas viram ~120 mil
    # selecionadas e ~1,2 G de caracteres — cerca de 75% a mais que o corpus de treino
    # inteiro de hoje, que tem 1,6 GB. Deixa a monocrática em ~35% dos documentos do STJ
    # que entram na seleção, ou seja, o colegiado segue dominante: o mérito continua
    # pesando mais que a admissibilidade, que é o que a medição de teor dizia ser a divisão
    # natural entre os dois. E é o maior volume que roda numa passada só em 24 GB — acima
    # disso a montagem teria de ser feita em lotes, com o espaço de tópicos partido.
    ap.add_argument("--monocraticas", type=int, default=0,
                    help="teto de decisões monocráticas do STJ a sortear (0 = nenhuma; "
                         "300000 é a composição decidida no G2b)")
    args = ap.parse_args()

    consolidacao = carregar_consolidacao()
    print(f"consolidação (súmulas, teses, temas, IRDR/IAC): {len(consolidacao)} — TODA preservada")

    # Cada acervo é agrupado no SEU espaço de tópicos: junto, o TJSP (21 mil decisões
    # longas e repetitivas) dominaria os clusters e afogaria as superiores.
    #
    # Os acervos entram como FUNÇÃO, não como lista já carregada, e a diferença é de vários
    # gigabytes. Carregados de uma vez, todos ficam em memória enquanto o primeiro é
    # processado — e o primeiro é o mais pesado: 558 mil acórdãos do DJe, ~7,5 G de
    # caracteres. Assim cada acervo é lido na sua vez e liberado ao fim dela.
    acervos = [("superiores", carregar_acordaos)]
    if args.tjsp in ("2_grau", "ambos"):
        acervos.append(("TJSP 2º grau", lambda: carregar_tjsp("2_grau")))
    if args.tjsp in ("1_grau", "ambos"):
        acervos.append(("TJSP 1º grau", lambda: carregar_tjsp("1_grau")))
    # Espaço de tópicos PRÓPRIO, pelo mesmo argumento que separa o TJSP: a monocrática é
    # outro gênero — é onde mora a admissibilidade — e junto com o acórdão ela dominaria os
    # agrupamentos pelo volume, afogando o mérito do colegiado.
    if args.monocraticas:
        acervos.append(("STJ monocráticas", lambda: carregar_monocraticas(args.monocraticas)))

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    n_chunks = seq = n_sel = 0
    with open(SAIDA, "w", encoding="utf-8") as out:
        for d in consolidacao:
            n_chunks += _grava(out, d, seq)
            seq += 1
            n_sel += 1
        del consolidacao
        for nome, carrega in acervos:
            acervo = carrega()
            if not acervo:
                continue
            elig = [d for d in acervo if elegivel(d)]
            # O acervo já foi peneirado para `elig`; segurar as duas listas dobra o texto em
            # memória sem servir a ninguém.
            n_disco = len(acervo)
            del acervo
            if args.selecao == "copia":
                escolhidos = selecionar_por_copia(elig, args.limiar_copia)
                print(f"{nome}: {n_disco} em disco | {len(elig)} elegíveis "
                      f"| selecionados: {len(escolhidos)}", flush=True)
            else:
                escolhidos, lab, _ = selecionar(elig, args.k, args.por_cluster,
                                                args.limiar, args.metodo)
                n_top = len({int(c) for c in lab if int(c) != -1})
                # O número que decide o tamanho do corpus é o de SEM TÓPICO: eles entram
                # inteiros, sem teto, por serem singulares por definição.
                _fora = sum(1 for c in lab if int(c) == -1)
                print(f"  {nome}: {_fora:,} sem tópico entram INTEIROS "
                      f"({_fora/max(1,len(lab)):.0%} dos elegíveis) + até {n_top} tópicos "
                      f"× {args.por_cluster}", flush=True)
                print(f"{nome}: {n_disco} em disco | {len(elig)} elegíveis | {n_top} tópicos "
                      f"| selecionados: {len(escolhidos)}", flush=True)
            for i in escolhidos:
                n_chunks += _grava(out, elig[i], seq)
                seq += 1
                n_sel += 1
            del elig
    print(f"TOTAL a padronizar: {n_sel}")
    print(f"✓ {n_sel} decisões → {n_chunks} chunks em {SAIDA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
