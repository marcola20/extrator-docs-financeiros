"""Configuração da aplicação, carregada de variáveis de ambiente ou .env."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores de configuração. Cada campo corresponde a uma variável de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://extrator:extrator@localhost:5432/extrator"
    anthropic_api_key: SecretStr = SecretStr("")


@lru_cache
def get_settings() -> Settings:
    """Retorna a configuração carregada uma única vez por processo."""
    return Settings()
