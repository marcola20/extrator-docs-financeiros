# ADR 009 — Extração do informe: um prompt, e cobertura não é aprovação

- Status: aceito
- Data: 2026-09-08

## Contexto

A Fase 2.2 liga o informe ao modelo. Três decisões precisavam ser tomadas
antes de medir qualquer coisa, e as três mudam o que o relatório significa.

## Decisão 1 — Um prompt para os dois layouts

O ADR 007 já recusou dois schemas, com o argumento de que dois dobrariam
alinhamento, eval e prompt. A mesma razão vale para o prompt, e há uma segunda:
**dois prompts tornariam a comparação entre layouts uma comparação entre
prompts.** Hoje o relatório separa fonte pagadora de instituição financeira e o
que ele mede é a diferença dos documentos; com um prompt por layout, qualquer
diferença passaria a ter duas explicações e nenhuma forma de separá-las.

O prompt único carrega as duas diferenças que o modelo não teria como
adivinhar, e nenhuma delas depende de saber qual documento é qual antes de ler:

- no comprovante, o identificador da linha é composto — a página imprime `3.`
  no cabeçalho do quadro e `1.` na linha, e a chave de casamento é `3.1`;
- na tabela de saldos, a coluna se lê pelo ano do cabeçalho, nunca pela posição.

**O critério para reverter é medido, não opinado** (mesma regra do ADR 008): o
eval reporta acurácia e recall de linha por layout, separados. Se os dois
divergirem de forma que o prompt possa explicar — instrução que serve a um e
atrapalha o outro —, os prompts se separam em `informe-fonte-pagadora-v2` e
`informe-instituicao-v2`, e a medição que motivou a separação vai para uma ADR
nova, com o número.

O que **não** é critério: o layout de fonte pagadora ter cobertura de
verificação menor. Isso é do documento (ADR 007) e nenhum prompt conserta.

## Decisão 2 — Não ter o que conferir bloqueia

É a decisão central desta fase. Ela já estava escrita em dois lugares, cada um
sobre um caso, e aqui vira uma regra só:

- a **Fase 1.2** decidiu que um PDF sem camada de texto vai para revisão. Os
  três detectores rodaram, não acharam nada, e "não achou" não é "está limpo";
- a **Fase 2.1** decidiu que quadro sem total impresso sai como `SEM_TOTAL`, e
  que aprovar por omissão faria todo quadro do comprovante parecer conferido.

A regra: **um sinal que não teve o que conferir conta como não executado, e não
executado bloqueia.** É o `Veredito.bloqueia` que a Fase 1.3 já tinha, aplicado
a dois sinais novos.

Em concreto:

| Situação | Sinal | Resultado |
|---|---|---|
| algum quadro com total impresso, somas fecham | aritmética | executou, aprovou |
| algum total impresso, alguma soma não fecha | aritmética | executou, reprovou |
| os três quadros `SEM_TOTAL` | aritmética | **não executou** |
| par com conta em comum, saldos batem | cruzamento | executou, aprovou |
| par com conta em comum, saldo diverge | cruzamento | executou, reprovou |
| par comparável e sem conta em comum | cruzamento | **não executou** |
| par incomparável (outro titular, outra fonte, anos não consecutivos) | cruzamento | **não executou** |
| documento sem par extraído | cruzamento | **não executou** |

A terceira linha do cruzamento merece destaque porque é uma armadilha real do
código: `ResultadoCruzamento.valido` devolve `True` num par sem conta nenhuma —
não há divergência, logo é válido. A Fase 2.1 já tinha registrado isso ao criar
`tem_cobertura` ao lado de `valido`; esta ADR é onde a distinção passa a
mandar em alguma coisa.

### A consequência, que é grande

**Nenhum comprovante de fonte pagadora é auto-aprovável.** Ele não imprime
total, então não há soma que confira; não tem saldo, então não há o que cruzar
entre anos. Um comprovante lido com 100% de acurácia vai para revisão.

Isso não é defeito da política. O ADR 007 já dizia, sobre esse layout: "é
motivo para a cobertura ser explícita por campo e a política de roteamento
mandar à revisão o que o layout não cobre". Metade do corpus estar nessa
situação é informação sobre o documento, não sobre o extrator.

### O que o relatório precisa imprimir por causa disso

Três contagens, e elas **não podem virar uma**:

- `auto_aprovados_com_cobertura` — a aritmética e o cruzamento rodaram e
  aprovaram. É o número que significa alguma coisa;
- `auto_aprovados_sem_cobertura` — zero por construção da política. Impresso
  para a invariante ser visível em vez de prometida: se um dia sair diferente
  de zero, a política regrediu e o relatório grita;
