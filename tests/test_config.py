import pytest
from pydantic import SecretStr

from app.config import Settings


def test_settings_usa_valores_padrao(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_url.startswith("postgresql+psycopg://")
    assert settings.anthropic_api_key == SecretStr("")


def test_settings_le_variaveis_de_ambiente(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-teste")

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key.get_secret_value() == "chave-teste"


class TestUrlDoBanco:
    """A normalização que existe por causa da hospedagem. Ver `app/config.py`."""

    @pytest.mark.parametrize(
        "recebida",
        ["postgres://u:s@host:5432/d", "postgresql://u:s@host:5432/d"],
    )
    def test_completa_o_driver_quando_falta(self, recebida: str) -> None:
        """O provedor entrega a URL no formato da libpq; o SQLAlchemy recusa."""
        settings = Settings(_env_file=None, database_url=recebida)

        assert settings.database_url == "postgresql+psycopg://u:s@host:5432/d"

    def test_nao_mexe_em_url_que_ja_tem_driver(self) -> None:
        recebida = "postgresql+psycopg://u:s@host:5432/d"

        assert Settings(_env_file=None, database_url=recebida).database_url == recebida

    def test_nao_mexe_em_sqlite(self) -> None:
        """A suíte inteira roda em SQLite; tocar nisso quebraria tudo."""
        recebida = "sqlite:///tmp/fila.db"

        assert Settings(_env_file=None, database_url=recebida).database_url == recebida

    def test_preserva_a_senha_e_os_parametros(self) -> None:
        recebida = "postgres://u:se%40nha@host/d?sslmode=require"

        assert Settings(_env_file=None, database_url=recebida).database_url == (
            "postgresql+psycopg://u:se%40nha@host/d?sslmode=require"
        )


def test_somente_leitura_desligado_por_padrao() -> None:
    """Quem roda localmente grava correção; quem liga é o render.yaml."""
    assert Settings(_env_file=None).demo_somente_leitura is False
