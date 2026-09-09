# Extrator de Documentos Financeiros

![Tela de revisão de um boleto cujo valor impresso diverge do codificado na linha digitável](docs/valor-divergente1.gif)

A extração está **correta**: o modelo leu `91,01`, que é o que a página imprime.
Quem mente é o documento — a linha digitável codifica `R$ 9.100,99`. Sanitização
e grounding aprovam, e com razão: não há texto injetado, e o valor está mesmo
impresso ali. Só o dígito verificador reprova.

Pipeline de extração estruturada de documentos financeiros brasileiros, com
validação determinística e roteamento para revisão humana. O provedor de LLM
é configurável — Gemini por padrão, SDK direto, sem framework
([ADR 003](docs/adr/003-abstracao-de-provedor-llm.md)).

A tese do projeto está no [ADR 002](docs/adr/002-validacao-por-digito-verificador.md):
**a confiança não vem do modelo.** Um boleto carrega quatro dígitos
verificadores e três campos redundantes com o código de barras. Isso permite
perguntar se a extração fecha aritmeticamente, em vez de perguntar ao modelo
o quanto ele acha que acertou.

## Demonstração no ar

<!-- O Render sufixou o nome do serviço: `extrator-web` já estava em uso. Esta
     é a URL que o painel mostra, e é ela que a variável API_INTERNA do front
     tem do lado da API (extrator-api-6b48). -->

