"""Fábrica: o que o ambiente diz vira objeto, e o erro diz o que corrigir."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm import ProvedorComCotaECache, cria_provedor
from app.llm.cache import CacheDeExtracao
from app.llm.gemini import MODELO_COMPARACAO, MODELO_PADRAO
from app.llm.limitador import Cota, CotaDiariaExcedida, LimitadorDeTaxa
from app.llm.provedor import ErroDeConfiguracao, ProvedorLLM
from tests.llm.falso import DocumentoFalso, ProvedorFalso, RelogioFalso

VARIAVEIS = (
    "LLM_PROVEDOR",
    "LLM_MODELO",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "LLM_RPM",
    "LLM_RPD",
)


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isola do .env e do ambiente da máquina."""
    for variavel in VARIAVEIS:
        monkeypatch.delenv(variavel, raising=False)


def _settings(tmp_path: Path, **campos: Any) -> Settings:
    padroes: dict[str, Any] = {
        "llm_arquivo_cotas": tmp_path / "cotas.json",
        "llm_cache_diretorio": tmp_path / "cache",
    }
    padroes.update(campos)
    return Settings(_env_file=None, **padroes)


def test_padrao_e_gemini_flash_lite(tmp_path: Path) -> None:
    settings = _settings(tmp_path, gemini_api_key=SecretStr("chave-de-teste"))

    provedor = cria_provedor(settings)

    assert isinstance(provedor, ProvedorLLM)
    assert isinstance(provedor, ProvedorComCotaECache)
    assert provedor.nome == "gemini"
    assert provedor.modelo == MODELO_PADRAO
    assert provedor.limitador.cota == Cota(rpm=15, rpd=500)


def test_chave_ausente_diz_qual_variavel_preencher(tmp_path: Path) -> None:
    settings = _settings(tmp_path, llm_provedor="gemini")

    with pytest.raises(ErroDeConfiguracao, match="GEMINI_API_KEY"):
        cria_provedor(settings)


def test_chave_ausente_da_anthropic_diz_a_variavel_dela(tmp_path: Path) -> None:
    settings = _settings(tmp_path, llm_provedor="anthropic")

    with pytest.raises(ErroDeConfiguracao, match="ANTHROPIC_API_KEY"):
        cria_provedor(settings)


def test_chave_do_outro_provedor_nao_serve(tmp_path: Path) -> None:
    """Ter chave da Anthropic não habilita o Gemini."""
    settings = _settings(
        tmp_path, llm_provedor="gemini", anthropic_api_key=SecretStr("chave-de-teste")
    )

    with pytest.raises(ErroDeConfiguracao, match="GEMINI_API_KEY"):
        cria_provedor(settings)


def test_provedor_desconhecido_lista_os_validos(tmp_path: Path) -> None:
    settings = _settings(tmp_path, llm_provedor="openai")

    with pytest.raises(ErroDeConfiguracao, match="anthropic, gemini") as erro:
        cria_provedor(settings)

    assert "LLM_PROVEDOR" in str(erro.value)


def test_nome_do_provedor_ignora_caixa_e_espaco(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path, llm_provedor="  Gemini ", gemini_api_key=SecretStr("chave-de-teste")
    )

    assert cria_provedor(settings).nome == "gemini"


def test_anthropic_e_escolhivel_pelo_ambiente(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path, llm_provedor="anthropic", anthropic_api_key=SecretStr("chave-de-teste")
    )

    provedor = cria_provedor(settings)

    assert provedor.nome == "anthropic"
    assert provedor.modelo == "claude-opus-5"


def test_llm_modelo_troca_o_modelo_e_a_cota(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        llm_modelo=MODELO_COMPARACAO,
        gemini_api_key=SecretStr("chave-de-teste"),
    )

    provedor = cria_provedor(settings)

    assert isinstance(provedor, ProvedorComCotaECache)
    assert provedor.modelo == MODELO_COMPARACAO
    assert provedor.limitador.cota == Cota(rpm=5, rpd=20)


def test_modelo_sem_preco_cadastrado_falha_cedo(tmp_path: Path) -> None:
    """Sem preço não há custo estimado, e custo estimado é parte do contrato."""
    settings = _settings(
        tmp_path, llm_modelo="gemini-inventado", gemini_api_key=SecretStr("chave-de-teste")
    )

    with pytest.raises(ErroDeConfiguracao, match="sem preço cadastrado"):
        cria_provedor(settings)


