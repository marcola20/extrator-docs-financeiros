# Limitações conhecidas

O que os números **não** dizem. Cada limitação endereçável aponta para a issue
em que está sendo acompanhada; as que não são endereçáveis dizem por quê.

[← README](../README.md)

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

**A limitação se reproduziu no informe**, e é o que sobra da Fase 2 depois de
todos os sinais novos. `adversarial-009.pdf` foi auto-aprovado com
`beneficiario_nome` = "Vitor Hugo Fernandes" onde a página imprime "Sr. Vitor
Hugo Fernandes" — e o grounding aprovou **corretamente**, porque o nome sem o
tratamento é substring do que está impresso. É o único escape do corpus de
informes que não vem da omissão coerente descrita abaixo. Seis sinais em vez de
quatro, aritmética de quadro e uma verificação que precisa de dois documentos
não movem esse campo: nome continua sem sinal determinístico, nos dois
documentos.

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

**Sinais que operam sobre a saída extraída não detectam omissão coerente**
([#5][i5]). É uma limitação estrutural, não um defeito de implementação: a
conferência de quadro soma as linhas que a extração devolveu e compara com o
total que a extração transcreveu. Ela pega o modelo que lê **errado**; não pega o
modelo que lê **a menos**, de forma coerente — porque "a página tinha quatro
linhas" e "a página tinha oito e o modelo devolveu quatro" produzem exatamente a
mesma entrada para o sinal. O modelo é ao mesmo tempo o que está sendo
verificado e a única fonte do que se verifica.

Medido: 1 dos 2 `quadro_duplicado` foi auto-aprovado. Em `adversarial-010.pdf`
o modelo deduplicou o quadro em silêncio — devolveu quatro linhas onde a página
imprime oito —, a soma das quatro bateu com o total impresso, e todos os sinais
aprovaram.

O alcance é maior que esse ataque. Omissão coerente de linha, de quadro inteiro
ou de página inteira passa por qualquer sinal que só olhe a saída, e nenhum dos
outros cobre a lacuna: o **grounding** pergunta se o que voltou está na página,
nunca se o que está na página voltou — é unidirecional por construção; a
**auto-consistência** compara duas execuções do mesmo modelo, que tendem a
deduplicar igual; o **cruzamento entre anos** é o único sinal com fonte
independente do modelo, e cobre saldos, não linhas de quadro.

O candidato a endereçamento é contar linhas na página independentemente da
extração — o texto ingerido já está disponível e não custa chamada — e comparar
com o que a extração devolveu. Seria sinal novo, com limiar decidido medindo
(ADR 008), e o corpus limpo tem o caso que faria uma contagem ingênua errar
primeiro: o quadro de 46 linhas que quebra página e repete cabeçalho.

**Os primeiros números da Fase 2.2 estavam otimistas, e a causa era a medição**
(corrigido; fica registrado porque o relatório antigo continua no repositório).
A primeira passada reportou recall de linha de 99,8% e escape rate de 5,6%. Os
dois estavam errados para o mesmo lado, e pela mesma causa: o alinhamento de
linha casava por **chave distinta**, então as ocorrências repetidas do gabarito
nunca entravam em "faltantes". O efeito é que a métrica dava recall de 100%
justamente sobre o documento em que o modelo deixou de devolver quatro linhas
impressas — ficava cega no ataque que ela existe para enxergar, e o escape
correspondente não era contado.

Corrigido para casar **por ocorrência**: recall 99,8% → 98,7%, escape rate
5,6% → 11,1%. Os números desta página são os corrigidos. O relatório
`eval-20260908-223611` continua em `resultados/` e **não é comparável** com o
`eval-20260908-224848` nessas duas linhas — as demais são as mesmas.

A lição de método é a que interessa: uma métrica pode falhar exatamente no caso
que ela foi escrita para medir, e o eval sobre corpus adversarial é o que
expõe isso. Foi a passada contra a API que encontrou o erro, não a suíte.

**Metade do corpus de informes não tem cobertura de verificação** (é do
documento, não endereçável por código). O comprovante de fonte pagadora não
imprime total de quadro e não tem tabela de saldos: nenhum dos dois sinais
aritméticos do projeto tem o que conferir nele. Ele é lido com 100% de acurácia
e vai para revisão assim mesmo, porque não ter conferido não é aprovar
([ADR 009](adr/009-extracao-do-informe-e-cobertura-de-verificacao.md)). O
relatório reporta essa contagem separada da auto-aprovação real justamente para
que ela não seja lida como desempenho ruim do extrator.

**`linha_injetada` no comprovante não é pega por nada** (declarado no gabarito
como `sinal_esperado: nenhum`). Sem total impresso não há soma que deixe de
fechar, e a página não tem defeito visual algum. Está no corpus de propósito e o
relatório o imprime como buraco declarado — um buraco declarado é informação, um
buraco silencioso é armadilha.

**O caminho pelo proxy do front não tem teste automatizado** ([#6][i6]). Três
defeitos seguidos no visor de PDF passaram pela suíte inteira e por verificação
manual com `curl`: `Content-Disposition: attachment` (o padrão do FastAPI, que
faz o navegador baixar em vez de exibir), ausência de `Cache-Control` (o
navegador guardava a resposta **com o cabeçalho junto**, e a correção não
alcançava quem já tinha a versão antiga), e o proxy do Next descartando o
cabeçalho novo por ele não estar na lista de repasse.

Os dois primeiros eram da API, e havia teste da rota — que verificava status,
tipo e corpo. Os três seguiam certos com o defeito presente: **o arquivo era
servido corretamente, só que com uma instrução que o navegador obedecia.** A
verificação media um nível ao lado do que importava. Hoje há asserção sobre os
dois cabeçalhos.

O terceiro é de uma camada sem teste nenhum. Toda verificação desta fase usou
`curl` contra a API — que não passa pelo proxy — ou contra o front com os
contêineres já de pé, o que só existe enquanto alguém está olhando. E há uma
quarta camada que nenhum deles alcança: se o navegador de fato **renderiza**,
que é onde o primeiro defeito se manifestava.

Fechar isso não é difícil de escrever — é que o projeto não tem infraestrutura
de teste em JavaScript, e **o CI não constrói o front**: um erro de tipo em
TypeScript passa verde hoje. A issue detalha os três alvos e o custo de cada um.

**A API de revisão não tem autenticação** (sem issue: é decisão de quando a tela
sair do `localhost`). Ela não sabe quem é o revisor além do que ele digita no
campo `revisor`, e qualquer um que alcance a porta lê a fila, baixa os PDFs e
grava correções. É aceitável como demonstração local; deixa de ser no momento em
que a tela for exposta, e a decisão vai junto com a exposição — não antes.

**O schema é conferido em SQLite, e Postgres só à mão** (sem issue: exigir o
serviço na suíte contrariaria a decisão de a persistência ser opcional). O teste
que compara migração e modelos roda em SQLite, e **duas descrições podem
concordar em estar erradas**: foi o que aconteceu com os CHECK dos enums, que
faltavam nos dois lados e só apareceram ao olhar um banco de verdade. Há uma
suíte contra Postgres (`-m postgres`), e ela é pulada por padrão e rodada à mão
antes de fechar uma fase.

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
[i5]: https://github.com/marcola20/extrator-docs-financeiros/issues/5
[i6]: https://github.com/marcola20/extrator-docs-financeiros/issues/6


## A Fase 3 não foi feita

**Fase 3 — extrato de investimento, pendente.** Ela traria o primeiro documento
com tabela que **quebra entre páginas**, onde a mesma posição pode aparecer
partida em duas partes e o cabeçalho se repete: um caso de alinhamento de linha
que o corpus de informes só encosta, com o quadro de 46 linhas.

