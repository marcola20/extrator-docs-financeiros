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
