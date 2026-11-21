#!/usr/bin/env python3
"""
rechunk_v4.py — Monta o corpus v4 com chunks de comprimento UNIFORME.

Por que uniforme importa (descoberto em 18/08/2026): o `iterate_batches` do mlx-lm
ORDENA o dataset inteiro por comprimento antes de formar os batches. No corpus atual
o comprimento é quase sinônimo de origem — jurisprudência bruta ~700-1.300 tokens,
card de lei ~1.550, doutrina ~2.000 — então cada batch saía de uma fonte só, e o
modelo nunca via os gêneros misturados num mesmo passo de gradiente. O resultado é
deriva de distribuição: a validação (mista) piora quando o embaralhamento encadeia
batches de um gênero só. Duas rodadas da ablação de rank produziram curvas de forma
IDÊNTICA, o que denunciou o artefato — não era overfitting.

Com todos os chunks numa faixa estreita, a ordenação por comprimento deixa de separar
por origem. E resolve de quebra o outro problema: 100% dos cards ricos de jurisprudência
estouravam os 2.048 do treino, perdendo 30% do texto, justamente os blocos finais de
pergunta e resposta.

Regras de corte:
  * cards (lei, jurisprudência rica, OAB) quebram na fronteira de bloco `<<ID=...>>`,
    repetindo o bloco de identificação em cada parte;
  * texto corrido (doutrina, jurisprudência bruta) quebra em parágrafo, repetindo o
    cabeçalho — o desenho semi-bruto que já vinha sendo usado;
  * held-out nunca entra.

Saída: data/pretrain_v4/{train,valid}.jsonl
"""
from __future__ import annotations

import argparse, collections, json, random, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUG = ROOT / "augmentation" / "output"
SAIDA = ROOT / "data" / "pretrain_v4"
_RX_ID_FICHA = re.compile(r"<<ID=([^|]+)\|")     # Q6
_IDX_DATA: dict = {}
_IDX_INF: dict = {}
_IDX_TESE: dict = {}
_RX_CONTEUDO = re.compile(r"\[CONTEÚDO\]\s*(.*?)(?=\n\[|\n<<|\Z)", re.S)


def _revogado(texto: str) -> bool:
    """O corpo do artigo É a nota de revogação, e não apenas a contém."""
    from expand_normas import revogado_por_inteiro
    m = _RX_CONTEUDO.search(texto)
    return revogado_por_inteiro(m.group(1).strip()) if m else False

ALVO_TOK, MIN_TOK, MAX_TOK = 1650, 1200, 1950   # faixa estreita: mediana ~1.650

