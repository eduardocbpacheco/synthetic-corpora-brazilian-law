#!/usr/bin/env python3
"""
monta_corpus_v3.py — o corpus v3 da réplica (Tucano 3,7B), feito a partir do CONGELADO.

O corpus das 180 condições (`data/ablacao_regime/{bruto,expandido}_completo.jsonl`, sha256 em
`pipeline/congelado.sha256`) NÃO é tocado: este script só o LÊ. A saída é um corpus novo,
`data/ablacao_regime_v3/`, que é o congelado + o que faltava, para a réplica continuar
comparável às condições já medidas. Não se rebalanceiam áreas: tudo o que o congelado tem
fica, e o que entra é só o que a auditoria de 14/11/2026 achou faltando.

O que muda em relação ao congelado, e por quê (detalhe e números em docs/CORPUS_V3.md):

  1. SPLIT · o `rechunk_v4` de 30/08 embaralhava blocos e mandava 2% para a validação,
     INCLUSIVE lei, súmula e enunciado; o pré-treino só lê o treino, e sumiam trechos
     inteiros (CF arts. 7–11, CTN 129–140, CC 24–43, CPC 99–108…). Os blocos perdidos NÃO
     precisam ser refeitos: são exatamente as linhas de `data/regimes/AB_*/valid.jsonl`,
     gravadas na mesma montagem (os `train.jsonl` de lá são byte a byte o congelado). Regra
     nova: norma, súmula, tese, enunciado → sempre treino; validação só de jurisprudência
     DECISÓRIA (acórdão, caso, nota de informativo) e POR DOCUMENTO — documento com alguma
     parte no treino vai inteiro para o treino.
  2. FONTE TRUNCADA · Código Civil, Código Penal, ECA, Estatuto da Pessoa Idosa, Estatuto do
     Desarmamento, Cheque e Duplicata: os blocos do congelado saem e entram os do texto
     recoletado (recoleta_v2/v3), com o mesmo divisor (`rechunk_v3.chunk_lei_bruta`) e o
     cabeçalho na forma do congelado.
  3. DIPLOMAS NUNCA COLETADOS · os 32 da auditoria + o Código de Ética da OAB + o Anexo I da
     LUG (OCR, `lug_anexo_ocr_v3.py`), nos dois braços.
  4. TRABALHO E TRIBUTÁRIO · sai o livro do TST fatiado (com cancelados) do bruto e as fichas
     antigas do TST do expandido; entram súmulas/OJs/PNs VIGENTES, um verbete por documento,
     as teses de IRR/IAC e as súmulas vigentes do CARF (`coleta_trab_trib_v3.py`).
  5. RÓTULOS · (a) `DOC=CP` no expandido congelado é o Código Penal MILITAR (B4): 440 fichas,
     413 delas dizem "Penal Militar" no texto. Viram `CPM`, e `CP` fica livre para o Código
     Penal de verdade; (b) a LC 107/2001 vinha batizada "Lei LINDB revisão" — é a lei que
     altera a LC 95/1998 (elaboração das leis); (c) B2 · nota de informativo do STJ é
     `juris` nos dois braços (no congelado estava `caso` no expandido).
  6. FICHAS NOVAS · `gera_cards_v3.py`, mesmo professor e prompt das fichas existentes.

PORTÃO: todo diploma da lista de referência (`referencia_v3.py`) com ≥ 98% dos artigos
VIGENTES nos dois braços. Abaixo disso a montagem aborta.

Uso:
    juridico-env/bin/python pipeline/monta_corpus_v3.py --cobertura   # só mede, não grava
    juridico-env/bin/python pipeline/monta_corpus_v3.py               # monta e grava
"""
from __future__ import annotations
import argparse, collections, datetime, hashlib, json, os, random, re, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
os.environ.setdefault("HF_HUB_OFFLINE", "1")        # tokenizadores do cache local, sem rede
sys.path.insert(0, str(RAIZ / "pipeline"))
sys.path.insert(0, str(RAIZ / "augmentation"))
import referencia_v3 as RV                                   # noqa: E402

CONGELADO = RAIZ / "data/ablacao_regime"
VALID_3008 = {"bruto": RAIZ / "data/regimes/AB_bruto/valid.jsonl",
              "expandido": RAIZ / "data/regimes/AB_expandido/valid.jsonl"}
SAIDA = RAIZ / "data/ablacao_regime_v3"
CARDS_NOVOS = SAIDA / "cards_v3.jsonl"            # escrito por gera_cards_v3.py
TST_VERBETES = RAIZ / "data/trabalho_v3/tst_verbetes.jsonl"
TST_TESES = RAIZ / "data/trabalho_v3/tst_teses.jsonl"
CARF = RAIZ / "data/tributario_v3/carf_sumulas.jsonl"
SEMENTE = 42
ORC_CASADO = 32_000_000
PISO_PORTAO = 98.0
FAMILIAS = {"tucano": "Polygl0t/Tucano2-qwen-3.7B-Instruct", "qwen": "Qwen/Qwen3-8B"}

