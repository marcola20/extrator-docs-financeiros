# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros
com validação determinística e roteamento para revisão humana.

## Contexto

Projeto de portfólio. Autor vem de C#/.NET, aprendendo Python de forma
aplicada. Preferir código explícito e tipado sobre "pythonices" mágicas.

## Princípios

- Sem framework de LLM (LangChain etc). SDK direto.
- Valor monetário sempre `Decimal`, nunca `float`.
- Confiança vem de validação determinística, não do confidence do modelo.
  Ver ADR 002.
- Todo dado é sintético. Documento real nunca entra no repo.

## Escopo por fase

1. Boleto — pipeline vertical, structured output, eval básico
   1. Gerador sintético, schema e validadores determinísticos
   2. Sanitização e documentos adversariais (defesa contra prompt injection)
   3. Extração via LLM com structured output, e eval
2. Informe de Rendimentos — seções, listas, validação cruzada entre anos
3. Extrato de investimento — multi-página, tabela com quebra
4. Revisão (Next.js) + observabilidade

## Stack

Python 3.12 / uv / FastAPI / Pydantic v2 / SQLAlchemy 2 / Postgres 16
pdfplumber / pypdfium2 / Pillow / SDK Anthropic
Jinja2 + WeasyPrint (geração dos PDFs sintéticos)
pytest / ruff / mypy / Docker Compose / Langfuse / Next.js 15

## Convenções

- Type hints obrigatórios. mypy em modo strict (`app/` e `tests/`).
- Testes junto da feature, não depois.
- Commits pequenos, em português, no imperativo.
- Desenvolvimento sempre no WSL2, repo em `~/projetos` (nunca `/mnt/*`).
  Nada de comando PowerShell ou caminho Windows. Ver ADR 001.
- Decisões de arquitetura viram ADR em `docs/adr/`, numerados, no formato
  contexto / decisão / consequências.

## Comandos

```bash
uv sync                # instala dependências (cria .venv)
uv run pytest          # testes
uv run ruff check .    # lint
uv run ruff format .   # formatação
uv run mypy            # tipos (strict em app/)
uv run uvicorn app.main:app --reload   # API em http://127.0.0.1:8000
docker compose up -d   # Postgres 16 local

# Boletos sintéticos em dados/sinteticos/boletos/, PDF + gabarito JSON.
# Recusa sobrescrever um lote existente; use --forcar, --saida ou --prefixo.
# Com --semente N o lote sai sempre igual.
uv run python -m app.geradores.boleto_sintetico --quantidade 15
```

## Estado atual

Fase 1.1 concluída (gerador, schema, validadores).
Próximo: Fase 1.2, sanitização e documentos adversariais.
