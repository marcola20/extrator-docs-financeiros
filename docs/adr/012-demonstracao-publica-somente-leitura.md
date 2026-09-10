# ADR 012 — Demonstração pública somente-leitura

## Contexto

A Fase 4.2 entregou uma tela de revisão que roda em `localhost`. Ela mostra o
que o projeto tem de próprio — por que cada documento está na fila, o que cada
sinal conseguiu afirmar, os trechos que o revisor não veria olhando a página —
e nada disso aparece num README. Quem avalia o projeto teria que clonar o
repositório, subir Postgres, aplicar migrações e semear a fila para ver a tela.

Um GIF resolve parte disso e já está no topo do README. O que ele não resolve é
a navegação: o GIF mostra um caminho, e o que a tela tem de interessante é
justamente **contrastar** casos — o documento que a aritmética barrou ao lado do
que ninguém conseguiu conferir.

Colocar a tela no ar levanta três problemas que a versão local não tinha.

**Escrita.** A tela grava correções, e a fila é a mesma para todos. Sem
autenticação — e a Fase 4.2 declarou "sem autenticação" como fora de escopo —,
o que um visitante digita fica na tela do visitante seguinte.

**Dados.** A demonstração não pode depender de chave de API. O tier gratuito do
Gemini é o orçamento do projeto (ADR 003), e um serviço público que chamasse o
modelo seria uma porta para gastá-lo.

**A primeira tela.** A fila lista arquivos. Para quem revisa documentos isso é
o certo; para quem abriu o link pela primeira vez, `adversarial-005.pdf` não diz
nada, e o caso mais interessante do corpus fica indistinguível dos outros sete.

## Decisão

### A API recusa a escrita; a tela apenas mostra a consequência

`DEMO_SOMENTE_LEITURA=1` faz `POST /revisao/{id}/correcoes` responder **403**. É
a única rota de escrita da API, e a recusa é uma dependência do FastAPI
(`recusa_escrita_na_demo`), avaliada **antes** de a decisão ser procurada.

A tela desabilita os campos e esconde o botão de gravar, mas isso é
consequência, não trava: ela recebe `somente_leitura` na própria resposta do
diagnóstico. Esconder o botão sem fechar a rota deixaria a gravação aberta para
qualquer `curl`, e a fila é semeada uma vez por implantação — o dano ficaria na
tela até o próximo deploy.

É a mesma regra do ADR 011 aplicada a mais um campo: **o front não decide**. Uma
variável de ambiente lida pelo navegador seria uma segunda definição da política,
e a que o visitante veria seria a errada quando as duas divergissem.

**403, e não 404 nem 405.** A rota existe e o pedido está bem formado; o que
falta é permissão. E 403 antes de procurar a decisão, porque responder 404 para
um id inexistente contaria quais ids existem e sugeriria "tente outro" quando
nenhum id vai funcionar.

### O banco é semeado na partida, com o provedor de gabarito

`docker/inicia-demo.sh` migra, **abre a porta**, e semeia atrás dela.
`semeia_fila` já existia e já não gastava cota: o provedor dele lê o gabarito
que está ao lado de cada PDF do corpus sintético e devolve aqueles campos, como
um extrator perfeito devolveria. **A demonstração não tem chave de API**, e
`LLM_SEM_REDE=1` transforma qualquer tentativa de chamar o modelo em erro alto.

`--completar` é o que torna a partida segura de repetir. O plano gratuito desliga
o serviço por inatividade e o religa na visita seguinte, então este script roda
muitas vezes, não uma; semear sempre duplicaria a fila a cada despertar, e
semear com `--limpar` a apagaria no meio da visita de alguém.

#### Tudo-ou-nada era a trava errada

A primeira forma disso foi "não faça nada se a fila tiver qualquer decisão". Ela
é segura de repetir e tem um modo de falha ruim: uma semeadura **interrompida no
meio** — o contêiner ficou sem memória, a instância foi reciclada — deixa parte
dos documentos gravados, e a partida seguinte lê "a fila não está vazia" e trata
isso como trabalho concluído. A demonstração fica pela metade sem erro nenhum, e
o buraco só aparece para quem abre o link e não acha um caso.

