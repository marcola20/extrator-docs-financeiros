"""Dublês para testar a camada de LLM sem tocar em rede.

`ProvedorFalso` existe também como prova do contrato: se ele para de servir
como `ProvedorLLM`, ou o Protocol mudou ou uma implementação divergiu.
"""

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel

from app.llm.provedor import (
    INSTRUCAO_PADRAO,
    ResultadoExtracao,
    UsoDeTokens,
)


class DocumentoFalso(BaseModel):
    """Schema mínimo para exercitar a extração."""

    titulo: str
    valor: Decimal


CARGA_PADRAO = {"titulo": "Boleto de teste", "valor": "123.45"}


class ProvedorFalso:
    """Provedor que devolve uma carga fixa e anota o que foi pedido."""

    def __init__(
        self,
        *,
        carga: dict[str, object] | None = None,
        erros: Sequence[Exception] = (),
        nome: str = "falso",
        modelo: str = "falso-1",
        uso: UsoDeTokens | None = None,
        custo: Decimal = Decimal("0.000100"),
    ) -> None:
        self._carga = carga if carga is not None else dict(CARGA_PADRAO)
        self._erros = list(erros)
        self._nome = nome
        self._modelo = modelo
        self._uso = uso if uso is not None else UsoDeTokens(entrada=100, saida=20)
        self._custo = custo
        self.chamadas: list[tuple[str, str]] = []

    @property
    def nome(self) -> str:
        return self._nome

    @property
    def modelo(self) -> str:
        return self._modelo

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        self.chamadas.append((texto, instrucao))
        if self._erros:
            raise self._erros.pop(0)
        return ResultadoExtracao(
            dados=schema.model_validate(self._carga),
            provedor=self._nome,
            modelo=self._modelo,
            uso=self._uso,
            custo_estimado_usd=self._custo,
        )


class RelogioFalso:
    """Relógio monotônico controlado, para o limitador não esperar de verdade."""

    def __init__(self) -> None:
        self.instante = 0.0
        self.dormidas: list[float] = []

    def agora(self) -> float:
        return self.instante

    def dorme(self, segundos: float) -> None:
        self.dormidas.append(segundos)
        self.instante += segundos

    def avanca(self, segundos: float) -> None:
        self.instante += segundos
