"""Normalização de valores e datas escritos de formas diferentes."""

from datetime import date
from decimal import Decimal

import pytest

from app.confianca import normalizacao


class TestNumero:
    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("1.847,30", Decimal("1847.30")),
            ("1847,30", Decimal("1847.30")),
            ("R$ 1.847,30", Decimal("1847.30")),
            ("R$1.847,30", Decimal("1847.30")),
            ("1847.30", Decimal("1847.30")),
            ("1,847.30", Decimal("1847.30")),
            ("1.234.567,89", Decimal("1234567.89")),
            ("0,50", Decimal("0.50")),
            ("1.847", Decimal("1847")),
        ],
    )
    def test_le_as_formas_usuais(self, texto: str, esperado: Decimal) -> None:
        assert normalizacao.numero(texto) == esperado

    def test_devolve_decimal_e_nunca_float(self) -> None:
        lido = normalizacao.numero("1.847,30")

        assert isinstance(lido, Decimal)

    @pytest.mark.parametrize("texto", ["", "abc", "R$", "   "])
    def test_recusa_o_que_nao_e_numero(self, texto: str) -> None:
        assert normalizacao.numero(texto) is None


class TestData:
    @pytest.mark.parametrize("texto", ["19/11/2026", "19-11-2026", "19.11.2026", "2026-11-19"])
    def test_le_as_formas_usuais(self, texto: str) -> None:
        assert normalizacao.data(texto) == date(2026, 11, 19)

    @pytest.mark.parametrize("texto", ["", "ontem", "32/13/2026"])
    def test_recusa_o_que_nao_e_data(self, texto: str) -> None:
        assert normalizacao.data(texto) is None


class TestFormasImpressas:
    def test_valor_cobre_com_e_sem_separador_de_milhar(self) -> None:
        formas = normalizacao.valor_como_impresso(Decimal("1847.30"))

        assert "1.847,30" in formas
        assert "1847,30" in formas
        assert "1847.30" in formas

    def test_data_cobre_os_formatos_de_impressao(self) -> None:
        formas = normalizacao.data_como_impressa(date(2026, 11, 19))

        assert "19/11/2026" in formas
        assert "2026-11-19" in formas