# Diplomas cujo texto no congelado veio de FONTE TRUNCADA: os blocos saem por inteiro e
# entram os do texto recoletado. Não basta acrescentar o que falta: o bloco antigo do
# Código Civil, por exemplo, é um pedaço do preâmbulo com 37 artigos, e misturar as duas
# coletas poria o mesmo artigo duas vezes com quebras diferentes.
TROCA_FONTE = ["CC", "CP", "ECA", "L10741", "L10826", "L7357", "L5474"]


# ── grupos ──────────────────────────────────────────────────────────────────────────────
# O congelado guarda só `text`. O grupo de cada documento é RECONSTRUÍDO pelo cabeçalho,
# com a regra que reproduz o manifesto de 30/08: no bruto ela dá 78,3 / 9,1 / 8,9 / 3,7
# (caso/juris/norma/enunciado), idêntico ao manifesto; no expandido fica a 0,2 pp.
_CASO_STF = re.compile(r"^(Rcl|HC|RE|ARE|MS|AP|ADI|ADPF|ADC|ADO|RHC|RMS|Inq|Pet|AO|AR|MI|AI|ACO|"
                       r"SL|SS|STP|Ext|IF|AC|HD)\b")


def grupo_bruto(t: str) -> str | None:
    h = t[:200]
    if h.startswith("<<LEI|"):
        return "norma"
    if h.startswith("<<ENUNCIADO|TST"):
        return "tst_antigo"                      # livro fatiado: sai no v3
    if h.startswith("<<ENUNCIADO"):
        return "enunciado"
    m = re.match(r"<<JURIS\|BRUTO\|([^|]+)\|([^>]*)>>", h)
    if not m:
        return None
    trib, resto = m.groups()
    if trib in ("TST", "CARF"):
        return "juris"
    if trib == "TJSP":
        return "juris" if re.match(r"(Súmula|IRDR|IAC)", resto) else "caso"
    if trib == "STF":
        # O inteiro teor ("Acórdão STF (inteiro teor)") não tem [RESUMO DA DECISÃO]; o
        # controle concentrado, que no MAPA é juris, tem. É o que separa os dois rótulos
        # que o mesmo "ADI 1234" recebia em 30/08.
        return ("caso" if _CASO_STF.match(resto) and "[RESUMO DA DECISÃO]" not in t[:3000]
                else "juris")
    return "juris"                               # STJ: informativo, tema, súmula, IAC


def grupo_expandido(t: str, b2: bool = True) -> str | None:
    # `search` nos primeiros caracteres, não `match`: uma ficha do congelado (CTB, art. 244)
    # abre com a cerca de markdown que o professor deixou, antes do marcador.
    m = re.search(r"<<ID=([^|>]*)\|DOC=([^|>]*)\|TYPE=([^|>]*)", t[:200])
    if not m:
        # Oito fichas de enunciado do CJF trazem no identificador o próprio texto do verbete
        # (Q21: o número não foi extraído), e o cabeçalho não fecha nos 200 caracteres.
        return "enunciado" if t.lstrip("`\n abcdefghijklmnopqrstuvwxyz").startswith("<<ID=ENUN:") else None
    i, _, ty = m.groups()
    if ty == "ART":
        return "norma"
    if ty == "ENUN" or i.startswith("ENUN:"):
        return "enunciado"
    if i.startswith("CASE:"):
        return "caso"
    if i.startswith("JURIS:TST:"):
        # Toda ficha do TST que chega aqui é do congelado: as 1.804 do livro de 2023, em seis
        # grafias de identificador, inclusive sobre verbete cancelado. Saem todas; as novas
        # (só vigentes) recebem o grupo em `docs_cards_novos`, sem passar por aqui.
        return "tst_antigo"
    if i.startswith("JURIS:STJ:INFJ"):
        # B2 · a nota de informativo é juris no bruto ("STJ — informativo"); no expandido
        # congelado estava em caso. `b2=False` reproduz o rótulo de 30/08.
        return "juris" if b2 else "caso"
    if i.startswith("JURIS:STF:"):
        return "juris" if re.match(r"(RG|SUM|SV|Tema)", i.split(":")[2]) else "caso"
    return "juris"


# ── validação: o que pode ficar fora do treino ─────────────────────────────────────────
_CONSOLIDACAO = re.compile(r"(Súmula|Tema|IRDR|IAC|OJ|Precedente Normativo)")


def elegivel_validacao(t: str, braco: str) -> bool:
    """Só jurisprudência DECISÓRIA vai para a validação; norma, súmula, tese e enunciado
    nunca — são justamente o que o modelo precisa ver inteiro, e o que sumia."""
    if braco == "bruto":
        m = re.match(r"<<JURIS\|BRUTO\|([^|]+)\|([^>]*)>>", t)
        return bool(m) and not _CONSOLIDACAO.match(m.group(2)) and m.group(1) not in ("TST", "CARF")
    g = grupo_expandido(t)
    if g == "caso":
        return True
    return t.startswith("<<ID=JURIS:STJ:INFJ")   # nota de informativo: decisão, não tese


