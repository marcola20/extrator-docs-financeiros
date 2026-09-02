"""Testes dos dígitos verificadores.

Os casos de módulo 10 e 11 são conferidos à mão nos comentários, para que o
teste não dependa da mesma implementação que ele valida.
"""

import pytest

from app.dominio.digito_verificador import (
    CampoLinhaDigitavel,
    ResultadoValidacao,
    modulo10,
    modulo11_boleto,
    valida_cnpj,
    valida_cpf,
    valida_linha_digitavel,
)

# Linha montada para os testes, com todos os DVs corretos:
# banco 341, vencimento 15/09/2026 (fator 1570), valor R$ 1.234,56.
LINHA_VALIDA = "34191090080000001234456789000009715700000123456"
LINHA_VALIDA_FORMATADA = "34191.09008 00000.012344 56789.000009 7 15700000123456"

# Campos 1 a 3 de linhas digitáveis de exemplo de domínio público. Só os
# 32 primeiros dígitos, que são a parte cujos DVs módulo 10 dão para conferir
# sem conhecer o vencimento e o valor originais.
CAMPOS_EXEMPLOS_PUBLICOS = [
    "34191790010104351004791020150008",
    "23793381286000782781395000063305",
]


class TestModulo10:
    @pytest.mark.parametrize(
        ("digitos", "dv"),
        [
            # 8*2=16 -> 7, 7*1=7, 6*2=12 -> 3, 5*1=5, 4*2=8, 3*1=3, 2*2=4, 1*1=1
            # soma 38, próxima dezena 40, DV 2
            ("12345678", 2),
            # soma 0, resto 0, DV 0
            ("0000000000", 0),
            # 5*2=10 -> 1, soma 1, DV 9
            ("5", 9),
            # 5*2=10 -> 1, 4*1=4, soma 5, DV 5
            ("45", 5),
            # 1*2=2, 2*1=2, 3*2=6, soma 10, resto 0, DV 0
            ("321", 0),
        ],
    )
    def test_casos_conferidos_a_mao(self, digitos: str, dv: int) -> None:
        assert modulo10(digitos) == dv

    def test_campos_de_exemplos_publicos_fecham(self) -> None:
        for campos in CAMPOS_EXEMPLOS_PUBLICOS:
            assert modulo10(campos[0:9]) == int(campos[9])
            assert modulo10(campos[10:20]) == int(campos[20])
            assert modulo10(campos[21:31]) == int(campos[31])

    def test_recusa_entrada_que_nao_e_digito(self) -> None:
        with pytest.raises(ValueError):
            modulo10("12a4")

    def test_recusa_entrada_vazia(self) -> None:
        with pytest.raises(ValueError):
            modulo10("")


class TestModulo11Boleto:
    @pytest.mark.parametrize(
        ("digitos", "dv"),
        [
            # 4*2 + 3*3 + 2*4 + 1*5 = 30; 30 % 11 = 8; DV = 11 - 8 = 3
            ("1234", 3),
            # 2*2 + 1*3 + 0*4 + 9*5 + 8*6 + 7*7 + 6*8 + 5*9
            #   + 4*2 + 3*3 + 2*4 + 1*5 = 272; 272 % 11 = 8; DV = 3
            # (12 dígitos: o peso volta de 9 para 2 no meio)
            ("123456789012", 3),
            # 1*2 + 3*3 = 11; resto 0; DV seria 11, então vira 1
            ("31", 1),
            # 3*2 + 2*3 = 12; resto 1; DV seria 10, então vira 1
            ("23", 1),
            # 2*2 + 2*3 = 10; DV = 1 pelo cálculo normal
            ("22", 1),
        ],
    )
    def test_casos_conferidos_a_mao(self, digitos: str, dv: int) -> None:
        assert modulo11_boleto(digitos) == dv

    def test_dv_fica_sempre_em_um_digito(self) -> None:
        for numero in range(0, 2000):
            assert 1 <= modulo11_boleto(f"{numero:010d}") <= 9

    def test_recusa_entrada_que_nao_e_digito(self) -> None:
        with pytest.raises(ValueError):
            modulo11_boleto("1234x")


