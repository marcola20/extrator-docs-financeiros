# Revisão humana

A fila persistida, a API que devolve o diagnóstico completo, a interface que o
mostra, e a correção humana virando caso de eval.

[← README](../README.md)

## O que a fase entregou

**Fase 4 — revisão humana.** O pipeline passa a ter estado: fila persistida em
Postgres, API que devolve o diagnóstico completo, interface em Next.js, correção
humana virando caso de eval, traces no Langfuse e CI em dois jobs. Persistência
é opcional — o pipeline e o eval continuam rodando sem banco.

## Revisão humana

Até a Fase 4 o pipeline não guardava nada: uma decisão vivia em memória e morria
com o processo, e a correção de um revisor não sobrevivia ao reinício. A fase deu
estado ao que o pipeline já sabia, e uma tela para olhar.

```bash
docker compose --profile revisao up -d   # banco, API e interface
uv run alembic upgrade head
PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --limpar
# http://localhost:3001
```

Fora do profile, `docker compose up -d` sobe só o Postgres. Persistência é
**opcional e desligada por padrão**: o pipeline e o eval rodam sem banco, porque
fazer a medição depender de um Postgres de pé transformaria "rodar o eval" numa
tarefa de infraestrutura.

O último comando popula a fila com sete cenários e **não gasta cota** — o
provedor dele lê o gabarito que está ao lado de cada PDF do corpus sintético, em
vez de chamar o modelo. É o que permite abrir a tela numa entrevista, ou gravar o
GIF do topo, sem consumir as 500 chamadas diárias do tier gratuito.

Os cenários caem em quadrantes diferentes do que a interface tem a dizer: valor
alucinado, nome trocado, leitura fiel, ataque com texto invisível, valor
divergente, e dois pares de informe — um sem cobertura, outro com. Os dois
últimos são os que mais importam. O `valor_divergente` é o do GIF: página
impecável, extração correta, e só a aritmética barrando. O par de comprovantes é
o oposto — nada reprovou, e ninguém conseguiu conferir.

### A API

| Rota | O que devolve |
|---|---|
| `GET /revisao/fila` | a fila, filtrável por tipo, por sinal e por estado do sinal |
| `GET /revisao/{id}` | o **diagnóstico completo** |
| `GET /revisao/{id}/pdf` | o arquivo original |
| `POST /revisao/{id}/correcoes` | as correções do revisor, em lote |
| `GET /revisao/estatisticas` | os números da fila |

O que `GET /revisao/{id}` devolve não são os campos extraídos: é o motivo de o
documento estar na fila.

- **qual sinal reprovou, e qual apenas não teve o que conferir.** Os quatro
  estados atravessam a API sem virar booleano — uma resposta com
  `"aprovado": false` parece razoável até alguém perguntar se o sinal chegou a
  rodar;
- **a mensagem que o sinal escreveu**, que aponta a causa: "não fecha: CNPJ da
  fonte pagadora inválido", "nenhum quadro tinha total impresso para conferir";
- **onde olhar**, quando o sinal fala de um lugar específico
  (`rendimentos_isentos[LCI].valor`);
- **os trechos que o sanitizador achou, com página e coordenadas**, para o
  revisor comparar com o que está impresso.

Pela mesma razão, o filtro separa "reprovou" de "não teve o que conferir": são
filas de trabalho diferentes. Um documento com erro a investigar não é a mesma
tarefa que um documento que ninguém conseguiu conferir — e no corpus de
informes o segundo grupo é a maioria (24 de 56).

### O que a API não faz

**Não processa documento.** Extrair custa cota e dezenas de segundos; um
endpoint que chamasse o modelo viraria porta para gastar orçamento.

**Não recalcula sinal.** Os vereditos vêm do banco como o pipeline os deixou.
Recalcular na leitura permitiria a tela mostrar uma coisa e o histórico guardar
outra, e a diferença apareceria como revisor discordando de si mesmo entre duas
aberturas da mesma página.

### A tela, e por que não é um CRUD

A tela existe para tornar visível **como o sistema decide**. Uma interface que
mostrasse só "documento, campos, aprove ou corrija" jogaria fora o que as três
fases anteriores construíram — e o que ela mostra bem é o que o projeto
comunica para quem nunca vai clonar o repositório.

