"""Grounding sobre documento multi-registro: cada resposta diz de qual linha fala."""

from app.confianca import grounding
from app.confianca.grounding import Situacao
from app.extracao.schema_transporte_informe import (
    InformeExtraido,
    LinhaExtraida,
    QuadroExtraido,
    SaldoExtraido,
)

PAGINA = """
Informe de Rendimentos Financeiros
Ano-calendário 2024 — Exercício 2025
Banco Aurora S/A  CNPJ 01.829.356/0001-03
Maysa da Costa  CPF 159.748.326-55

Rendimentos Sujeitos à Tributação Exclusiva
CDB         Certificado de Depósito Bancário     15.174,75
Fundo DI    Fundo de investimento referenciado DI  7.148,59
Total                                            22.323,34

Saldos em 31 de dezembro
CDB 8056747      6.771,59      9.289,25
"""


def _extraido(**mudancas: object) -> InformeExtraido:
    base: dict[str, object] = {
        "layout": "instituicao_financeira",
        "ano_calendario": "2024",
        "exercicio": "2025",
        "fonte_pagadora_cnpj": "01.829.356/0001-03",
        "fonte_pagadora_nome": "Banco Aurora S/A",
        "beneficiario_cpf": "159.748.326-55",
        "beneficiario_nome": "Maysa da Costa",
        "rendimentos_exclusivos": QuadroExtraido(
            linhas=[
                LinhaExtraida(
                    identificador="CDB",
                    descricao="Certificado de Depósito Bancário",
                    valor="15.174,75",
                ),
                LinhaExtraida(
                    identificador="Fundo DI",
                    descricao="Fundo de investimento referenciado DI",
                    valor="7.148,59",
                ),
            ],
            total_impresso="22.323,34",
        ),
        "saldos": [
            SaldoExtraido(
                especificacao="CDB 8056747",
                saldo_31_12="9.289,25",
                saldo_31_12_anterior="6.771,59",
            )
        ],
    }
    base.update(mudancas)
    return InformeExtraido(**base)


def _conferencia(resultado: grounding.ResultadoGrounding, local: str) -> grounding.Conferencia:
    return next(c for c in resultado.conferencias if c.local == local)


class TestLeituraFielPassa:
    def test_informe_bem_lido_e_aprovado(self) -> None:
        assert grounding.confere_informe(_extraido(), PAGINA).aprovado

    def test_confere_valor_de_linha_um_a_um(self) -> None:
        resultado = grounding.confere_informe(_extraido(), PAGINA)

        assert (
            _conferencia(resultado, "rendimentos_exclusivos[CDB].valor").situacao
            is Situacao.ENCONTRADO
        )

    def test_a_formatacao_impressa_nao_derruba(self) -> None:
        """`15174.75` e `15.174,75` são o mesmo valor — `app.confianca.normalizacao`."""
        resultado = grounding.confere_informe(
            _extraido(
                rendimentos_exclusivos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="CDB", valor="15174.75")],
                    total_impresso="15174,75",
                )
            ),
            PAGINA,
        )

        assert (
            _conferencia(resultado, "rendimentos_exclusivos[CDB].valor").situacao
            is Situacao.ENCONTRADO
        )


