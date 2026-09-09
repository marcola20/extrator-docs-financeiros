# ADR 010 — Persistência opcional, e o que pode ou não ser versionado

- Status: aceito
- Data: 2026-09-09

## Contexto

Até a Fase 4 o pipeline não persistia nada. O Postgres estava no
docker-compose desde a Fase 1 e nunca tinha sido usado; a fila de revisão não
existia, e uma correção humana não sobrevivia ao reinício do processo.

Três decisões precisavam ser tomadas antes de escrever tabela nenhuma.

## Decisão 1 — Persistência é opcional, e desligada por padrão

O eval processa 56 documentos e é o instrumento de medição do projeto. Se ele
passasse a exigir um Postgres de pé, "rodar o eval" viraria uma tarefa de
infraestrutura — e a tarefa apareceria justamente quando alguém quisesse
conferir um número, que é o pior momento para ela aparecer.

Então `PERSISTENCIA_ATIVA` é falso por padrão. O pipeline não importa
SQLAlchemy, não conhece `app/persistencia`, e não mudou nesta fase; um teste
confere isso lendo o texto dos dois arquivos de pipeline, porque a tentação de
gravar de dentro do pipeline aparece no primeiro endpoint.

Quem persiste é a API, e a tradução mora em `app/persistencia/gravacao.py`, de
mão única: lê o resultado em memória e escreve linhas.

Com a persistência desligada, as rotas de revisão devolvem **503 com o nome da
variável a ligar**. Um 500 genérico faria parecer defeito da API o que é
ambiente sem banco de propósito.

## Decisão 2 — Sinal tem quatro estados no banco, não um booleano

É o cuidado que as três fases anteriores defenderam e que uma tabela mal
desenhada apagaria em silêncio.

| Estado | O que aconteceu | Bloqueia |
|---|---|---|
| `CONFERIDO` | o sinal rodou e aprovou | não |
| `DIVERGENTE` | o sinal rodou e reprovou | sim |
| `SEM_COBERTURA` | não havia o que conferir | **sim** |
| `DISPENSADO` | o operador desligou o sinal | não |

Gravar `aprovou: bool` confundiria `SEM_COBERTURA` com aprovação ou com
reprovação — as duas leituras erradas, em direções opostas. Gravar `null`
perderia a distinção para `DISPENSADO`, que também não rodou, mas foi escolha
registrada do operador e não bloqueia.

A distinção não é acadêmica: ela chega à tela. Um revisor precisa saber se está
olhando um documento que **falhou** numa conferência ou um que **ninguém
conseguiu conferir** — são trabalhos diferentes, e no corpus de informes o
segundo grupo é a maioria da fila (24 de 56 na passada de 2026-09-08).

Duas consequências que precisaram de código:

- existem agora **duas** definições de "bloqueia" — `Veredito.bloqueia` na
  política e `EstadoDoSinal.bloqueia` no banco. Um teste amarra as duas, pela
  mesma razão do ADR 005: enquanto a regra morar em dois lugares, ela diverge, e
  a divergência apareceria como documento na fila com o sinal marcado como
  aprovado;
- `escopo` é **nulo por padrão**. Sanitização, domínio, aritmética e cruzamento
  falam do documento inteiro; só o grounding fala de um lugar, e no informe esse
  lugar é `rendimentos_isentos[LCI].valor` — um endereço, não um nome de campo.
  Uma coluna `campo` obrigatória obrigaria a inventar valor para quatro dos seis
  sinais.

## Decisão 3 — O payload bruto vai para JSONB, e isso não contradiz a trava dos relatórios

Esta é a decisão que parece contraditória sem a justificativa, e é por isso que
ela está escrita aqui.

**O que foi decidido antes.** Na Fase 2.2, `resultados/` saiu do `.gitignore`:
os relatórios de eval passaram a ser versionados, sob a condição de que **não
carregam valor extraído nenhum** — só taxas, contagens e booleanos.
`tests/test_relatorios_versionados.py` é a trava que mantém a condição
verdadeira, e ela existe justamente para impedir alguém de acrescentar o que o
modelo escreveu "para depurar um escape".

