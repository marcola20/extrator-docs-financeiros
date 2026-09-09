# Desenvolvimento

Requisitos, setup, os comandos de qualidade, a estrutura do repositório e a
política sobre dados.

[← README](../README.md)

## Requisitos

- WSL2 / Linux (ver [ADR 001](adr/001-desenvolvimento-em-wsl2.md))
- Python 3.12 e [uv](https://docs.astral.sh/uv/)
- Docker, para o Postgres, a API e a interface
- Bibliotecas nativas do WeasyPrint, que gera os PDFs sintéticos, e o tesseract
  em **português**, que o detector de divergência texto/imagem usa. Sem o pacote
  de idioma o OCR cai para inglês num documento em português, e passa a acusar
  divergência em documento limpo:

  ```bash
  sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
                   libcairo2 libgdk-pixbuf-2.0-0 \
                   tesseract-ocr tesseract-ocr-por
  ```

Node não é requisito: o front é construído em contêiner (`node:22-alpine`).

## Setup

```bash
uv sync
cp .env.example .env
docker compose up -d
uv run uvicorn app.main:app --reload
```

A API sobe em http://127.0.0.1:8000. `GET /health` responde `status`, e também
se persistência e observabilidade estão ligadas neste ambiente — as duas são
opcionais e vêm desligadas.

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy                    # strict, em app/ e tests/
uv run pytest -m "not slow"    # ~2 min: tudo menos OCR
uv run pytest                  # ~7 min: a suíte inteira
```

Os testes marcados `slow` renderizam a página e chamam OCR; são eles a diferença
entre os dois tempos. O CI roda o conjunto rápido em cada PR e a suíte inteira no
merge para `main`.

Uma suíte fica **fora** dos dois comandos e pula sozinha sem banco de pé. Ela
confere o que o SQLite não prova — tipo de coluna, CHECK, `timestamptz` — e exige
uma variável explícita porque **apaga as tabelas** ao terminar:

```bash
PYTEST_POSTGRES=1 uv run pytest -m postgres
```

O front tem build e checagem de tipos próprios, e nenhum dos dois está no CI
([#6][i6]):

```bash
docker run --rm -v "$PWD/web":/app -w /app node:22-alpine npm run build
```

## Estrutura

```
app/dominio/         boleto, informe, linha digitável, DVs, cruzamento entre anos
app/ingestao/        leitura do PDF: texto ou visão, com sanitização junto
app/seguranca/       sanitização de documentos não confiáveis
app/extracao/        prompts versionados e extração, um extrator por documento
app/confianca/       grounding, auto-consistência e roteamento
app/pipeline.py      boleto: de um PDF a uma decisão
app/pipeline_informe.py  informe: de um par de anos consecutivos a duas decisões

app/llm/             provedores, limitador de taxa e cache
app/geradores/       corpus sintético — limpo, adversarial, e a fila de demonstração
app/avaliacao/       métricas de linha, realimentação, e o que os dois evals compartilham
eval.py              medição contra os corpora (`--informes` troca o corpus)

app/persistencia/    modelo de dados da fila, opcional por configuração
app/api/             API de revisão: fila, diagnóstico, correções, estatísticas
app/observabilidade.py   traces no Langfuse, mudos quando não configurado
migracoes/           migrações Alembic
web/                 interface de revisão em Next.js

tests/               testes, junto da feature
dados/sinteticos/    documentos sintéticos versionados, limpos e adversariais
dados/real/          documentos reais para teste local, fora do git
resultados/          relatórios de eval, um JSON por passada
docs/adr/            decisões de arquitetura
```

## Dados

Todo dado versionado neste repositório é sintético, gerado por templates
Jinja2 + WeasyPrint. O `.gitignore` bloqueia `dados/` inteiro, exceto
`dados/sinteticos/`.

A avaliação roda sempre contra esse dataset sintético versionado: ele é
fixo e reprodutível, então dá para comparar duas execuções e saber que a
diferença veio da mudança no extrator, não do corpus.

Documentos reais são testados apenas localmente, sem versionamento. Ficam
em `dados/real/`, que o git ignora por inteiro — eles contêm dados
pessoais de terceiros (nome, CPF, CNPJ, endereço, agência e conta) e um
commit é permanente. Ver [`dados/real/LEIA-ME.md`](../dados/real/LEIA-ME.md).
Além do `.gitignore`, `tests/test_dados_reais_nao_versionados.py` falha se
algum arquivo de lá aparecer rastreado.

Documento real também não é enviado pelo tier gratuito do provedor, que treina
o modelo com o que recebe. Ver [ADR 003](adr/003-abstracao-de-provedor-llm.md).

[i6]: https://github.com/marcola20/extrator-docs-financeiros/issues/6
