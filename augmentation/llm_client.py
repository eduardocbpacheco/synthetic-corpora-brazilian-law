"""
llm_client.py — Cliente LLM unificado para todos os scripts de augmentation.

Detecta automaticamente o provider via variáveis de ambiente:
  - Bedrock:      AWS_ACCESS_KEY_ID (+ AWS_REGION) — Mistral Large 3, PADRÃO
  - Azure OpenAI: API_ENDPOINT + API_KEY + API_VERSION + MODEL_NAME
  - Groq:         GROQ_API_KEY
  - Together AI:  TOGETHER_API_KEY

DIRETRIZ DO PROJETO: todo dado de TREINO é gerado pelo melhor professor do
benchmark (Mistral Large 3 via Bedrock) — nunca por gpt-4o/gpt-4o-mini. Por isso
o Bedrock vem primeiro. Para forçar outro provider: LLM_PROVIDER=azure|groq|together.

Uso:
    from augmentation.llm_client import get_client, chat

    client, model = get_client()
    resposta = chat(client, model, "seu prompt aqui", max_tokens=2000)
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
log = logging.getLogger(__name__)


TEACHER_BEDROCK = "mistral.mistral-large-3-675b-instruct"   # melhor professor do benchmark


class _BedrockChatShim:
    """Expõe a interface .chat.completions.create() do OpenAI SDK em cima do
    Bedrock converse(), para que chat()/chat_paralelo() funcionem sem alteração."""

    def __init__(self, br):
        self._br = br
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, max_tokens=2000, temperature=0.4, **_):
        system = [{"text": m["content"]} for m in messages if m["role"] == "system"]
        conversa = [
            {"role": m["role"], "content": [{"text": m["content"]}]}
            for m in messages if m["role"] != "system"
        ]
        kwargs = dict(
            modelId=model,
            messages=conversa,
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        if system:
            kwargs["system"] = system
        r = self._br.converse(**kwargs)
        texto = r["output"]["message"]["content"][0]["text"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=texto))]
        )


def get_client() -> tuple:
    """
    Retorna (client, model_name) do provider disponível no .env.
    Prioridade: Bedrock (Mistral L3) > Azure > Groq > Together AI.
    """
    forcado = os.environ.get("LLM_PROVIDER", "").lower()

    # Bedrock / Mistral Large 3 — professor padrão do projeto
    if forcado in ("", "bedrock") and (
        os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE")
    ):
        import boto3
        from botocore.config import Config
        br = boto3.client(
            "bedrock-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
            config=Config(read_timeout=180, retries={"max_attempts": 3}),
        )
        model = os.environ.get("BEDROCK_MODEL_ID", TEACHER_BEDROCK)
        log.info(f"Provider: Bedrock | Modelo: {model}")
        return _BedrockChatShim(br), model

    # Azure OpenAI
    if os.environ.get("API_ENDPOINT") and os.environ.get("API_KEY"):
        from openai import AzureOpenAI
        client = AzureOpenAI(
            azure_endpoint=os.environ["API_ENDPOINT"],
            api_key=os.environ["API_KEY"],
            api_version=os.environ.get("API_VERSION", "2024-12-01-preview"),
        )
        model = os.environ.get("MODEL_NAME", "gpt-4o-mini")
        log.info(f"Provider: Azure OpenAI | Modelo: {model}")
        return client, model

    # Groq
    if os.environ.get("GROQ_API_KEY"):
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        model = "llama-3.3-70b-versatile"
        log.info(f"Provider: Groq | Modelo: {model}")
        return client, model

    # Together AI
    if os.environ.get("TOGETHER_API_KEY"):
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["TOGETHER_API_KEY"],
            base_url="https://api.together.xyz/v1",
        )
        model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
        log.info(f"Provider: Together AI | Modelo: {model}")
        return client, model

    raise EnvironmentError(
        "Nenhuma credencial LLM encontrada no .env. "
        "Configure API_KEY (Azure), GROQ_API_KEY ou TOGETHER_API_KEY."
    )


def chat_paralelo(
    client,
    model: str,
    prompts: list[tuple[str, str]],
    max_tokens: int = 2000,
    temperature: float = 0.4,
    workers: int = 5,
    on_result=None,
) -> list[str | None]:
    """
    Processa lista de prompts em paralelo.

    prompts: lista de (system, user)
    on_result(idx, resultado, exception): callback opcional para cada conclusão
    retorna: lista alinhada com prompts, valor=texto ou None se erro
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    resultados: list[str | None] = [None] * len(prompts)

    def _processar(idx: int) -> None:
        system, user = prompts[idx]
        try:
            resp = chat(client, model, user, system=system,
                        max_tokens=max_tokens, temperature=temperature)
            resultados[idx] = resp
            if on_result:
                on_result(idx, resp, None)
        except Exception as e:
            if on_result:
                on_result(idx, None, e)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_processar, i) for i in range(len(prompts))]
        for _ in as_completed(futures):
            pass
    return resultados


def chat(
    client,
    model: str,
    prompt: str,
    system: str = "",
    max_tokens: int = 2000,
    temperature: float = 0.4,
    retries: int = 5,
) -> str:
    """
    Chama o LLM com retry automático. Retorna o texto gerado.
    Compatível com OpenAI, AzureOpenAI e Groq (todos têm .chat.completions.create).
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for tentativa in range(1, retries + 1):
        try:
            r = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return r.choices[0].message.content.strip()
        except Exception as e:
            err = str(e)
            # Rate limit: espera mais
            espera = 60 if "429" in err or "rate" in err.lower() or "throttl" in err.lower() else 2 ** tentativa
            if tentativa < retries:
                log.warning(f"  Tentativa {tentativa}/{retries}: {type(e).__name__} — aguardando {espera}s")
                time.sleep(espera)
            else:
                raise