FONTES = [
    # (arquivo, categoria, campo, tipo_de_corte)
    (AUG / "cf88_expandida.jsonl",           "CF88",                  "expansao", "bloco"),
    (AUG / "codigos_expandidos.jsonl",       "Código",                "expansao", "bloco"),
    (AUG / "leis_federais_expandidas.jsonl", "Lei Federal",           "expansao", "bloco"),
    (AUG / "leis_sp_expandidas.jsonl",       "Lei Estadual SP",       "expansao", "bloco"),
    (AUG / "sumulas_stf_rica.jsonl",         "Súmula STF (rico)",     "expansao", "bloco"),
    (AUG / "temas_stj_rica.jsonl",           "Tema STJ (rico)",       "expansao", "bloco"),
    (AUG / "rg_stf_rica.jsonl",              "RG STF (rico)",         "expansao", "bloco"),
    (AUG / "stf_acordaos_rica.jsonl",        "Acórdão STF (rico)",    "expansao", "bloco"),
    # B2 · NÃO é acórdão: 4.142 dos 4.195 registros trazem `tipo` = "Nota de
    # Informativo STJ" no próprio arquivo, e todos os 4.195 têm `juris_id` começando
    # em JURIS:STJ:INFJ. É a expansão das notas de informativo, o mesmo material que
    # o braço bruto traz como "STJ — informativo".
    (AUG / "stj_acordaos_rica.jsonl",        "Nota de informativo STJ (rico)", "expansao", "bloco"),
    (AUG / "casos_tjsp_expandidos.jsonl",    "Caso TJSP",             "expansao", "bloco"),
    (ROOT / "data/juris_bruto/juris_bruto_chunks.jsonl", "Jurisprudência bruta", "text", "prosa"),
    (ROOT / "data/doutrina/doutrina_chunks_enriquecido.jsonl", "Doutrina", "text", "prosa"),
    # A ESCADA DA OAB em formato de bloco (oab_para_cpt.py). O `CLAUDE.md` descreve isso
    # como etapa de pré-treino desde o início e nunca tinha sido implementado — o material
    # da OAB só existia como chat, que serve ao fine-tuning. Em bloco, o modelo aprende o
    # REGISTRO da tarefa (como um enunciado de peça se encadeia com a peça), não a
    # responder quando interpelado. Faltava também `oab_1fase_expandida` no v4: o v3 tinha
    # 531 chunks dela e eu os perdi ao reescrever este script do zero.
    (ROOT / "data/oab_cpt/oab_blocos.jsonl", "OAB (escada I-III)", "text", "bloco"),
    # Enunciados (TST, Jornadas CJF, FONAJE, FPPC), UM VERBETE POR DOCUMENTO.
    #
    # Antes vinha `enunciados_blocos.jsonl`, que é o LIVRO fatiado em pedaços de tamanho
    # fixo: 2.637 blocos dos quais só 166 traziam número identificável, nenhum começava num
    # limite de verbete, e o primeiro do TST era a ficha catalográfica da publicação. A
    # extração por verbete já existia ao lado e não era usada.
    #
    # A troca fecha o C15 e o B5, e alinha o pareamento (D4): as fichas do expandido saem
    # de `enunciados.jsonl`, e agora o bruto sai da mesma lista.
    (ROOT / "data/enunciados/enunciados_bruto.jsonl", "Enunciado (bruto)", "text", "bloco"),
    # Cards dos enunciados, ROTEADOS POR NATUREZA JURÍDICA. Súmula e OJ do TST são
    # consolidação da jurisprudência do tribunal, com autoridade institucional; enunciado
    # de jornada/FONAJE/FPPC é doutrina qualificada, persuasiva. Tratar igual ensinaria o
    # modelo a afirmar como obrigatório o que é opinião — daí duas categorias distintas.
    (ROOT / "data/enunciados/cards_tst.jsonl", "Súmula/OJ TST (card)", "text", "bloco"),
    (ROOT / "data/enunciados/cards_doutrinarios.jsonl", "Enunciado doutrinário (card)", "text", "bloco"),
]

MARCADOR = re.compile(r"(?=<<ID=)")

# Súmula, tese de repercussão geral, tema repetitivo, IRDR e IAC são CURTOS por
# natureza (300-600 tokens). O filtro de "sobra pequena" descartava justamente essa
# consolidação — que é a parte que o pesquisador mandou preservar inteira.
CONSOLIDACAO = re.compile(r"súmula|repercussão geral|tema repetitivo|IRDR|IAC", re.I)
# Questão de 1ª fase tem ~365 tokens e dissertativa ~666: ambas caem abaixo do mínimo de
# sobra e eram descartadas em massa (560 de 560 no nível I, 802 de 1.295 no nível II).
# Item curto POR NATUREZA não é sobra de quebra — mesmo caso da consolidação.
# `enunciado` entrou aqui depois de uma perda medida: dos 4.169 verbetes, só 31 chegavam
# ao corpus — 99% caíam no piso de tamanho. A causa é encadeada e vale registrar, porque a
# origem é uma CORREÇÃO: o C15 trocou `enunciados_blocos.jsonl`, que era o livro fatiado em
# pedaços grandes, por `enunciados_bruto.jsonl`, um verbete por documento. Certo do ponto de
# vista de identidade — e, do ponto de vista do fatiador, cada documento virou 378 caracteres
# e ~113 tokens, abaixo dos 720 que o corte exige. A isenção existe exatamente para material
# curto POR NATUREZA, e o verbete é o caso mais claro disso: súmula e enunciado são a mesma
# forma de texto. Estar de fora da lista era esquecimento, não desenho.
CURTO_POR_NATUREZA = re.compile(
    r"súmula|repercussão geral|tema repetitivo|IRDR|IAC|OAB|enunciado", re.I)
