"""Contrato entre o pipeline e o provedor de LLM.

O pipeline conhece este módulo e mais nada do provedor: nem `google.genai`,
nem `anthropic`. Trocar de provedor é trocar a implementação por trás do
`ProvedorLLM`, sem tocar em quem extrai.

A interface é fina de propósito — uma chamada de extração e os números que
ela custou. Não é um framework de LLM: não há cadeia, agente, memória nem
roteador aqui, e não deve haver. Ver ADR 003.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from app.seguranca.delimitadores import INSTRUCAO_DE_ISOLAMENTO

MILHAO = Decimal(1_000_000)

# Custo é dinheiro, então é Decimal (ver CLAUDE.md). Seis casas porque uma
# extração barata custa frações de centavo de dólar e a soma de um eval
# inteiro não pode ser engolida pelo arredondamento.
CASAS_DE_CUSTO = Decimal("0.000001")

INSTRUCAO_PADRAO = (
    "Extraia os campos pedidos do documento e devolva apenas dados no schema "
    "solicitado. Use somente o que está escrito no documento; não complete "
    "campo ausente com suposição.\n\n" + INSTRUCAO_DE_ISOLAMENTO
)


class ErroDeProvedor(Exception):
    """Falha originada na camada de provedor de LLM."""


class ErroDeConfiguracao(ErroDeProvedor):
    """Provedor mal configurado: chave ausente, nome desconhecido, modelo sem preço."""


class ErroDeExtracao(ErroDeProvedor):
    """O provedor respondeu, mas a resposta não virou uma instância do schema."""


class ErroTransitorio(ErroDeProvedor):
    """A chamada não chegou a produzir resposta, por algo que pode passar sozinho.

    A distinção que importa para o pipeline não é *qual* código HTTP veio, é se
    repetir a mesma chamada tem chance de dar outro resultado. Um 503 do
    provedor sobrecarregado tem; um schema inválido não tem. Esta é a família
    que o `LimitadorDeTaxa` sabe repetir com backoff — cada implementação
    traduz para cá os erros do seu SDK que se encaixam nisso.

    `espera_sugerida_s` é o que o provedor pediu explicitamente (cabeçalho
    `Retry-After`), quando pediu. O limitador usa o maior entre ela e o próprio
    backoff.
    """

    def __init__(self, mensagem: str, espera_sugerida_s: float | None = None) -> None:
        super().__init__(mensagem)
        self.espera_sugerida_s: float | None = espera_sugerida_s


class ErroDeTaxa(ErroTransitorio):
    """O provedor recusou por excesso de requisições (HTTP 429).

    Transitório de um tipo específico: a chamada foi recusada por cota, não por
    indisponibilidade. Vale a pena distinguir no relatório do eval — 429 depois
    do backoff diz que o corpus não cabe no tier, e 503 diz que o provedor
    estava fora do ar.
    """


@dataclass(frozen=True)
class UsoDeTokens:
    """Tokens cobrados por uma chamada."""

    entrada: int
    saida: int

    def __post_init__(self) -> None:
        if self.entrada < 0 or self.saida < 0:
            raise ValueError(f"contagem de tokens negativa: {self.entrada=}, {self.saida=}")

    @property
    def total(self) -> int:
        return self.entrada + self.saida


@dataclass(frozen=True)
class Preco:
    """Preço de tabela de um modelo, em dólar por milhão de tokens."""

    entrada_por_milhao: Decimal
    saida_por_milhao: Decimal

    def custo(self, uso: UsoDeTokens) -> Decimal:
        """Custo estimado da chamada, em dólar."""
        bruto = (
            Decimal(uso.entrada) * self.entrada_por_milhao
            + Decimal(uso.saida) * self.saida_por_milhao
        ) / MILHAO
        return bruto.quantize(CASAS_DE_CUSTO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ResultadoExtracao[TSchema: BaseModel]:
    """O que uma extração devolve: o dado validado e o que ele custou.

    `custo_estimado_usd` é o preço de tabela do modelo, não a fatura. No tier
    gratuito do Gemini a chamada não é cobrada e este número continua sendo
    preenchido — ele responde "quanto isto custaria pago", que é o dado que
    interessa para decidir se o pipeline cabe em orçamento.
    """

    dados: TSchema
    provedor: str
    modelo: str
    uso: UsoDeTokens
    custo_estimado_usd: Decimal
    do_cache: bool = False


@runtime_checkable
class ProvedorLLM(Protocol):
    """Um provedor capaz de extrair dados estruturados de um texto."""

    @property
    def nome(self) -> str:
        """Identificador curto do provedor, ex.: `gemini`."""
        ...

    @property
    def modelo(self) -> str:
        """Identificador exato do modelo em uso."""
        ...

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        """Extrai `schema` de `texto`.

        Devolve uma instância já validada — o que significa que os validadores
        do domínio (ver ADR 002) rodaram. Levanta `ErroDeExtracao` se a resposta
        não validar, e `ErroTransitorio` (`ErroDeTaxa` em 429) quando repetir a
        chamada tem chance de dar outro resultado.
        """
        ...
