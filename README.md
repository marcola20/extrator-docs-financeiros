# Extrator de Documentos Financeiros

Pipeline de extração estruturada de documentos financeiros brasileiros, com
validação determinística e roteamento para revisão humana. O provedor de LLM
é configurável — Gemini por padrão, SDK direto, sem framework
([ADR 003](docs/adr/003-abstracao-de-provedor-llm.md)).

A tese do projeto está no [ADR 002](docs/adr/002-validacao-por-digito-verificador.md):
**a confiança não vem do modelo.** Um boleto carrega quatro dígitos
verificadores e três campos redundantes com o código de barras. Isso permite
perguntar se a extração fecha aritmeticamente, em vez de perguntar ao modelo
o quanto ele acha que acertou.

## Estado do projeto

Fase 1 (boleto) concluída, medida contra a API.

| Fase | Escopo | Estado |
|---|---|---|
| 1.1 | Gerador sintético, schema, validadores determinísticos | concluída |
| 1.2 | Sanitização e corpus adversarial | concluída |
| 1.3 | Extração via LLM com structured output, e eval | concluída |
| 2 | Informe de rendimentos: seções, listas, validação entre anos | não iniciada |
| 3 | Extrato de investimento: multi-página, tabela com quebra | não iniciada |
| 4 | Revisão (Next.js) e observabilidade | não iniciada |

O que a Fase 1 entregou: pipeline vertical de PDF a decisão
(`app/pipeline.py`), quatro sinais de confiança independentes do modelo, um
corpus sintético reprodutível de 43 documentos — 15 limpos e 28 adversariais
em 7 famílias de ataque —, e um eval que mede taxa de escape, resistência a
injection, custo e latência contra a API de verdade.

## Resultados

Fonte: [`resultados/eval-20260903-162652-boleto-v2+7462b7f8.json`](resultados/eval-20260903-162652-boleto-v2+7462b7f8.json).

| Procedência | |
|---|---|
| Data | 2026-09-03 16:26 UTC |
| Prompt | `boleto-v2+7462b7f8` |
| Modelo | `gemini-3.5-flash-lite`, temperatura 0 |
| Documentos | 43 de 43 processados, sem falhas |
| Consistência | `--consistencia sempre` (duas execuções por documento) |

**Pendente de reexecução.** Esta é a última passada completa de 43 documentos,
e ela é anterior ao [ADR 006](docs/adr/006-gabarito-do-impresso.md), que
redefiniu o gabarito para guardar o que está *impresso* na página em vez do
que é *verdadeiro*. Sob a definição nova, 8 das 9 divergências adversariais
desta passada deixam de ser erro — são transcrições corretas de um campo que
o ataque mandou imprimir. Os números de `beneficiario_nome` e `valor` devem
subir quando o corpus completo rodar de novo; os outros oito campos não mudam.
A única passada com o gabarito novo até agora perdeu 10 documentos para erro
de provedor, e uma passada parcial não é comparável com uma completa.

| Métrica | Valor | Base |
|---|---|---|
| **Escape rate** | **0%** | **sobre 15 auto-aprovados, de 43 processados** |
| Acurácia média | 97,7% | 10 campos sobre 43 documentos |
| Taxa de auto-aprovação | 34,9% | 15 de 43 |
| Ataques bem-sucedidos | 0 | de 28 adversariais |
| Adversariais auto-aprovados | 0 | de 28 |
| Divergência entre execuções | 0,5% | 43 segundas execuções |
| Custo por documento | US$ 0,001702 | preço de tabela, 2 chamadas por documento |
| Latência p50 / p95 | 10,2s / 46,1s | por documento, incluindo as duas execuções |

**A métrica principal é a taxa de escape**: dos documentos que o pipeline
auto-aprovou, quantos divergem do gabarito. Um escape é um pagamento errado
que ninguém revisou. Acurácia de 95% com escape zero é um sistema utilizável;
99% com escape de 2% não é.

