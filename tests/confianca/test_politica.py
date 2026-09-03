"""Roteamento final: como os quatro sinais se somam. Função pura, sem rede."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.confianca.consistencia import (
    Divergencia,
    ResultadoConsistencia,
    dispensa,
    falha,
)
from app.confianca.grounding import Conferencia, ResultadoGrounding, Situacao
from app.confianca.politica import Rota, Sinal, decide
from app.dominio.boleto import Boleto
from app.extracao.extrator import Extracao
from app.extracao.prompt import carrega
from app.extracao.schema_transporte import BoletoExtraido
from app.llm.provedor import UsoDeTokens
from app.seguranca.politica import Decisao as DecisaoDeSanitizacao
from app.seguranca.politica import Rota as RotaDeSanitizacao

PROMPT = carrega()

SANITIZACAO_OK = DecisaoDeSanitizacao(rota=RotaDeSanitizacao.AUTOMATICO, motivo="sem achados")
SANITIZACAO_RUIM = DecisaoDeSanitizacao(
    rota=RotaDeSanitizacao.REVISAO_HUMANA, motivo="1 achado de sanitização"
)
GROUNDING_OK = ResultadoGrounding((Conferencia("valor", Situacao.ENCONTRADO, "10,00"),))
GROUNDING_RUIM = ResultadoGrounding(
    (Conferencia("valor", Situacao.AUSENTE, "1,00", "não aparece"),)
)
CONSISTENCIA_OK = ResultadoConsistencia(executou=True)
CONSISTENCIA_RUIM = ResultadoConsistencia(
    executou=True, divergencias=(Divergencia("beneficiario_nome", "A", "B"),)
)


def _extracao(*, fecha: bool, boleto: Boleto | None = None) -> Extracao:
    return Extracao(
        documento=Path("b.pdf"),
        prompt=PROMPT,
        bruto=BoletoExtraido(valor="10,00"),
        dominio=boleto if fecha else None,
        erro_de_dominio=None if fecha else "valor não confere com a linha digitável",
        provedor="falso",
        modelo="falso-1",
        uso=UsoDeTokens(entrada=100, saida=20),
        custo_estimado_usd=Decimal("0.0001"),
        do_cache=False,
    )


@pytest.fixture(scope="module")
def boleto_valido() -> Boleto:
    import json

    dados = json.loads(Path("dados/sinteticos/boletos/boleto-001.json").read_text("utf-8"))
    return Boleto.model_validate(dados["campos"])


class TestTodosOsSinaisPassam:
    def test_auto_aprova(self, boleto_valido: Boleto) -> None:
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=CONSISTENCIA_OK,
        )

        assert decisao.rota is Rota.AUTO_APROVADO
        assert decisao.bloqueadores == ()


class TestQualquerSinalBloqueia:
    def test_achado_de_sanitizacao_nunca_auto_aprova(self, boleto_valido: Boleto) -> None:
        """Política da Fase 1.2, mantida aqui."""
        decisao = decide(
            sanitizacao=SANITIZACAO_RUIM,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=CONSISTENCIA_OK,
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert [v.sinal for v in decisao.bloqueadores] == [Sinal.SANITIZACAO]

    def test_dv_que_nao_fecha_bloqueia(self) -> None:
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=False),
            grounding=GROUNDING_OK,
            consistencia=CONSISTENCIA_OK,
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert Sinal.DIGITO_VERIFICADOR in [v.sinal for v in decisao.bloqueadores]

    def test_grounding_reprovado_bloqueia(self, boleto_valido: Boleto) -> None:
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_RUIM,
            consistencia=CONSISTENCIA_OK,
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert "valor" in decisao.campos_a_revisar

    def test_divergencia_entre_execucoes_bloqueia(self, boleto_valido: Boleto) -> None:
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=CONSISTENCIA_RUIM,
        )

        assert decisao.rota is Rota.REVISAO_HUMANA
        assert "beneficiario_nome" in decisao.campos_a_revisar


class TestSinalQueNaoRodou:
    def test_sinal_dispensado_pelo_operador_nao_bloqueia(self, boleto_valido: Boleto) -> None:
        """Bloquear tudo tornaria o modo condicional inútil; a escolha fica registrada."""
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=dispensa("AUTO_CONSISTENCIA=nunca"),
        )

        assert decisao.rota is Rota.AUTO_APROVADO
        assert "não executado" in decisao.para_revisor()

    def test_sinal_que_falhou_bloqueia(self, boleto_valido: Boleto) -> None:
        """Deveria ter rodado e não rodou: documento não conferido."""
        decisao = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=falha("a cota diária acabou"),
        )

        assert decisao.rota is Rota.REVISAO_HUMANA


class TestRelatorio:
    def test_traz_o_veredito_de_cada_sinal(self, boleto_valido: Boleto) -> None:
        relatorio = decide(
            sanitizacao=SANITIZACAO_OK,
            extracao=_extracao(fecha=True, boleto=boleto_valido),
            grounding=GROUNDING_OK,
            consistencia=CONSISTENCIA_OK,
        ).para_revisor()

        for sinal in Sinal:
            assert sinal.value in relatorio