# Medido junto com o N11, na mesma auditoria: o piso de tamanho também derruba metade do
# espelho de acórdão (57% do texto chega) e do informativo do STF (56%). Os dois são
# DIGESTO — o espelho tem mediana de 1,7 mil caracteres e a nota de informativo ~3 mil,
# ambos abaixo dos ~2,4 mil que o corte exige. É a mesma natureza da súmula: texto curto
# porque a forma é curta, não porque ficou faltando pedaço.
CURTO_POR_FONTE = re.compile(r"espelho|informativo", re.I)


def eh_consolidacao(texto: str, categoria: str, fonte: str = "") -> bool:
    return (bool(CURTO_POR_NATUREZA.search(categoria))
            or bool(CURTO_POR_FONTE.search(fonte))
            or bool(CONSOLIDACAO.search(texto[:200])))


# ── N13 · A RESERVA DE JURISPRUDÊNCIA FOI ABANDONADA (decisão do pesquisador, 18/09/2026)
#
# Havia 1.360 casos reservados em `data/holdout/holdout_test_ids.json`, com a intenção
# declarada de "nunca entram no CPT". A reserva era incoerente e, apurada, desnecessária:
#
#  · INCOERENTE: o filtro excluía por `juris_id`, campo que só existe nos arquivos de
#    EXPANSÃO. O braço bruto usa `id`, então a ficha do caso reservado era barrada e o
#    acórdão inteiro do mesmo caso entrava pela porta da frente. Barrava e deixava passar;
#  · DESNECESSÁRIA: **nada avalia sobre esses casos**. As nove referências de `avaliacao/`
#    apontam para `data/oab/benchmark.jsonl`, e o benchmark da OAB é feito de questões de
#    prova, não de julgados — não há sobreposição a proteger. Os únicos consumidores do
#    arquivo de reserva eram estes dois construtores, que dele só sabiam excluir.
#
# Manter custava ~34 M de caracteres (14,66 M já medidos no v4 e 19,68 M que a coleta nova
# do DJe trouxe) em troca de um rigor aparente. O artigo declara que a avaliação é o
# benchmark da OAB e que não há holdout de jurisprudência.
#
# Os arquivos FICAM em `data/holdout/`, junto com `mapa_holdout.json`, que reconstrói o elo
# ficha→julgado para 1.268 dos 1.360. Se a avaliação "dado o julgado, produza a ficha" for
# adiante, tudo que é preciso para religar a reserva está preservado — o que se removeu foi
# o filtro, não a informação.
def holdout() -> set:
    return set()


def fator(textos: list[str], tok) -> float:
    """tokens por char, medido por categoria — varia de 0,219 na doutrina a 0,283 nos cards."""
    am = textos[:120]
    return sum(len(tok(t).input_ids) for t in am) / max(sum(len(t) for t in am), 1)


def parte_por_bloco(texto: str, alvo_chars: int) -> list[str]:
    """Quebra na fronteira <<ID=...>>, repetindo o primeiro bloco como identificação."""
    blocos = [b for b in MARCADOR.split(texto) if b.strip()]
    if not blocos:
        return [texto]
    cabeca = blocos[0].strip()
    if len(texto) <= alvo_chars:
        return [texto]
    partes, atual = [], ""
    for b in blocos:
        if atual and len(atual) + len(b) > alvo_chars:
            partes.append(atual.strip())
            atual = cabeca + "\n\n" if b is not blocos[0] else ""
        atual += b
    if atual.strip() and atual.strip() != cabeca:
        partes.append(atual.strip())
    return partes or [texto]