class TestValorInventadoCai:
    def test_valor_de_linha_que_nao_esta_na_pagina(self) -> None:
        resultado = grounding.confere_informe(
            _extraido(
                rendimentos_exclusivos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="CDB", valor="99.999,99")]
                )
            ),
            PAGINA,
        )

        assert not resultado.aprovado
        assert resultado.ausentes[0].local == "rendimentos_exclusivos[CDB].valor"

    def test_a_descricao_diz_qual_linha_e_nao_so_qual_campo(self) -> None:
        """Num documento com quarenta valores, "valor não aparece" não é informação."""
        resultado = grounding.confere_informe(
            _extraido(
                rendimentos_exclusivos=QuadroExtraido(
                    linhas=[LinhaExtraida(identificador="Fundo DI", valor="1,00")]
                )
            ),
            PAGINA,
        )

        assert "rendimentos_exclusivos[Fundo DI].valor" in resultado.descricao()

    def test_saldo_inventado_cai(self) -> None:
        resultado = grounding.confere_informe(
            _extraido(
                saldos=[
                    SaldoExtraido(
                        especificacao="CDB 8056747",
                        saldo_31_12="41.128,23",
                        saldo_31_12_anterior="6.771,59",
                    )
                ]
            ),
            PAGINA,
        )

        assert not resultado.aprovado
        assert resultado.ausentes[0].local == "saldos[CDB 8056747].saldo_31_12"

    def test_conta_que_nao_existe_na_pagina_cai_pela_especificacao(self) -> None:
        resultado = grounding.confere_informe(
            _extraido(
                saldos=[
                    SaldoExtraido(
                        especificacao="Fundo Imobiliário 8812345",
                        saldo_31_12="9.289,25",
                        saldo_31_12_anterior="6.771,59",
                    )
                ]
            ),
            PAGINA,
        )

        assert not resultado.aprovado
        assert "Fundo Imobiliário 8812345" in resultado.descricao()


class TestTotalSomadoEmVezDeTranscrito:
    """O risco que este sinal cobre de graça, e que nenhum outro cobriria."""

    def test_total_calculado_pelo_modelo_nao_esta_na_pagina(self) -> None:
        """Um total somado faria a aritmética concordar consigo mesma sempre.

        Aqui a página imprime 22.323,34 e o modelo devolveu a soma das duas
        linhas que *ele* leu. O número não está impresso, então o grounding o
        acusa — e é ele que impede o sinal de aritmética de virar tautologia.
        """
        resultado = grounding.confere_informe(
            _extraido(
                rendimentos_exclusivos=QuadroExtraido(
                    linhas=[
                        LinhaExtraida(identificador="CDB", valor="15.174,75"),
                        LinhaExtraida(identificador="Fundo DI", valor="7.148,59"),
                        LinhaExtraida(identificador="LCI", valor="1.000,00"),
                    ],
                    total_impresso="23.323,34",
                )
            ),
            PAGINA,
        )

        ausentes = {c.local for c in resultado.ausentes}

        assert "rendimentos_exclusivos.total_impresso" in ausentes


class TestIsencaoDeclarada:
    def test_layout_e_isento_porque_e_classificacao(self) -> None:
        conferencia = _conferencia(grounding.confere_informe(_extraido(), PAGINA), "layout")

        assert conferencia.situacao is Situacao.ISENTO
        assert "classificação" in conferencia.motivo

    def test_identificador_de_linha_e_isento_e_o_motivo_esta_escrito(self) -> None:
        """No comprovante a página traz `3.` e `1.` separados; `3.1` não existe nela."""
        resultado = grounding.confere_informe(_extraido(), PAGINA)
        conferencia = _conferencia(resultado, "rendimentos_exclusivos[CDB].chave")

        assert conferencia.situacao is Situacao.ISENTO
        assert "recall e precisão de linha" in conferencia.motivo

    def test_isento_nao_conta_como_conferido_na_taxa(self) -> None:
        resultado = grounding.confere_informe(_extraido(), PAGINA)
        confereveis = [
            c
            for c in resultado.conferencias
            if c.situacao in (Situacao.ENCONTRADO, Situacao.AUSENTE)
        ]

        assert all(c.campo not in grounding.CAMPOS_ISENTOS_DO_INFORME for c in confereveis)


class TestBoletoNaoMudou:
    def test_conferencia_de_boleto_continua_sem_local(self) -> None:
        """O boleto não tem mais de um valor por campo; `onde` cai no nome do campo."""
        conferencia = grounding.Conferencia("valor", Situacao.ENCONTRADO, "10,00")

        assert conferencia.local == ""
        assert conferencia.onde == "valor"