A troca não é de probabilidade, é de modo de falha: `--completar` compara
**documento a documento** e semeia só o que falta, então uma semeadura
interrompida se conserta sozinha no despertar seguinte. Medido: interrompida
depois de 5 dos 11 documentos, a partida seguinte anuncia "3 de 8 cenário(s)
faltando", grava 6 documentos em 14,4 s, e não duplica nenhum dos 5 que já
estavam.

Duas consequências de desenho:

- **o par de informes é a unidade de pendência, e o documento é a unidade de
  gravação.** Um par pela metade conta como pendente — o cruzamento entre anos
  precisa dos dois — e é **reprocessado** inteiro, porque não há como conferir um
  sozinho; mas só é gravado o documento que ainda não tem decisão. Sem essa
  distinção, completar um par interrompido criaria uma segunda decisão para o
  que sobreviveu, e a fila mostraria o mesmo informe duas vezes;
- **o log termina dizendo quais dos cinco casos da entrada estão no banco.** É a
  pergunta que importa para a demonstração — não "quantos documentos foram
  gravados", e sim "os cinco casos que a entrada promete estão lá?" —, e uma
  semeadura parcial passa a aparecer no log em vez de ficar muda. A lista vem de
  `app/demo.py`, o mesmo módulo que a API lê.

#### A ordem foi aprendida errando: o primeiro deploy não subiu

A primeira versão semeava **antes** do uvicorn, e a implantação falhou com
`No open ports detected`, repetido até `Port scan timeout reached`. Não houve
erro nenhum no semeador — ele estava rodando, e a hospedagem desistiu de esperar
a porta abrir.

A causa é o custo, e o custo é o OCR: a semeadura processa cada documento pelo
pipeline inteiro, e o detector de divergência texto/imagem renderiza a página a
300 DPI e roda o tesseract em cima. Medido em máquina de desenvolvimento:
**1,7–2,0 s por boleto, 4,5 s por par de informe, 23 s no total** — e numa
instância gratuita compartilhada isso é vários minutos.

Encurtar não era opção. Semear com `--sem-ocr` caberia na janela e destruiria a
demonstração: sem a comparação texto/imagem, a política da Fase 1.2 barra
**todo** documento, a fila sairia inteira bloqueada pelo mesmo sinal, e o caso
"boleto limpo, auto-aprovado" da entrada seria falso.

Então a ordem passou a ser: migrar (rápido, e pré-requisito de tudo), `exec` no
uvicorn, e a semeadura em **segundo plano**. A API sobe em segundos e a fila se
povoa atrás dela. Três consequências, todas assumidas:

- **quem visita durante a primeira semeadura vê a fila se enchendo.** A entrada
  já sabia desenhar caso indisponível; o texto passou a dizer que uma instância
  recém-implantada leva alguns minutos, em vez de mandar rodar um comando que
  quem está de fora não pode rodar. Só vale para o primeiro deploy: no despertar
  seguinte `--se-vazia` acha a fila cheia e sai em 1,8 s;
- **um zumbi.** O processo em segundo plano continua filho do PID 1, que depois
  do `exec` é o uvicorn — e o uvicorn não chama `wait()`. Evitá-lo custaria não
  usar `exec`, e aí o SIGTERM da hospedagem chegaria ao shell em vez do uvicorn,
  que é quem precisa dele. Uma entrada na tabela de processos, sem memória e sem
  descritor, é o preço menor;
- **a semeadura deixou de poder derrubar a partida**, e isso agora é de graça:
  `set -e` não alcança job em background. É a decisão certa de qualquer forma —
  fila vazia é degradação, página que não abre é queda.

#### O log ficou em branco, e isso atrapalhou mais que a falha

O único sinal no log era o `echo` do shell. As linhas do Python não apareciam,
e não por não existirem: o stdout do Python é **bloco-bufferizado quando não é
terminal**, e dentro de um contêiner ele nunca é. Um processo que demora minutos
sem imprimir nada é indistinguível de um travado.

Duas correções, e as duas eram necessárias: `PYTHONUNBUFFERED=1` na imagem, e uma
linha por documento — **ao começar e ao terminar**. Duas e não uma porque a
pergunta que o log precisa responder é "onde travou", e o documento que trava é
justamente o que nunca imprime a linha de fim.

### Uma página de entrada, por situação

`/` apresenta cinco casos, uma frase cada, e o clique leva ao diagnóstico
daquele documento. A fila continua inteira, em `/fila`.

