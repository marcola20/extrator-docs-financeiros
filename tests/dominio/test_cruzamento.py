"""Cruzamento entre os informes de dois anos consecutivos.

O sinal desta fase que um adversário com controle da página não consegue
satisfazer sozinho: são dois documentos afirmando a mesma grandeza. Os testes
cobrem as três respostas que ele pode dar — confere, diverge, e **não dá para
comparar** —, porque tratar a terceira como aprovação é o erro que apaga o
sinal inteiro.
"""

from decimal import Decimal

from app.dominio.cruzamento import Incomparavel, cruza
from app.dominio.informe import Informe, Layout, LinhaDeQuadro, Quadro, SaldoDeConta

CNPJ = "34028316000103"
OUTRO_CNPJ = "45997418000153"
CPF = "52998224725"
OUTRO_CPF = "11144477735"


def _saldo(especificacao: str, atual: str, anterior: str) -> SaldoDeConta:
    return SaldoDeConta(
        especificacao=especificacao,
        saldo_31_12=Decimal(atual),
        saldo_31_12_anterior=Decimal(anterior),
    )


def _vazio(identificador: str) -> Quadro:
    return Quadro(identificador=identificador, linhas=(), total_impresso=Decimal("0.00"))


def _informe(
    ano: int,
    saldos: tuple[SaldoDeConta, ...],
    *,
    cnpj: str = CNPJ,
    cpf: str = CPF,
) -> Informe:
    return Informe(
        layout=Layout.INSTITUICAO_FINANCEIRA,
        ano_calendario=ano,
        exercicio=ano + 1,
        fonte_pagadora_cnpj=cnpj,
        fonte_pagadora_nome="Banco Fictício S/A",
        beneficiario_cpf=cpf,
        beneficiario_nome="Fulano de Tal",
        rendimentos_tributaveis=_vazio("rendimentos_tributaveis"),
        rendimentos_isentos=_vazio("rendimentos_isentos"),
        rendimentos_exclusivos=_vazio("rendimentos_exclusivos"),
        saldos=saldos,
    )


