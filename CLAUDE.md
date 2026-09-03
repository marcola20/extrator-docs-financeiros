# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros
com validação determinística e roteamento para revisão humana.

## Contexto

Projeto de portfólio. Autor vem de C#/.NET, aprendendo Python de forma
aplicada. Preferir código explícito e tipado sobre "pythonices" mágicas.

## Princípios

- SDK do provedor direto, atrás de interface fina (`app/llm`). Sem
  framework de LLM (LangChain etc). Ver ADR 003.
- Valor monetário sempre `Decimal`, nunca `float`.
- Confiança vem de validação determinística, não do confidence do modelo.
  Ver ADR 002.
- Todo dado é sintético. Documento real nunca entra no repo, e não é
  enviado pelo tier gratuito — ele treina o modelo do provedor. Ver ADR 003.

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
pdfplumber / pypdfium2 / Pillow
google-genai (padrão) / SDK Anthropic (comparação)
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
uv run python -m app.geradores.boleto_sintetico --quantidade 15

# Cache de extrações do LLM, para não gastar cota reexecutando eval igual.
uv run python -m app.llm.cache --limpar
```

## Corpus reproduzível

Comparar dois evals exige que o corpus seja o mesmo, ou que a troca seja
visível. Reproduzir um lote precisa de **duas** coisas, não uma: a semente e a
data de referência. O vencimento é sorteado como deslocamento a partir dessa
data, então a mesma semente em outro dia gera outro corpus, silenciosamente.

As duas ficam gravadas em `gerado_com` no gabarito de cada documento. Para
regerar o corpus atual, é só repetir o que está lá:

```bash
uv run python -m app.geradores.boleto_sintetico \
    --quantidade 15 --semente 2026 --data-referencia 2026-09-03 --forcar
uv run python -m app.geradores.boleto_adversarial \
    --quantidade 28 --semente 2026 --data-referencia 2026-09-03 --forcar
```

Regerar com outra semente ou outra data é legítimo, mas invalida a comparação
com os evals anteriores em `resultados/` — o corpus passa a ser outro, e o
`gerado_com` dos gabaritos é o que denuncia isso.

## Provedor de LLM

Configurável por `LLM_PROVEDOR` e `LLM_MODELO` (ver ADR 003). A motivação é
restrição de custo: o tier gratuito do Gemini é o orçamento do projeto.

- Padrão: `gemini` / `gemini-3.5-flash-lite` — 15 RPM, 500 RPD.
- Comparação final: `gemini-3.8-flash` — 5 RPM, 20 RPD, ou seja uma passada
  de eval por dia.
- `anthropic` / `claude-opus-5` existe para comparação futura.

Cota e cache ficam fora do Protocol, num decorador montado pela fábrica.
Identificadores de modelo são fixos, sem apelido `-latest`, para dois evals
continuarem comparáveis.

## Estado atual

Fase 1.1 concluída (gerador, schema, validadores).
Camada de provedor de LLM pronta e testada sem rede — nenhuma chamada real
foi feita ainda, e o structured output do Gemini não foi exercitado com o
schema `Boleto`.
Próximo: Fase 1.2, sanitização e documentos adversariais.