def chave_documento(t: str, braco: str) -> str:
    if braco == "bruto":
        return t.split("\n", 1)[0]
    m = re.search(r"\|DOC=([^|>]+)\|", t[:300])
    return m.group(1) if m else t[:80]


# ── correções de rótulo ─────────────────────────────────────────────────────────────────
NOME_LC107 = "LC 107/2001 (altera a LC 95/1998, sobre elaboração e redação das leis)"


def corrige_rotulos(t: str, braco: str) -> tuple[str, list[str]]:
    feitas = []
    if braco == "expandido" and "|DOC=CP|" in t[:300]:
        # B4 no congelado: estas fichas são do Código Penal MILITAR. Troca só os
        # identificadores, nunca o texto: uma remissão a "CP:ART:121" no corpo da ficha é
        # ambígua, e reescrevê-la seria adivinhar.
        t = (t.replace("<<ID=CP:", "<<ID=CPM:").replace("|DOC=CP|", "|DOC=CPM|")
              .replace("PARENT=CP>>", "PARENT=CPM>>").replace("PARENT=CP:", "PARENT=CPM:"))
        t = re.sub(r"(— )CP( ART \d)", r"\1CPM\2", t)
        feitas.append("CP→CPM")
    if "Lei LINDB revisão" in t:
        t = t.replace("Lei LINDB revisão", NOME_LC107)
        feitas.append("LC107")
    return t, feitas


# ── leitura do congelado ────────────────────────────────────────────────────────────────
def le_jsonl(p: Path) -> list[str]:
    return [json.loads(l)["text"] for l in p.open(encoding="utf-8") if l.strip()]


def confere_congelado() -> None:
    """O portão F8 em miniatura: o v3 só se monta sobre o congelado intacto."""
    ref = json.loads("\n".join(l for l in (RAIZ / "pipeline/congelado.sha256").read_text().splitlines()
                               if not l.startswith("#")))
    for nome, r in ref.items():
        h = hashlib.sha256((CONGELADO / nome).read_bytes()).hexdigest()
        if h != r["sha256"]:
            raise SystemExit(f"ABORTA: {nome} não bate com congelado.sha256")


def base_congelada() -> dict:
    """Congelado + o que a validação de 30/08 levou indevidamente, já com rótulos corrigidos.

    Devolve {"bruto": [...], "expandido": [...], "valid": {...}, "log": {...}}; cada doc é
    {text, grupo, origem}.
    """
    log = collections.Counter()
    out = {"bruto": [], "expandido": [], "valid": {"bruto": [], "expandido": []}}
    for braco in ("bruto", "expandido"):
        treino = le_jsonl(CONGELADO / f"{braco}_completo.jsonl")
        valid = le_jsonl(VALID_3008[braco])
        chaves_treino = {chave_documento(t, braco) for t in treino}
        docs = [(t, "congelado") for t in treino]
        # A medida ANTES, para a tabela antes/depois: o congelado como está, só com o rótulo
        # CP→CPM aplicado — sem ele o Código Penal apareceria com 97% de fichas que são do
        # Penal Militar.
        out.setdefault("antes", {})[braco] = [{"text": corrige_rotulos(t, braco)[0]} for t in treino]
        for t in valid:
            if elegivel_validacao(t, braco) and chave_documento(t, braco) not in chaves_treino:
                out["valid"][braco].append(t)
                log[f"{braco}: validação mantida (documento inteiro fora do treino)"] += 1
            else:
                docs.append((t, "restaurado_da_validacao_3008"))
                log[f"{braco}: restaurado da validação de 30/08"] += 1
        for t, origem in docs:
            t, feitas = corrige_rotulos(t, braco)
            for f in feitas:
                log[f"{braco}: rótulo {f}"] += 1
            g = grupo_bruto(t) if braco == "bruto" else grupo_expandido(t)
            if g == "tst_antigo":
                log[f"{braco}: TST antigo removido"] += 1
                continue
            out[braco].append({"text": t, "grupo": g, "origem": origem})
    out["log"] = log
    return out


# ── blocos de lei ───────────────────────────────────────────────────────────────────────
_RESUMOS = None


