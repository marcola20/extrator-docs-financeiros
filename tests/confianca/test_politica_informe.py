"""Roteamento do informe, e a regra de que não ter o que conferir não aprova."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.confianca import politica_informe
from app.confianca.consistencia import Divergencia, ResultadoConsistencia
from app.confianca.grounding import Conferencia, ResultadoGrounding, Situacao
from app.confianca.politica import DecisaoFinal, Rota, Sinal, Veredito
from app.dominio.cruzamento import (
    ContaNovaComHistorico,
    DivergenciaDeSaldo,
    Incomparavel,
    ResultadoCruzamento,
)
from app.extracao.extrator_informe import ExtracaoDeInforme, confere_quadros, para_dominio
from app.extracao.prompt import PROMPT_INFORME, carrega
from app.extracao.schema_transporte_informe import (
    InformeExtraido,
    LinhaExtraida,
    QuadroExtraido,
    SaldoExtraido,
)
from app.llm.provedor import UsoDeTokens
from app.seguranca.politica import Decisao
from app.seguranca.politica import Rota as RotaDeSanitizacao

PROMPT = carrega(PROMPT_INFORME)
SANITIZACAO_LIMPA = Decisao(rota=RotaDeSanitizacao.AUTOMATICO, motivo="nenhum achado")
SANITIZACAO_COM_ACHADO = Decisao(rota=RotaDeSanitizacao.REVISAO_HUMANA, motivo="1 achado")
GROUNDING_OK = ResultadoGrounding(())
CONSISTENCIA_OK = ResultadoConsistencia(executou=True)
CRUZAMENTO_COM_COBERTURA = ResultadoCruzamento(contas_conferidas=("CDB 8056747",))


def _bancario(**mudancas: object) -> InformeExtraido:
    base: dict[str, object] = {
        "layout": "instituicao_financeira",
        "ano_calendario": "2024",
        "exercicio": "2025",
        "fonte_pagadora_cnpj": "01.829.356/0001-03",
        "fonte_pagadora_nome": "Banco Aurora S/A",
        "beneficiario_cpf": "159.748.326-55",
        "beneficiario_nome": "Maysa da Costa",
        "rendimentos_exclusivos": QuadroExtraido(
            linhas=[LinhaExtraida(identificador="CDB", valor="1.000,00")],
            total_impresso="1.000,00",
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


def _comprovante() -> InformeExtraido:
    """Sem total e sem saldo: o layout pobre em sinal do ADR 007."""
    return InformeExtraido(
        layout="fonte_pagadora",
        ano_calendario="2024",
        exercicio="2025",
        fonte_pagadora_cnpj="01.829.356/0001-03",
        fonte_pagadora_nome="Metalúrgica Vale Verde Ltda",
        beneficiario_cpf="159.748.326-55",
        beneficiario_nome="Maysa da Costa",
        rendimentos_exclusivos=QuadroExtraido(
            linhas=[LinhaExtraida(identificador="5.1", valor="4.000,00")]
        ),
    )


def _extracao(bruto: InformeExtraido) -> ExtracaoDeInforme:
    dominio, erro = para_dominio(bruto)
    return ExtracaoDeInforme(
        documento=Path("informe-001.pdf"),
        prompt=PROMPT,
        bruto=bruto,
        dominio=dominio,
        erro_de_dominio=erro,
        conferencias=confere_quadros(bruto),
        provedor="falso",
        modelo="falso-1",
        uso=UsoDeTokens(entrada=100, saida=20),
        custo_estimado_usd=Decimal("0.0001"),
        do_cache=False,
    )


def _decide(**mudancas: object) -> DecisaoFinal:
    argumentos: dict[str, object] = {
        "sanitizacao": SANITIZACAO_LIMPA,
        "extracao": _extracao(_bancario()),
        "grounding": GROUNDING_OK,
        "consistencia": CONSISTENCIA_OK,
        "cruzamento": CRUZAMENTO_COM_COBERTURA,
    }
    argumentos.update(mudancas)
    return politica_informe.decide(**argumentos)  # type: ignore[arg-type]


def _veredito(decisao: DecisaoFinal, sinal: Sinal) -> Veredito:
    return next(v for v in decisao.vereditos if v.sinal is sinal)


class TestOCaminhoFeliz:
    def test_informe_bancario_verificado_e_auto_aprovado(self) -> None:
        decisao = _decide()

        assert decisao.rota is Rota.AUTO_APROVADO

    def test_os_seis_sinais_aparecem_no_relatorio(self) -> None:
        decisao = _decide()

        assert {v.sinal for v in decisao.vereditos} == {
            Sinal.SANITIZACAO,
            Sinal.CRUZAMENTO,
            Sinal.DOMINIO,
            Sinal.ARITMETICA,
            Sinal.GROUNDING,
            Sinal.CONSISTENCIA,
        }


class TestSemTotalNaoEAprovacao:
    """A regra da 2.1 chegando ao roteamento: `SEM_TOTAL` não é quadro conferido."""

    def test_comprovante_sem_total_nunca_e_auto_aprovado(self) -> None:
        decisao = _decide(
            extracao=_extracao(_comprovante()),
            cruzamento=ResultadoCruzamento(contas_conferidas=()),
        )

        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_a_aritmetica_sai_como_nao_executada_e_nao_como_aprovada(self) -> None:
        decisao = _decide(extracao=_extracao(_comprovante()))
        veredito = _veredito(decisao, Sinal.ARITMETICA)

        assert not veredito.executou
        assert veredito.bloqueia
        assert "nenhum quadro tinha total impresso" in veredito.detalhe

    def test_e_o_bloqueio_e_por_falta_de_cobertura_e_nao_por_reprovacao(self) -> None:
        """A distinção que o relatório precisa: ninguém reprovou, ninguém conferiu."""
        decisao = _decide(
            extracao=_extracao(_comprovante()),
            cruzamento=ResultadoCruzamento(contas_conferidas=()),
        )

        assert decisao.so_falta_de_cobertura
        assert {v.sinal for v in decisao.bloqueadores_por_falta_de_cobertura} == {
            Sinal.ARITMETICA,
            Sinal.CRUZAMENTO,
        }


class TestCruzamentoSemCobertura:
    def test_documento_sem_par_extraido_bloqueia(self) -> None:
        decisao = _decide(cruzamento=None)
        veredito = _veredito(decisao, Sinal.CRUZAMENTO)

        assert not veredito.executou
        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_par_sem_conta_em_comum_bloqueia_mesmo_saindo_valido(self) -> None:
        """`ResultadoCruzamento.valido` é `True` num par sem conta nenhuma.

        Tratar isso como aprovação é exatamente o erro que a 2.1 registrou.
        """
        vazio = ResultadoCruzamento(contas_conferidas=())

        assert vazio.valido, "é o comportamento do domínio, e é por isso que a política filtra"

        decisao = _decide(cruzamento=vazio)

        assert not _veredito(decisao, Sinal.CRUZAMENTO).executou
        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_par_incomparavel_nao_conta_como_conferido(self) -> None:
        decisao = _decide(
            cruzamento=ResultadoCruzamento(incomparavel=Incomparavel.TITULAR_DIFERENTE)
        )
        veredito = _veredito(decisao, Sinal.CRUZAMENTO)

        assert not veredito.executou
        assert "titular_diferente" in veredito.detalhe

    def test_saldo_divergente_entre_anos_reprova(self) -> None:
        """O ataque `saldo_anterior_adulterado`: nenhum sinal interno o pega."""
        decisao = _decide(
            cruzamento=ResultadoCruzamento(
                contas_conferidas=("CDB 8056747",),
                divergencias=(
                    DivergenciaDeSaldo(
                        especificacao="CDB 8056747",
                        declarado_no_ano=Decimal("8609.04"),
                        declarado_no_ano_anterior=Decimal("6771.59"),
                    ),
                ),
            )
        )
        veredito = _veredito(decisao, Sinal.CRUZAMENTO)

        assert veredito.executou and not veredito.aprovou
        assert "CDB 8056747" in decisao.campos_a_revisar

    def test_conta_nova_com_historico_reprova(self) -> None:
        decisao = _decide(
            cruzamento=ResultadoCruzamento(
                contas_conferidas=("CDB 8056747",),
                contas_novas_com_historico=(
                    ContaNovaComHistorico(
                        especificacao="LCI 99", saldo_anterior_declarado=Decimal("100.00")
                    ),
                ),
            )
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert "LCI 99" in decisao.campos_a_revisar


class TestAritmeticaQueReprova:
    def test_total_adulterado_reprova_e_diz_qual_quadro(self) -> None:
        bruto = _bancario(
            rendimentos_exclusivos=QuadroExtraido(
                linhas=[LinhaExtraida(identificador="CDB", valor="1.000,00")],
                total_impresso="2.837,45",
            )
        )

        decisao = _decide(extracao=_extracao(bruto))
        veredito = _veredito(decisao, Sinal.ARITMETICA)

        assert veredito.executou and not veredito.aprovou
        assert "rendimentos_exclusivos" in decisao.campos_a_revisar
        assert not decisao.so_falta_de_cobertura, "isto é reprovação, não falta de cobertura"

    def test_o_dominio_reprova_junto_e_os_dois_aparecem(self) -> None:
        bruto = _bancario(
            rendimentos_exclusivos=QuadroExtraido(
                linhas=[LinhaExtraida(identificador="CDB", valor="1.000,00")],
                total_impresso="2.837,45",
            )
        )

        decisao = _decide(extracao=_extracao(bruto))

        assert {v.sinal for v in decisao.bloqueadores} == {Sinal.DOMINIO, Sinal.ARITMETICA}


class TestOsOutrosSinaisContinuamBloqueando:
    def test_achado_de_sanitizacao_nunca_auto_aprova(self) -> None:
        decisao = _decide(sanitizacao=SANITIZACAO_COM_ACHADO)

        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_dv_de_cnpj_errado_bloqueia(self) -> None:
        decisao = _decide(extracao=_extracao(_bancario(fonte_pagadora_cnpj="01.829.356/0001-04")))

        assert not _veredito(decisao, Sinal.DOMINIO).aprovou

    def test_grounding_ausente_bloqueia_e_aponta_o_lugar(self) -> None:
        decisao = _decide(
            grounding=ResultadoGrounding(
                (
                    Conferencia(
                        "valor",
                        Situacao.AUSENTE,
                        "99,99",
                        "não aparece",
                        "rendimentos_isentos[LCI].valor",
                    ),
                )
            )
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert "rendimentos_isentos[LCI].valor" in decisao.campos_a_revisar

    def test_divergencia_entre_execucoes_bloqueia(self) -> None:
        decisao = _decide(
            consistencia=ResultadoConsistencia(
                executou=True,
                divergencias=(Divergencia("rendimentos_isentos[LCI].valor", "10,00", "100,00"),),
                campos_comparados=20,
            )
        )

        assert decisao.rota is Rota.REVISAO_HUMANA

    def test_consistencia_dispensada_nao_bloqueia(self) -> None:
        """Sinal desligado por configuração é escolha registrada, não ponto cego."""
        decisao = _decide(
            consistencia=ResultadoConsistencia(
                executou=False, motivo_de_nao_executar="condicional", dispensado=True
            )
        )

        assert decisao.rota is Rota.AUTO_APROVADO

    def test_consistencia_que_falhou_bloqueia(self) -> None:
        decisao = _decide(
            consistencia=ResultadoConsistencia(
                executou=False, motivo_de_nao_executar="sem segundo provedor", dispensado=False
            )
        )

        assert decisao.rota is Rota.REVISAO_HUMANA


@pytest.mark.parametrize("sinal", list(Sinal))
def test_todo_sinal_tem_valor_estavel_para_o_relatorio(sinal: Sinal) -> None:
    """Os nomes vão para JSON de eval; renomear um quebra comparação com passadas velhas."""
    assert sinal.value == sinal.value.lower()
