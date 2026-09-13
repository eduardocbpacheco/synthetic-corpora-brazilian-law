"""
Módulo do juiz LLM para avaliação de respostas jurídicas — Rabula-style.

Avalia CRITÉRIO A CRITÉRIO, retornando resultado estruturado com pontuações
individuais. Nunca colapsa para uma nota final — isso é responsabilidade
do script de agregação (aggregate_results.py).

Estrutura de retorno de avaliar_resposta():
    {
        "criterios": [
            {
                "id":               "A",
                "texto":            "Atipicidade da conduta...",
                "acerto":           1,          # 0 ou 1
                "pontuacao_max":    0.60,
                "pontuacao_obtida": 0.60,
            },
            {
                "id":               "B",
                "texto":            "Violação à reserva...",
                "acerto":           0,
                "pontuacao_max":    0.55,
                "pontuacao_obtida": 0.0,
            }
        ],
        "pontuacao_obtida": 0.60,   # soma das pontuacoes obtidas
        "pontuacao_max":    1.15,   # soma das pontuacoes máximas
        "score_ponderado":  0.522,  # pontuacao_obtida / pontuacao_max
        "n_criterios":      2,
        "n_acertos":        1,
    }

Backends suportados:
  - "anthropic": Claude via API (padrão para produção)
  - "groq":      Llama 3.3 70B via Groq API (sem restrições de ToS para treino)
  - "mlx":       modelo local via mlx_lm (ex: sabiazinho-3 local)

Uso:
    from judge import avaliar_criterio, avaliar_resposta

    resultado = avaliar_resposta(
        questao="...",
        resposta_candidato="...",
        gabarito="...",
        criterios=[{"id": "A", "texto": "...", "pontuacao_max": 0.60}, ...],
        backend="anthropic",
        judge_model="claude-haiku-4-5-20251001",
    )
    # resultado["criterios"][0]["acerto"] → 1
    # resultado["pontuacao_obtida"]       → 0.60
    # resultado["score_ponderado"]        → 0.522
"""

from __future__ import annotations

import os
import re
import time
import logging
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt do juiz
# ---------------------------------------------------------------------------

PROMPT_JUIZ = """Você é um avaliador jurídico especializado no Exame da OAB (2ª fase).

QUESTÃO:
{questao}

GABARITO OFICIAL:
{gabarito}

CRITÉRIO DE AVALIAÇÃO:
{criterio}

RESPOSTA DO CANDIDATO:
{resposta}

---
O candidato atendeu a este critério específico?

Regras:
- Avalie APENAS o critério acima, não a resposta como um todo.
- O critério é binário: ou foi atendido (SIM) ou não foi (NÃO).
- Aceite paráfrases corretas e artigos equivalentes quando o gabarito listar alternativas ("ou").
- Ignore erros de formatação que não comprometam o conteúdo jurídico.

Responda APENAS com "SIM" ou "NÃO"."""


# ---------------------------------------------------------------------------
# Backend: Anthropic (Claude)
# ---------------------------------------------------------------------------

def _avaliar_anthropic(
    prompt: str,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 16,
    retries: int = 3,
) -> str:
    """Chama a API Anthropic e retorna o texto bruto da resposta."""
    try:
        import anthropic
    except ImportError:
        raise ImportError(
            "SDK da Anthropic não instalado. Execute: pip install anthropic"
        )

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    for tentativa in range(1, retries + 1):
        try:
            msg = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text.strip()
        except Exception as e:
            logger.warning(f"[Anthropic] Tentativa {tentativa}/{retries} falhou: {e}")
            if tentativa < retries:
                time.sleep(2 ** tentativa)
            else:
                raise


# ---------------------------------------------------------------------------
# Backend: Groq (Llama 3.3 70B)
# ---------------------------------------------------------------------------

GROQ_JUDGE_MODEL = "llama-3.3-70b-versatile"