def resumo_sem_modelo(numero: str, texto: str) -> tuple[str, str]:
    """O resumo do cabeçalho do bloco SEM chamar modelo.

    Os diplomas que já existiam têm resumo no cache (`leis/resumos_lei.json`, semeado com os
    203 do congelado — N10), e ele é reaproveitado. Para os diplomas novos o cabeçalho leva
    a EMENTA da própria lei ("Dispõe sobre…", "Regula…"), que é texto da fonte: assim o
    braço bruto não ganha texto de modelo novo, e o v3 não depende de mais uma chamada paga.
    """
    global _RESUMOS
    if _RESUMOS is None:
        _RESUMOS = json.loads((RAIZ / "leis/resumos_lei.json").read_text("utf-8"))
    if numero in _RESUMOS:
        return _RESUMOS[numero], "cache_N10"
    t = re.sub(r"<revogado>.*?</revogado>", " ", texto or "", flags=re.S)
    m = re.search(r"(Institui|Disp[õo]e|Regula|Estabelece|Altera|Aprova|Define|Regulamenta|"
                  r"Promulga)[^.]{0,300}\.", t)
    return (re.sub(r"\s+", " ", m.group(0)).strip() if m else f"Norma {numero}."), "ementa"


def blocos_lei(chave: str, nome_lei: str | None = None) -> list[str]:
    """Blocos brutos do diploma, pelo divisor do v4 e no FORMATO do congelado.

    O divisor atual põe `<<LEI|BRUTO|{apelido ou chave}>>` e uma linha `[CHAVE]`; o congelado
    é de antes disso e usa `<<LEI|BRUTO|{número}>>` sem `[CHAVE]`. Vale a forma do congelado,
    para que um bloco recoletado e um antigo não pareçam documentos de espécies diferentes.
    """
    import rechunk_v3 as R3
    d = RV.POR_CHAVE[chave]
    f = RV.fonte(chave)
    # As páginas do Planalto vêm com CRLF, e "Art.\r\n18" não abre linha para nenhum dos
    # dois divisores: a Lei 8.137 perdia 8 de 18 artigos só por isso.
    texto = RV._normaliza_artigo_por_extenso(f["texto"].replace("\r\n", "\n").replace("\r", "\n"))
    nome = nome_lei or d["nome"]
    resumo, _ = resumo_sem_modelo(d["lei"], texto)
    blocos = R3.chunk_lei_bruta(nome, d["lei"], resumo, texto, chave=None)
    return [re.sub(r"^<<LEI\|BRUTO\|[^>]*>>", f"<<LEI|BRUTO|{d['lei']}>>", b, count=1) for b in blocos]


def nome_lei_congelado(docs: list[dict], lei: str) -> str | None:
    for x in docs:
        if x["text"].startswith(f"<<LEI|BRUTO|{lei}>>"):
            m = re.search(r"(?m)^\[LEI\] (.*) \(" + re.escape(lei) + r"\)$", x["text"][:400])
            if m:
                return m.group(1)
    return None


# ── TST e CARF ──────────────────────────────────────────────────────────────────────────
_CLASSE_TST = {"SUM": "SUM", "OJ-SDI1": "OJ-SDI1", "OJ-SDI1T": "OJ-SDI1T", "OJ-SDI2": "OJ-SDI2",
               "OJ-SDC": "OJ-SDC", "OJ-TP/OE": "OJ-TPOE", "PN": "PN", "IRR": "IRR", "IAC": "IAC"}
MIN_CHARS_VERBETE = 60          # PN 42 e PN 116 saem do PDF com 29 e 47 caracteres: extração quebrada


def itens_trab_trib() -> list[dict]:
    """Um item por verbete VIGENTE: {jid, cabecalho, rotulo, texto, tribunal, tipo, status}."""
    itens = []
    for p in (TST_VERBETES, TST_TESES):
        for l in p.open(encoding="utf-8"):
            r = json.loads(l)
            if not r["vigente"] or len(r["texto"]) < MIN_CHARS_VERBETE:
                continue
            cl = _CLASSE_TST[r["tipo"]]
            tese = r["tipo"] in ("IRR", "IAC")
            texto = (f"[QUESTÃO] {r['titulo']}\n[TESE] {r['texto']}" if tese and r.get("titulo")
                     else r["texto"])
            itens.append({"jid": f"JURIS:TST:{cl}:{r['numero']}", "tribunal": "TST",
                          "cabecalho": (f"Tema {r['numero']} de {r['tipo']} do TST" if tese
                                        else f"{r['rotulo']}"),
                          "tipo": ("Tese de IRR/IAC do TST" if tese else "Súmula/OJ/PN do TST"),
                          "status": ("Vinculante (art. 896-C da CLT)" if tese
                                     else "Persuasivo (uniformização do TST)"),
                          "area": "Direito do Trabalho", "numero": r["numero"], "texto": texto})
    for l in CARF.open(encoding="utf-8"):
        r = json.loads(l)
        if not r["vigente"]:
            continue
        st = "Observância obrigatória pelos conselheiros do CARF (RICARF)"
        if r.get("vinculante"):
            st += "; vinculante para a administração tributária federal (portaria ministerial)"
        itens.append({"jid": f"JURIS:CARF:SUM:{r['numero']}", "tribunal": "CARF",
                      "cabecalho": f"Súmula {r['numero']} do CARF", "tipo": "Súmula do CARF",
                      "status": st, "area": "Direito Tributário", "numero": r["numero"],
                      "texto": r["texto"]})
    return itens


