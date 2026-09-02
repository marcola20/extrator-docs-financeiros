"""Testes da montagem e conversão entre código de barras e linha digitável."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.dominio.digito_verificador import valida_linha_digitavel
from app.dominio.linha_digitavel import (
    DATA_BASE_FATOR,
    FATOR_MAXIMO,
    FATOR_REINICIO,
    codigo_barras_de_linha_digitavel,
    fator_vencimento,
    formata_linha_digitavel,
    linha_digitavel_de_codigo_barras,
    monta_codigo_barras,
    valor_em_centavos,
)

CAMPO_LIVRE = "1090000000012345678900000"


class TestFatorVencimento:
    @pytest.mark.parametrize(
        ("vencimento", "fator"),
        [
            # Marcos documentados pela Febraban.
            (date(1997, 10, 7), 0),
            (date(2000, 7, 3), 1000),
            (date(2025, 2, 21), FATOR_MAXIMO),
            # Virada do ciclo: no dia seguinte o fator volta para 1000.
            (date(2025, 2, 22), FATOR_REINICIO),
            (date(2025, 2, 23), 1001),
            # Boletos do ciclo novo.
            (date(2026, 9, 2), 1557),
            (date(2026, 12, 25), 1671),
        ],
    )
    def test_datas_de_referencia(self, vencimento: date, fator: int) -> None:
        assert fator_vencimento(vencimento) == fator

    def test_fator_cabe_sempre_em_quatro_digitos(self) -> None:
        vencimento = date(2025, 2, 22)
        for _ in range(0, 4000):
            assert FATOR_REINICIO <= fator_vencimento(vencimento) <= FATOR_MAXIMO
            vencimento += timedelta(days=1)

    def test_recusa_data_anterior_a_base(self) -> None:
        with pytest.raises(ValueError, match="anterior à data base"):
            fator_vencimento(DATA_BASE_FATOR - timedelta(days=1))


class TestValorEmCentavos:
    @pytest.mark.parametrize(
        ("valor", "centavos"),
        [
            (Decimal("0.01"), 1),
            (Decimal("1234.56"), 123456),
            (Decimal("1234.5"), 123450),
            (Decimal("99999999.99"), 9999999999),
        ],
    )
    def test_converte(self, valor: Decimal, centavos: int) -> None:
        assert valor_em_centavos(valor) == centavos

    def test_recusa_fracao_de_centavo(self) -> None:
        with pytest.raises(ValueError, match="fração de centavo"):
            valor_em_centavos(Decimal("10.005"))


class TestMontaCodigoBarras:
    def test_monta_com_o_layout_esperado(self) -> None:
        codigo = monta_codigo_barras(
            banco_codigo="341",
            vencimento=date(2026, 9, 15),
            valor=Decimal("1234.56"),
            campo_livre=CAMPO_LIVRE,
        )

        assert len(codigo) == 44
        assert codigo[0:3] == "341"
        assert codigo[3] == "9"
        assert codigo[4].isdigit()
        assert codigo[5:9] == "1570"
        assert codigo[9:19] == "0000123456"
        assert codigo[19:44] == CAMPO_LIVRE

    @pytest.mark.parametrize("banco", ["34", "3411", "abc"])
    def test_recusa_codigo_de_banco_invalido(self, banco: str) -> None:
        with pytest.raises(ValueError, match="código do banco"):
            monta_codigo_barras(
                banco_codigo=banco,
                vencimento=date(2026, 9, 15),
                valor=Decimal("10.00"),
                campo_livre=CAMPO_LIVRE,
            )

    @pytest.mark.parametrize("livre", ["", "123", CAMPO_LIVRE + "0", "x" * 25])
    def test_recusa_campo_livre_invalido(self, livre: str) -> None:
        with pytest.raises(ValueError, match="campo livre"):
            monta_codigo_barras(
                banco_codigo="341",
                vencimento=date(2026, 9, 15),
                valor=Decimal("10.00"),
                campo_livre=livre,
            )


class TestConversao:
    def test_ida_e_volta_preserva_o_codigo(self) -> None:
        codigo = monta_codigo_barras(
            banco_codigo="237",
            vencimento=date(2026, 3, 10),
            valor=Decimal("87.65"),
            campo_livre=CAMPO_LIVRE,
        )

        linha = linha_digitavel_de_codigo_barras(codigo)

        assert len(linha) == 47
        assert codigo_barras_de_linha_digitavel(linha) == codigo

    def test_linha_gerada_passa_na_validacao(self) -> None:
        codigo = monta_codigo_barras(
            banco_codigo="001",
            vencimento=date(2026, 11, 30),
            valor=Decimal("4321.09"),
            campo_livre=CAMPO_LIVRE,
        )

        resultado = valida_linha_digitavel(linha_digitavel_de_codigo_barras(codigo))

        assert resultado.valido, resultado.descricao()

    def test_campos_da_linha_apontam_para_o_codigo_de_barras(self) -> None:
        codigo = monta_codigo_barras(
            banco_codigo="104",
            vencimento=date(2026, 5, 20),
            valor=Decimal("50.00"),
            campo_livre=CAMPO_LIVRE,
        )

        linha = linha_digitavel_de_codigo_barras(codigo)

        assert linha[0:4] == codigo[0:4]  # banco e moeda
        assert linha[32] == codigo[4]  # DV geral
        assert linha[33:47] == codigo[5:19]  # fator e valor

    @pytest.mark.parametrize("codigo", ["", "1" * 43, "1" * 45])
    def test_recusa_codigo_de_barras_com_tamanho_errado(self, codigo: str) -> None:
        with pytest.raises(ValueError, match="código de barras"):
            linha_digitavel_de_codigo_barras(codigo)

    @pytest.mark.parametrize("linha", ["", "1" * 46, "1" * 48])
    def test_recusa_linha_com_tamanho_errado(self, linha: str) -> None:
        with pytest.raises(ValueError, match="linha digitável"):
            codigo_barras_de_linha_digitavel(linha)


class TestFormataLinhaDigitavel:
    def test_formata_nos_cinco_campos(self) -> None:
        linha = "34191090080000001234456789000009715700000123456"

        assert formata_linha_digitavel(linha) == (
            "34191.09008 00000.012344 56789.000009 7 15700000123456"
        )

    def test_formatacao_e_reversivel_pela_validacao(self) -> None:
        linha = "34191090080000001234456789000009715700000123456"

        assert valida_linha_digitavel(formata_linha_digitavel(linha)).valido

    def test_recusa_tamanho_errado(self) -> None:
        with pytest.raises(ValueError, match="linha digitável"):
            formata_linha_digitavel("123")