Os cinco não se repetem — cada um mostra uma coisa que os outros não mostram:

| Caso | O que ele demonstra |
|---|---|
| boleto com valor adulterado | a página está impecável e a extração está certa; só a linha digitável desmente |
| informe com saldo do ano anterior trocado | o documento fecha em tudo; só o informe do ano passado desmente |
| boleto com instrução invisível | o sanitizador achou o que o revisor não veria |
| comprovante sem cobertura | nada reprovou, e ninguém conseguiu conferir |
| boleto limpo | como é quando dá certo |

O segundo **não existia na fila semeada** e foi acrescentado por esta fase. O
corpus adversarial de informes já tinha a família `saldo_anterior_adulterado`
desde a Fase 2.1, mas os dois pares que a demonstração semeava eram o comprovante
sem cobertura e o bancário auto-aprovado. Sem ele, o cruzamento entre anos —
o único sinal do projeto que um adversário com controle da página não satisfaz
sozinho — aparecia na tela apenas como um sinal que sempre aprova.

Medido na semeadura: sanitização, domínio, aritmética e grounding dizem
`conferido` naquele par, e só `cruzamento` reprova.

**Qual PDF é qual mora num lugar só** (`app/demo.py`). Três dos cinco casos são
adversariais, e o corpus adversarial numera os arquivos na ordem de geração —
regerar com outra semente troca os números, o que é legítimo e quebraria
qualquer caminho literal. Os casos localizam o documento pela família do ataque,
lendo o gabarito; e o mesmo módulo é lido pelo semeador e pela API, para os dois
não discordarem sobre qual arquivo é qual. `tests/test_demo.py` é a trava.

### O cold start é tratado na interface, não escondido

Dois serviços gratuitos dormem por inatividade, e a primeira visita acorda os
dois em série: pode levar mais de um minuto. A interface diz isso.

- `loading.tsx` nas três rotas, para o cabeçalho aparecer na hora em vez de a
  aba ficar em branco. A nota sobre o servidor adormecido só entra **depois de
  quatro segundos** — mostrá-la desde o primeiro quadro diria "o servidor está
  acordando" numa página que já carregou, e um aviso que mente ensina a ignorar
  os avisos;
- a falha por não haver resposta (conexão recusada ou tempo esgotado) deixou de
  ser "a API não respondeu" genérico: ela é uma tela própria, que explica o
  plano gratuito e **tenta de novo sozinha**, quantas vezes forem necessárias;
- a busca tem prazo total de 65 s, com as repetições dentro. O padrão do
  `fetch` — esperar indefinidamente — deixaria a página pendurada sem dizer
  nada; um valor curto desistiria de um servidor que ia responder.

#### O 502 da API acordando era tratado como falha

O tratamento acima cobria o front acordando e a API que não responde nada.
Faltava o caso que de fato acontece na primeira visita: a hospedagem segura a
requisição do navegador até o front subir, e só então o servidor do Next chama a
API — que ainda está dormindo, e para essa chamada a hospedagem responde **502**.
A tela lia o 502 como "a API respondeu com erro", e quem abria o link pela
primeira vez via "A API não respondeu — Bad Gateway". A demonstração só
funcionava para quem já tivesse acordado a API abrindo `/health` à mão.

A correção é o raciocínio do `ErroTransitorio` do limitador do provedor: o erro
diz "ainda não", não "não". `web/lib/espera.ts` repete 502, 503 e 504 com backoff
exponencial — 1 s, dobrando até 8 s — dentro do prazo de 65 s, e o servidor do
Next faz isso **dentro** da renderização: quem está olhando vê o `loading.tsx`,
com a nota sobre o servidor acordando, durante toda a espera. A tela de falha
("O servidor não acordou a tempo") só aparece com o prazo esgotado.

Três decisões de desenho:

- **o 503 da própria API não se repete.** Ela responde 503 quando a persistência
  está desligada, e aquele 503 diz "não": nenhuma espera liga o banco. O critério
  é quem respondeu — erro da API é JSON com `detail`, como todo erro do FastAPI; o
  da hospedagem, não. Repetir todo 503 faria a tela que ensina a ligar o banco
  chegar um minuto atrasada;