**[Abrir a demonstração](https://extrator-web-47i7.onrender.com)** — API real,
Postgres real, corpus sintético. Cinco casos, apresentados pela situação que cada
um mostra, e o clique abre o diagnóstico ao lado do PDF.

> **A primeira visita demora.** Os dois serviços rodam no plano gratuito do
> Render, que os desliga depois de alguns minutos sem acesso e os liga de novo na
> primeira requisição. Acordar leva de **30 a 60 segundos**, e a tela diz isso e
> tenta de novo sozinha — não é erro. Depois disso a navegação é imediata.

A instância pública é **somente leitura**: dá para abrir qualquer documento, ver
o diagnóstico e navegar pela fila, mas gravar correção está desligado — e quem
recusa é a API (403), não a tela. Nenhuma chamada ao modelo acontece lá: o banco
é semeado na partida com o gabarito que está ao lado de cada PDF do corpus. Ver
[ADR 012](docs/adr/012-demonstracao-publica-somente-leitura.md).

## Estado

Fases 1, 2 e 4 concluídas e medidas contra a API. A Fase 3 está
[pendente](docs/limitacoes.md#a-fase-3-não-foi-feita).

| Fase | Escopo | Estado |
|---|---|---|
| 1 | Boleto: pipeline vertical, quatro sinais, eval contra a API | concluída |
| 2 | Informe: multi-registro, seis sinais, cruzamento entre anos | concluída |
| 3 | Extrato de investimento: multi-página, tabela com quebra | **pendente** |
| 4 | Persistência, API de revisão, interface, observabilidade, CI | concluída |

## Resultados

Duas passadas completas contra a API do Gemini, com corpus sintético
reprodutível. Os relatórios ficam em [`resultados/`](resultados/).

| | Boleto | Informe |
|---|---|---|
| **Escape rate** | **0,0%** sobre 15 auto-aprovados | **11,1%** sobre 18 auto-aprovados |
| Ataques bem-sucedidos | 0 de 28 adversariais | 1 de 16 com carga |
| Acurácia média | 99,5% | 99,7% |
| Documentos | 43 | 56 |

A métrica principal é a taxa de escape: **dos documentos que o pipeline
auto-aprovou, quantos divergem do gabarito.** Ela vem sempre com o denominador,
porque 0% sobre 15 documentos afirma muito menos que a mesma taxa sobre centenas.

[Resultados completos](docs/resultados.md) — acurácia por campo, desempenho por
layout, resistência por família de ataque, e os dois episódios em que uma
métrica mediu a coisa errada.

## O argumento, num documento

O GIF acima é a família `valor_divergente`, e ela é a tese num caso só. A página
não tem defeito que um detector possa ver — nenhum texto escondido, nenhuma
instrução injetada — e o extrator **lê certo**, porque transcrever o que está
impresso é o comportamento correto. O que barra é aritmética: o valor não fecha
com os dez dígitos de centavos dentro da linha digitável, protegidos por quatro
dígitos verificadores. Detecção por padrão teria deixado passar os quatro
documentos da família; o cruzamento pegou os quatro.
Ver o [modelo de ameaças](docs/modelo-de-ameacas.md).

## O que os números não dizem

Três limitações carregam o resto; a lista inteira está em
[limitações conhecidas](docs/limitacoes.md).

- **O corpus é sintético e de template único**, então o escape rate descreve
  esse template, não o mundo ([#1][i1]).
- **Campos de texto livre não têm sinal forte**, e é de lá que vêm os únicos
  escapes das duas fases — inclusive o do informe, apesar dos seis sinais
  ([#2][i2]).
- **Sinais que operam sobre a saída extraída não detectam omissão coerente**: um
  modelo que deduplica um quadro em silêncio passa pela aritmética, porque ela
  soma o que ele devolveu, não o que a página imprime ([#5][i5]).

## Como foi construído

O histórico de commits mostra assistência de agente de codificação, então vale
ser explícito sobre a divisão. Do autor: a escolha do domínio e do escopo, a
validação contra a realidade do setor financeiro, o recorte das fases, a revisão
da saída e as decisões de arquitetura — todas registradas em
[`docs/adr/`](docs/adr/), com o que cada uma custou. Do agente: implementação a
partir de especificação escrita.

O mecanismo é uma instrução do [`CLAUDE.md`](CLAUDE.md): especificação que parece
errada se aponta **antes** de implementar, em vez de preencher a lacuna em
silêncio. É decisão de projeto, e nos três casos abaixo o que estava errado era a
especificação, não o código:

- a spec da Fase 2 descrevia os quadros do informe como "lista de linhas mais um
  total" — layout de extrato bancário, não o modelo da Receita. O Anexo I da IN
  RFB desmente isso em três pontos, e o schema mudou antes da implementação
  ([ADR 007](docs/adr/007-estrutura-do-informe-de-rendimentos.md));
- o primeiro eval reportou 50% de escape. O número era da medição: eval e
  pipeline comparavam campos por definições de igualdade diferentes, e hoje
  compartilham um módulo só
  ([ADR 005](docs/adr/005-sinais-de-confianca.md));
- a métrica de linha casava por chave distinta e ficava cega justamente no
  ataque que existia para medir. Corrigida para casar por ocorrência, o recall
  caiu de 99,8% para 98,7%
  ([ADR 009](docs/adr/009-extracao-do-informe-e-cobertura-de-verificacao.md)).

## Como rodar

```bash
uv sync
cp .env.example .env      # GEMINI_API_KEY=...  (o tier gratuito basta)
uv run pytest -m "not slow"
```

O eval é o que fala com a API, e só roda quando invocado à mão:

```bash
uv run python eval.py --limite 5   # ensaio curto antes de gastar cota
uv run python eval.py              # 43 boletos, ~6 min a 15 RPM
uv run python eval.py --informes   # 28 pares = 56 documentos, ~12 min
```

A fila de revisão precisa de banco, e é opcional — pipeline e eval rodam sem ela:

```bash
docker compose --profile revisao up -d
uv run alembic upgrade head
PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --limpar
# http://localhost:3001 — a entrada; a fila fica em /fila
```

O último comando popula a fila sem gastar cota: o provedor dele lê o gabarito ao
lado de cada PDF do corpus, em vez de chamar o modelo. Localmente a gravação de
correções fica **ligada** — o modo somente-leitura é da instância pública.
Requisitos, comandos de qualidade e estrutura em
[desenvolvimento](docs/desenvolvimento.md); como a demonstração é publicada, em
[revisão humana](docs/revisao.md#a-demonstração-pública).

## Documentação

| | |
|---|---|
| [Resultados](docs/resultados.md) | as duas medições, por campo e por layout, e como reproduzi-las |
| [Modelo de ameaças](docs/modelo-de-ameacas.md) | as quatro camadas de defesa e os dois corpora adversariais |
| [Revisão humana](docs/revisao.md) | a fila, a API, a tela, e a realimentação do eval |
| [Limitações conhecidas](docs/limitacoes.md) | o que os números não dizem, com as issues |
| [Desenvolvimento](docs/desenvolvimento.md) | requisitos, setup, qualidade, estrutura, dados |
| [Decisões de arquitetura](docs/adr/) | as doze ADRs, com o que cada decisão custou |

[i1]: https://github.com/marcola20/extrator-docs-financeiros/issues/1
[i2]: https://github.com/marcola20/extrator-docs-financeiros/issues/2
[i5]: https://github.com/marcola20/extrator-docs-financeiros/issues/5
