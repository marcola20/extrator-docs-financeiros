"""Contrato do Protocol e a aritmética de custo."""

from decimal import Decimal

import pytest

from app.llm.provedor import (
    Preco,
    ProvedorLLM,
    ResultadoExtracao,
    UsoDeTokens,
)
from tests.llm.falso import DocumentoFalso, ProvedorFalso


def _usa_provedor(provedor: ProvedorLLM) -> ResultadoExtracao[DocumentoFalso]:
    """Aceita qualquer `ProvedorLLM`.

    O valor deste teste está tanto no runtime quanto no mypy: passar um objeto
    que não implemente o Protocol aqui não compila em modo strict.
    """
    return provedor.extrai("documento", DocumentoFalso)


def test_provedor_falso_satisfaz_o_protocol() -> None:
    falso = ProvedorFalso()

    assert isinstance(falso, ProvedorLLM)

    resultado = _usa_provedor(falso)

    assert isinstance(resultado.dados, DocumentoFalso)
    assert resultado.dados.valor == Decimal("123.45")


def test_extracao_devolve_tokens_e_custo() -> None:
    falso = ProvedorFalso(uso=UsoDeTokens(entrada=1_000, saida=200), custo=Decimal("0.000750"))

    resultado = falso.extrai("documento", DocumentoFalso)

    assert resultado.uso.entrada == 1_000
    assert resultado.uso.saida == 200
    assert resultado.uso.total == 1_200
    assert resultado.custo_estimado_usd == Decimal("0.000750")
    assert resultado.do_cache is False


def test_custo_usa_decimal_e_nao_float() -> None:
    """Um milhão de tokens de entrada custa exatamente o preço de tabela."""
    preco = Preco(Decimal("0.30"), Decimal("2.50"))

    custo = preco.custo(UsoDeTokens(entrada=1_000_000, saida=1_000_000))

    assert custo == Decimal("2.800000")
    assert isinstance(custo, Decimal)


def test_custo_de_chamada_pequena_nao_arredonda_para_zero() -> None:
    """O eval soma milhares de chamadas; engolir a fração inviabiliza a conta."""
    preco = Preco(Decimal("0.30"), Decimal("2.50"))

    custo = preco.custo(UsoDeTokens(entrada=1_200, saida=300))

    # 1200 * 0.30/1e6 + 300 * 2.50/1e6 = 0.00036 + 0.00075
    assert custo == Decimal("0.001110")


def test_uso_de_tokens_recusa_contagem_negativa() -> None:
    with pytest.raises(ValueError, match="negativa"):
        UsoDeTokens(entrada=-1, saida=0)