def doc_bruto_juris(it: dict) -> str:
    """Na forma das súmulas do congelado (`<<JURIS|BRUTO|STJ|Súmula 498 do STJ>>`)."""
    resumo = re.sub(r"\s+", " ", it["texto"])[:1200]
    return (f"<<JURIS|BRUTO|{it['tribunal']}|{it['cabecalho']}>>\n"
            f"[DECISÃO] {it['cabecalho']} · {it['tribunal']}\n"
            f"[RESUMO DA DECISÃO] {resumo}\n[TEXTO — parte 1/1]\n{it['texto']}")


# ── validação: completar até 2%, por documento ──────────────────────────────────────────
V4 = RAIZ / "data/pretrain_v4/train.jsonl"
# Só as famílias de documento decisório que o congelado já tinha, para a validação medir a
# mesma distribuição do treino: acórdão do TJSP, acórdão do STF, nota de informativo do STJ.
CANDIDATAS_VALID = {
    "bruto": {("Jurisprudência bruta", "TJSP — 2º grau"), ("Jurisprudência bruta", "STJ — informativo"),
              ("Acórdão STF (inteiro teor)", None)},
    "expandido": {("Acórdão STF (rico)", None), ("Caso TJSP", None),
                  ("Nota de informativo STJ (rico)", None)},
}
FRACAO_VALID = 0.02


def completa_validacao(valid: dict, docs: dict) -> dict:
    """Leva cada braço a ~2% de validação, POR DOCUMENTO e só com jurisprudência decisória.

    A validação de 30/08 que sobra depois da regra nova é quase nada no expandido (um
    documento: as notas de informativo saem por número de informativo, e quase todo
    informativo tem alguma nota no treino). O complemento vem do `pretrain_v4`, de
    documentos que NÃO estão no treino do v3 em parte nenhuma (chave de documento ausente
    do braço), sorteados com a semente do corpus.
    """
    log = collections.Counter()
    for braco in ("bruto", "expandido"):
        alvo = int(FRACAO_VALID * len(docs[braco]))
        no_treino = {chave_documento(x["text"], braco) for x in docs[braco]}
        ja = {chave_documento(t, braco) for t in valid[braco]}
        pool = collections.defaultdict(list)
        for l in V4.open(encoding="utf-8"):
            d = json.loads(l)
            cat, fon = d.get("categoria"), d.get("fonte")
            if (cat, fon) not in CANDIDATAS_VALID[braco] and (cat, None) not in CANDIDATAS_VALID[braco]:
                continue
            t = d["text"]
            k = chave_documento(t, braco)
            if k in no_treino or k in ja or not elegivel_validacao(t, braco):
                continue
            pool[k].append(t)
        chaves = sorted(pool)
        random.Random(SEMENTE).shuffle(chaves)
        for k in chaves:
            if len(valid[braco]) >= alvo:
                break
            valid[braco].extend(pool[k])
            log[f"{braco}: documentos de validação do pretrain_v4"] += 1
        log[f"{braco}: linhas de validação"] = len(valid[braco])
    return dict(log)


# ── pendências de ficha (lidas por gera_cards_v3.py) ────────────────────────────────────
def pendencias(base: dict) -> dict:
    """O que falta de ficha depois de restaurar a validação: artigos vigentes sem ficha nos
    diplomas da referência, e os verbetes de TST/CARF."""
    pres = RV.presenca_cards([x["text"] for x in base["expandido"]])
    normas = []
    for d in RV.DIPLOMAS:
        docs = set(d["docs"]) | {d["novo_doc"]}
        if d["chave"] == "CP":
            docs = {"CP"}                      # o `CP` do congelado já virou `CPM`
        tem = set().union(*[{n for n, _ in pres.get(x, set())} for x in docs])
        for (n, suf), art in sorted(RV.artigos_vigentes(d["chave"]).items()):
            if n not in tem:
                normas.append({"tarefa": "norma", "chave": d["chave"], "id": art["id"],
                               "doc_id": d["novo_doc"], "diploma": d["nome"], "num_art": n,
                               "sufixo": suf, "texto": art["texto"]})
    juris = [{"tarefa": "juris", **it} for it in itens_trab_trib()]
    return {"normas": normas, "juris": juris}


