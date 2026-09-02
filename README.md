# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros
(boleto, informe de rendimentos, extrato de investimento) usando o SDK da
Anthropic diretamente, com validação determinística e roteamento para
revisão humana.

Estado: fase 0 — esqueleto do projeto. Nenhuma extração implementada ainda.

## Requisitos

- WSL2 / Linux (ver [ADR 001](docs/adr/001-desenvolvimento-em-wsl2.md))
- Python 3.12 e [uv](https://docs.astral.sh/uv/)
- Docker, para o Postgres local
- Bibliotecas nativas do WeasyPrint:

  ```bash
  sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                   libcairo2 libgdk-pixbuf-2.0-0
  ```

## Setup

```bash
uv sync
cp .env.example .env
docker compose up -d
uv run uvicorn app.main:app --reload
```

A API sobe em http://127.0.0.1:8000; `GET /health` responde `{"status": "ok"}`.

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Estrutura

```
app/                 código da aplicação (FastAPI, configuração)
tests/               testes, junto da feature
dados/sinteticos/    documentos sintéticos versionados
docs/adr/            decisões de arquitetura
```

## Dados

Todo dado neste repositório é sintético, gerado por templates Jinja2 +
WeasyPrint. Documentos reais nunca entram aqui: o `.gitignore` bloqueia
`dados/` inteiro, exceto `dados/sinteticos/`.
