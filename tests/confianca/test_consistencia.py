"""Sinal 3: duas execuções concordam?"""

import pytest
from pydantic import SecretStr

from app.confianca.consistencia import (
    ModoConsistencia,
    compara,
    deve_executar,
    dispensa,
    falha,
    provedor_para_segunda_execucao,
)
from app.config import Settings
from app.extracao.schema_transporte import BoletoExtraido
from app.llm import ProvedorComCotaECache


def _extraido(**campos: str) -> BoletoExtraido:
    base = {"linha_digitavel": "123", "beneficiario_nome": "Empresa", "valor": "10.00"}
    return BoletoExtraido(**(base | campos))


class TestComparacao:
    def test_execucoes_iguais_concordam(self) -> None:
        resultado = compara(_extraido(), _extraido())

        assert resultado.concordam
        assert resultado.taxa_de_divergencia == 0.0

    def test_divergencia_nomeia_o_campo_e_os_dois_valores(self) -> None:
        resultado = compara(_extraido(), _extraido(beneficiario_nome="Outra"))

        assert not resultado.concordam
        (divergencia,) = resultado.divergencias
        assert divergencia.campo == "beneficiario_nome"
        assert divergencia.primeira == "Empresa"
        assert divergencia.segunda == "Outra"

    def test_espaco_em_volta_nao_e_divergencia(self) -> None:
        assert compara(_extraido(), _extraido(valor=" 10.00 ")).concordam


class TestQuandoRoda:
    def test_sempre_roda_sempre(self) -> None:
        assert deve_executar(ModoConsistencia.SEMPRE, algum_sinal_falhou=False)[0]
        assert deve_executar(ModoConsistencia.SEMPRE, algum_sinal_falhou=True)[0]

    def test_condicional_so_roda_quando_outro_sinal_falhou(self) -> None:
        roda_sem_falha, motivo = deve_executar(
            ModoConsistencia.CONDICIONAL, algum_sinal_falhou=False
        )
        roda_com_falha, _ = deve_executar(ModoConsistencia.CONDICIONAL, algum_sinal_falhou=True)

        assert not roda_sem_falha
        assert roda_com_falha
        assert "ponto cego" in motivo

    def test_nunca_nao_roda(self) -> None:
        roda, motivo = deve_executar(ModoConsistencia.NUNCA, algum_sinal_falhou=True)

        assert not roda
        assert "nunca" in motivo


class TestDispensadoVersusFalho:
    def test_dispensado_registra_a_escolha(self) -> None:
        resultado = dispensa("operador desligou")

        assert not resultado.executou
        assert resultado.dispensado

    def test_falha_nao_e_dispensa(self) -> None:
        """Sinal que deveria rodar e não rodou é documento não conferido."""
        resultado = falha("cota estourou")

        assert not resultado.executou
        assert not resultado.dispensado


class TestSegundaExecucao:
    def test_o_provedor_da_segunda_execucao_nao_tem_cache(self, tmp_path: object) -> None:
        """Sem isto a segunda execução seria um acerto de cache, e o sinal, tautologia."""
        settings = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("chave-de-teste"),
            llm_arquivo_cotas=tmp_path / "cotas.json",  # type: ignore[operator]
            llm_cache_diretorio=tmp_path / "cache",  # type: ignore[operator]
        )

        provedor = provedor_para_segunda_execucao(settings)

        assert isinstance(provedor, ProvedorComCotaECache)
        assert not provedor.cache.ativo


@pytest.mark.parametrize("modo", list(ModoConsistencia))
def test_todo_modo_e_reconhecido(modo: ModoConsistencia) -> None:
    assert deve_executar(modo, algum_sinal_falhou=True)[0] in (True, False)