def _avaliar_groq(
    prompt: str,
    model: str = GROQ_JUDGE_MODEL,
    max_tokens: int = 16,
    retries: int = 5,
) -> str:
    """Chama a API Groq e retorna o texto bruto da resposta."""
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("SDK da Groq não instalado. Execute: pip install groq")

    import os
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    for tentativa in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            espera = 60 if "rate_limit" in type(e).__name__.lower() or "429" in str(e) else 2 ** tentativa
            logger.warning(f"[Groq] Tentativa {tentativa}/{retries} falhou: {e} — aguardando {espera}s")
            if tentativa < retries:
                time.sleep(espera)
            else:
                raise


# ---------------------------------------------------------------------------
# Backend: Azure OpenAI (GPT-4o-mini)
# ---------------------------------------------------------------------------

def _avaliar_azure(prompt: str, model: str = "", max_tokens: int = 16, retries: int = 3) -> str:
    """Chama Azure OpenAI (deployment GPT-4o-mini) e retorna o texto bruto."""
    try:
        from openai import AzureOpenAI
    except ImportError:
        raise ImportError("Execute: pip install openai")

    client = AzureOpenAI(
        azure_endpoint=os.environ["API_ENDPOINT"],
        api_key=os.environ["API_KEY"],
        api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
    )
    model = model or os.environ.get("MODEL_NAME", "gpt-4o-mini")

    for tentativa in range(1, retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            espera = 60 if "429" in str(e) or "throttl" in str(e).lower() else 2 ** tentativa
            logger.warning(f"[Azure] Tentativa {tentativa}/{retries} falhou: {e} — aguardando {espera}s")
            if tentativa < retries:
                time.sleep(espera)
            else:
                raise


# ---------------------------------------------------------------------------
# Backend: MLX local
# ---------------------------------------------------------------------------

_mlx_model_cache: dict[str, Any] = {}


def _carregar_mlx(model_path: str) -> tuple:
    """Carrega (e cacheia) modelo MLX para o juiz."""
    if model_path not in _mlx_model_cache:
        from mlx_lm import load
        logger.info(f"[MLX Judge] Carregando modelo juiz: {model_path}")
        model, tokenizer = load(model_path)
        _mlx_model_cache[model_path] = (model, tokenizer)
    return _mlx_model_cache[model_path]


def _avaliar_mlx(prompt: str, model_path: str, max_tokens: int = 32) -> str:
    """Gera resposta com modelo MLX local."""
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler

    model, tokenizer = _carregar_mlx(model_path)

    if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
        messages = [{"role": "user", "content": prompt}]
        texto_formatado = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
    else:
        texto_formatado = prompt

    sampler = make_sampler(temp=0.0)  # juiz sempre determinístico
    resposta = generate(
        model,
        tokenizer,
        prompt=texto_formatado,
        max_tokens=max_tokens,
        sampler=sampler,
        verbose=False,
    )
    return resposta.strip()


# ---------------------------------------------------------------------------
# Parse da resposta do juiz
# ---------------------------------------------------------------------------

def _parse_sim_nao(texto: str) -> int:
    """Interpreta resposta SIM/NÃO do juiz. Retorna 1 ou 0."""
    t = texto.upper().strip()
    if re.search(r"\bSIM\b", t):
        return 1
    if re.search(r"\bN[ÃA]O\b", t) or re.search(r"\bNO\b", t):
        return 0
    # Fallback por presença de substring
    if "SIM" in t:
        return 1
    logger.warning(f"[Judge] Resposta ambígua: {texto!r} → assumindo 0.")
    return 0


# ---------------------------------------------------------------------------
# Funções públicas
# ---------------------------------------------------------------------------

def avaliar_criterio(
    resposta: str,
    criterio: str,
    gabarito: str,
    questao: str = "",
    backend: str = "anthropic",
    judge_model: str = "claude-haiku-4-5-20251001",
) -> int:
    """
    Avalia se a resposta cumpre um critério específico.

    Returns:
        1 se cumprido, 0 caso contrário.
    """
    prompt = PROMPT_JUIZ.format(
        questao=questao,
        gabarito=gabarito,
        criterio=criterio,
        resposta=resposta,
    )

    if backend == "anthropic":
        texto = _avaliar_anthropic(prompt, model=judge_model)
    elif backend == "groq":
        texto = _avaliar_groq(prompt, model=judge_model or GROQ_JUDGE_MODEL)
    elif backend == "azure":
        texto = _avaliar_azure(prompt, model=judge_model)
    elif backend == "mlx":
        texto = _avaliar_mlx(prompt, model_path=judge_model)
    else:
        raise ValueError(f"Backend desconhecido: {backend!r}. Use 'anthropic', 'groq', 'azure' ou 'mlx'.")

    return _parse_sim_nao(texto)


def avaliar_resposta(
    questao: str,
    resposta_candidato: str,
    gabarito: str,
    criterios: list[dict],
    backend: str = "anthropic",
    judge_model: str = "claude-haiku-4-5-20251001",
) -> dict:
    """
    Avalia uma resposta completa contra todos os critérios, com pontuações.

    Args:
        questao:             Enunciado da questão.
        resposta_candidato:  Texto da resposta a avaliar.
        gabarito:            Gabarito oficial.
        criterios:           Lista de dicts com chaves:
                               "id"            (str, obrigatório)
                               "texto"         (str, obrigatório)
                               "pontuacao_max" (float, opcional — default 1.0)
        backend:             "anthropic" ou "mlx".
        judge_model:         ID do modelo juiz.

    Returns:
        Dict estruturado com granularidade por critério:
        {
            "criterios": [
                {
                    "id":               str,
                    "texto":            str,
                    "acerto":           int,   # 0 ou 1
                    "pontuacao_max":    float,
                    "pontuacao_obtida": float,
                },
                ...
            ],
            "pontuacao_obtida": float,  # soma das pontuacoes obtidas
            "pontuacao_max":    float,  # soma das pontuacoes máximas
            "score_ponderado":  float,  # pontuacao_obtida / pontuacao_max  ∈ [0, 1]
            "n_criterios":      int,
            "n_acertos":        int,
        }
    """
    if not criterios:
        logger.warning("[Judge] Lista de critérios vazia.")
        return {
            "criterios": [],
            "pontuacao_obtida": 0.0,
            "pontuacao_max": 0.0,
            "score_ponderado": 0.0,
            "n_criterios": 0,
            "n_acertos": 0,
        }

    resultado_criterios = []

    for crit in criterios:
        crit_id    = crit.get("id", "?")
        crit_texto = crit.get("texto", "")
        pts_max    = float(crit.get("pontuacao_max") or 1.0)

        acerto = avaliar_criterio(
            resposta=resposta_candidato,
            criterio=crit_texto,
            gabarito=gabarito,
            questao=questao,
            backend=backend,
            judge_model=judge_model,
        )

        resultado_criterios.append({
            "id":               crit_id,
            "texto":            crit_texto,
            "acerto":           acerto,
            "pontuacao_max":    pts_max,
            "pontuacao_obtida": pts_max if acerto else 0.0,
        })

    pts_obtida = sum(c["pontuacao_obtida"] for c in resultado_criterios)
    pts_max    = sum(c["pontuacao_max"]    for c in resultado_criterios)
    n_acertos  = sum(c["acerto"]           for c in resultado_criterios)

    return {
        "criterios":        resultado_criterios,
        "pontuacao_obtida": round(pts_obtida, 4),
        "pontuacao_max":    round(pts_max, 4),
        "score_ponderado":  round(pts_obtida / pts_max, 4) if pts_max > 0 else 0.0,
        "n_criterios":      len(resultado_criterios),
        "n_acertos":        n_acertos,
    }