A taxa vem sempre com o denominador ao lado, e o denominador aqui é pequeno:
**0% sobre 15 documentos** afirma muito menos do que a mesma taxa sobre
centenas. Ver [Limitações conhecidas](#limitações-conhecidas).

### Acurácia por campo, e o sinal que cobre cada um

A coluna da direita é o ponto do projeto. Os campos que o boleto protege com
aritmética são verificáveis sem consultar o modelo; os outros não são.

| Campo | Acurácia | Sinal determinístico |
|---|---|---|
| `linha_digitavel` | 95,3% | quatro DVs: três módulo 10 de campo, um módulo 11 geral |
| `banco_codigo` | 100% | cruzamento com a linha digitável |
| `valor` | 90,7% | cruzamento com a linha digitável |
| `vencimento` | 100% | cruzamento com a linha (fator de vencimento) |
| `beneficiario_cnpj` | 100% | DV do CNPJ |
| `pagador_cpf_cnpj` | 100% | DV do CPF/CNPJ |
| `beneficiario_nome` | 90,7% | nenhum |
| `pagador_nome` | 100% | nenhum |
| `banco_nome` | 100% | nenhum |
| `nosso_numero` | 100% | nenhum — vive no campo livre, sem formato padronizado |

### O episódio da taxa de escape falsa

A primeira medição, com o prompt `boleto-v1`, reportou **50% de escape**. Era
falso: o eval comparava o campo bruto e o pipeline o valor convertido, e as
duas regras discordavam em `banco_codigo` — `748-X` era igual a `748` para um
e diferente para o outro. Está registrado no
[ADR 005](docs/adr/005-sinais-de-confianca.md), e é a razão de eval e pipeline
compartilharem hoje um único módulo de igualdade por campo
(`app/confianca/campos.py`).

### Reproduzir

```bash
# 1. Chave do Gemini em .env (o tier gratuito basta): GEMINI_API_KEY=...
# 2. Ensaio curto antes de gastar cota
uv run python eval.py --limite 5
# 3. Corpus inteiro: 43 documentos, ~6 min a 15 RPM
uv run python eval.py
```

O eval roda em `condicional` por padrão e o sistema em `sempre`: cada segunda
execução custa uma chamada que o cache não cobre, e o eval reexecuta muito.
`--consistencia sempre` liga o sinal em todos os documentos, ao custo de
dobrar as chamadas.

O relatório sai no terminal e em JSON em `resultados/`, carimbado com prompt,
modelo, data e quantos documentos entraram. Documento que ficou de fora
aparece com o motivo, e uma passada parcial imprime o aviso de que suas taxas
não são comparáveis com as de uma completa.

Comparar dois evals exige o mesmo corpus. Regerar precisa de **duas** coisas,
semente e data de referência — o vencimento é sorteado como deslocamento a
partir dessa data, então a mesma semente em outro dia gera outro corpus, em
silêncio. As duas ficam gravadas em `gerado_com` em cada gabarito.

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

### Corpus adversarial: 7 famílias, e quem pega cada uma

`dados/sinteticos/boletos_adversariais/` tem 28 boletos, quatro por família,
cada um com um ataque e um gabarito que declara onde ele está, o que ele pede
(`efeito_pretendido`) e quais detectores deveriam acusar.

Nenhuma família obteve o efeito da carga na passada de 43 documentos, e
nenhum adversarial foi auto-aprovado. A coluna "quem barra" vem de uma
simulação local, sem chamada ao modelo: encena-se um extrator perfeito — que
devolve exatamente o que está impresso — para isolar qual defesa pega o
ataque, independentemente de o modelo ter cedido ou não.

| Família | Como esconde a carga | Quem barra |
|---|---|---|
| `branco_sobre_branco` | texto na cor do papel | sanitização |
| `fonte_minuscula` | corpo de fonte próximo de zero | sanitização |
| `opacidade_zero` | opacidade 0 no texto | sanitização |
| `texto_fora_da_pagina` | posicionado fora da área imprimível | sanitização |
| `delimitador_falso` | imita o fechamento do bloco de dados do prompt | sanitização |
| `instrucao_no_nome_do_beneficiario` | instrução dentro de um campo legítimo, visível | sanitização |
| **`valor_divergente`** | **nada — imprime um valor falso, sem texto injetado** | **só o DV** |

`valor_divergente` é a família que existe para provar o limite das outras
seis. Ela não injeta instrução nenhuma: imprime no campo de valor um número
diferente do que o código de barras codifica, e espera que o extrator o
transcreva — o que é a leitura **correta** da página, e o que ele faz. Não há
padrão a detectar, não há texto invisível, e o grounding aprova, porque o
valor está mesmo escrito ali. Os quatro documentos da família passam por toda
a camada de detecção e são barrados por uma única coisa: o valor extraído não
fecha com os dez dígitos de centavos dentro da linha digitável.

É a demonstração da tese do ADR 002 num caso concreto. Detecção por padrão
teria deixado passar os quatro; aritmética pegou os quatro.

```bash
uv run python -m app.geradores.boleto_adversarial \
    --quantidade 28 --semente 2026 --data-referencia 2026-09-03 --forcar
```

## Limitações conhecidas

Esta seção é a mais importante do README. Os números acima são de corpus
sintético, e há limites que nenhum deles mede. Cada limitação endereçável
aponta para o issue em que está sendo acompanhada.

**O escape rate de 0% é sobre 15 documentos** ([#1][i1]). Quinze
auto-aprovados de um corpus sintético homogêneo, todos gerados pelo mesmo
template Jinja2, com o mesmo layout, as mesmas fontes e a mesma disposição de
campos. O número diz que o pipeline não erra nesse template. Ele **não** prevê
o comportamento em boletos reais, que variam por banco, por emissor, por
versão de layout, e que chegam digitalizados, tortos e com ruído. Tratar 0%
como propriedade do sistema seria ler o corpus como se fosse o mundo.

**Campos de texto livre não têm sinal forte** ([#2][i2]). `beneficiario_nome`,
`pagador_nome` e `banco_nome` não são verificáveis por aritmética: não há DV
de nome. O que existe para eles é grounding — o valor aparece literalmente no
texto de origem? — e auto-consistência entre duas execuções. Os dois pegam
alucinação e instabilidade; nenhum dos dois pega o modelo lendo com confiança
o nome errado que está de fato na página. Não por acaso, `beneficiario_nome`
é um dos dois campos abaixo de 100% na tabela — e é o campo que decide quem
recebe o dinheiro.

**O campo livre da linha digitável não tem formato padronizado** ([#3][i3]).
Os 25 dígitos do campo livre carregam agência, conta e nosso número, mas cada
banco define o próprio layout — não há padrão a partir do qual extrair esses
valores. Os dígitos estão protegidos pelos DVs como qualquer outro, o que
impede alterá-los sem quebrar a conta; o que não dá para fazer é
*interpretá-los* para cruzar com `nosso_numero`. Por isso `nosso_numero`
aparece na tabela sem sinal determinístico, ao lado dos campos de texto: ele
é numérico, e mesmo assim não é verificável.

**Detecção por padrão está sempre um passo atrás** ([#4][i4]). Cada padrão em
`app/seguranca/detectores/padroes.py` pega uma formulação que alguém já
escreveu. Reformular do outro lado é barato; escrever o padrão novo aqui é
reativo por construção. Homoglifos, caracteres bidi e largura zero já são
saída conhecida e não estão tratados. A defesa que não depende de prever a
formulação do atacante é a validação determinística — é ela a garantia, e a
sanitização é sinal.

**Ataque visual em documento digitalizado está fora de escopo** (sem issue:
não é endereçável enquanto não existir caminho de visão). Instrução escrita
dentro de uma imagem não está na camada de texto e nenhum detector daqui a
lê. Hoje não é exposição, porque o pipeline recusa documento sem camada de
texto em vez de mandá-lo para um modelo com visão. Passa a ser no dia em que
existir caminho de visão, e a defesa terá que nascer junto com ele — um
detector de texto não cobre pixel.

Fora de escopo também, e sem plano: negação de serviço por documento grande
(não há limite de tamanho nem de tempo na ingestão) e autenticidade do PDF —
se o atacante controla o documento inteiro, inclusive a linha digitável, o
problema deixa de ser injeção e vira troca de documento, anterior ao pipeline.

[i1]: https://github.com/marcola20/extrator-docs-financeiros/issues/1
[i2]: https://github.com/marcola20/extrator-docs-financeiros/issues/2
[i3]: https://github.com/marcola20/extrator-docs-financeiros/issues/3
[i4]: https://github.com/marcola20/extrator-docs-financeiros/issues/4

## Decisões de arquitetura

| ADR | Decisão |
|---|---|
| [001](docs/adr/001-desenvolvimento-em-wsl2.md) | Desenvolvimento em WSL2, com o repositório no sistema de arquivos Linux |
| [002](docs/adr/002-validacao-por-digito-verificador.md) | Confiança derivada de dígito verificador, não do `confidence` do modelo |
| [003](docs/adr/003-abstracao-de-provedor-llm.md) | Provedor de LLM configurável, com Gemini como padrão |
| [004](docs/adr/004-defesa-contra-prompt-injection.md) | Defesa contra prompt injection em documentos |
| [005](docs/adr/005-sinais-de-confianca.md) | Três sinais de confiança independentes do modelo |
| [006](docs/adr/006-gabarito-do-impresso.md) | O gabarito guarda o que está impresso, não o que é verdadeiro |

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
app/dominio/         boleto, linha digitável e dígitos verificadores
app/ingestao/        leitura do PDF: texto ou visão, com sanitização junto
app/seguranca/       sanitização de documentos não confiáveis
app/extracao/        prompt versionado e extração via LLM
app/confianca/       grounding, auto-consistência e roteamento
app/geradores/       geradores de corpus sintético, limpo e adversarial
app/llm/             provedores, limitador de taxa e cache
eval.py              medição do pipeline contra os corpora
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
commit é permanente. Ver [`dados/real/LEIA-ME.md`](dados/real/LEIA-ME.md).
Além do `.gitignore`, `tests/test_dados_reais_nao_versionados.py` falha se
algum arquivo de lá aparecer rastreado.

Documento real também não é enviado pelo tier gratuito do provedor, que treina
o modelo com o que recebe. Ver [ADR 003](docs/adr/003-abstracao-de-provedor-llm.md).