# ── fichas novas → documentos ───────────────────────────────────────────────────────────
def docs_cards_novos(tok=None) -> tuple[list[dict], dict]:
    """Aplica às fichas novas as mesmas passagens de montagem do v4 (rechunk_v4): artigo
    revogado por inteiro fora (F5), citação de julgado com número-molde fora (Q2), forma
    natural da referência (Q4), e corte por bloco na faixa de ~1.650 tokens."""
    from referencias import spans_julgados_inventados, forma_natural
    from sanitize import remove_julgado_inventado, acrescenta_forma_natural
    import rechunk_v4 as R4
    if not CARDS_NOVOS.exists():
        return [], {}
    regs = {}
    for l in CARDS_NOVOS.open(encoding="utf-8"):
        r = json.loads(l)
        if (r.get("expansao") or "").startswith("<<ID="):
            regs[r["id"]] = r                    # a última geração de cada id vale
    log = collections.Counter()
    brutos = []
    for r in regs.values():
        t = r["expansao"].strip()
        if r["tarefa"] == "norma" and r.get("sufixo"):
            # O prompt formata `{num_art:04d}` e o sufixo se perdia: 75 e 75-A colidiam
            # no mesmo `:ART:0075`. Nas fichas NOVAS o sufixo volta ao identificador.
            base = f"{r['doc_id']}:ART:{r['num_art']:04d}"
            t = re.sub(re.escape(base) + r"(?=[|:>])", f"{base}-{r['sufixo']}", t)
        if R4._revogado(t):
            log["F5 revogado"] += 1
            continue
        sp = spans_julgados_inventados(t)
        if sp:
            t = remove_julgado_inventado(t, sp)
            log["Q2 julgados-molde removidos"] += len(sp)
        t2 = acrescenta_forma_natural(t, forma_natural)
        log["Q4 forma natural"] += t2 != t
        brutos.append((t2, "norma" if r["tarefa"] == "norma" else "juris", r["id"]))
    if tok is None:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(FAMILIAS["tucano"])
    docs = []
    for g in ("norma", "juris"):
        textos = [t for t, gg, _ in brutos if gg == g]
        if not textos:
            continue
        f = R4.fator(textos, tok)
        alvo = int(R4.ALVO_TOK / f)
        for t in textos:
            # Ficha inteira nunca cai no piso de sobra do v4: o piso existe para o resto de
            # uma quebra, e aplicá-lo à ficha curta apagaria o artigo curto do braço.
            for p in R4.parte_por_bloco(t, alvo):
                docs.append({"text": p, "grupo": g, "origem": "ficha_nova_v3"})
        log[f"fator {g}"] = round(f, 3)
    return docs, dict(log)


# ── cobertura e portão ──────────────────────────────────────────────────────────────────
def cobertura(bruto: list[dict], exp: list[dict]) -> list[dict]:
    pb = RV.presenca_bruto([x["text"] for x in bruto])
    pc = RV.presenca_cards([x["text"] for x in exp])
    linhas = []
    for d in RV.DIPLOMAS:
        c = RV.cobertura(d["chave"], pb, pc)
        linhas.append({"chave": d["chave"], "nome": d["nome"], "area": d["area"], **c})
    return linhas


def portao(linhas: list[dict]) -> list[str]:
    return [f"{x['chave']}: bruto {x['pct_bruto']}% · fichas {x['pct_cards']}%"
            for x in linhas if x["vigentes"] and min(x["pct_bruto"], x["pct_cards"]) < PISO_PORTAO]


