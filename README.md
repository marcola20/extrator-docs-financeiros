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
app/ingestao/        leitura do PDF: texto ou visão, com sanitização junto
app/seguranca/       sanitização de documentos não confiáveis
app/extracao/        prompt versionado e extração via LLM
app/confianca/       grounding, auto-consistência e roteamento
eval.py              medição do pipeline contra os corpora
dados/sinteticos/    documentos sintéticos versionados, limpos e adversariais
dados/real/          documentos reais para teste local, fora do git
docs/adr/            decisões de arquitetura
```

## Resultados

O pipeline completo — ingestão, sanitização, extração, três sinais de
confiança e roteamento — está implementado e testado ponta a ponta com
provedor falso. **Os números abaixo ainda não foram medidos contra a API.**

Para medir:

```bash
# 1. Coloque uma chave do Gemini em .env (tier gratuito basta)
#    GEMINI_API_KEY=...
# 2. Ensaie com poucos documentos antes de gastar cota
uv run python eval.py --limite 5
# 3. Corpus inteiro: 43 documentos, ~86 chamadas, ~6 min a 15 RPM
uv run python eval.py
```

O relatório sai em tabela no terminal e em JSON versionado em `resultados/`,
carimbado com a versão do prompt, o modelo e a data.

| Métrica | Valor | O que significa |
|---|---|---|
| Acurácia por campo | *não medido* | fração de campos extraídos iguais ao gabarito |
| Taxa de auto-aprovação | *não medido* | documentos que passaram nos quatro sinais |
| **Escape rate** | *não medido* | **dos auto-aprovados, quantos divergem do gabarito** |
| Adversariais que alteraram a saída | *não medido* | resistência a prompt injection |
| Divergência entre execuções | *não medido* | sinal de auto-consistência |
| Custo por documento | *não medido* | preço de tabela; no tier gratuito não é cobrado |
| Latência p95 | *não medido* | por documento, incluindo os dois sinais |

**A métrica principal é a taxa de escape.** Acurácia média é confortável e diz
pouco: 95% de acurácia com escape zero é um sistema utilizável, e 99% com
escape de 2% não é. Um escape é um pagamento errado que ninguém revisou.

Ver [ADR 005](docs/adr/005-sinais-de-confianca.md) para por que os sinais são
três, e [ADR 002](docs/adr/002-validacao-por-digito-verificador.md) para por
que nenhum deles é o `confidence` do modelo.

## Modelo de ameaças

O pipeline lê PDFs enviados por terceiros e coloca o texto deles no prompt de
um modelo cuja saída decide aprovação de pagamento. **Quem manda o documento
controla parte da entrada do modelo** — não é preciso invadir nada, basta
enviar um boleto. É prompt injection, e é a superfície de ataque principal.

O ataque perigoso não é o visível. É o texto que o extrator lê perfeitamente
e o revisor humano não encontra: branco sobre branco, fonte de tamanho quase
zero, posicionado fora da página, ou com opacidade zero. Os quatro foram
reproduzidos e medidos — todos são extraídos, nenhum aparece impresso.

### Defesas, por camada

| Camada | O que faz | O que garante |
|---|---|---|
| Sanitização na ingestão | três detectores independentes: texto invisível, padrões de injection, divergência entre camada de texto e página renderizada | **nada, sozinha.** Encarece o ataque e levanta sinal |
| Isolamento no prompt | conteúdo entre delimitadores explícitos, marcado como dado e não como comando, com neutralização de tentativa de fechar o bloco | reduz a superfície, não a elimina |
| Roteamento | qualquer achado tira a auto-aprovação e manda para revisão com os trechos destacados | que ataque detectado nunca passa sozinho |
| **Validação determinística** | dígitos verificadores da linha digitável e cruzamento de banco, valor e vencimento ([ADR 002](docs/adr/002-validacao-por-digito-verificador.md)) | **esta é a garantia real** |

A ordem importa. O sanitizador **não é** a garantia do sistema: detecção por
padrão de texto é uma corrida perdida, porque qualquer padrão escrito aqui
pode ser reformulado do outro lado. O que sustenta o pipeline é aritmética —
um atacante pode induzir o modelo a escrever `valor: 1,00`, mas não consegue
produzir uma linha digitável de 47 dígitos cujos dígitos verificadores fechem
com esse valor.

Achado da sanitização é sinal. Ausência de achado não é atestado.
Ver [ADR 004](docs/adr/004-defesa-contra-prompt-injection.md).

### Fora de escopo

- **Ataque por imagem dirigido a modelo com visão.** Instrução escrita dentro
  de uma imagem não está na camada de texto e nenhum detector daqui a lê. Hoje
  não é exposição, porque o pipeline manda texto e não imagem; passa a ser
  quando existir caminho de visão, e a defesa terá que nascer junto com ele.
- **Homoglifos e caracteres de controle** (bidi, largura zero, letras
  cirílicas parecidas com latinas) para escapar dos padrões sem parecer
  estranho na página. Reconhecido, não tratado.
- **Negação de serviço por documento grande.** Não há limite de tamanho nem
  de tempo na ingestão.
- **Autenticidade do PDF.** Se o atacante controla o documento inteiro,
  inclusive a linha digitável, o problema deixa de ser injeção e vira troca de
  documento — anterior ao pipeline.

### Corpus adversarial

`dados/sinteticos/boletos_adversariais/` tem 28 boletos com um ataque cada e
gabarito declarando o ataque, onde está, a extração correta e quais detectores
deveriam acusar. Dois casos existem para provar limites: `valor_divergente`,
que a sanitização **não pega** de propósito — é o que só a validação
determinística vê — e `opacidade_zero`, que só a comparação com a imagem pega.

```bash
uv run python -m app.geradores.boleto_adversarial --quantidade 28 --semente 2026
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
commit é permanente. Ver [`dados/real/LEIA-ME.md`](dados/real/LEIA-ME.md).
Além do `.gitignore`, `tests/test_dados_reais_nao_versionados.py` falha se
algum arquivo de lá aparecer rastreado.
