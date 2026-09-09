# ADR 011 — A interface de revisão, e o estado que ela não pode apagar

- Status: aceito
- Data: 2026-09-09

## Contexto

A tela da Fase 4.2 é a única parte do projeto que alguém vê sem clonar o
repositório. O que ela mostra bem é o que o projeto comunica.

O risco não é técnico. É que uma interface competente e comum — documento à
esquerda, campos à direita, botão de aprovar — jogue fora exatamente o que as
três fases anteriores construíram, e o faça sem que ninguém note. A informação
que este pipeline produz e um extrator comum não produz é **por que** um
documento não foi aprovado sozinho, e com que confiança.

## Decisão 1 — Os quatro estados, e só um deles ganha marca de certo

O enunciado da fase pedia três estados: conferido, divergente e sem cobertura.
São os da conferência de quadro da Fase 2 (`Cobertura`). A tabela de sinais da
Fase 4.1 tem **quatro**, porque `DISPENSADO` — o sinal que o operador desligou
por configuração — não é nenhum dos outros três: ele não rodou, como
`SEM_COBERTURA`, mas não bloqueia, porque houve escolha e ela está registrada.

Desenhar a interface para três faria o quarto cair no visual de "conferido",
que é precisamente o erro que a fase existe para não cometer. A tela mostra os
quatro.

Duas regras de desenho carregam a distinção, e as duas são sobre percepção, não
sobre dado:

**Só `conferido` recebe marca de certo.** Os outros três recebem glifos que não
podem ser lidos como aprovação: `!` para divergente, `—` para quem não teve o
que conferir, `⦸` para quem foi desligado. Um ✓ cinza continua sendo um ✓ num
relance, e relance é como uma fila é lida.

**`sem_cobertura` tem borda tracejada.** Preenchimento contínuo é a linguagem
visual de "resolvido". O tracejado diz "falta coisa aqui" sem depender de cor —
o que resolve, de passagem, o caso de quem não distingue vermelho de verde e
para quem um semáforo não comunica nada.

O rótulo também não é uma palavra só. "Sem cobertura" não significa nada para
quem abre a tela pela primeira vez; "não havia o que conferir — não é aprovação"
significa. O glifo é `aria-hidden`, e a informação de verdade é texto.

## Decisão 2 — O diagnóstico vem antes do documento

A ordem da página é a hierarquia da informação, e aqui ela inverte o esperado:
**por que este documento está na fila** vem antes do PDF.

E dentro dela, dois grupos separados:

- **um sinal reprovou** — há erro concreto, e a mensagem que o pipeline escreveu
  aponta onde: "valor 99999.99 não confere com a linha digitável (R$ 179.66)".
  As mensagens vão inteiras para a tela, sem reescrita: elas são o produto das
  fases anteriores, e resumi-las perderia a precisão que custou a existir;
- **um sinal não teve o que conferir** — não há erro apontado, e o documento
  precisa ser lido do zero.

Juntar os dois numa lista de "problemas" faria o segundo grupo parecer menos
urgente do que é. Ele é o mais fácil de despachar com um "parece bom",
justamente porque nada está gritando — e no corpus de informes ele é a maioria
da fila (24 de 56 na passada de 2026-09-08).

O mesmo vale para o filtro: `?sinal=aritmetica&estado=divergente` e
`?sinal=aritmetica&estado=sem_cobertura` são duas filas de trabalho, e a
interface permite pedir cada uma.

## Decisão 3 — O front não decide nada

`bloqueia` vem calculado da API. Os estados vêm do banco como o pipeline os
deixou. Nenhum estado é derivado no navegador.

A tentação de derivar é real e barata: `bloqueia = estado !== "conferido"` é uma
linha, e estaria errada — `dispensado` não bloqueia. Mais importante que o caso
específico: seria uma **segunda definição da política**, na camada mais distante
dela, e é o erro que o ADR 005 registra sobre a definição de igualdade de campo.
Enquanto a regra morar em dois lugares, ela diverge.

## Decisão 4 — Proxy em route handler, não CORS nem rewrite

O navegador nunca fala com a API diretamente: tudo passa por `/api/*` no próprio
Next. Isso evita CORS sem tocar no backend da 4.1 — a restrição da fase era
consumir a API como ela está — e faz o `<iframe>` do PDF ser mesma origem, o que
elimina uma conversa inteira sobre cabeçalhos e credenciais.