- `bloqueados_so_por_falta_de_cobertura` — nada reprovou, e nada foi conferido.
  É o tamanho do que a política está segurando.

Somar a primeira com a segunda faria a taxa de auto-aprovação descrever ao
mesmo tempo documento verificado e documento sobre o qual ninguém afirmou nada.

## Decisão 3 — A aritmética é calculada sobre o transporte, não sobre o domínio

`Informe.model_validate` recusa a instância inteira quando um quadro diverge, e
recusa também quando duas linhas repetem o identificador. Os dois casos são
ataques do corpus — `total_adulterado` e `quadro_duplicado` —, e é exatamente
neles que a aritmética tem algo a dizer.

Se a conferência de quadro só existisse dentro do `Quadro` validado, ela
ficaria **muda nos dois ataques que ela é a única a pegar**. Então ela é
calculada direto do que o modelo escreveu, com a mesma função de soma que o
domínio usa (`app.dominio.informe.confere_soma`) — uma implementação, dois
chamadores, pela razão do ADR 005.

### O risco que isso cria, e o que o cobre

Se o modelo **somar as linhas** em vez de transcrever o total impresso, a
conferência passa a comparar a soma consigo mesma e concorda sempre. O sinal
que pega linha injetada viraria tautologia.

Duas coisas cobrem isso, e nenhuma delas é confiança no modelo:

1. o prompt gasta um parágrafo proibindo (`Nunca some as linhas para preencher
   este campo`), com a razão escrita;
2. **o grounding confere `total_impresso` como qualquer outro valor.** Um total
   calculado é um número que não está impresso na página, e cai como ausente.

A segunda é a que vale, porque não depende de o modelo obedecer.

## O que a decisão não resolve

**O buraco de cobertura declarado continua declarado.** `linha_injetada` num
quadro sem total impresso não é pega por nada: não há soma que deixe de fechar
e a página não tem defeito visual. Está no corpus com `sinal_esperado: nenhum`,
e o relatório o imprime como buraco declarado — nunca como ataque barrado. Para
isso o agrupamento das famílias de ataque é por **família e sinal esperado**, e
não por família: `linha_injetada` aparece nos dois layouts, e agrupando só pelo
nome o `nenhum` do comprovante desapareceria dentro do `aritmetica` do bancário,
com o relatório afirmando cobertura que não existe.

**A auto-consistência não é disparada por falta de cobertura.** No modo
condicional, a segunda execução acontece quando algum sinal **reprova** — não
quando um sinal não teve o que conferir. Metade do corpus é comprovante, que
nunca terá cobertura e nunca será auto-aprovado; gastar uma segunda chamada em
cada um deles dobraria a cota sem mudar decisão nenhuma. O custo assumido: nos
comprovantes, o único sinal que falaria sobre os números não roda, e eles vão
para revisão sem nada dito sobre a estabilidade da leitura.

**O corpus tem 56 documentos, não 40.** O corpus adversarial é de 16 **pares**
— 32 PDFs, dos quais 16 carregam a carga. Extrair só o documento atacado
economizaria cota e mataria o cruzamento entre anos, que precisa dos dois. Os
56 cabem numa passada do tier gratuito.

## A medição, e o que ela desmentiu

Passada completa de 2026-09-08, 56 documentos, `gemini-3.5-flash-lite`,
consistência condicional. Fonte:
[`resultados/eval-20260908-224848-informe-v1+44161a56.json`](../../resultados/eval-20260908-224848-informe-v1+44161a56.json).

### O prompt único se sustenta

| | fonte_pagadora | instituicao_financeira |
|---|---|---|
| Documentos | 28 | 28 |
| Acurácia média (escalares) | 100,0% | 99,5% |
| Recall de linha | 99,1% | 98,3% |
| Precisão de linha | 99,6% | 100,0% |

Os dois layouts ficam dentro de um ponto percentual em todas as medidas. Não há
o que um prompt por layout fosse consertar, e o critério de reversão desta ADR
não foi atingido. `informe-v1` fica.

O que **não** é comparável entre os dois é a auto-aprovação — 0 de 28 contra 18
de 28 —, e essa diferença é do documento, não do prompt: o comprovante não tem
total nem saldo.

### O `quadro_duplicado` derrotou a aritmética uma vez em duas

Em `adversarial-010` o modelo **deduplicou o quadro em silêncio**: a página
imprime oito linhas, quatro delas repetidas, e ele devolveu quatro. A soma das
quatro bate com o total impresso — que o ataque não tocou —, a aritmética
confere, e o documento foi auto-aprovado.

