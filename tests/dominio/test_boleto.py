"""Testes do schema Boleto e dos seus validadores."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from app.dominio.boleto import Boleto
from app.dominio.digito_verificador import modulo11_boleto
from app.dominio.linha_digitavel import linha_digitavel_de_codigo_barras

# banco 341, vencimento 15/09/2026 (fator 1570), valor R$ 1.234,56
LINHA = "34191090080000001234456789000009715700000123456"
LINHA_FORMATADA = "34191.09008 00000.012344 56789.000009 7 15700000123456"

CAMPOS_MINIMOS: dict[str, Any] = {
    "linha_digitavel": LINHA,
    "beneficiario_nome": "Companhia Sintética de Energia S.A.",
    "beneficiario_cnpj": "11222333000181",
    "valor": Decimal("1234.56"),
    "vencimento": date(2026, 9, 15),
    "banco_codigo": "341",
    "banco_nome": "Itaú Unibanco",
}


def monta(**alteracoes: Any) -> Boleto:
    """Cria um boleto válido, trocando só os campos passados."""
    return Boleto(**{**CAMPOS_MINIMOS, **alteracoes})


class TestBoletoValido:
    def test_aceita_os_campos_minimos(self) -> None:
        boleto = monta()

        assert boleto.linha_digitavel == LINHA
        assert boleto.pagador_nome is None
        assert boleto.pagador_cpf_cnpj is None
        assert boleto.nosso_numero is None

    def test_aceita_pagador_com_cpf(self) -> None:
        boleto = monta(pagador_nome="Ana Sintética", pagador_cpf_cnpj="111.444.777-35")

        assert boleto.pagador_cpf_cnpj == "11144477735"

    def test_aceita_pagador_com_cnpj(self) -> None:
        boleto = monta(pagador_nome="Loja Sintética Ltda", pagador_cpf_cnpj="00.000.000/0001-91")

        assert boleto.pagador_cpf_cnpj == "00000000000191"

    def test_guarda_valor_como_decimal(self) -> None:
        boleto = monta()

        assert isinstance(boleto.valor, Decimal)
        assert boleto.valor == Decimal("1234.56")


class TestNormalizacao:
    def test_aceita_linha_formatada_e_guarda_so_os_digitos(self) -> None:
        assert monta(linha_digitavel=LINHA_FORMATADA).linha_digitavel == LINHA

    def test_aceita_cnpj_formatado(self) -> None:
        assert monta(beneficiario_cnpj="11.222.333/0001-81").beneficiario_cnpj == "11222333000181"

    @pytest.mark.parametrize("entrada", ["1", 1, "01", "001"])
    def test_completa_o_codigo_do_banco_com_zeros(self, entrada: Any) -> None:
        linha = _linha_valida(banco="001", valor_centavos=123456, fator=1570)

        boleto = monta(linha_digitavel=linha, banco_codigo=entrada)

        assert boleto.banco_codigo == "001"

    def test_nosso_numero_em_branco_vira_none(self) -> None:
        assert monta(nosso_numero="   ").nosso_numero is None

    def test_propriedade_devolve_a_linha_formatada(self) -> None:
        assert monta().linha_digitavel_formatada == LINHA_FORMATADA


class TestLinhaDigitavelInvalida:
    def test_recusa_linha_com_dv_trocado(self) -> None:
        mutante = LINHA[:9] + str((int(LINHA[9]) + 1) % 10) + LINHA[10:]

        with pytest.raises(ValidationError, match="campo_1"):
            monta(linha_digitavel=mutante)

    @pytest.mark.parametrize("linha", ["", "123", LINHA + "0"])
    def test_recusa_tamanho_errado(self, linha: str) -> None:
        with pytest.raises(ValidationError, match="47 dígitos"):
            monta(linha_digitavel=linha)


class TestDocumentosInvalidos:
    def test_recusa_cnpj_do_beneficiario_invalido(self) -> None:
        with pytest.raises(ValidationError, match="CNPJ do beneficiário inválido"):
            monta(beneficiario_cnpj="11222333000180")

    def test_recusa_cnpj_de_digitos_repetidos(self) -> None:
        with pytest.raises(ValidationError, match="CNPJ do beneficiário inválido"):
            monta(beneficiario_cnpj="11111111111111")

    def test_recusa_cpf_do_pagador_invalido(self) -> None:
        with pytest.raises(ValidationError, match="CPF do pagador inválido"):
            monta(pagador_cpf_cnpj="11144477730")

    def test_recusa_documento_com_tamanho_estranho(self) -> None:
        with pytest.raises(ValidationError, match="11 ou 14 dígitos"):
            monta(pagador_cpf_cnpj="1234567890")


class TestValor:
    def test_recusa_float(self) -> None:
        with pytest.raises(ValidationError, match="nunca float"):
            monta(valor=1234.56)

    def test_aceita_string(self) -> None:
        assert monta(valor="1234.56").valor == Decimal("1234.56")

    def test_recusa_string_que_nao_e_numero(self) -> None:
        with pytest.raises(ValidationError, match="valor monetário inválido"):
            monta(valor="mil reais")

    def test_recusa_fracao_de_centavo(self) -> None:
        with pytest.raises(ValidationError, match="fração de centavo"):
            monta(valor=Decimal("1234.565"))

    @pytest.mark.parametrize("valor", [Decimal("0"), Decimal("-1.00")])
    def test_recusa_valor_nao_positivo(self, valor: Decimal) -> None:
        with pytest.raises(ValidationError):
            monta(valor=valor)


class TestCoerenciaComALinha:
    def test_recusa_banco_diferente_do_que_esta_na_linha(self) -> None:
        with pytest.raises(ValidationError, match="não confere com a linha digitável"):
            monta(banco_codigo="237")

    def test_recusa_valor_diferente_do_que_esta_na_linha(self) -> None:
        with pytest.raises(ValidationError, match=r"não confere com a linha digitável \(R\$"):
            monta(valor=Decimal("999.99"))

    def test_recusa_vencimento_diferente_do_fator(self) -> None:
        with pytest.raises(ValidationError, match="não confere com o fator"):
            monta(vencimento=date(2026, 9, 16))

    def test_nao_cobra_coerencia_quando_a_linha_traz_valor_zerado(self) -> None:
        """Boleto sem valor definido leva zeros na linha; o campo impresso vale."""
        linha_sem_valor = _linha_valida(valor_centavos=0, fator=1570)

        boleto = monta(linha_digitavel=linha_sem_valor, valor=Decimal("77.00"))

        assert boleto.valor == Decimal("77.00")

    def test_nao_cobra_coerencia_quando_a_linha_traz_fator_zerado(self) -> None:
        linha_sem_fator = _linha_valida(valor_centavos=123456, fator=0)

        boleto = monta(linha_digitavel=linha_sem_fator, vencimento=date(2030, 1, 1))

        assert boleto.vencimento == date(2030, 1, 1)


class TestSerializacao:
    def test_dump_json_preserva_o_valor_como_texto(self) -> None:
        dados = monta().model_dump(mode="json")

        assert dados["valor"] == "1234.56"
        assert dados["vencimento"] == "2026-09-15"

    def test_ida_e_volta_por_json(self) -> None:
        original = monta(pagador_nome="Ana Sintética", pagador_cpf_cnpj="11144477735")

        assert Boleto.model_validate_json(original.model_dump_json()) == original

    def test_recusa_campo_desconhecido(self) -> None:
        with pytest.raises(ValidationError):
            monta(campo_inventado="x")


def _linha_valida(*, valor_centavos: int, fator: int, banco: str = "341") -> str:
    """Monta uma linha com todos os DVs certos para o fator e o valor pedidos."""
    sem_dv = f"{banco}9{fator:04d}{valor_centavos:010d}1090000000012345678900000"
    codigo = f"{sem_dv[:4]}{modulo11_boleto(sem_dv)}{sem_dv[4:]}"
    return linha_digitavel_de_codigo_barras(codigo)