# ── montagem ────────────────────────────────────────────────────────────────────────────
def monta(so_cobertura: bool = False) -> None:
    confere_congelado()
    base = base_congelada()
    log = base["log"]
    bruto, exp = base["bruto"], base["expandido"]

    # (2) troca de fonte e (3) diplomas novos, no braço bruto.
    #
    # Além dos sete de fonte truncada conhecida, troca-se todo diploma da referência que,
    # MESMO depois de devolvida a validação, segue abaixo do piso no bruto: aí a lacuna não
    # é do split, é do texto antigo (a S.A. e a LEP vinham de `leis_federais.jsonl`, de uma
    # coleta que não trazia a redação atual inteira).
    pb = RV.presenca_bruto([x["text"] for x in bruto])
    troca = list(TROCA_FONTE)
    for d in RV.DIPLOMAS:
        if d["docs"] and d["chave"] not in troca:
            if RV.cobertura(d["chave"], pb, {})["pct_bruto"] < PISO_PORTAO:
                troca.append(d["chave"])
    log["bruto: diplomas com fonte trocada"] = ", ".join(troca)
    fora = {RV.POR_CHAVE[k]["lei"] for k in troca}
    nomes = {k: nome_lei_congelado(bruto, RV.POR_CHAVE[k]["lei"]) for k in troca}
    antes = len(bruto)
    bruto = [x for x in bruto if not any(x["text"].startswith(f"<<LEI|BRUTO|{l}>>") for l in fora)]
    log["bruto: blocos de fonte truncada removidos"] = antes - len(bruto)
    for k in troca:
        for b in blocos_lei(k, nomes.get(k)):
            bruto.append({"text": b, "grupo": "norma", "origem": f"lei_recoletada:{k}"})
            log["bruto: blocos de fonte recoletada"] += 1
    novos = [d["chave"] for d in RV.DIPLOMAS if not d["docs"] and d["chave"] not in troca]
    for k in novos:
        nome = None
        if k == "D57663":
            nome = "Lei Uniforme de Genebra (Anexo I do Decreto 57.663/1966)"
        for b in blocos_lei(k, nome):
            bruto.append({"text": b, "grupo": "norma", "origem": f"lei_nova:{k}"})
            log["bruto: blocos de diploma novo"] += 1

    # (4) TST/CARF no bruto
    for it in itens_trab_trib():
        bruto.append({"text": doc_bruto_juris(it), "grupo": "juris",
                      "origem": f"{it['tribunal'].lower()}_v3"})
        log[f"bruto: verbete {it['tribunal']} vigente"] += 1

    # (6) fichas novas
    novas, log_cards = docs_cards_novos()
    exp = exp + novas
    log["expandido: documentos de ficha nova"] = len(novas)

    linhas = cobertura(bruto, exp)
    antes = {x["chave"]: x for x in cobertura(base["antes"]["bruto"], base["antes"]["expandido"])}
    for x in linhas:
        a = antes[x["chave"]]
        x.update({"antes_bruto": a["bruto"], "antes_cards": a["cards"],
                  "antes_pct_bruto": a["pct_bruto"], "antes_pct_cards": a["pct_cards"]})
    reprovados = portao(linhas)
    print("\n".join(f"  {k}: {v}" for k, v in sorted(log.items())))
    print(f"  fichas novas: {log_cards}")
    for x in linhas:
        if min(x["pct_bruto"], x["pct_cards"]) < 100:
            print(f"    {x['chave']:8} vig {x['vigentes']:5}  bruto {x['pct_bruto']:5.1f}%  "
                  f"fichas {x['pct_cards']:5.1f}%")
    if so_cobertura:
        print(f"\nportão: {len(reprovados)} diploma(s) abaixo de {PISO_PORTAO}%")
        return
    if reprovados:
        raise SystemExit("ABORTA · portão de cobertura:\n  " + "\n  ".join(reprovados))
    sem = sum(1 for x in bruto + exp if x["grupo"] is None)
    if sem:
        raise SystemExit(f"ABORTA: {sem} documento(s) sem grupo — a composição não fecharia")
    lv = completa_validacao(base["valid"], {"bruto": bruto, "expandido": exp})
    print("\n".join(f"  {k}: {v}" for k, v in lv.items()))
    log.update(lv)
    grava(bruto, exp, base["valid"], linhas, dict(log), log_cards)


def _tokens(textos: list[str], tok) -> list[int]:
    n = []
    for i in range(0, len(textos), 2000):
        n.extend(len(e) for e in tok(textos[i:i + 2000])["input_ids"])
    return n


