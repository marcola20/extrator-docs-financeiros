"""Configuração da aplicação, carregada de variáveis de ambiente ou .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Valores de configuração. Cada campo corresponde a uma variável de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://extrator:extrator@localhost:5432/extrator"

    # Persistência é opcional, e desligada por padrão. O pipeline e o eval
    # rodam sem banco — fazer a medição depender de um Postgres de pé
    # transformaria "rodar o eval" numa tarefa de infraestrutura. Só a fila de
    # revisão da Fase 4 precisa dele. Ver ADR 010.
    persistencia_ativa: bool = False

    # Provedor de LLM (ADR 003). O padrão é o Gemini por causa do tier gratuito.
    llm_provedor: str = "gemini"
    # Vazio significa "use o modelo padrão do provedor".
    llm_modelo: str = ""

    gemini_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")

    # Zero significa "use a cota de tabela do provedor" (app/llm/gemini.py).
    llm_rpm: int = 0
    llm_rpd: int = 0
    llm_arquivo_cotas: Path = Path("dados/estado-cotas.json")

    llm_cache_ativo: bool = True
    llm_cache_diretorio: Path = Path("dados/cache-llm")

    # Observabilidade (Fase 4). Sem chave pública, o observador é mudo e nada
    # acontece — o eval processa 56 documentos e não pode passar a depender de
    # um serviço. Ver `app/observabilidade.py`.
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
    langfuse_host: str = "http://localhost:3000"

    # Trava de rede. Ligada, `cria_provedor` recusa montar qualquer provedor
    # que fale com a API. Existe para o CI: nenhum job dele chama o modelo, e
    # sem a trava essa promessa dependeria de nenhum teste novo esquecer de
    # injetar um dublê — o tipo de erro que aparece como job travado em
    # timeout de rede, ou como cota consumida sem ninguém pedir.
    llm_sem_rede: bool = False

    # Sinal de auto-consistência (ADR 005): sempre | condicional | nunca.
    # "sempre" dobra o consumo de cota e dá taxa base comparável entre
    # documentos; "condicional" economiza metade e assume um ponto cego.
    auto_consistencia: str = "sempre"


@lru_cache
def get_settings() -> Settings:
    """Retorna a configuração carregada uma única vez por processo."""
    return Settings()
