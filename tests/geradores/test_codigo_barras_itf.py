"""Testes do desenho do código de barras Intercalado 2 de 5."""

import pytest

from app.geradores import codigo_barras_itf


class TestElementos:
    def test_alterna_barra_e_espaco(self) -> None:
        lista = list(codigo_barras_itf.elementos("1234"))

        for indice, (e_barra, _) in enumerate(lista):
            assert e_barra == (indice % 2 == 0)

    def test_quantidade_de_elementos(self) -> None:
        """4 do início + 10 por par de dígitos + 3 do fim."""
        assert len(list(codigo_barras_itf.elementos("1234"))) == 4 + 2 * 10 + 3
        assert len(list(codigo_barras_itf.elementos("0" * 44))) == 4 + 22 * 10 + 3

    def test_comeca_com_quatro_elementos_estreitos(self) -> None:
        inicio = list(codigo_barras_itf.elementos("1234"))[:4]

        assert [largura for _, largura in inicio] == [1, 1, 1, 1]

    def test_termina_com_barra_larga_espaco_e_barra_estreitos(self) -> None:
        fim = list(codigo_barras_itf.elementos("1234"))[-3:]

        assert fim == [(True, 3), (False, 1), (True, 1)]

    def test_cada_digito_tem_exatamente_dois_elementos_largos(self) -> None:
        for digito, padrao in codigo_barras_itf.PADROES.items():
            assert padrao.count(codigo_barras_itf.LARGO) == 2, digito
            assert len(padrao) == 5, digito

    def test_primeiro_digito_do_par_vira_barra_e_o_segundo_espaco(self) -> None:
        # 1 -> wnnnw nas barras, 0 -> nnwwn nos espaços
        miolo = list(codigo_barras_itf.elementos("10"))[4:-3]

        assert [largura for e_barra, largura in miolo if e_barra] == [3, 1, 1, 1, 3]
        assert [largura for e_barra, largura in miolo if not e_barra] == [1, 1, 3, 3, 1]

    @pytest.mark.parametrize("digitos", ["123", "12a4", ""])
    def test_recusa_entrada_invalida(self, digitos: str) -> None:
        with pytest.raises(ValueError):
            list(codigo_barras_itf.elementos(digitos))


class TestSvg:
    def test_gera_um_svg_com_barras(self) -> None:
        desenho = codigo_barras_itf.svg("34197157000001234561090000000012345678900000")

        assert desenho.startswith("<svg")
        assert desenho.endswith("</svg>")
        assert desenho.count("<rect") == 4 // 2 + 22 * 5 + 2

    def test_largura_total_bate_com_a_soma_das_unidades(self) -> None:
        digitos = "1234567890" * 4 + "1234"
        unidades = sum(largura for _, largura in codigo_barras_itf.elementos(digitos))

        desenho = codigo_barras_itf.svg(digitos, unidade_mm=0.5)

        assert f'width="{unidades * 0.5:.3f}mm"' in desenho
