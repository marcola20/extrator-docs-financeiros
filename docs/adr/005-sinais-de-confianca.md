# ADR 005 — Três sinais de confiança independentes do modelo

- Status: aceito
- Data: 2026-09-03

## Contexto

A Fase 1.3 fecha o pipeline: um PDF entra, uma decisão sai. A decisão é se o
documento pode ser auto-aprovado ou vai para revisão humana, e ela vale
dinheiro — auto-aprovar uma extração errada é pagar o valor errado.

O ADR 002 já decidiu de onde a confiança **não** vem: não do `confidence`
auto-reportado pelo modelo. Aquele ADR resolveu banco, valor e vencimento,
que estão codificados de forma redundante na linha digitável. Sobrou o resto:
`beneficiario_nome`, `beneficiario_cnpj`, `pagador_nome`, `nosso_numero` —
campos sem redundância aritmética nenhuma, e que também decidem para quem o
dinheiro vai.

## Decisão

Três sinais, nenhum deles produzido pelo modelo que está sendo conferido.

### 1. Dígito verificador — a única garantia

É o ADR 002 rodando. A conversão do que o modelo devolveu para o `Boleto` do
domínio **é** o sinal: se ela levanta `ValidationError`, banco, valor ou
vencimento não fecham com a linha digitável.

Cobre três campos e nada mais. É pouco em quantidade e muito em força: é
aritmética, e o atacante não a controla.

### 2. Grounding — o valor aparece no texto de origem?

Pergunta textual e determinística. Pega alucinação: um CNPJ que o modelo
produziu mas que não está escrito em lugar nenhum da página.

**Não pega troca de campo.** Se o modelo põe o CNPJ do pagador no campo do
beneficiário, os dois estão na página e o grounding aprova. É a limitação
principal deste sinal, e está num teste com esse nome.

**Isenção é declarada, nunca silenciosa.** `banco_nome` é derivável de
`banco_codigo` e pode não estar impresso por extenso. Reprová-lo daria falso
positivo constante; aprová-lo em silêncio seria pior, porque o relatório
diria "grounding ok" sobre um campo nunca conferido. Ele sai como `ISENTO`,
com o motivo escrito, e a taxa de grounding só conta o que foi de fato
conferido.

### 3. Auto-consistência — duas execuções concordam?

É o único sinal que alcança `beneficiario_nome` e `nosso_numero`. Não prova
correção — duas execuções podem errar igual —, mas divergência é sinal de
leitura instável, e leitura instável num campo que decide destinatário é
motivo suficiente para um humano olhar.

**A assimetria é o ponto: divergência é evidência forte, concordância é
evidência fraca.**

#### O tradeoff: sempre vs. condicional

| | `sempre` | `condicional` |
|---|---|---|
| Chamadas por documento | 2 | 1, e 2 só quando outro sinal falhou |
| Cota do corpus (43 docs) | 86 | ~50 |
| Taxa base | comparável entre documentos | não existe |
| Ponto cego | nenhum | documentos que passam nos outros sinais |

`sempre` é o padrão por causa da taxa base. Sem ela não dá para dizer se a
divergência de um documento é alta: alta comparada a quê? Medir divergência
só nos documentos que já falharam produz um número enviesado por construção,
tirado justamente da amostra pior.

O ponto cego do `condicional` é específico e vale nomear: um documento em que
sanitização, DV e grounding passam **não recebe o único sinal que cobre
`beneficiario_nome` e `nosso_numero`**. É exatamente o caso em que a
auto-aprovação acontece — ou seja, economiza-se a conferência bem onde ela
mais importa. Por isso é opção, não padrão.

`nunca` existe para desenvolvimento. O sinal sai como **dispensado**, e a
diferença entre dispensado e falho chega à política.

#### Duas armadilhas que a implementação encontrou

**O cache tornaria o sinal uma tautologia.** A segunda execução com o mesmo
prompt e documento é um acerto de cache: devolveria o primeiro resultado byte
a byte, e o sinal diria "concordam" sempre. A segunda passa por um provedor
com cache desligado.

**A temperatura enfraquece o sinal.** O provedor roda com `temperature=0.0`
para a extração ser reprodutível (ADR 003). Com amostragem determinística, o
que este sinal mede é a não-determinação residual do serviço — real, mas
fraca. É limitação medida, não defeito: **concordância aqui vale pouco.**

