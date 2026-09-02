# ADR 003 — Provedor de LLM configurável, com Gemini como padrão

- Status: aceito
- Data: 2026-09-02

## Contexto

A Fase 1.3 precisa chamar um LLM. Até aqui o projeto assumia a API da
Anthropic, e o CLAUDE.md dizia "SDK direto da Anthropic".

**Não há orçamento para API paga.** Este é um projeto de portfólio, sem
receita e sem verba, e o eval não é uma chamada: são 15 boletos por rodada,
várias rodadas por dia enquanto o prompt está sendo ajustado. O tier gratuito
do Gemini cobre isso; a alternativa paga, não.

Então a motivação é restrição de custo. **A portabilidade entre provedores é
consequência de resolver isso, não o objetivo.** Vale ser explícito porque a
diferença muda o desenho: uma abstração feita para portabilidade tenta cobrir
o denominador comum de vários SDKs e cresce sozinha. Uma abstração feita para
caber num orçamento precisa apenas do que o pipeline usa — e o que ele usa é
uma chamada de extração.

As cotas do tier gratuito são a restrição real de engenharia:

| Modelo | Papel | RPM | RPD |
|---|---|---|---|
| `gemini-3.5-flash-lite` | desenvolvimento | 15 | 500 |
| `gemini-3.8-flash` | comparação final | 5 | 20 |

500 requisições por dia dão folga para iterar. 20 dão exatamente uma passada
de eval sobre o lote de 15 boletos, com cinco de sobra. Isso não é um detalhe
de configuração: é o que obriga o cache e o limitador a existirem.

## Decisão

### 1. Um Protocol fino, com o SDK do provedor direto atrás

`app/llm/provedor.py` define `ProvedorLLM`: recebe texto e um schema
Pydantic, devolve instância validada, mais tokens e custo estimado. Nada
além disso. Sem framework de LLM — nem LangChain, nem cadeia, nem agente,
nem roteador. Cada implementação fala com o SDK do seu provedor diretamente.

O princípio do projeto muda de "SDK direto da Anthropic" para "SDK do
provedor direto, atrás de interface fina". O que continua valendo é a parte
que importava: nenhuma camada de terceiros entre o código e a API.

O retorno carrega `UsoDeTokens` e `custo_estimado_usd` porque a métrica de
custo por documento extraído é um resultado do projeto, não um detalhe
operacional. Custo é dinheiro, então é `Decimal`.

### 2. Gemini 3.5 Flash Lite como padrão, Anthropic para comparação

`LLM_PROVEDOR` e `LLM_MODELO` escolhem. O padrão é `gemini` com
`gemini-3.5-flash-lite`. A implementação da Anthropic (`claude-opus-5`) é
mínima e existe para o dia em que houver crédito e valer a comparação — e,
já hoje, para provar que o Protocol serve a mais de um SDK. Ela não é
exercitada contra a API de verdade.

Os identificadores de modelo são fixos, sem os apelidos `-latest`. Um alias
é trocado por baixo a cada versão nova, e dois evals deixariam de ser
comparáveis sem nada no repositório ter mudado.

### 3. A estratégia de dois modelos virou um resultado reportável

O que começou como racionamento — iterar no barato, gastar o caro só no
fim — se mostrou uma coisa que dá para medir e relatar:

- **Flash Lite no desenvolvimento.** 500 RPD é o que permite ajustar prompt
  com o eval rodando junto.
- **Flash na comparação final.** 20 RPD força uma passada por dia, o que na
  prática obriga a fechar a mudança antes de medir.

O mesmo corpus sintético (ADR 002) passa pelos dois modelos e produz duas
linhas comparáveis: acerto por campo e custo estimado por documento. A
pergunta "o modelo mais barato basta para extrair boleto?" tem resposta
medida, com um número de custo do lado. Um projeto de portfólio que responde
isso vale mais do que um que só reporta acurácia do modelo melhor.

### 4. Cache em disco indexado pelo que determina a resposta

`app/llm/cache.py` guarda cada extração sob o hash de
(provedor, modelo, instrução, documento). Reexecutar o eval sem ter mexido
em prompt nem em corpus não gasta cota nenhuma.

A chave inclui o prompt de propósito: prompt novo é chave nova, e a entrada
velha fica órfã sozinha. Não existe cache servindo resposta de prompt antigo.
Invalidar à mão (`--limpar` na CLI) serve para uma coisa só: rodar de novo o
mesmo prompt contra o modelo.