Começou como `rewrites()` no `next.config.ts`, e **não funcionava na imagem**. O
Next resolve os rewrites durante o `next build` e grava o destino já resolvido no
manifesto de rotas; com `API_INTERNA` ausente na hora de construir, ficou
congelado `127.0.0.1:8000`, que dentro do contêiner do front é ele mesmo. O
sintoma foi um 500 só no PDF: as páginas leem a variável em tempo de requisição,
e o rewrite não.

Um route handler lê o ambiente a cada chamada, e a mesma imagem serve para o
`docker compose` e para o desenvolvimento local.

## Decisão 5 — O pareamento de informes, que a 4.1 deixou pendente

O eval de informe processa **pares**: o cruzamento entre anos precisa dos dois
documentos. Um caso de correção humana sozinho entraria já sem cobertura,
medindo a ausência do par e não a leitura — e a 4.1 declarou isso como pendente.
Deixar de novo seria adiar o mesmo item duas fases seguidas.

O pareamento usa o **mesmo critério** que `app.dominio.cruzamento` aplica para
decidir se dois informes são comparáveis: mesmo titular, mesma fonte pagadora,
anos consecutivos. Não é regra nova — é a mesma, aplicada antes, para saber
quais documentos vale juntar. A identidade é comparada por dígitos, porque o
transporte guarda o que estava impresso e os dois documentos podem formatar o
mesmo CPF de formas diferentes (ADR 006). Nunca por nome (ADR 007).

Cada documento entra em no máximo um par. Com 2023, 2024 e 2025 do mesmo titular
há dois pares possíveis que dividem o de 2024, e formar os dois mediria o mesmo
documento duas vezes — o relatório do eval é indexado por documento. Sobra o mais
novo, e o exportador diz quantos ficaram assim.

## O que a decisão não resolve

**Não há autenticação.** A API não sabe quem é o revisor além do que ele digita
em `revisor`. É aceitável enquanto a tela roda em `localhost` como demo, e deixa
de ser no momento em que ela for exposta — a decisão vai junto com a exposição.

**Não há realce sobre o PDF.** Os achados carregam página e coordenadas, e a
tela as mostra em texto, com um clique que leva o visor à página. Desenhar o
retângulo por cima do documento exigiria renderizar o PDF com pdf.js e converter
coordenadas de PDF para pixels de tela — dependência pesada para uma fase cujo
pedido era sobriedade. Fica como o melhoramento mais óbvio.

**A tela não pagina.** A fila devolve até 200 itens por página e a interface
mostra o primeiro lote. Com o volume de uma demo isso não aparece; com fila de
verdade, aparece.

**Node não roda no WSL desta máquina.** O `npm` do `PATH` é o do Windows, em
`/mnt/c`, o que a ADR 001 proíbe. Build, lint e tipos rodam em contêiner
`node:22-alpine`. O CI não constrói o front — ele roda a suíte Python —, e
adicionar esse job é trabalho pequeno e ainda não feito.

**Nada em `web/` tem teste automatizado**, e isso cobrou preço logo depois desta
ADR ser escrita: três defeitos seguidos no visor de PDF passaram pela suíte e
por verificação manual com `curl`, incluindo um em que o próprio proxy descartava
um cabeçalho no caminho. Está na
[issue #6](https://github.com/marcola20/extrator-docs-financeiros/issues/6), com
os três alvos possíveis — o route handler isolado, a pilha pelo compose, e o
navegador — e o custo de cada um.

## Consequências

**Positivas**

- A distinção que o projeto passou três fases protegendo chega à tela, e chega
  de forma que resiste a um relance e a daltonismo.
- As mensagens do pipeline — que são o produto dessas fases — aparecem inteiras
  para quem revisa.
- A realimentação de informes fechou: revisar um par exporta um par, e ele entra
  no eval com procedência.
- Nenhuma lógica de decisão foi duplicada no navegador.

**Negativas / custos aceitos**

- Sem autenticação, sem realce no PDF e sem paginação na tela.
- O front acrescenta um segundo ecossistema de ferramentas ao projeto, e ele não
  está coberto pelo CI.