def parte_por_prosa(texto: str, alvo_chars: int) -> list[str]:
    """Quebra em parágrafo, repetindo o cabeçalho (linhas antes do corpo)."""
    if len(texto) <= alvo_chars:
        return [texto]
    linhas = texto.split("\n")
    corte = 0
    for i, l in enumerate(linhas[:12]):
        if l.startswith("[TEXTO") or l.startswith("[CONTEÚDO"):
            corte = i + 1
            break
    cabeca = "\n".join(linhas[:corte]).strip()
    corpo = "\n".join(linhas[corte:])
    orc = max(alvo_chars - len(cabeca) - 40, 800)
    partes, atual = [], ""
    for par in re.split(r"\n\s*\n", corpo):
        if atual and len(atual) + len(par) > orc:
            partes.append(atual.strip())
            atual = ""
        atual += par + "\n\n"
    if atual.strip():
        partes.append(atual.strip())
    return [f"{cabeca}\n{p}" if cabeca else p for p in partes] or [texto]


def inteiro_teor_stf() -> dict:
    """doc_id -> inteiro teor. Baixado por baixa_inteiro_teor_stf.py; o crawler original
    só tinha guardado a ementa e o cabeçalho (413 chars contra ~11.000 do inteiro teor)."""
    p = ROOT / "data/juris_bruto/inteiro_teor_stf.jsonl"
    if not p.exists():
        return {}
    saida = {}
    for l in p.read_text("utf-8", errors="replace").splitlines():
        try:
            d = json.loads(l)
        except Exception:
            continue
        if len((d.get("inteiro_teor") or "").strip()) > 1500:
            saida[d["doc_id"]] = d
    return saida


def chunks_stf_inteiro_teor(alvo_chars: int) -> list[dict]:
    """Acórdãos do STF com o texto integral, no mesmo desenho semi-bruto: cabeçalho de
    identificação e ementa repetidos em cada parte."""
    saida = []
    for d in inteiro_teor_stf().values():
        ident = " · ".join(x for x in [d.get("processo") or "", "STF",
                                       f"Rel. {d['relator']}" if d.get("relator") else "",
                                       f"j. {d['data_julgamento']}" if d.get("data_julgamento") else ""] if x)
        ementa = re.sub(r"\s+", " ", (d.get("ementa") or "")).strip()[:1200]
        cab = (f"<<JURIS|BRUTO|STF|{d.get('processo') or d['doc_id']}>>\n"
               f"[DECISÃO] {ident}\n" + (f"[RESUMO DA DECISÃO] {ementa}\n" if ementa else ""))
        corpo = re.sub(r"\n{3,}", "\n\n", d["inteiro_teor"].strip())
        orc = max(alvo_chars - len(cab) - 60, 1500)
        partes, atual = [], ""
        for par in re.split(r"\n\s*\n", corpo):
            if atual and len(atual) + len(par) > orc:
                partes.append(atual.strip())
                atual = ""
            atual += par + "\n\n"
        if atual.strip():
            partes.append(atual.strip())
        for k, pt in enumerate(partes):
            saida.append({"categoria": "Decisão monocrática STF (inteiro teor)",
                          "fonte": "STF — inteiro teor",
                          "text": f"{cab}[TEXTO — parte {k+1}/{len(partes)}]\n{pt}"})
    return saida


