"""Aritmética de quadro e validadores do informe.

O teste que mais importa aqui não é o da soma que fecha: é o da soma que **não
pode ser conferida**. Quadro sem total impresso tem que sair como `SEM_TOTAL`,
nunca como aprovado — o modelo oficial da Receita não imprime total nos
quadros 4 e 5, e aprovar por omissão faria dois terços de todo comprovante de
fonte pagadora parecer verificado sem que nada tivesse sido verificado.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.dominio.informe import (
    Cobertura,
    Informe,
    Layout,
    LinhaDeQuadro,
    Quadro,
    SaldoDeConta,
)

CNPJ = "34028316000103"
CPF = "52998224725"


def _linha(identificador: str, valor: str) -> LinhaDeQuadro:
    return LinhaDeQuadro(identificador=identificador, descricao="linha", valor=Decimal(valor))


def _quadro(
    identificador: str = "rendimentos_isentos",
    linhas: tuple[LinhaDeQuadro, ...] = (),
    total: str | None = None,
) -> Quadro:
    return Quadro(
        identificador=identificador,
        titulo="Quadro de teste",
        linhas=linhas,
        total_impresso=None if total is None else Decimal(total),
    )


def _informe(**sobrescreve: object) -> Informe:
    padrao: dict[str, object] = {
        "layout": Layout.INSTITUICAO_FINANCEIRA,
        "ano_calendario": 2025,
        "exercicio": 2026,
        "fonte_pagadora_cnpj": CNPJ,
        "fonte_pagadora_nome": "Banco Fictício S/A",
        "beneficiario_cpf": CPF,
        "beneficiario_nome": "Fulano de Tal",
        "rendimentos_tributaveis": _quadro("rendimentos_tributaveis"),
        "rendimentos_isentos": _quadro("rendimentos_isentos"),
        "rendimentos_exclusivos": _quadro("rendimentos_exclusivos"),
    }
    padrao.update(sobrescreve)
    return Informe.model_validate(padrao)


class TestAritmeticaDeQuadro:
    def test_soma_que_fecha_sai_conferida(self) -> None:
        quadro = _quadro(linhas=(_linha("a", "100.00"), _linha("b", "50.50")), total="150.50")

        conferencia = quadro.confere()

        assert conferencia.cobertura is Cobertura.CONFERIDO
        assert conferencia.tem_cobertura
        assert not conferencia.divergiu

    def test_soma_que_nao_fecha_sai_divergente(self) -> None:
        quadro = _quadro(linhas=(_linha("a", "100.00"), _linha("b", "50.50")), total="200.00")

        conferencia = quadro.confere()

        assert conferencia.cobertura is Cobertura.DIVERGENTE
        assert conferencia.divergiu
        assert "150.50" in conferencia.descricao()

    def test_quadro_sem_total_nao_e_aprovado_por_omissao(self) -> None:
        """O caso do modelo oficial: quadros 4 e 5 não imprimem total."""
        quadro = _quadro(linhas=(_linha("4.1", "1000.00"), _linha("4.7", "300.00")))

        conferencia = quadro.confere()

        assert conferencia.cobertura is Cobertura.SEM_TOTAL
        assert not conferencia.tem_cobertura
        assert not conferencia.divergiu
        assert "não conferida" in conferencia.descricao()

    def test_quadro_vazio_com_total_zero_confere(self) -> None:
        """Quadro sem linha nenhuma é comum: contribuinte sem rendimento isento."""
        quadro = _quadro(total="0.00")

        assert quadro.soma_das_linhas == Decimal("0")
        assert quadro.confere().cobertura is Cobertura.CONFERIDO

    def test_quadro_vazio_com_total_nao_zero_diverge(self) -> None:
        quadro = _quadro(total="10.00")

        assert quadro.confere().divergiu

    def test_identificador_repetido_e_recusado(self) -> None:
        """É o quadro duplicado do corpus adversarial; casaria duas vezes."""
        with pytest.raises(ValidationError, match="repetido"):
            _quadro(linhas=(_linha("4.1", "10.00"), _linha("4.1", "20.00")))

    def test_valor_float_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="nunca float"):
            LinhaDeQuadro(identificador="a", valor=10.5)

    def test_fracao_de_centavo_e_recusada(self) -> None:
        with pytest.raises(ValidationError, match="fração de centavo"):
            _linha("a", "10.005")


class TestInformeFecha:
    def test_informe_coerente_instancia(self) -> None:
        informe = _informe(
            rendimentos_isentos=_quadro(
                "rendimentos_isentos", (_linha("Poupança", "120.00"),), total="120.00"
            )
        )

        assert informe.ano_calendario == 2025

    def test_quadro_divergente_derruba_o_informe(self) -> None:
        with pytest.raises(ValidationError, match="diverge do total impresso"):
            _informe(
                rendimentos_isentos=_quadro(
                    "rendimentos_isentos", (_linha("Poupança", "120.00"),), total="999.00"
                )
            )

    def test_exercicio_tem_que_ser_o_ano_seguinte(self) -> None:
        """É o único sinal que `ano_calendario` tem."""
        with pytest.raises(ValidationError, match="não confere com o ano-calendário"):
            _informe(exercicio=2027)

    def test_cnpj_com_dv_errado_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="CNPJ da fonte pagadora inválido"):
            _informe(fonte_pagadora_cnpj="34028316000104")

    def test_cpf_com_dv_errado_e_recusado(self) -> None:
        with pytest.raises(ValidationError, match="CPF do beneficiário inválido"):
            _informe(beneficiario_cpf="52998224726")

    def test_quadros_sem_cobertura_sao_listados(self) -> None:
        """O relatório precisa poder dizer quanto do documento ninguém conferiu."""
        informe = _informe(
            rendimentos_tributaveis=_quadro("3", (_linha("3.1", "50000.00"),)),
            rendimentos_isentos=_quadro("4", (_linha("4.1", "100.00"),), total="100.00"),
            rendimentos_exclusivos=_quadro("5", (_linha("5.1", "4000.00"),)),
        )

        assert informe.quadros_sem_cobertura == ("3", "5")


class TestLayoutFontePagadora:
    def _fonte_pagadora(self, **sobrescreve: object) -> Informe:
        return _informe(layout=Layout.FONTE_PAGADORA, **sobrescreve)

    def test_irrf_do_decimo_terceiro_nao_pode_exceder_o_decimo_terceiro(self) -> None:
        with pytest.raises(ValidationError, match="excede o próprio 13º"):
            self._fonte_pagadora(
                rendimentos_exclusivos=_quadro(
                    "5", (_linha("5.1", "4000.00"), _linha("5.2", "4500.00"))
                )
            )

    def test_irrf_menor_que_o_decimo_terceiro_passa(self) -> None:
        informe = self._fonte_pagadora(
            rendimentos_exclusivos=_quadro("5", (_linha("5.1", "4000.00"), _linha("5.2", "300.00")))
        )

        assert informe.layout is Layout.FONTE_PAGADORA

    def test_comprovante_de_fonte_pagadora_nao_pode_ter_saldo(self) -> None:
        """O documento não tem saldo; aceitar um seria aceitar campo inventado."""
        with pytest.raises(ValidationError, match="não tem saldo em 31/12"):
            self._fonte_pagadora(
                saldos=(
                    SaldoDeConta(
                        especificacao="Conta Corrente",
                        saldo_31_12=Decimal("10.00"),
                        saldo_31_12_anterior=Decimal("0.00"),
                    ),
                )
            )


class TestSaldos:
    def test_especificacao_repetida_e_recusada(self) -> None:
        """A especificação é a chave do cruzamento entre anos."""
        saldo = SaldoDeConta(
            especificacao="Conta Corrente 1219",
            saldo_31_12=Decimal("10.00"),
            saldo_31_12_anterior=Decimal("5.00"),
        )

        with pytest.raises(ValidationError, match="especificação de saldo repetida"):
            _informe(saldos=(saldo, saldo))

    def test_saldo_negativo_e_aceito(self) -> None:
        """Conta corrente com saldo devedor existe e vai para Dívidas e Ônus Reais."""
        informe = _informe(
            saldos=(
                SaldoDeConta(
                    especificacao="Conta Corrente 1219",
                    saldo_31_12=Decimal("-350.00"),
                    saldo_31_12_anterior=Decimal("120.00"),
                ),
            )
        )

        assert informe.saldos[0].saldo_31_12 == Decimal("-350.00")
