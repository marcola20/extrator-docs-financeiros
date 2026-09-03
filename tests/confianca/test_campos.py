"""A definição única de igualdade por campo.

O teste que mais importa aqui é o último: os três consumidores — conversão,
grounding e eval — têm que concordar. Foi a discordância entre eles que
produziu a taxa de escape falsa do ADR 005.
"""

import pytest

from app.confianca.campos import (
    TIPOS,
    TipoDeCampo,
    ValorIlegivel,
    canonico,
    codigo_do_banco,
    iguais,
    tipo,
)
from app.extracao.schema_transporte import CAMPOS


class TestTabelaDeTipos:
    def test_todo_campo_do_schema_tem_tipo_declarado(self) -> None:
        """Campo novo sem tipo é erro na hora, não texto por omissão."""
        assert set(TIPOS) == set(CAMPOS)

    def test_campo_desconhecido_e_erro(self) -> None:
        with pytest.raises(KeyError, match="não tem tipo"):
            tipo("campo_que_nao_existe")


class TestCodigoDoBanco:
    @pytest.mark.parametrize(
        ("impresso", "esperado"),
        [
            ("748-X", "748"),
            ("001-9", "001"),
            ("341-7", "341"),
            ("756-0", "756"),
            ("104-x", "104"),
            ("756", "756"),
            ("748 - X", "748"),
            ("3417", "341"),
        ],
    )
    def test_descarta_o_dv_do_banco(self, impresso: str, esperado: str) -> None:
        assert codigo_do_banco(impresso) == esperado

    @pytest.mark.parametrize("ruim", ["", "abc", "12", "12345", "34-7"])
    def test_forma_impossivel_tem_erro_que_aponta_a_causa(self, ruim: str) -> None:
        with pytest.raises(ValorIlegivel) as erro:
            codigo_do_banco(ruim)

        mensagem = str(erro.value)
        assert "banco_codigo" in mensagem
        assert "três dígitos" in mensagem
        assert "341-7" in mensagem

    def test_a_separacao_e_por_regra_e_nao_por_acidente(self) -> None:
        """Antes um digitos() genérico resolvia: certo com DV em letra,
        `0019` com DV numérico, e a mensagem culpava o modelo."""
        assert codigo_do_banco("748-X") == codigo_do_banco("748") == "748"
        assert codigo_do_banco("001-9") == codigo_do_banco("001") == "001"


class TestCanonico:
    @pytest.mark.parametrize(
        ("campo", "escrito", "esperado"),
        [
            ("valor", "R$ 1.847,30", "1847.30"),
            ("valor", "1847,30", "1847.30"),
            ("valor", "1847.30", "1847.30"),
            ("vencimento", "19/11/2026", "2026-11-19"),
            ("vencimento", "2026-11-19", "2026-11-19"),
            ("beneficiario_cnpj", "03.721.465/0001-20", "03721465000120"),
            ("banco_codigo", "748-X", "748"),
            ("beneficiario_nome", "  Comércio  LTDA ", "comercio ltda"),
        ],
    )
    def test_formas_diferentes_dao_a_mesma_canonica(
        self, campo: str, escrito: str, esperado: str
    ) -> None:
        assert canonico(campo, escrito) == esperado

    @pytest.mark.parametrize(
        ("campo", "ruim"),
        [("valor", "grátis"), ("vencimento", "ontem"), ("linha_digitavel", "abc")],
    )
    def test_ilegivel_diz_as_formas_aceitas(self, campo: str, ruim: str) -> None:
        with pytest.raises(ValorIlegivel, match="aceit"):
            canonico(campo, ruim)


class TestIguais:
    @pytest.mark.parametrize(
        ("campo", "a", "b"),
        [
            ("banco_codigo", "748-X", "748"),
            ("banco_codigo", "001-9", "001"),
            ("valor", "1.847,30", "1847.30"),
            ("vencimento", "19/11/2026", "2026-11-19"),
            ("linha_digitavel", "34191.09008 00000", "3419109008 00000"),
            ("beneficiario_nome", "Comércio LTDA", "comercio ltda"),
        ],
    )
    def test_reconhece_o_mesmo_valor(self, campo: str, a: str, b: str) -> None:
        assert iguais(campo, a, b)

    @pytest.mark.parametrize(
        ("campo", "a", "b"),
        [
            ("banco_codigo", "748", "756"),
            ("valor", "1847.30", "1.00"),
            ("vencimento", "19/11/2026", "20/11/2026"),
        ],
    )
    def test_reconhece_valor_diferente(self, campo: str, a: str, b: str) -> None:
        assert not iguais(campo, a, b)

    def test_vazio_so_e_igual_a_vazio(self) -> None:
        assert iguais("nosso_numero", "", "")
        assert iguais("nosso_numero", "  ", "")
        assert not iguais("nosso_numero", "123", "")

    def test_ilegivel_nunca_e_igual_nem_a_outro_ilegivel(self) -> None:
        """Não se sabe o que nenhum dos dois é."""
        assert not iguais("valor", "grátis", "grátis")


class TestOsTresConsumidoresConcordam:
    """O invariante que o ADR 005 registra: uma definição, três usos."""

    @pytest.mark.parametrize(
        ("campo", "extraido", "gabarito"),
        [
            ("banco_codigo", "748-X", "748"),
            ("banco_codigo", "001-9", "001"),
            ("valor", "R$ 3.112,30", "3112.30"),
            ("vencimento", "19/11/2026", "2026-11-19"),
            ("beneficiario_cnpj", "03.721.465/0001-20", "03721465000120"),
        ],
    )
    def test_conversao_e_eval_veem_o_mesmo_valor(
        self, campo: str, extraido: str, gabarito: str
    ) -> None:
        """A conversão canoniza; o eval compara. Os dois pelo mesmo caminho."""
        assert canonico(campo, extraido) == canonico(campo, gabarito)
        assert iguais(campo, extraido, gabarito)

    def test_o_caso_que_produziu_o_escape_falso(self) -> None:
        """boleto-004: extraído `748-X`, gabarito `748`.

        O pipeline convertia para `748` e auto-aprovava, corretamente. O eval
        comparava texto, achava diferente, e contava como escape — a métrica
        principal acusando um pagamento errado que não existia.
        """
        assert iguais("banco_codigo", "748-X", "748")
        assert canonico("banco_codigo", "748-X") == "748"


def test_todo_tipo_tem_canonizador() -> None:
    for valor in TipoDeCampo:
        campo = next(c for c, t in TIPOS.items() if t is valor)
        assert canonico(campo, _exemplo(valor))


def _exemplo(valor: TipoDeCampo) -> str:
    return {
        TipoDeCampo.DIGITOS: "123456",
        TipoDeCampo.CODIGO_DE_BANCO: "341-7",
        TipoDeCampo.VALOR: "10,00",
        TipoDeCampo.DATA: "19/11/2026",
        TipoDeCampo.TEXTO: "texto",
    }[valor]
