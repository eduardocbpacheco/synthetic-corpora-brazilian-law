"""
Juiz LLM estilo Rabula — uma chamada por questão, JSON estruturado.

Diferenças vs avaliacao/judge.py:
  - 1 call por questão (não por critério)
  - retorna JSON com todos critérios + acerto + raciocínio
  - cache buster força re-inferência
  - suporta múltiplas runs (default 5) por chamador externo
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import re
import secrets
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(_ROOT / ".env")

from prompts import PROMPT_DISCURSIVA, PROMPT_DOCUMENT_WRITING  # noqa: E402

log = logging.getLogger(__name__)


def gerar_cache_buster() -> tuple[str, str, str]:
    """Token + dois inteiros para soma trivial — quebra cache do provedor."""
    token = f"<!-- token: {secrets.token_hex(6)} -->"
    n1 = str(random.randint(0, 100))
    n2 = str(random.randint(0, 100))
    return token, n1, n2


def montar_prompt(
    tipo: str,
    resposta_candidato: str,
    gabarito: str,
    criterios: list[dict] | str,
) -> tuple[str, int]:
    """Constrói o prompt completo. Retorna (prompt, soma_esperada_do_cache_beaker)."""
    if tipo == "discursive":
        template = PROMPT_DISCURSIVA
    elif tipo in ("document_writing", "peca", "practical"):
        template = PROMPT_DOCUMENT_WRITING
    else:
        raise ValueError(f"tipo inválido: {tipo!r}")

    cache_buster, n1, n2 = gerar_cache_buster()
    soma = int(n1) + int(n2)

    if isinstance(criterios, list):
        criterios_str = json.dumps(criterios, ensure_ascii=False, indent=2)
    else:
        criterios_str = str(criterios)

    prompt = template.format(
        cache_buster=cache_buster,
        num1=n1,
        num2=n2,
        resposta_candidato=resposta_candidato,
        gabarito=gabarito,
        criterios=criterios_str,
    )
    return prompt, soma


# ---------------------------------------------------------------------------
# Backend Azure (gpt-4o-mini — eleito pelo paper como melhor alinhamento humano)
# ---------------------------------------------------------------------------

def _get_azure_client():
    from openai import AzureOpenAI
    import httpx

    # Timeouts agressivos para evitar travas em sockets zumbi do Azure noturno.
    # max_retries=0: desabilita backoff interno do SDK (controlamos retries aqui)
    return AzureOpenAI(
        azure_endpoint=os.environ["API_ENDPOINT"],
        api_key=os.environ["API_KEY"],
        api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
        timeout=httpx.Timeout(connect=15.0, read=90.0, write=15.0, pool=15.0),
        max_retries=0,
    )


def _call_azure(client, model: str, prompt: str, retries: int = 5) -> str:
    for tent in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.2,
                timeout=90.0,
            )
            return resp.choices[0].message.content
        except Exception as e:
            es = str(e).lower()
            if "429" in es or "throttl" in es or "rate" in es:
                espera = 60
            elif "timeout" in es or "connect" in es:
                espera = min(2 ** tent, 60)
            else:
                espera = 2 ** tent
            log.warning(f"[Azure] tent {tent}/{retries}: {type(e).__name__}: {e} — aguardando {espera}s")
            if tent < retries:
                time.sleep(espera)
            else:
                raise


# ---------------------------------------------------------------------------
# Backend Groq (Llama 3.3 70B e outros)
# ---------------------------------------------------------------------------

def _get_groq_client():
    from groq import Groq
    return Groq(api_key=os.environ["GROQ_API_KEY"])


def _call_groq(client, model: str, prompt: str, retries: int = 5) -> str:
    for tent in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4000,
                temperature=0.2,
            )
            return resp.choices[0].message.content
        except Exception as e:
            es = str(e).lower()
            if "429" in es or "rate" in es or "throttl" in es:
                espera = 60
            elif "timeout" in es or "connect" in es:
                espera = min(2 ** tent, 60)
            else:
                espera = 2 ** tent
            log.warning(f"[Groq] tent {tent}/{retries}: {type(e).__name__}: {e} — aguardando {espera}s")
            if tent < retries:
                time.sleep(espera)
            else:
                raise


# ---------------------------------------------------------------------------
# Backend Bedrock (AWS)
# ---------------------------------------------------------------------------

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        from botocore.config import Config
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(read_timeout=120, retries={"max_attempts": 0},
                          max_pool_connections=64),
        )
    return _bedrock_client


_TETO: dict[str, int] = {}

# ── Limitador de taxa por modelo ──────────────────────────────────────────────
# A cota da conta é em REQUISIÇÕES POR MINUTO e é por modelo. Bater nela e esperar o
# backoff é a pior estratégia possível: em 24/08, seis workers disputando as 5 vagas/min
# do Opus 4.6 renderam 4 arquivos em 50 minutos, porque cada recusa disparava espera de
# 15-60 s e a maioria das chamadas esgotava as 6 tentativas antes de passar.
#
# Respeitando o limite, cada chamada passa na primeira tentativa: 5/min são 300/hora.
# O limitador serializa por modelo, então o número de workers deixa de importar — pode-se
# usar muitos, e modelos diferentes seguem em paralelo porque têm cotas separadas.
#
# Medido em 25/08 via service-quotas. Os Claude vêm por perfil cross-region, onde o teto é
# muito menor que o on-demand dos demais.
# Lista de partida, complementada em tempo de execução pela própria API de cotas.
# Manter isto à mão foi erro: eu mapeei só os Claude e deixei 100 para o resto, mas o
# Mixtral 8x7B tem 4 RPM e o Llama 3 8B tem 8 — modelos antigos têm cota mínima, menor
# que a do Opus. Descobri isso só depois de ver os throttles.
_RPM = {
    "anthropic.claude-opus-4-6": 5, "anthropic.claude-opus-4-5": 5,
    "anthropic.claude-sonnet-4-6": 10, "anthropic.claude-sonnet-4-5": 10,
    "anthropic.claude-haiku-4-5": 10,
    "mixtral-8x7b": 4, "llama3-8b": 8, "llama3-70b": 8, "llama3-1-8b": 8,
}
_RPM_PADRAO = 100          # Kimi, GPT-OSS e a maioria dos on-demand
_rpm_api: dict[str, int] | None = None


def _rpm_de(model: str) -> int:
    """RPM do modelo: lista à mão, depois a API de cotas, depois o padrão.

    Consultar a API evita a classe de erro que já custou tempo aqui — supor cota alta para
    um modelo que tem cota mínima. A consulta é uma vez por processo e falha em silêncio,
    porque não vale derrubar o julgamento por não conseguir ler uma cota.
    """
    global _rpm_api
    for k, v in _RPM.items():
        if k in model:
            return v
    if _rpm_api is None:
        _rpm_api = {}
        try:
            import boto3
            sq = boto3.client("service-quotas", region_name=os.environ.get("AWS_REGION", "us-east-1"))
            for pg in sq.get_paginator("list_service_quotas").paginate(ServiceCode="bedrock"):
                for q in pg["Quotas"]:
                    if "requests per minute" in q["QuotaName"].lower():
                        _rpm_api[q["QuotaName"].lower()] = int(q["Value"])
        except Exception as e:
            log.warning(f"[cotas] não foi possível ler as cotas: {type(e).__name__}")
    if _rpm_api:
        # casa pelo maior número de palavras do id presentes no nome da cota
        pecas = [x for x in re.split(r"[.\-:_]", model.lower()) if len(x) > 2 and x != "us"]
        melhor, best_n = None, 0
        for nome, v in _rpm_api.items():
            n = sum(1 for x in pecas if x in nome)
            if n > best_n:
                melhor, best_n = v, n
        if melhor is not None and best_n >= 2:
            return melhor
    return _RPM_PADRAO
# Margem por faixa de cota. Em 25/08, 90% do teto ainda produziu 7 throttles no Opus 4.6
# (5/min) e ZERO no Sonnet 4.6 (10/min) — cota baixa não tolera folga pequena, porque a
# janela de contagem da AWS não é um minuto deslizante perfeito e um par de chamadas
# próximas já estoura.
def _margem(rpm: int) -> float:
    # 0,40 nas cotas mínimas: com 0,65 o Opus 4.6 (5 RPM) ainda era recusado, o que indica
    # que a janela de contagem da AWS é mais curta que um minuto — chamadas espaçadas por
    # 18,5 s ainda caíam juntas na mesma janela. A 0,40 são 30 s entre chamadas, 120/hora.
    return 0.40 if rpm <= 5 else 0.70 if rpm <= 10 else 0.90

_ultima: dict[str, float] = {}
_trava_taxa = threading.Lock()


def _espera_vaga(model: str) -> None:
    """Bloqueia até haver vaga na cota do modelo."""
    rpm = _rpm_de(model)
    intervalo = 60.0 / (rpm * _margem(rpm))
    while True:
        with _trava_taxa:
            agora = time.monotonic()
            prox = _ultima.get(model, 0.0) + intervalo
            if agora >= prox:
                _ultima[model] = agora
                return
            falta = prox - agora
        time.sleep(falta)


def _call_bedrock(client, model: str, prompt: str, retries: int = 6) -> str:
    # Modelos com limite menor (Llama 3 = 2048; Mistral 7B/Small também tem limites)
    if "llama3" in model or "mistral-7b" in model or "mistral-small" in model:
        max_tok = 2048
    elif "gpt-oss" in model or "magistral" in model or "kimi" in model or "deepseek.r1" in model:
        # Reasoning models gastam tokens em reasoningContent antes do JSON final.
        # Peças têm ~600 critérios → JSON output sozinho pode passar de 8k tokens.
        max_tok = 16000
    else:
        max_tok = 8000  # era 4000 — peças com muitos critérios cortavam
    # Teto aprendido por modelo. O Mixtral aceita 4.096 e o padrão aqui pede 8.000 —
    # 1.575 chamadas foram perdidas por isso, todas com ValidationException que o retry
    # repetia seis vezes sem nunca ajustar. Mesmo defeito que os respondentes tiveram.
    max_tok = min(max_tok, _TETO.get(model, max_tok))
    for tent in range(1, retries + 1):
        _espera_vaga(model)
        try:
            resp = client.converse(
                modelId=model,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": max_tok, "temperature": 0.2},
            )
            # Verifica se o output foi truncado por max_tokens
            stop_reason = resp.get("stopReason", "")
            text = ""
            for blk in resp["output"]["message"]["content"]:
                if "text" in blk:
                    text = blk["text"]; break
            if stop_reason == "max_tokens" and tent < retries:
                # Dobrar só se houver espaço abaixo do teto do modelo. Sem esta guarda,
                # o Mixtral 8x7B entrava em laço: teto 4.096, o retry dobrava para 8.190,
                # a API recusava, o handler refixava em 4.095, e voltava a estourar
                # max_tokens — duas correções minhas brigando entre si, queimando
                # chamadas de uma cota de 4 RPM sem nunca produzir veredicto.
                teto = _TETO.get(model)
                if teto is not None and max_tok >= teto:
                    raise ValueError(
                        f"{model}: resposta não cabe no teto de saída do modelo "
                        f"({teto} tokens). Não é falha transitória — este juiz não "
                        f"consegue julgar itens deste tamanho.")
                log.warning(f"[Bedrock] {model}: hit max_tokens={max_tok} — retry com 2x")
                max_tok = min(max_tok * 2, 32000)
                if teto is not None:
                    max_tok = min(max_tok, teto)
                continue
            return text
        except Exception as e:
            es = str(e).lower()
            if "tokens per day" in es:
                # Cota DIÁRIA de tokens, não RPM. Nenhuma espera dentro do dia recupera
                # orçamento já gasto, então repetir só queima tentativas: o Opus 4.6
                # acumulou 76 recusas destas sem produzir um veredicto. Aborta de imediato
                # para o chamador poder passar ao próximo modelo.
                raise RuntimeError(f"{model}: cota diária de tokens esgotada")
            m_lim = re.search(r"model limit of (\d+)", str(e))
            if m_lim and max_tok > int(m_lim.group(1)):
                max_tok = int(m_lim.group(1)) - 1
                _TETO[model] = max_tok
                log.warning(f"[Bedrock] {model}: teto de saída fixado em {max_tok}")
                continue
            if "throttl" in es or "429" in es or "rate" in es:
                espera = 20 * tent + random.uniform(0, 10)
            elif "timeout" in es or "connect" in es:
                espera = min(2 ** tent, 60)
            else:
                espera = 2 ** tent
            log.warning(f"[Bedrock] tent {tent}/{retries}: {type(e).__name__}: {e} — aguardando {espera}s")
            if tent < retries:
                time.sleep(espera)
            else:
                raise


# ── Maritaca (Sabiá) ──────────────────────────────────────────────────────────
# Único fornecedor do elenco que oferece processamento em território nacional (variantes
# BR-SP, 30% mais caras). Para o Pretor.ia no TJSP isso pode ser requisito e não
# preferência, então ter o κ do Sabiá medido na MESMA régua dos outros importa: a
# pergunta deixa de ser "qual o melhor juiz" e passa a ser "qual o melhor que pode rodar".
_maritaca_client = None


def _get_maritaca_client():
    global _maritaca_client
    if _maritaca_client is None:
        import openai
        chave = os.environ.get("MARITACA_API_KEY")
        if not chave:
            raise RuntimeError("MARITACA_API_KEY ausente — veja .env.maritaca")
        # API compatível com o cliente da OpenAI; só muda base_url e chave.
        _maritaca_client = openai.OpenAI(api_key=chave,
                                         base_url="https://chat.maritaca.ai/api",
                                         max_retries=0, timeout=300.0)
    return _maritaca_client


def _call_maritaca(client, model: str, prompt: str, retries: int = 6) -> str:
    # Mesma folga de saída dos juízes de raciocínio no Bedrock: uma peça tem ~29 partes e
    # o JSON de veredictos sozinho passa de 8k tokens.
    max_tok = 16000 if "thinking" in model else 8000
    for tent in range(1, retries + 1):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tok, temperature=0.2,
            )
            return r.choices[0].message.content or ""
        except Exception as e:
            es = str(e).lower()
            if "throttl" in es or "429" in es or "rate" in es:
                espera = 20 * tent + random.uniform(0, 10)
            elif "timeout" in es or "connect" in es:
                espera = min(2 ** tent, 60)
            else:
                espera = 2 ** tent
            log.warning(f"[Maritaca] tent {tent}/{retries}: {type(e).__name__}: "
                        f"{str(e)[:120]} — aguardando {espera:.0f}s")
            if tent < retries:
                time.sleep(espera)
            else:
                raise


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    return t


def parsear_resposta_juiz(raw: str) -> dict:
    """Aceita JSON cru ou cercado por ```json. Retorna dict com chave 'resultado'.
    Tolera formatos alternativos:
      - {"resultado": [...]}            ← padrão
      - {"criterios": [...]}            ← alias
      - [...]                           ← lista direta (Phi-4 às vezes)
      - {"A": {...}, "B": {...}}        ← dict por letra (raro)
    """
    txt = _strip_json_fence(raw)
    # strict=False aceita quebra de linha e tab CRUS dentro de string. Sem isso, MiniMax
    # M2.5 quebrava em toda peça ("Invalid control character at line 1 column 1652"): ele
    # escreve a justificativa com \n literal em vez de escapado. É defeito de formatação,
    # não de julgamento — descartar o modelo por isso enviesaria a tabela de κ a favor de
    # quem serializa melhor, que não é o que se está medindo.
    def _tenta(t: str):
        return json.loads(t, strict=False)

    def _conserta(t: str) -> str:
        """Conserta os dois defeitos de serialização que aparecem na prática.

        Vírgula sobrando antes de } ou ] — o Sabiazinho-4 produz isso em ~4% das peças —
        e cerca de código residual. Nenhum dos dois muda o VEREDICTO; descartar a chamada
        por causa deles enviesaria o κ a favor de quem serializa melhor, que não é o que
        se está medindo. O mesmo motivo do strict=False acima.
        """
        t = re.sub(r",(\s*[}\]])", r"\1", t)
        return t

    try:
        parsed = _tenta(txt)
    except Exception:
        try:
            parsed = _tenta(_conserta(txt))
        except Exception:
            parsed = None
    if parsed is None:
        # Último recurso antes de extrair bloco: reparo tolerante.
        #
        # O defeito que sobrava era ASPAS NÃO ESCAPADAS dentro do valor — o juiz escreve
        # citações como: "citou o art. 5º, "caput", da CF". O parser fecha a string na
        # segunda aspa e reclama de vírgula faltando. É frequente num juiz jurídico,
        # porque justificativa boa cita dispositivo entre aspas, e era determinístico por
        # questão: as mesmas falhas reapareciam nas cinco repetições. Custava ~40 chamadas
        # por modelo na repescagem do κ.
        #
        # Vale a mesma razão do strict=False e do _conserta: é defeito de serialização,
        # não de julgamento, e descartar a chamada enviesaria o κ a favor de quem
        # serializa melhor, que não é o que se está medindo.
        try:
            import json_repair
            parsed = json_repair.loads(txt)
            if not parsed:
                parsed = None
        except Exception:
            parsed = None
    if parsed is None:
        # tenta extrair primeiro bloco {...} ou [...]
        m = re.search(r"(\{.*\}|\[.*\])", txt, flags=re.DOTALL)
        if not m:
            raise ValueError(f"juiz não retornou JSON: {raw[:300]}")
        try:
            parsed = json.loads(_conserta(m.group(0)), strict=False)
        except Exception:
            import json_repair
            parsed = json_repair.loads(m.group(0))

    # Normaliza para dict {resultado: [...]}
    if isinstance(parsed, list):
        return {"resultado": parsed}
    if isinstance(parsed, dict):
        if "resultado" in parsed or "criterios" in parsed:
            return parsed
        # dict por letra → tentar achatar
        if all(isinstance(v, dict) for v in parsed.values()):
            flat = []
            for k, v in parsed.items():
                if "acerto" in v:
                    v.setdefault("letra", k)
                    flat.append(v)
            if flat:
                return {"resultado": flat}
    return parsed


# ---------------------------------------------------------------------------
# Entrada pública — 1 avaliação (1 juiz, 1 run)
# ---------------------------------------------------------------------------

def avaliar_questao(
    tipo: str,
    resposta_candidato: str,
    gabarito: str,
    criterios: list[dict],
    *,
    backend: str = "azure",
    judge_model: str = "",
    return_raw: bool = False,
) -> dict:
    """
    Avalia 1 questão (1 juiz, 1 run). Retorna dict:
        {
          'resultado': [
            {'letra': 'A', 'parte': 'I', 'pontos': 0.5, 'acerto': 1, 'raciocinio': '...'},
            ...
          ],
          'soma_esperada': int,   # validação do cache_beaker
          'soma_obtida':   int|None,
          'raw':           str    # se return_raw=True
        }
    """
    prompt, soma_esperada = montar_prompt(tipo, resposta_candidato, gabarito, criterios)

    if backend == "azure":
        client = _get_azure_client()
        model = judge_model or os.environ.get("MODEL_NAME", "gpt-4o-mini")
        raw = _call_azure(client, model, prompt)
    elif backend == "groq":
        client = _get_groq_client()
        model = judge_model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        raw = _call_groq(client, model, prompt)
    elif backend == "bedrock":
        client = _get_bedrock_client()
        model = judge_model or "amazon.nova-pro-v1:0"
        raw = _call_bedrock(client, model, prompt)
    elif backend == "maritaca":
        client = _get_maritaca_client()
        model = judge_model or "sabiazinho-4"
        raw = _call_maritaca(client, model, prompt)
    else:
        raise ValueError(f"backend não suportado: {backend!r}")

    parsed = parsear_resposta_juiz(raw)
    resultado = parsed.get("resultado") or parsed.get("criterios") or []

    soma_obtida = None
    if resultado and isinstance(resultado, list) and isinstance(resultado[0], dict):
        cb = resultado[0].get("cache_beaker")
        try:
            soma_obtida = int(cb) if cb is not None else None
        except (TypeError, ValueError):
            soma_obtida = None

    out: dict[str, Any] = {
        "resultado": resultado,
        "soma_esperada": soma_esperada,
        "soma_obtida": soma_obtida,
    }
    if return_raw:
        out["raw"] = raw
    return out


def calcular_pontuacao(resultado: list[dict]) -> tuple[float, float]:
    """Soma `pontos * acerto`. Retorna (pontuacao_obtida, pontuacao_max)."""
    obtida = 0.0
    maxima = 0.0
    for item in resultado:
        try:
            pts = float(item.get("pontos") or 0)
            acerto = int(item.get("acerto") or 0)
        except (TypeError, ValueError):
            continue
        maxima += pts
        if acerto == 1:
            obtida += pts
    return round(obtida, 4), round(maxima, 4)


def voto_majoritario(runs: list[list[dict]]) -> list[dict]:
    """
    Recebe N avaliações da MESMA questão (N runs).
    Retorna lista de critérios com `acerto` = voto majoritário (≥ ceil(N/2)).

    Casa cada critério pelo par (letra, parte) — discursivas — ou (numero, parte) — peças.
    """
    if not runs:
        return []
    # Pega primeiro item NÃO vazio E que seja dict (juízes ruins às vezes injetam strings)
    first_item = None
    for run in runs:
        for it in run:
            if isinstance(it, dict):
                first_item = it; break
        if first_item is not None:
            break
    if first_item is None:
        return []
    key_fields = ("letra", "parte") if "letra" in first_item else ("numero", "parte")

    indexed: dict[tuple, list[dict]] = {}
    for run in runs:
        for item in run:
            if not isinstance(item, dict):
                continue
            key = tuple(str(item.get(k)) for k in key_fields)
            indexed.setdefault(key, []).append(item)

    consolidado = []
    threshold = (len(runs) + 1) // 2  # maioria simples
    for key, lst in indexed.items():
        acertos = sum(int(it.get("acerto") or 0) for it in lst)
        ref = lst[0]
        consolidado.append({
            **{k: ref.get(k) for k in key_fields},
            "pontos": ref.get("pontos"),
            "acerto": 1 if acertos >= threshold else 0,
            "votos_acerto": acertos,
            "n_runs": len(lst),
            "raciocinios": [it.get("raciocinio", "") for it in lst],
        })
    return consolidado