### 4. Como os quatro se somam

Somando a sanitização da Fase 1.2, são quatro. Não há peso, pontuação nem
limiar: **qualquer sinal que reprove manda para revisão.** Falso positivo
custa tempo de revisor, falso negativo custa um pagamento errado, e os dois
não se equivalem.

Sinal que **não rodou** não conta como aprovado — mesma regra da Fase 1.2. A
exceção é o sinal **dispensado** por configuração: aí houve escolha, ela fica
no relatório, e o ponto cego é do operador. Sem essa distinção, o modo
`nunca` bloquearia tudo e seria inútil.

### 5. Schema de transporte, e não o schema de domínio

O modelo não devolve um `Boleto`. Devolve um `BoletoExtraido`, todo em texto e
sem validador. Duas razões:

- **Acurácia por campo.** O `Boleto` recusa a instância inteira quando um
  campo não fecha. Se o modelo acerta nove e erra o valor, o resultado seria
  "falhou", e o eval não distinguiria um modelo que erra um campo de outro que
  erra tudo.
- **Evidência.** O grounding pergunta se o valor aparece **literalmente** no
  texto. Para isso é preciso o que o modelo escreveu: `Decimal("1847.30")` não
  diz se ele escreveu `1.847,30` ou `R$ 1.847,30`.

Era a pergunta em aberto que o ADR 003 deixou para esta fase, e a resposta é
esta. Uma descoberta veio junto, e só apareceu numa chamada de verdade: o SDK
aceita o schema localmente, mas **a API do Gemini recusa
`additionalProperties`** com `400 INVALID_ARGUMENT`. `extra="forbid"` no
Pydantic emite esse campo, então ele não pode estar no schema de transporte.

### 6. O caminho de visão fica fechado na extração

A ingestão detecta PDF sem camada de texto e rasteriza, como pedido. A
extração **recusa** esse caminho.

Não é esquecimento. Os três detectores da Fase 1.2 operam sobre a camada de
texto; sem ela, todos rodam sobre nada e não acham nada. Um documento
digitalizado chegava ao fim do pipeline como "limpo" tendo sido inspecionado
por ninguém — o furo foi encontrado nesta fase e fechado: `houve_o_que_
inspecionar` agora separa não-achou de não-procurou.

Com o furo fechado, mandar a imagem de um documento não confiável ao modelo
seria abrir uma superfície que nenhuma defesa cobre, e o ADR 004 registrou que
essa defesa tem que ser desenhada junto com o caminho. Enquanto ela não
existir, documento sem camada de texto vai para revisão humana. É reversível:
o dia em que houver defesa para imagem, a recusa sai.

## Consequências

**Positivas**

- Nenhum dos quatro sinais é produzido pelo modelo que está sendo conferido.
  Um erro de leitura não vem acompanhado de um sinal que o abone.
- Os campos sem redundância aritmética deixam de estar completamente
  descobertos: grounding pega invenção, consistência pega instabilidade.
- A decisão é auditável campo a campo. O revisor recebe qual sinal bloqueou,
  por quê, e quais campos conferir.
- A política é função pura, testada sem LLM nenhum.

**Negativas / custos aceitos**

- **`sempre` dobra o consumo de cota.** Com 500 RPD, o corpus de 43
  documentos cabe duas vezes por dia, e não mais.
- **Concordância entre execuções vale pouco a temperatura zero.** O sinal é
  quase todo unilateral: serve para reprovar, quase não serve para aprovar.
- **Grounding não pega troca de campo**, que é justamente o erro que um
  modelo comete em documento de layout denso.
- **Três campos têm garantia forte; sete têm garantia fraca.** Nenhum arranjo
  de sinais textuais muda isso — a redundância aritmética só existe para os
  três.
- **Documento digitalizado não é processado.** Vai inteiro para revisão.

**Não decidido aqui**

- Se a taxa de escape medida justifica auto-aprovação em produção. É o eval
  que responde, e ele ainda não rodou contra a API — ver o README.
- Se vale ter um sinal para troca de campo (posição do valor na página em
  relação ao rótulo, por exemplo).
- Como os sinais viram métrica em observabilidade (Fase 4).