Entrada corrompida, de formato antigo ou que não valida mais no schema conta
como ausência, nunca como erro. O cache é uma economia; se ele virar uma
fonte de falha, ele custa mais do que economiza.

### 5. Limitador com as duas cotas tratadas de formas diferentes

`app/llm/limitador.py` separa por natureza:

- **RPM** é janela deslizante de um minuto. Estourar custa segundos, então o
  limitador espera sozinho e segue.
- **RPD** só zera na virada do dia. Esperar não é opção, então ele levanta
  `CotaDiariaExcedida` e devolve a decisão a quem chamou.

O contador diário é persistido em disco porque o processo reinicia muitas
vezes durante o desenvolvimento, e um contador em memória recomeçaria do zero
achando que tem 500 chamadas quando já gastou 400.

Um 429 é repetido com backoff exponencial, e **cada repetição consome a cota
local**: o provedor conta a requisição recusada, e um contador que não
contasse mentiria justamente na hora em que a cota está apertada.

## Consequências

**Positivas**

- O pipeline cabe no orçamento que existe, que é zero.
- Custo por documento é medido desde a primeira extração, em `Decimal`, e não
  vira uma estimativa feita depois por cima do log.
- Trocar de provedor é variável de ambiente, não refatoração.
- Cache e cota são decorador (`ProvedorComCotaECache`), não estão dentro do
  Protocol: quem extrai não sabe que existem, e um teste pode montar o
  provedor sem nenhum dos dois.
- A camada inteira é testável sem rede. Os testes usam provedor falso,
  relógio falso e cliente dublê dos dois SDKs.

**Negativas / custos aceitos**

- **O tier gratuito usa o conteúdo enviado para melhorar produtos do Google.**
  Está na página de preços: no tier gratuito, "content used to improve our
  products" é *sim*; no pago, *não*. Isso proíbe uma coisa concreta:
  **documento real de `dados/real/` não pode ser enviado pelo tier gratuito.**
  São dados pessoais de terceiros (nome, CPF, CNPJ, endereço, conta) e não são
  nossos para doar a treinamento. O corpus sintético não tem esse problema, e
  é com ele que o eval roda. Testar layout real exige tier pago ou outro
  provedor — e isso ainda não foi resolvido, ver "não decidido" abaixo.
  Ver `dados/real/LEIA-ME.md`.
- **20 RPD no Flash significa uma passada de eval por dia.** Errar o prompt na
  rodada da comparação custa o dia inteiro.
- **As cotas do tier gratuito não são publicadas na documentação.** Os números
  desta tabela vieram do painel do AI Studio e podem mudar sem aviso.
- **`custo_estimado_usd` é preço de tabela, não fatura.** No tier gratuito
  nada é cobrado e o número continua sendo preenchido — ele responde "quanto
  isto custaria pago". O preço do `gemini-3.8-flash` dobra em 2027-01-01
  ($1.50/$7.50 por milhão), e a tabela em `app/llm/gemini.py` precisa ser
  reconferida.
- **O limitador não coordena entre processos.** O arquivo de estado é lido e
  escrito sem trava, então dois processos rodando eval ao mesmo tempo contam a
  menos. Dentro de um processo há `Lock`.
- **O cache não é versionado** (fica em `dados/`, que o git ignora). CI não
  aproveita: lá o eval ou roda com cota de verdade ou não roda.
- **Modelo sem preço cadastrado é erro de configuração**, não aviso. Escolher
  um modelo novo em `LLM_MODELO` falha na hora, com a mensagem dizendo qual
  constante editar. É rígido de propósito: custo estimado silenciosamente zero
  seria pior do que não subir.

**Não verificado ainda**

Nenhuma chamada real foi feita a nenhum dos dois provedores — esta ADR cobre
só a camada de provedor. Em particular, **o structured output do Gemini ainda
não foi exercitado com o schema `Boleto`**. O SDK converte o modelo Pydantic
para o formato de schema dele, que não aceita tudo; `Decimal`, `date` e os
validadores do ADR 002 podem exigir um schema de transporte mais simples, com
a conversão para o domínio acontecendo depois. É a primeira coisa a descobrir
na Fase 1.3.

**Não decidido aqui**

- O prompt de extração em si, e a separação entre instrução e conteúdo contra
  prompt injection. É a Fase 1.2.
- Como testar contra documento real sem entregá-lo ao treinamento de terceiro.
- Onde as métricas de custo e acerto são registradas (Langfuse, Fase 4).