class TestValidaLinhaDigitavel:
    def test_aceita_linha_valida(self) -> None:
        resultado = valida_linha_digitavel(LINHA_VALIDA)

        assert resultado.valido
        assert resultado.erros == ()
        assert resultado.descricao() == "ok"

    def test_aceita_linha_formatada(self) -> None:
        assert valida_linha_digitavel(LINHA_VALIDA_FORMATADA).valido

    @pytest.mark.parametrize(
        ("linha", "quantidade"),
        [("", 0), ("123", 3), (LINHA_VALIDA + "0", 48), (LINHA_VALIDA[:-1], 46)],
    )
    def test_reprova_tamanho_errado_apontando_o_formato(self, linha: str, quantidade: int) -> None:
        resultado = valida_linha_digitavel(linha)

        assert not resultado.valido
        assert resultado.campos_invalidos == (CampoLinhaDigitavel.FORMATO,)
        assert resultado.erros[0].encontrado == str(quantidade)

    @pytest.mark.parametrize(
        ("posicao", "campo"),
        [
            (0, CampoLinhaDigitavel.CAMPO_1),
            (9, CampoLinhaDigitavel.CAMPO_1),
            (10, CampoLinhaDigitavel.CAMPO_2),
            (20, CampoLinhaDigitavel.CAMPO_2),
            (21, CampoLinhaDigitavel.CAMPO_3),
            (31, CampoLinhaDigitavel.CAMPO_3),
            (32, CampoLinhaDigitavel.DV_GERAL),
            (46, CampoLinhaDigitavel.DV_GERAL),
        ],
    )
    def test_aponta_qual_campo_falhou(self, posicao: int, campo: CampoLinhaDigitavel) -> None:
        resultado = valida_linha_digitavel(_troca_digito(LINHA_VALIDA, posicao))

        assert not resultado.valido
        assert campo in resultado.campos_invalidos

    def test_toda_troca_de_um_digito_e_detectada(self) -> None:
        """Módulo 10 e módulo 11 juntos pegam qualquer alteração de um dígito só."""
        for posicao in range(len(LINHA_VALIDA)):
            original = LINHA_VALIDA[posicao]
            for digito in "0123456789":
                if digito == original:
                    continue
                mutante = LINHA_VALIDA[:posicao] + digito + LINHA_VALIDA[posicao + 1 :]
                resultado = valida_linha_digitavel(mutante)
                assert not resultado.valido, f"passou com o dígito {posicao} trocado por {digito}"

    def test_erro_diz_o_esperado_e_o_encontrado(self) -> None:
        resultado = valida_linha_digitavel(_troca_digito(LINHA_VALIDA, 9))

        erro = resultado.erros[0]
        assert erro.campo is CampoLinhaDigitavel.CAMPO_1
        assert erro.esperado == LINHA_VALIDA[9]
        assert erro.encontrado != LINHA_VALIDA[9]
        assert "módulo 10" in erro.mensagem

    def test_acumula_falhas_de_campos_diferentes(self) -> None:
        mutante = _troca_digito(_troca_digito(LINHA_VALIDA, 9), 20)

        resultado = valida_linha_digitavel(mutante)

        assert resultado.campos_invalidos[:2] == (
            CampoLinhaDigitavel.CAMPO_1,
            CampoLinhaDigitavel.CAMPO_2,
        )


class TestResultadoValidacao:
    def test_reprovado_exige_ao_menos_um_erro(self) -> None:
        with pytest.raises(ValueError):
            ResultadoValidacao.reprovado()


class TestValidaCpf:
    @pytest.mark.parametrize(
        "cpf",
        ["111.444.777-35", "11144477735", "529.982.247-25", "398.402.070-83"],
    )
    def test_aceita_cpf_valido(self, cpf: str) -> None:
        assert valida_cpf(cpf)

    @pytest.mark.parametrize(
        "cpf",
        [
            "111.444.777-30",  # DV2 errado
            "111.444.777-45",  # DV1 errado
            "123.456.789-00",
            "",
            "1114447773",  # 10 dígitos
            "111444777350",  # 12 dígitos
            "abc.def.ghi-jk",
        ],
    )
    def test_recusa_cpf_invalido(self, cpf: str) -> None:
        assert not valida_cpf(cpf)

    @pytest.mark.parametrize("digito", list("0123456789"))
    def test_recusa_digitos_repetidos(self, digito: str) -> None:
        """000.000.000-00 e afins fecham na conta, mas não são CPF."""
        assert not valida_cpf(digito * 11)


class TestValidaCnpj:
    @pytest.mark.parametrize(
        "cnpj",
        ["11.222.333/0001-81", "11222333000181", "00.000.000/0001-91", "60.746.948/0001-12"],
    )
    def test_aceita_cnpj_valido(self, cnpj: str) -> None:
        assert valida_cnpj(cnpj)

    @pytest.mark.parametrize(
        "cnpj",
        [
            "11.222.333/0001-80",  # DV2 errado
            "11.222.333/0001-91",  # DV1 errado
            "12.345.678/0001-00",
            "",
            "1122233300018",  # 13 dígitos
            "112223330001811",  # 15 dígitos
        ],
    )
    def test_recusa_cnpj_invalido(self, cnpj: str) -> None:
        assert not valida_cnpj(cnpj)

    @pytest.mark.parametrize("digito", list("0123456789"))
    def test_recusa_digitos_repetidos(self, digito: str) -> None:
        assert not valida_cnpj(digito * 14)


def _troca_digito(linha: str, posicao: int) -> str:
    """Troca o dígito da posição pelo seguinte, dando a volta de 9 para 0."""
    novo = str((int(linha[posicao]) + 1) % 10)
    return linha[:posicao] + novo + linha[posicao + 1 :]