**O que foi decidido agora.** A tabela `extracao` guarda o payload bruto do
modelo em JSONB — exatamente o que o relatório não pode guardar.

As duas decisões são a mesma regra aplicada a destinos diferentes, e o que as
separa é **para onde o dado vai**:

| | `resultados/*.json` | tabela `extracao` |
|---|---|---|
| Destino | repositório público, para sempre | banco local, do operador |
| Some quando | nunca — commit é para sempre | o volume é apagado |
| Quem lê | qualquer pessoa na internet | quem tem acesso ao banco |
| Conteúdo | taxas, contagens, booleanos | o que o modelo escreveu |

Um relatório com valor extraído seria dado de documento **publicado**. O mesmo
dado no banco local é o dado que a aplicação processa — não guardá-lo lá seria
não ter aplicação.

E ele precisa estar lá por duas razões concretas:

- **reprocessar sem gastar cota.** Rodar um sinal novo sobre extrações passadas
  não custa chamada nenhuma se o bruto está guardado. Sem ele, mudar a política
  obrigaria a reextrair o corpus inteiro;
- **auditoria.** A pergunta "o modelo escreveu `1.847,30` ou `1847.30`?" só tem
  resposta no bruto. É a mesma razão de o schema de transporte ser todo texto
  (ADR 006).

**A regra que sobrevive às duas decisões:** o que é versionado não carrega
conteúdo de documento; o que carrega conteúdo de documento não é versionado.

## Decisão 4 — Realimentação mora fora do git

Mesma regra, terceira aplicação, e a que quase virou um erro.

A correção humana é o melhor gabarito que existe — foi conferida por gente — e
a intenção da Fase 4 é realimentar a medição com ela. O caminho óbvio seria
acrescentá-la ao corpus de eval, em `dados/sinteticos/`. E o corpus de eval é
versionado, num repositório público.

Só que a correção humana é sobre um documento **real**. `dados/real/LEIA-ME.md`
já registra por que isso não pode acontecer, e registra também qual é o campo
mais sensível — a linha digitável, que não identifica o boleto: ela **é** a
ordem de pagamento, e quem tem os 47 dígitos quita o documento.

Então o corpus de realimentação:

- mora em `dados/realimentacao/`, coberto pelo `.gitignore` que já vale para
  `dados/*`;
- guarda **caminho e hash** do PDF, nunca uma cópia;
- devolve lista vazia quando o diretório não existe — o caso de um clone novo e
  do CI.

### A flag é desligada por padrão, e a razão é de medição, não de segurança

Misturar casos reais ao corpus sintético sem distinção contaminaria toda
comparação com os baselines: a acurácia mudaria por o corpus ter crescido, não
por o extrator ter melhorado, e separar os dois efeitos depois seria impossível.
É exatamente o erro que o ADR 006 registra sobre a passada em que corpus e
gabarito mudaram juntos.

`--com-realimentacao` liga; quando ligada, a procedência entra em `corpus`, e
com isso a retomada **já recusa** somar uma passada que os incluiu a uma que
não incluiu — sem código novo, porque `corpus` inteiro entra na conferência de
compatibilidade.

Só revisão **fechada** vira caso. Um gabarito pela metade entraria na medição
afirmando campos que ninguém conferiu.

## Decisão 5 — O CI trava a promessa de não chamar o provedor

"Nenhuma chamada de rede ao provedor" é fácil de escrever num YAML e difícil de
manter: basta um teste novo esquecer de injetar um dublê. O sintoma seria um job
parado em timeout de rede, ou cota consumida sem ninguém ter pedido.

`LLM_SEM_REDE=1` faz a fábrica recusar montar qualquer provedor de verdade, com
a mensagem endereçada a quem escreveu o teste que esbarrou nela.

Dois cuidados no job completo, que não são óbvios:

- `tesseract-ocr-por` não é opcional. O detector de divergência texto/imagem lê
  documento em português e **cai para inglês** quando o pacote de idioma falta,
  degradando o OCR e acusando divergência em documento limpo — falso positivo de
  infraestrutura;
- os testes de OCR **pulam** quando tesseract não existe, e no CI isso seria
  pior que falhar: a suíte ficaria verde sem ter rodado o que o job existe para
  rodar. O job confere que `por` está na lista antes de começar.