- **só GET se repete.** O proxy também repassa o POST de correção, e um 504 não
  garante que a gravação deixou de acontecer. Repetir escrita às cegas é o jeito
  de gravar duas vezes;
- **o fim do prazo chega como "esgotou", nunca como tentativa abortada.** Quando
  a espera seguinte não cabe no que sobrou, a busca para ali, até 8 s antes do
  prazo. Espremer uma última tentativa contra o fim a faria estourar como
  `TimeoutError`, que a tela lê como "sem resposta" e desenha como servidor
  acordando — o contrário do que aconteceu.

Medido localmente, contra uma API falsa que responde 502 `text/plain` por 20 s: o
loading chega em 0,08 s, as tentativas saem em 0, 1, 3, 7, 15 e 23 s, e os casos
aparecem aos 23 s. Com o 503 em JSON, a tela de banco chega em 78 ms, com uma
requisição só. Com uma API que nunca acorda e prazo de 20 s, a falha aparece aos
15 s, depois de cinco tentativas. Pelo proxy, o POST durante o sono volta 502 na
hora, com uma requisição, e o GET repete até voltar 200, aos 7 s.

**Acordar a API antes, pela página de entrada, foi considerado e não feito.** A
ideia era disparar `/health` assim que a entrada carrega, para a API ir acordando
enquanto a pessoa lê os cinco casos. Mas os cinco casos **vêm** da API
(`/demo/casos`): quando eles estão na tela, ela já acordou, e o ping sairia com o
trabalho feito. A espera em série — o front, depois a API — só encurtaria se algo
acordasse a API antes de o front responder, e até ali o único código rodando é o
navegador esperando o HTML.

## Consequências

**A demonstração não demonstra a gravação.** Corrigir um campo é metade do que a
tela faz, e um visitante não vai ver essa metade funcionando — vai ver a nota
dizendo que está desligada e por quê. É o custo aceito: a alternativa é uma fila
que acumula o que estranhos digitaram.

**O corpus entra na imagem da API, e o tesseract também.** Local, o corpus é
volume; na hospedagem não há volume, e sem os PDFs o semeador não teria o que
processar e o visor responderia 404. São 2,4 MB. O tesseract é mais caro (~50 MB)
e é obrigatório por um motivo de conteúdo, não de rigor: sem a comparação
texto/imagem, a política da Fase 1.2 barra **todo** documento — "não achar é
diferente de não procurar" —, a fila sairia inteira bloqueada pelo mesmo sinal, e
o caso "boleto limpo, auto-aprovado" da entrada seria falso.

**A imagem deixou de ser só "a API".** O `CMD` continua sendo o uvicorn e nada
mais — é o que o `docker compose` local usa —, mas a imagem agora carrega o que
é preciso para processar documento na partida. A promessa que continua valendo é
a que importa: **nenhuma requisição processa documento**, e importar `app.main`
não carrega pdfplumber nem os SDKs de LLM. `app/demo.py` só importa a biblioteca
padrão por causa disso, e há um teste que o verifica.

**O banco público é descartável, e isso é uma propriedade e não um risco.** Nada
nele é original: tudo veio do corpus sintético versionado, e o semeador o
reconstrói do zero. É o mesmo raciocínio do ADR 010 — o que carrega conteúdo de
documento não é versionado, e o que não é versionado precisa ser descartável.

**A URL da API fica fora do `render.yaml`** (`sync: false`, o Render pergunta ao
criar o blueprint). Rede privada entre serviços é recurso de plano pago; no
gratuito, o servidor do Next chama a API pela URL pública dela, e essa URL
depende do nome que o serviço acabou recebendo. Um palpite errado gravado no
arquivo apareceria como "a API não respondeu" — numa tela que, por desenho, culpa
o cold start.

**`DATABASE_URL` passou a ser normalizada.** Serviços gerenciados entregam a URL
no formato da libpq (`postgres://`), que o SQLAlchemy 2 recusa, e `postgresql://`
sem driver escolhe o psycopg2, que este projeto não instala. `Settings` completa
o driver quando ele falta. `sqlite://` e URLs que já trazem `+driver` passam
intactas.

**A fila mudou de endereço.** `/` é a entrada e `/fila` é a fila, o que muda
qualquer link salvo para a raiz. A alternativa — deixar a entrada em `/demo` —
manteria os links e daria à demonstração pública uma primeira tela que ela existe
para não ter.
