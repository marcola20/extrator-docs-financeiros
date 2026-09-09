# Imagem da API de revisão.
#
# Enxuta de propósito: importar `app.main` não carrega WeasyPrint, pdfplumber,
# pypdfium2 nem os SDKs de LLM — conferido, e é consequência de a API só ler o
# banco e servir arquivo. Ela **não processa documento**: extrair custa cota e
# dezenas de segundos, e um endpoint que chamasse o modelo viraria porta para
# gastar orçamento (ver `app/api/revisao.py`).
#
# Quem gera corpus e roda o eval continua fazendo isso fora daqui, com `uv` no
# WSL, onde as bibliotecas nativas do WeasyPrint já estão instaladas.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# As dependências primeiro, para a camada delas ser reaproveitada quando só o
# código muda.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY app ./app
COPY migracoes ./migracoes
# `alembic.ini` para rodar migração de dentro do contêiner; o README porque o
# `pyproject.toml` o declara e o hatchling recusa construir o pacote sem ele.
COPY alembic.ini README.md ./
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