## A verificação contra Postgres, e o que ela achou

Esta seção começou dizendo que nada tinha rodado contra Postgres, porque o
Docker não estava disponível. Rodou depois, e vale registrar o que a execução
mudou — foi ela que justificou a migração `a4ac89d142f4`.

**O que se confirmou.** `payload` é JSONB de verdade e as colunas de data são
`timestamptz`; as duas variantes que o SQLite não podia provar. O ciclo
`upgrade` → `downgrade base` → `upgrade head` funciona, e o schema resultante
bate com os modelos tabela a tabela e coluna a coluna. Um ensaio de ponta a
ponta gravou dois documentos, listou a fila, abriu o diagnóstico, baixou o PDF,
submeteu uma correção e exportou o caso de realimentação.

**O que se descobriu.** As três colunas de enum tinham sido criadas como VARCHAR
**sem restrição nenhuma**. A causa é um padrão do SQLAlchemy 2:
`Enum(native_enum=False)` só emite o CHECK com `create_constraint=True`, e o
padrão é `False`. A ADR e o commit afirmavam "VARCHAR com CHECK"; o banco tinha
só o VARCHAR.

Por que passou despercebido: o teste que compara migração e modelos compara os
dois **entre si**, e os dois estavam igualmente sem a restrição. Ele não podia
achar isso — ele confere consistência, não intenção. E o inspector do SQLite não
reporta CHECK, então nem olhar o banco de teste teria mostrado.

O efeito prático era estreito e real: quem escreve pelo ORM não conseguiria
introduzir um quinto estado, porque o SQLAlchemy valida na entrada; um `UPDATE`
direto conseguiria. A garantia de que o conjunto é fechado — que é o ponto
inteiro dos quatro estados — existia por convenção.

Corrigido em `a4ac89d142f4`, com o CHECK conferido no Postgres recusando um
`insert` de `'talvez'`. A migração usa `batch_alter_table` porque o SQLite não
sabe alterar constraint, e sem isso ela rodaria em produção e falharia no banco
onde é testada. Os testes novos olham o **DDL**, que é onde a ausência era
visível desde o começo.

A lição de método, que é a que interessa: um teste de consistência entre duas
descrições não substitui rodar contra a coisa real. As duas descrições podem
concordar em estar erradas.

## O que a decisão não resolve

**A realimentação do informe exporta, mas ainda não entra no eval.** O eval de
informe processa **pares**, e um caso de correção humana só entra quando os dois
documentos do par foram revisados — sem o par, o cruzamento entre anos não tem o
que conferir e o caso mediria a ausência do par, não a leitura. O exportador já
marca isso (`utilizavel` é falso para informe sem par); ligar os pares ao corpus
é da 4.2.

**Não há autenticação.** A API não sabe quem é o revisor além do que ele digita
em `revisor`. É aceitável enquanto ela roda em `localhost` sem interface, e deixa
de ser no momento em que a tela da 4.2 for exposta — a decisão vai junto com ela.

## Consequências

**Positivas**

- O eval e o pipeline continuam sem dependência de serviço, que era a condição
  de a medição continuar barata.
- A fila de revisão distingue "falhou" de "não foi conferido", que é a
  informação que o projeto inteiro produz e que não tinha onde ser guardada.
- O payload bruto permite rodar um sinal novo sobre extrações passadas sem
  gastar cota.
- A regra sobre versionamento ficou explícita, e vale para os três casos:
  relatório sobe, banco não sobe, realimentação não sobe.

**Negativas / custos aceitos**

- Duas definições de "bloqueia" passam a existir, amarradas por teste. É
  duplicação real, aceita porque a alternativa — a API carregar a política para
  responder uma listagem — acoplaria a tela ao pipeline.
- A suíte roda em SQLite, e um schema pode estar errado nos dois de forma
  concordante — foi o que aconteceu com os CHECK. Rodar contra Postgres continua
  sendo uma etapa manual.
- A observabilidade completa custa cinco contêineres. Ficou num profile, e o
  padrão continua sendo só o Postgres.