Não é falha de implementação da aritmética: é um limite estrutural dela.
**A conferência de quadro opera sobre o que o modelo devolveu, não sobre o que
a página imprime.** Um modelo que corrige o documento ao ler apaga a evidência
antes de o sinal chegar nela, e nenhum ajuste do sinal recupera isso — quem
teria de acusar é um detector sobre o texto ingerido, comparando o que a página
repete com o que a extração devolveu. Fica registrado como buraco conhecido, não
como pendência esquecida, e está na
[issue #5](https://github.com/marcola20/extrator-docs-financeiros/issues/5) —
**sinais que operam sobre a saída extraída não detectam omissão coerente**, que
é mais geral do que este ataque: vale para linha, quadro ou página inteira que
o modelo deixe de devolver de forma consistente.

O outro `quadro_duplicado` do corpus foi barrado normalmente, o que diz que a
derrota depende de o modelo deduplicar — comportamento que varia com o
documento, não com a defesa.

### A métrica de linha estava cega para esse mesmo caso

A primeira passada
([`eval-20260908-223611`](../../resultados/eval-20260908-223611-informe-v1+44161a56.json))
reportou **recall de 100%** sobre `adversarial-010`, o documento em que o modelo
deixou de devolver quatro linhas impressas. O alinhamento casava por chave
distinta, então as ocorrências repetidas do gabarito nunca entravam em
`faltantes`.

Corrigido: o casamento consome **uma ocorrência esperada por linha devolvida**.
O recall do corpus caiu de 99,8% para 98,7% e o escape rate subiu de 5,6% para
11,1% — os dois números da primeira passada estavam otimistas pela mesma causa,
e ela era da medição, não do extrator.

O relatório antigo fica no repositório, e esta seção é o que impede alguém de
lê-lo como comparável.

### O escape que sobra é o de sempre

`adversarial-009` foi auto-aprovado com `beneficiario_nome` = "Vitor Hugo
Fernandes" onde a página imprime "Sr. Vitor Hugo Fernandes". O grounding
aprovou, corretamente: o nome sem o tratamento **é** substring do que está
impresso. Nome não tem verificação — é a issue #2, a mesma que produziu os
únicos escapes da Fase 1, agora reproduzida no informe.

### Números do corpus

| Métrica | Valor | Base |
|---|---|---|
| **Escape rate** | **11,1%** | sobre 18 auto-aprovados, de 56 processados |
| Acurácia média (escalares) | 99,7% | 7 campos sobre 56 documentos |
| Recall / precisão de linha | 98,7% / 99,8% | 468 casadas de 474 esperadas |
| Recall / precisão de saldo | 100% / 100% | 92 saldos |
| Auto-aprovados com cobertura | 18 | de 56 |
| Auto-aprovados sem cobertura | 0 | invariante da política |
| Barrados só por falta de cobertura | 24 | 22 comprovantes, 2 bancários |
| Ataques bem-sucedidos | 1 | de 16 documentos com carga |
| Custo por documento | US$ 0,003070 | preço de tabela |
| Latência p50 / p95 | 2,3s / 25,6s | segunda passada, com cache |

A latência desta passada **não vale como medida do pipeline**: a maior parte das
extrações veio do cache, porque ela reexecutou o corpus depois da correção da
métrica. A da primeira passada (p50 7,3s) é a que descreve chamada de verdade.

## Consequências

**Positivas**

- A taxa de auto-aprovação passa a ser legível: o que ela conta é documento
  verificado, e o que não foi verificado aparece numa contagem própria.
- Os dois ataques que só a aritmética pega continuam pegos mesmo quando o
  documento não instancia no domínio.
- Comparar os dois layouts é comparar documentos, e não prompts.
- Um total calculado pelo modelo cai no grounding, sem depender de obediência.

**Negativas / custos aceitos**

- Metade do corpus vai para revisão por falta de cobertura, e a taxa de
  auto-aprovação do conjunto fica baixa por razão estrutural. Comparar essa
  taxa com a do boleto não diz nada.
- A auto-consistência tem ponto cego justamente no layout mais pobre em sinal.
- **A aritmética de quadro não cobre o modelo que deduplica.** Ela olha o que
  o modelo devolveu, e um modelo que corrige o documento ao ler apaga a
  evidência antes de ela chegar ao sinal. Medido: 1 de 2 `quadro_duplicado`.
  Issue #5, como limitação estrutural de todo sinal que roda sobre a saída
  extraída — não como bug desta implementação.
- O escape que sobra é de nome, e nome não tem verificação (issue #2). Nenhum
  dos seis sinais desta fase o alcança: a issue #2 se reproduz no informe.