def test_cota_do_ambiente_sobrepoe_a_de_tabela(tmp_path: Path) -> None:
    settings = _settings(tmp_path, llm_rpm=2, llm_rpd=7, gemini_api_key=SecretStr("chave-de-teste"))

    provedor = cria_provedor(settings)

    assert isinstance(provedor, ProvedorComCotaECache)
    assert provedor.limitador.cota == Cota(rpm=2, rpd=7)


def _composto(tmp_path: Path, base: ProvedorFalso, cota: Cota) -> ProvedorComCotaECache:
    return ProvedorComCotaECache(
        base=base,
        limitador=LimitadorDeTaxa(
            "falso:falso-1",
            cota,
            tmp_path / "cotas.json",
            agora=RelogioFalso().agora,
            hoje=lambda: date(2026, 9, 2),
            dorme=lambda _: None,
        ),
        cache=CacheDeExtracao(diretorio=tmp_path / "cache"),
    )


def test_acerto_de_cache_nao_chama_o_provedor_nem_gasta_cota(tmp_path: Path) -> None:
    base = ProvedorFalso()
    provedor = _composto(tmp_path, base, Cota(rpm=10, rpd=10))

    primeiro = provedor.extrai("documento", DocumentoFalso)
    segundo = provedor.extrai("documento", DocumentoFalso)

    assert len(base.chamadas) == 1
    assert primeiro.dados.valor == segundo.dados.valor == Decimal("123.45")
    assert primeiro.do_cache is False
    assert segundo.do_cache is True
    assert provedor.limitador.restante_hoje() == 9


def test_documento_diferente_chama_o_provedor_de_novo(tmp_path: Path) -> None:
    base = ProvedorFalso()
    provedor = _composto(tmp_path, base, Cota(rpm=10, rpd=10))

    provedor.extrai("documento A", DocumentoFalso)
    provedor.extrai("documento B", DocumentoFalso)

    assert len(base.chamadas) == 2


def test_cota_diaria_estourada_atravessa_o_composto(tmp_path: Path) -> None:
    base = ProvedorFalso()
    provedor = _composto(tmp_path, base, Cota(rpm=10, rpd=1))

    provedor.extrai("documento A", DocumentoFalso)

    with pytest.raises(CotaDiariaExcedida):
        provedor.extrai("documento B", DocumentoFalso)


class TestTravaDeRede:
    """`LLM_SEM_REDE` é a promessa do CI transformada em código.

    Nenhum job do CI chama o provedor. Sem a trava, essa promessa dependeria de
    nenhum teste novo esquecer de injetar um dublê — e o sintoma seria um job
    parado em timeout de rede, ou cota consumida sem ninguém ter pedido.
    """

    def test_a_fabrica_recusa_montar_provedor(self, tmp_path: Path) -> None:
        configuracao = Settings(
            _env_file=None,
            llm_provedor="gemini",
            gemini_api_key=SecretStr("chave-de-teste"),
            llm_arquivo_cotas=tmp_path / "cotas.json",
            llm_cache_diretorio=tmp_path / "cache",
            llm_sem_rede=True,
        )

        with pytest.raises(ErroDeConfiguracao, match="LLM_SEM_REDE"):
            cria_provedor(configuracao)

    def test_a_mensagem_diz_o_que_fazer_num_teste(self) -> None:
        """O destinatário é quem escreveu o teste que esbarrou nisto."""
        configuracao = Settings(_env_file=None, llm_sem_rede=True)

        with pytest.raises(ErroDeConfiguracao, match="provedor de mentira"):
            cria_provedor(configuracao)

    def test_desligada_por_padrao(self, tmp_path: Path) -> None:
        """O desenvolvimento local fala com a API; é o CI que não fala."""
        configuracao = Settings(
            _env_file=None,
            gemini_api_key=SecretStr("chave-de-teste"),
            llm_arquivo_cotas=tmp_path / "cotas.json",
            llm_cache_diretorio=tmp_path / "cache",
        )

        assert not configuracao.llm_sem_rede
        assert cria_provedor(configuracao) is not None
