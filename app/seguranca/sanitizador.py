"""Sanitização de documentos de origem não confiável.

## O que este módulo NÃO garante

O sanitizador **não é** a garantia do sistema, e não deve ser apresentado
como tal. Detecção por padrão de texto é uma corrida perdida: qualquer
padrão que se escreva aqui pode ser reformulado do outro lado. Um detector
de "ignore as instruções anteriores" não cobre "desconsidere o que foi dito
acima", que não cobre a mesma frase em inglês, em base64, ou dita de um
jeito que ninguém previu.

A garantia real é a validação determinística do ADR 002. Um atacante pode
induzir o modelo a escrever `valor: 1,00`; o que ele não consegue é produzir
uma linha digitável de 47 dígitos cujos quatro dígitos verificadores fechem
com esse valor. É aritmética, e ela não obedece a instrução nenhuma.

O que este módulo entrega, então, é outra coisa:

- **defesa em profundidade** — encarece o ataque e pega o oportunista;
- **sinal de alerta** — um documento com achado nunca é auto-aprovado, e o
  revisor humano recebe o trecho suspeito e onde ele está.

Ver ADR 004.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

MAX_TRECHO = 160


class Severidade(StrEnum):
    """Quão forte é o indício. Não é probabilidade de ataque."""

    ALTA = "alta"
    """Só existe de propósito: texto invisível, delimitador falso."""

    MEDIA = "media"
    """Compatível com ataque, mas com explicação inocente plausível."""

    BAIXA = "baixa"
    """Vale registrar para o revisor, não sustenta conclusão sozinho."""


class TipoAchado(StrEnum):
    """Qual detector encontrou, e o quê."""

    TEXTO_QUASE_INVISIVEL = "texto_quase_invisivel"
    FONTE_MINUSCULA = "fonte_minuscula"
    TEXTO_FORA_DA_PAGINA = "texto_fora_da_pagina"
    PADRAO_DE_INJECAO = "padrao_de_injecao"
    DELIMITADOR_FALSO = "delimitador_falso"
    DIVERGENCIA_TEXTO_IMAGEM = "divergencia_texto_imagem"


@dataclass(frozen=True, slots=True)
class Local:
    """Onde o achado está, para o revisor conseguir olhar."""

    pagina: int
    """Número da página, começando em 1."""

    x0: float | None = None
    topo: float | None = None
    x1: float | None = None
    base: float | None = None

    def __str__(self) -> str:
        if self.x0 is None or self.topo is None:
            return f"página {self.pagina}"
        return f"página {self.pagina}, ({self.x0:.0f}, {self.topo:.0f})"


@dataclass(frozen=True, slots=True)
class Achado:
    """Um indício encontrado, com o trecho e onde ele está."""

    tipo: TipoAchado
    severidade: Severidade
    local: Local
    trecho: str
    detalhe: str

    def __post_init__(self) -> None:
        if not self.trecho:
            raise ValueError("achado sem trecho não ajuda o revisor")

    def __str__(self) -> str:
        return f"[{self.severidade}] {self.tipo} em {self.local}: {self.detalhe} — {self.trecho!r}"


def recorta(texto: str) -> str:
    """Encurta um trecho para caber numa mensagem, sem perder o começo."""
    limpo = " ".join(texto.split())
    if len(limpo) <= MAX_TRECHO:
        return limpo
    return limpo[: MAX_TRECHO - 1] + "…"


@dataclass(frozen=True, slots=True)
class ResultadoSanitizacao:
    """O que a sanitização viu. Não decide o que fazer com o documento.

    A decisão é da política de roteamento (`app.seguranca.politica`), que é
    separada de propósito: detectar e decidir mudam por motivos diferentes e
    em ritmos diferentes.
    """

    documento: Path
    texto: str
    """Exatamente o texto que irá ao modelo — o mesmo que foi analisado."""

    achados: tuple[Achado, ...] = ()
    detectores_executados: frozenset[str] = field(default_factory=frozenset)

    @property
    def limpo(self) -> bool:
        return not self.achados

    @property
    def houve_o_que_inspecionar(self) -> bool:
        """Se havia camada de texto para os detectores olharem.

        Um PDF digitalizado tem zero chars e texto vazio: os três detectores
        rodam, não acham nada, e o documento sairia como limpo. Não é limpo —
        é não inspecionado, e a diferença precisa chegar à política.
        """
        return bool(self.texto.strip())

    @property
    def severidade_maxima(self) -> Severidade | None:
        if not self.achados:
            return None
        ordem = {Severidade.BAIXA: 0, Severidade.MEDIA: 1, Severidade.ALTA: 2}
        return max((a.severidade for a in self.achados), key=lambda s: ordem[s])

    def por_tipo(self, tipo: TipoAchado) -> tuple[Achado, ...]:
        return tuple(a for a in self.achados if a.tipo == tipo)

    def descricao(self) -> str:
        if self.limpo:
            return "nenhum achado"
        return "\n".join(str(a) for a in self.achados)