def grava(bruto, exp, valid, linhas, log, log_cards) -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from transformers import AutoTokenizer
    SAIDA.mkdir(parents=True, exist_ok=True)
    docs = {"bruto": bruto, "expandido": exp}
    # uma ordem aleatória por braço, reusada pelas duas famílias (como build_ablacao_regime)
    for b in docs:
        random.Random(SEMENTE).shuffle(docs[b])
    tokens = {}
    for fam, nome in FAMILIAS.items():
        tok = AutoTokenizer.from_pretrained(nome)
        for b in docs:
            tokens[(fam, b)] = _tokens([x["text"] for x in docs[b]], tok)
            print(f"  {fam}/{b}: {sum(tokens[(fam, b)])/1e6:.2f} M tokens", flush=True)
    for b in docs:
        with open(SAIDA / f"{b}_completo.jsonl", "w", encoding="utf-8") as f:
            for x in docs[b]:
                f.write(json.dumps({"text": x["text"], "grupo": x["grupo"], "origem": x["origem"]},
                                   ensure_ascii=False) + "\n")
        with open(SAIDA / f"{b}_valid.jsonl", "w", encoding="utf-8") as f:
            for t in valid[b]:
                f.write(json.dumps({"text": t}, ensure_ascii=False) + "\n")

    def comp(b, fam, chave="grupo"):
        c = collections.Counter()
        for x, k in zip(docs[b], tokens[(fam, b)]):
            c[x[chave]] += k
        s = sum(c.values())
        return {g: round(100 * v / s, 1) for g, v in c.most_common()}

    man = {"desenho": "corpus v3 da réplica — congelado de 30/08 + lacunas da auditoria de 14/11/2026",
           "gerado_em": datetime.datetime.now().isoformat(timespec="seconds"),
           "base": {"congelado": "data/ablacao_regime/{bruto,expandido}_completo.jsonl (sha256 conferido)",
                    "validacao_3008": "data/regimes/AB_{bruto,expandido}/valid.jsonl"},
           "regra_de_orcamento": "a mesma do congelado: o orçamento é o braço bruto inteiro, por "
                                 "família de tokenizador; o expandido é truncado até casar.",
           "semente_amostra": SEMENTE, "familias": {}, "composicao_pct": {}, "origem_pct": {},
           "log": log, "fichas_novas": log_cards, "cobertura": linhas}
    for fam in FAMILIAS:
        orc = sum(tokens[(fam, "bruto")])
        disp = sum(tokens[(fam, "expandido")])
        man["familias"][fam] = {
            "tokenizador": FAMILIAS[fam], "orcamento_tokens": orc,
            "bruto": {"docs": len(bruto), "tokens": orc, "epocas": 1.0},
            "expandido": {"docs_disponiveis": len(exp), "tokens_disponiveis": disp,
                          "tokens": min(orc, disp), "epocas": round(min(orc, disp) / disp, 3)},
            "valid": {b: len(valid[b]) for b in valid}}
        man["composicao_pct"][fam] = {b: comp(b, fam) for b in docs}
        # O expandido não é lido inteiro: a regra do orçamento corta o embaralhamento no
        # tamanho do bruto. A cobertura que o MODELO vê é a do prefixo, e não a do arquivo —
        # fica medida aqui por diploma, para ninguém ler os 100% do arquivo como os do treino.
        acc, corte = 0, len(exp)
        for i, k in enumerate(tokens[(fam, "expandido")]):
            if acc + k > orc:
                corte = i
                break
            acc += k
        pc = RV.presenca_cards([x["text"] for x in docs["expandido"][:corte]])
        man["familias"][fam]["expandido"]["docs_no_prefixo"] = corte
        man["familias"][fam]["cobertura_fichas_no_prefixo"] = {
            x["chave"]: RV.cobertura(x["chave"], {}, pc)["pct_cards"] for x in linhas}
        man["origem_pct"][fam] = {b: comp(b, fam, "origem") for b in docs}

    # ── par de composição casada a 32M (mesma regra de build_ablacao_regime), com o B2
    cotas = {}
    for g in ("caso", "juris", "norma", "enunciado"):
        disp = {b: sum(k for x, k in zip(docs[b], tokens[("tucano", b)]) if x["grupo"] == g)
                for b in docs}
        cotas[g] = min(disp.values())
    # O teto do par casado é a SOMA DOS MÍNIMOS por grupo: acima dela algum grupo de algum
    # braço não tem material para a cota. No congelado ela passava de 32 M; com o B2 a nota
    # de informativo sai de `caso` no expandido, o `caso` do expandido encolhe para ~10 M, e
    # o teto pode cair abaixo de 32 M. Escalar acima do teto (o que o código antigo faria)
    # deixaria o braço curto sem aviso e com composição diferente — então o orçamento é o
    # menor dos dois, e o manifesto registra o pedido e o viável.
    teto = sum(cotas.values())
    orc_casado = min(ORC_CASADO, int(teto))
    esc = orc_casado / teto
    print(f"  casado: disponível por grupo (mín. entre braços, tucano) "
          + ", ".join(f"{g} {v/1e6:.2f} M" for g, v in cotas.items())
          + f" · teto {teto/1e6:.2f} M · orçamento {orc_casado/1e6:.2f} M", flush=True)
    cotas = {g: v * esc for g, v in cotas.items()}
    man["casado_composicao"] = {"orcamento_pedido": ORC_CASADO, "teto_viavel": int(teto),
                                "orcamento_tokens": orc_casado,
                                "cotas_pct": {g: round(100 * v / orc_casado, 1) for g, v in cotas.items()},
                                "bracos": {}}
    for fam in FAMILIAS:
        for b in docs:
            rest, sel, c = dict(cotas), [], collections.Counter()
            for x, k in zip(docs[b], tokens[(fam, b)]):
                if rest[x["grupo"]] - k < 0:
                    continue
                rest[x["grupo"]] -= k
                sel.append(x)
                c[x["grupo"]] += k
            cam = SAIDA / f"casado_{fam}_{b}.jsonl"
            with open(cam, "w", encoding="utf-8") as f:
                for x in sel:
                    f.write(json.dumps({"text": x["text"]}, ensure_ascii=False) + "\n")
            s = sum(c.values())
            man["casado_composicao"]["bracos"][f"{fam}_{b}"] = {
                "arquivo": os.path.relpath(cam, RAIZ), "docs_usados": len(sel), "tokens_usados": s,
                "composicao_pct": {g: round(100 * v / s, 1) for g, v in c.most_common()}}
            print(f"  casado {fam}/{b}: {len(sel)} docs, {s/1e6:.2f} M", flush=True)
    man["arquivos_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(SAIDA.glob("*.jsonl")) if p.name != CARDS_NOVOS.name}
    (SAIDA / "manifesto.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), "utf-8")
    print(f"\n✓ manifesto em {os.path.relpath(SAIDA / 'manifesto.json', RAIZ)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cobertura", action="store_true", help="só mede a cobertura, não grava")
    a = ap.parse_args()
    monta(so_cobertura=a.cobertura)