def chunks_lei_bruta() -> list[dict]:
    """Legislação BRUTA — texto original com `[LEI]` e `[RESUMO DA LEI]` repetidos em cada
    parte. Reaproveita rechunk_v3 (inclusive o cache de resumos do Bedrock, para não
    regerar). Ficou de fora da primeira versão do v4 por esquecimento meu: o v3 tinha."""
    sys.path.insert(0, str(ROOT / "pipeline"))
    import rechunk_v3 as R3
    leis, _ = R3.carregar_leis_brutas()
    saida = []
    for L in leis:
        texto = (L.get("texto") or "").strip()
        if not texto:
            continue
        res = R3.resumo_lei(L["nome"], L["numero"], texto)
        for k, txt in enumerate(R3.chunk_lei_bruta(L["nome"], L["numero"], res, texto,
                                                   L.get("chave"))):
            saida.append({"categoria": f"{L['cat']} (bruta)", "fonte": "leis/ (texto original)",
                          "text": txt})
    return saida


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta o corpus v4 com chunks uniformes.")
    ap.add_argument("--valid-frac", type=float, default=0.02)
    ap.add_argument("--max-doutrina", type=float, default=0.35,
                    help="fração máxima do corpus que pode ser doutrina (0 = sem teto)")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT / "pipeline"))
    sys.path.insert(0, str(ROOT / "augmentation"))
    from referencias import spans_julgados_inventados, forma_natural   # Q2, Q4
    from sanitize import (remove_julgado_inventado, acrescenta_forma_natural,
                          preenche_data)                                   # Q6
    from datas_precedente import indice, data_de
    from teses_oficiais import indice as indice_tese, insere as insere_tese  # Q1
    from expand_normas import revogado_por_inteiro                           # F5/V4
    global _IDX_DATA, _IDX_INF, _IDX_TESE
    _IDX_DATA, _IDX_INF = indice()
    _IDX_TESE = indice_tese()
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained("Polygl0t/Tucano2-qwen-3.7B-Instruct")
    fora = holdout()
    random.seed(42)
    SAIDA.mkdir(parents=True, exist_ok=True)

    todos, resumo, n_limpas, n_natural, n_data, n_tese, n_revogado = [], [], 0, 0, 0, 0, 0
    for caminho, categoria, campo, modo in FONTES:
        if not caminho.exists():
            resumo.append((categoria, 0, 0, "AUSENTE"))
            continue
        brutos, pulados = [], 0
        for l in caminho.read_text("utf-8").splitlines():
            if not l.strip():
                continue
            d = json.loads(l)
            if d.get("juris_id") in fora:
                pulados += 1
                continue
            t = (d.get(campo) or "").strip()
            # F5/V4 · artigo revogado ou vetado POR INTEIRO não entra. São 45 nos arquivos
            # de expansão, e a distinção que importa é entre o artigo inteiro e o inciso:
            # 1.123 artigos EM VIGOR citam algum inciso revogado e devem ficar. Quem separa
            # os dois é `revogado_por_inteiro`, que exige que o corpo do artigo SEJA a nota
            # de revogação — não que ele a contenha. A trava de geração já existia em
            # expand_normas.py; esta é a da montagem, para os que já foram gerados.
            if _revogado(t):
                n_revogado += 1
                continue
            # Q2 · a citação de julgado FABRICADA sai aqui, na montagem, porque a ficha já
            # está gerada: a trava de `augmentation/verify.py` impede que nasçam novas, mas
            # as 1.205 que já existem em 860 fichas só desaparecem do treino se a montagem
            # as tirar. Ensinar `REsp 1.234.567` — que aparece 538 vezes — é ensinar a
            # inventar precedente com a forma certa, que é o pior dos dois mundos.
            sp = spans_julgados_inventados(t)
            if sp:
                t = remove_julgado_inventado(t, sp)
                n_limpas += len(sp)
            # Q4 · o item que ABRE com o índice ganha a forma natural na frente, com o
            # índice preservado entre parênteses. `CF88:ART:0195` é o que o pipeline
            # resolve; "art. 195 da Constituição Federal" é o que uma pessoa escreve e
            # busca, e é a forma em que a pergunta chega na prova.
            antes_q4 = t
            t = acrescenta_forma_natural(t, forma_natural)
            if t != antes_q4:
                n_natural += 1
            # Q6 · a data que a ficha declara faltar, quando a coleta a tem.
            m_id = _RX_ID_FICHA.match(t)
            if m_id:
                dt = data_de(m_id.group(1), _IDX_DATA, _IDX_INF)
                if dt:
                    antes_q6 = t
                    t = preenche_data(t, dt)
                    if t != antes_q6:
                        n_data += 1
                # Q1 · a tese como a corte publicou, e não a paráfrase do gerador. Só
                # entra onde existe tese publicada: informativo e acórdão comum não têm,
                # e ali a ratio decidendi é mesmo o que existe.
                doc = m_id.group(1).split(":QA:")[0]
                tese = _IDX_TESE.get(doc)
                if tese:
                    antes_q1 = t
                    t = insere_tese(t, tese)
                    if t != antes_q1:
                        n_tese += 1
            if len(t) > 200:
                brutos.append((t, d.get("fonte_arquivo") or ""))
        if not brutos:
            resumo.append((categoria, 0, pulados, "vazio"))
            continue
        f = fator([t for t, _ in brutos], tok)
        alvo_chars = int(ALVO_TOK / f)
        partir = parte_por_bloco if modo == "bloco" else parte_por_prosa
        n = 0
        for t, fonte in brutos:
            for p in partir(t, alvo_chars):
                if len(p) * f < MIN_TOK * 0.6 and not eh_consolidacao(p, categoria, fonte):
                    continue                        # sobra pequena demais (consolidação é isenta)
                todos.append({"categoria": categoria, "fonte": fonte, "text": p})
                n += 1
        resumo.append((categoria, n, pulados, f"{f:.3f} tok/char · alvo {alvo_chars} chars"))

    # TETO DE DOUTRINA (decisão do pesquisador, 18/08): no máximo 35% do corpus.
    # A prova cobra lei e jurisprudência, não produção acadêmica. Ao cortar, sai TESE
    # antes de ARTIGO — artigo concentra mais argumento por token, e foi por isso que
    # a coleta da SciELO e das revistas institucionais inverteu a proporção.
    if args.max_doutrina:
        dout = [d for d in todos if d["categoria"] == "Doutrina"]
        resto = [d for d in todos if d["categoria"] != "Doutrina"]
        teto = int(len(resto) * args.max_doutrina / (1 - args.max_doutrina))
        if len(dout) > teto:
            def prioridade(d):
                fonte = d.get("fonte", "")
                if "Tese" in fonte or "Dissertação" in fonte:
                    return 2          # cortado primeiro
                if "IPEA" in fonte or "Conleg" in fonte:
                    return 1          # análise de política pública: segundo a sair
                return 0              # artigo científico e de revista institucional: fica
            random.shuffle(dout)
            dout.sort(key=prioridade)
            cortados = len(dout) - teto
            dout = dout[:teto]
            print(f"teto de doutrina em {args.max_doutrina:.0%}: {cortados} chunks fora, {teto} mantidos")
        todos = resto + dout

    # N12 · a substituição não vale mais, e o que ela apagava não era extrato.
    #
    # A regra era: o inteiro teor substitui o extrato dos mesmos acórdãos. Duas coisas
    # mudaram desde que foi escrita, e as duas foram medidas em 17/09:
    #
    #   · o `build_juris_bruto` passou a FUNDIR o extrato com a íntegra, ficando com o
    #     texto maior. O que chega aqui como "STF — acórdão" já é a íntegra: 6.919
    #     documentos e 61,1 M de caracteres, apagados por uma regra que supunha extrato;
    #   · o que entrava no lugar NÃO é acórdão. Os 2.543 documentos de
    #     `inteiro_teor_stf()` têm `doc_id` começando em `despacho` — os 2.543 —, e são
    #     decisões monocráticas. O `build_juris_bruto` exclui despacho de propósito, pela
    #     razão do B6: despacho e acórdão têm naturezas diferentes e tratá-los igual ensina
    #     o expediente que move o processo como se fosse julgamento colegiado.
    #
    # Ou seja: o corpus apagava 61 M de acórdão de verdade e punha 37,9 M de despacho
    # rotulado como acórdão. O rótulo passa a dizer o que o material é, e a substituição sai.
    extras = chunks_stf_inteiro_teor(int(ALVO_TOK / 0.27))
    if extras:
        for x in extras:
            x["categoria"] = "Decisão monocrática STF (inteiro teor)"
        todos += extras
        resumo.append(("Decisão monocrática STF (inteiro teor)", len(extras), 0,
                       "despacho, não acórdão — fora dos braços até haver decisão de escopo"))
    brutas = chunks_lei_bruta()
    if brutas:
        todos += brutas
        resumo.append(("Legislação bruta", len(brutas), 0, "reaproveita rechunk_v3"))

    # ETAPA 4/5 · o BRAÇO passa a ser campo gravado, e não inferência da etapa 6.
    #
    # CORPUS-BRUTO-TOTAL e CORPUS-EXPANDIDO-TOTAL não existiam como coisas distintas: os
    # dois saíam neste mesmo `train.jsonl`, e só o `MAPA` de `aws/build_ablacao_regime.py`
    # os separava, lá na montagem da ablação. A consequência já se materializou — um
    # documento cuja `(categoria, fonte)` não estivesse no MAPA caía fora sem reclamar, e
    # em 17/09 isso escondia quatro das seis fontes de acórdão, ~120 M tokens.
    #
    # O MAPA é IMPORTADO, não recopiado: duas tabelas que precisam concordar acabam
    # discordando. Aqui ele só carimba; quem corta continua sendo a etapa 6.
    # A raiz entra no `sys.path` só o tempo do import, e sai.
    #
    # ARMADILHA DA RAIZ: há um diretório `peft/` no topo do projeto — 4,1 GB de adaptadores
    # TREINADOS, não código. Com a raiz no caminho de importação ele vira pacote de espaço
    # de nomes e SOMBREIA a biblioteca `peft`; quem importar `sentence_transformers` depois
    # disso quebra com `ImportError: cannot import name 'PeftMixedModel'`, e o rastro não
    # menciona a pasta em lugar nenhum — parece ambiente corrompido, e eu perdi tempo
    # achando que era.
    #
    # Quem põe a raiz no caminho, na prática, é o DIRETÓRIO CORRENTE: `python -c` e
    # `python -` colocam o cwd em `sys.path[0]`. Script chamado por caminho escapa, porque
    # aí `sys.path[0]` é a pasta DO SCRIPT — é por isso que a montagem funciona. Este `pop`
    # não conserta o caso do cwd; ele só evita que ESTE import deixe a raiz para trás.
    sys.path.insert(0, str(ROOT))
    try:
        from aws.build_ablacao_regime import classifica as _classifica
    finally:
        if sys.path and sys.path[0] == str(ROOT):
            sys.path.pop(0)
    _sem_braco = collections.Counter()
    for d in todos:
        alvo = _classifica(d)
        d["braco"] = alvo[0] if alvo else ""
        if not alvo:
            _sem_braco[(d["categoria"], d.get("fonte", ""))] += len(d["text"])
    _n_br = collections.Counter(d["braco"] or "(sem braço)" for d in todos)
    print("\nbraço carimbado na montagem:")
    for k, v in _n_br.most_common():
        print(f"    {k:14} {v:>8,} chunks")
    if _sem_braco:
        _ch = sum(_sem_braco.values())
        print(f"    {_ch/1e6:.1f} M chars em {len(_sem_braco)} pares (categoria, fonte) "
              f"sem braço — listados para que não sumam em silêncio:")
        for (cat, fon), c in _sem_braco.most_common(12):
            print(f"      {c/1e6:>7.1f} M  {cat} · {fon}")

    random.shuffle(todos)
    corte = int(len(todos) * (1 - args.valid_frac))
    for nome, parte in [("train", todos[:corte]), ("valid", todos[corte:])]:
        with open(SAIDA / f"{nome}.jsonl", "w", encoding="utf-8") as f:
            for i, d in enumerate(parte):
                f.write(json.dumps({"text": d["text"], "categoria": d["categoria"],
                                    "fonte": d.get("fonte", ""), "braco": d.get("braco", "")},
                                   ensure_ascii=False) + "\n")

    print("%-24s %8s %8s  %s" % ("categoria", "chunks", "held-out", "calibração"))
    for cat, n, h, obs in resumo:
        print("%-24s %8d %8d  %s" % (cat, n, h, obs))
    if n_limpas:
        print(f"  Q2 · {n_limpas:,} citações de julgado fabricadas removidas na montagem")
    if n_natural:
        print(f"  Q4 · {n_natural:,} documentos ganharam a forma natural da referência")
    if n_data:
        print(f"  Q6 · {n_data:,} fichas tiveram a data preenchida a partir da coleta")
    if n_tese:
        print(f"  Q1 · {n_tese:,} fichas receberam o texto OFICIAL da tese")
    if n_revogado:
        print(f"  F5 · {n_revogado:,} fichas de artigo revogado por inteiro ficaram fora")
    print(f"\n✓ train {corte} · valid {len(todos)-corte} → {SAIDA.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