class TestParConsistente:
    def test_par_que_fecha_e_valido(self) -> None:
        anterior = _informe(2024, (_saldo("Conta Corrente 1219", "9800.00", "7000.00"),))
        atual = _informe(2025, (_saldo("Conta Corrente 1219", "12450.03", "9800.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert resultado.contas_conferidas == ("Conta Corrente 1219",)
        assert resultado.divergencias == ()

    def test_varias_contas_sao_casadas_uma_a_uma(self) -> None:
        anterior = _informe(
            2024,
            (_saldo("Conta Corrente", "9800.00", "0.00"), _saldo("Poupança", "3000.00", "0.00")),
        )
        atual = _informe(
            2025,
            (
                _saldo("Conta Corrente", "12450.03", "9800.00"),
                _saldo("Poupança", "3120.55", "3000.00"),
            ),
        )

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert sorted(resultado.contas_conferidas) == ["Conta Corrente", "Poupança"]


class TestParInconsistente:
    def test_saldo_que_nao_fecha_reprova_e_diz_qual_conta(self) -> None:
        """Casar por conta é o que permite apontar a conta, não só o documento."""
        anterior = _informe(
            2024,
            (_saldo("Conta Corrente", "9800.00", "0.00"), _saldo("Poupança", "3000.00", "0.00")),
        )
        atual = _informe(
            2025,
            (
                _saldo("Conta Corrente", "12450.03", "9800.00"),
                _saldo("Poupança", "3120.55", "2500.00"),
            ),
        )

        resultado = cruza(atual, anterior)

        assert not resultado.valido
        assert [d.especificacao for d in resultado.divergencias] == ["Poupança"]
        assert resultado.divergencias[0].diferenca == Decimal("-500.00")
        assert "Poupança" in resultado.descricao()

    def test_conta_nova_sem_saldo_anterior_e_legitima(self) -> None:
        """Conta aberta durante o ano não tem par, e isso não é erro."""
        anterior = _informe(2024, (_saldo("Conta Corrente", "9800.00", "0.00"),))
        atual = _informe(
            2025,
            (
                _saldo("Conta Corrente", "12450.03", "9800.00"),
                _saldo("CDB 2025", "5000.00", "0.00"),
            ),
        )

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert resultado.contas_novas == ("CDB 2025",)

    def test_conta_nova_com_saldo_anterior_reprova(self) -> None:
        """Em 31/12 do ano anterior a conta não existia; saldo ali não fecha."""
        anterior = _informe(2024, (_saldo("Conta Corrente", "9800.00", "0.00"),))
        atual = _informe(
            2025,
            (
                _saldo("Conta Corrente", "12450.03", "9800.00"),
                _saldo("CDB 2025", "5000.00", "4000.00"),
            ),
        )

        resultado = cruza(atual, anterior)

        assert not resultado.valido
        assert [c.especificacao for c in resultado.contas_novas_com_historico] == ["CDB 2025"]

    def test_conta_que_sumiu_fica_registrada_como_nao_conferida(self) -> None:
        """O saldo dela no ano anterior não foi cruzado por ninguém."""
        anterior = _informe(
            2024,
            (_saldo("Conta Corrente", "9800.00", "0.00"), _saldo("Poupança", "3000.00", "0.00")),
        )
        atual = _informe(2025, (_saldo("Conta Corrente", "12450.03", "9800.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert resultado.contas_sem_conferencia == ("Poupança",)


class TestParIncomparavel:
    def test_titular_diferente_nao_e_comparavel(self) -> None:
        anterior = _informe(2024, (_saldo("Conta", "100.00", "0.00"),), cpf=OUTRO_CPF)
        atual = _informe(2025, (_saldo("Conta", "200.00", "100.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.incomparavel is Incomparavel.TITULAR_DIFERENTE

    def test_fonte_diferente_nao_e_comparavel(self) -> None:
        anterior = _informe(2024, (_saldo("Conta", "100.00", "0.00"),), cnpj=OUTRO_CNPJ)
        atual = _informe(2025, (_saldo("Conta", "200.00", "100.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.incomparavel is Incomparavel.FONTE_DIFERENTE

    def test_anos_nao_consecutivos_nao_sao_comparaveis(self) -> None:
        anterior = _informe(2023, (_saldo("Conta", "100.00", "0.00"),))
        atual = _informe(2025, (_saldo("Conta", "200.00", "100.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.incomparavel is Incomparavel.ANOS_NAO_CONSECUTIVOS

    def test_ordem_invertida_nao_e_comparavel(self) -> None:
        """Passar os dois trocados não pode virar cruzamento silencioso."""
        anterior = _informe(2024, (_saldo("Conta", "9800.00", "0.00"),))
        atual = _informe(2025, (_saldo("Conta", "12450.03", "9800.00"),))

        resultado = cruza(anterior, atual)

        assert resultado.incomparavel is Incomparavel.ANOS_NAO_CONSECUTIVOS

    def test_incomparavel_nao_e_valido(self) -> None:
        """ "Não conferi" não pode passar por "conferi e está certo"."""
        anterior = _informe(2023, (_saldo("Conta", "100.00", "0.00"),))
        atual = _informe(2025, (_saldo("Conta", "200.00", "100.00"),))

        resultado = cruza(atual, anterior)

        assert not resultado.valido
        assert not resultado.comparavel


def test_quadro_com_linha_serve_de_ancora_para_o_gerador() -> None:
    """Guarda de sanidade: o cruzamento não olha quadro, só saldo."""
    quadro = Quadro(
        identificador="rendimentos_isentos",
        linhas=(LinhaDeQuadro(identificador="Poupança", valor=Decimal("120.00")),),
        total_impresso=Decimal("120.00"),
    )
    anterior = _informe(2024, (_saldo("Conta", "9800.00", "0.00"),))
    atual = _informe(2025, (_saldo("Conta", "12450.03", "9800.00"),))
    atual = atual.model_copy(update={"rendimentos_isentos": quadro})

    assert cruza(atual, anterior).valido


class TestCoberturaDoCruzamento:
    """`valido` sozinho mente quando não havia o que conferir."""

    def test_par_sem_saldo_nenhum_e_valido_mas_nao_tem_cobertura(self) -> None:
        """Dois comprovantes de fonte pagadora: comparáveis, e nada a cruzar.

        É o caso que o corpus vai ter de verdade — o layout de fonte pagadora
        não tem saldo —, e tratar isso como verificação bem-sucedida faria
        metade do corpus parecer coberta pelo sinal mais forte da fase.
        """
        anterior = _informe(2024, ())
        atual = _informe(2025, ())

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert not resultado.tem_cobertura
        assert resultado.contas_conferidas == ()

    def test_par_com_conta_casada_tem_cobertura(self) -> None:
        anterior = _informe(2024, (_saldo("Conta", "9800.00", "0.00"),))
        atual = _informe(2025, (_saldo("Conta", "12450.03", "9800.00"),))

        assert cruza(atual, anterior).tem_cobertura

    def test_conta_so_nova_nao_da_cobertura(self) -> None:
        """Conta sem par não foi cruzada com nada; não conta como conferida."""
        anterior = _informe(2024, ())
        atual = _informe(2025, (_saldo("CDB 2025", "5000.00", "0.00"),))

        resultado = cruza(atual, anterior)

        assert resultado.valido
        assert not resultado.tem_cobertura
        assert resultado.contas_novas == ("CDB 2025",)

    def test_incomparavel_nao_tem_cobertura(self) -> None:
        anterior = _informe(2023, (_saldo("Conta", "100.00", "0.00"),))
        atual = _informe(2025, (_saldo("Conta", "200.00", "100.00"),))

        assert not cruza(atual, anterior).tem_cobertura