**Por que este documento está aqui** vem antes do PDF, e separa dois casos que
pedem trabalho diferente:

- *um sinal reprovou* — há erro concreto, e a mensagem do pipeline aponta onde:
  "valor 99999.99 não confere com a linha digitável (R$ 179.66)";
- *um sinal não teve o que conferir* — não há erro apontado, e o documento
  precisa ser lido do zero. É o caso mais fácil de despachar com um "parece
  bom", justamente porque nada está gritando.

**Os quatro estados de sinal** atravessam a interface sem virar semáforo. O
enunciado da fase falava em três — conferido, divergente, sem cobertura —, que
são os da conferência de quadro da Fase 2; a tabela de sinais da 4.1 tem
`dispensado` também, para o sinal que o operador desligou. Desenhar para três
faria o quarto cair no visual de "conferido".

Duas regras de desenho protegem a distinção:

1. **Só `conferido` recebe marca de certo.** Os outros três recebem glifos que
   não podem ser lidos como aprovação (`!`, `—`, `⦸`). Um ✓ cinza ainda é um ✓
   num relance, e é o que a pessoa lê.
2. **`sem_cobertura` tem borda tracejada.** Preenchimento contínuo é a linguagem
   de "resolvido"; o tracejado diz "falta coisa aqui" sem depender de cor, o que
   também resolve daltonismo.

**Os trechos suspeitos** aparecem em monoespaçado com página e coordenadas, e
clicar leva o visor àquela página do PDF. O ponto deles é que o revisor não os
encontraria olhando o documento: texto branco sobre branco, corpo de fonte
próximo de zero, conteúdo posicionado fora da página.

### O que o front não faz

Nenhuma decisão. `bloqueia` vem calculado da API, as mensagens vêm prontas do
pipeline, e nenhum estado é derivado no navegador. O front busca, tipa e
apresenta.

O navegador também nunca fala com a API diretamente: tudo passa por um proxy em
`/api/*`. Isso evita CORS sem tocar no backend da 4.1, e faz o `<iframe>` do PDF
ser mesma origem.

### Fora de escopo, deliberadamente

- **Sem autenticação.** É demo local; a API não sabe quem é o revisor além do
  que ele digita. Deixa de ser aceitável no momento em que a tela for exposta.
- **Sem realce sobre o PDF.** Os achados carregam as coordenadas e a tela as
  mostra, mas desenhar o retângulo por cima exigiria renderizar o documento com
  pdf.js e converter coordenadas de PDF para pixels — dependência pesada para o
  que a fase pedia.

### Realimentação: correção humana vira caso de eval

O que o revisor corrigiu é um gabarito conferido por gente — o melhor caso de
teste que existe. E é sobre um documento **real**, então ele não entra no
repositório:

```bash
uv run python -m app.avaliacao.exporta_realimentacao   # grava em dados/realimentacao/
uv run python eval.py --com-realimentacao              # desligado por padrão
```

Os casos guardam **caminho e hash** do PDF, nunca uma cópia, e o diretório é
coberto pelo `.gitignore`. A flag é desligada por padrão porque misturá-los ao
corpus sintético sem distinção contaminaria a comparação com os baselines: a
acurácia mudaria por o corpus ter crescido, não por o extrator ter melhorado.
Quando ligada, a procedência entra no relatório — e a retomada passa a recusar
somar uma passada com realimentação a uma sem.

### A regra sobre o que é versionado

Três decisões que parecem contraditórias e são a mesma regra
([ADR 010](adr/010-persistencia-e-fila-de-revisao.md)):

| | Versionado? | Por quê |
|---|---|---|
| `resultados/*.json` | **sim** | taxas, contagens e booleanos; uma trava impede que passe a guardar valor extraído |
| tabela `extracao` (JSONB) | não | é o payload bruto do modelo, e o banco é local |
| `dados/realimentacao/` | não | é gabarito de documento real |

**O que é versionado não carrega conteúdo de documento; o que carrega conteúdo
de documento não é versionado.**

