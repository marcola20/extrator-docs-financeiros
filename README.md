# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros
(boleto, informe de rendimentos, extrato de investimento) usando o SDK da
Anthropic diretamente, com validação determinística e roteamento para
revisão humana.

## Setup

```bash
uv sync
cp .env.example .env
docker compose up -d
uv run uvicorn app.main:app --reload
```

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Todo dado neste repositório é sintético. Documentos reais nunca entram aqui.
