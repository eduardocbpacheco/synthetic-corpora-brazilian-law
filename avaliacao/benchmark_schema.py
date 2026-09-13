"""
Dataclasses que definem o schema do benchmark jurídico OAB (2ª fase).

O benchmark é armazenado em arquivos JSONL, um objeto por linha.
Use QuestaoDiscursiva para questões dissertativas e QuestaoPeca para
questões de elaboração de peça processual.

Formato JSONL esperado (discursiva):
{
  "tipo": "discursiva",
  "id": "41-disc-1",
  "enunciado": "...",
  "gabarito": "...",
  "criterios": [{"id": "A", "texto": "...", "pontuacao_max": 0.60}],
  "exame": "41",
  "area": "Direito Administrativo",
  "split": "benchmark"
}

Formato JSONL esperado (peca):
{
  "tipo": "peca",
  "id": "41-peca-1",
  "enunciado": "...",
  "tipo_peca": "Mandado de Segurança",
  "gabarito": "...",
  "criterios": [{"id": "1", "texto": "...", "pontuacao_max": 0.55}],
  "exame": "41",
  "area": "Direito Administrativo",
  "split": "benchmark"
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Criterio:
    """Critério individual de avaliação de uma questão."""

    id: str                          # ex: "A", "B", "1", "2"
    texto: str                       # descrição do critério que o candidato deve cumprir
    pontuacao_max: float | None = None  # pontuação máxima do critério (ex: 0.60)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Criterio":
        pts = d.get("pontuacao_max")
        return cls(
            id=str(d["id"]),
            texto=d["texto"],
            pontuacao_max=float(pts) if pts is not None else None,
        )


@dataclass
class QuestaoDiscursiva:
    """Questão dissertativa da 2ª fase do Exame da OAB."""

    id: str                        # ex: "41-disc-1"
    enunciado: str                 # texto da questão
    gabarito: str                  # gabarito oficial completo
    criterios: List[Criterio]      # lista de critérios de avaliação
    exame: str                     # número do exame OAB, ex: "41"
    area: str                      # área jurídica, ex: "Direito Civil"
    split: str                     # "benchmark" ou "train"
    tipo: str = field(default="discursiva", init=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "QuestaoDiscursiva":
        criterios = [Criterio.from_dict(c) for c in d.get("criterios", [])]
        return cls(
            id=d["id"],
            enunciado=d["enunciado"],
            gabarito=d["gabarito"],
            criterios=criterios,
            exame=str(d["exame"]),
            area=d["area"],
            split=d["split"],
        )

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class QuestaoPeca:
    """Questão de elaboração de peça jurídica da 2ª fase do Exame da OAB."""

    id: str                        # ex: "41-peca-1"
    enunciado: str                 # texto da questão / caso prático
    tipo_peca: str                 # ex: "Recurso de Apelação", "Mandado de Segurança"
    gabarito: str                  # gabarito oficial / estrutura esperada da peça
    criterios: List[Criterio]      # critérios de avaliação (estrutura, argumentação, etc.)
    exame: str                     # número do exame OAB
    area: str                      # área jurídica, ex: "Direito Processual Civil"
    split: str                     # "benchmark" ou "train"
    tipo: str = field(default="peca", init=False)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "QuestaoPeca":
        criterios = [Criterio.from_dict(c) for c in d.get("criterios", [])]
        return cls(
            id=d["id"],
            enunciado=d["enunciado"],
            tipo_peca=d["tipo_peca"],
            gabarito=d["gabarito"],
            criterios=criterios,
            exame=str(d["exame"]),
            area=d["area"],
            split=d["split"],
        )

    def to_jsonl_line(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# Tipo união para facilitar type hints
Questao = QuestaoDiscursiva | QuestaoPeca


def load_benchmark(caminho_jsonl: str) -> List[Questao]:
    """
    Carrega um arquivo JSONL de benchmark e retorna lista de questões.

    Detecta automaticamente o tipo pelo campo "tipo" em cada linha.
    Filtra apenas questões com split="benchmark" por padrão.

    Args:
        caminho_jsonl: Caminho para o arquivo .jsonl

    Returns:
        Lista de QuestaoDiscursiva ou QuestaoPeca
    """
    questoes: List[Questao] = []
    with open(caminho_jsonl, "r", encoding="utf-8") as f:
        for i, linha in enumerate(f, 1):
            linha = linha.strip()
            if not linha:
                continue
            try:
                d = json.loads(linha)
            except json.JSONDecodeError as e:
                print(f"[AVISO] Linha {i} inválida em {caminho_jsonl}: {e}")
                continue

            tipo = d.get("tipo", "discursiva")
            if tipo == "discursiva":
                questoes.append(QuestaoDiscursiva.from_dict(d))
            elif tipo == "peca":
                questoes.append(QuestaoPeca.from_dict(d))
            else:
                print(f"[AVISO] Tipo desconhecido na linha {i}: {tipo!r}")

    return questoes


def load_benchmark_split(caminho_jsonl: str, split: str = "benchmark") -> List[Questao]:
    """Carrega apenas questões de um determinado split."""
    todas = load_benchmark(caminho_jsonl)
    return [q for q in todas if q.split == split]
