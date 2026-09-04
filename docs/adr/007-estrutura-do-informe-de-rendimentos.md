# ADR 007 — Estrutura do informe de rendimentos, e o que nele é verificável

- Status: aceito
- Data: 2026-09-04

## Contexto

A Fase 2 começa por um documento que difere do boleto em espécie, não em
grau: o boleto é registro único, e o informe é multi-registro — quadros com
listas de linhas. A tentação é modelar todo quadro como "lista de linhas mais
um total" e checar a soma. O documento real não é assim, e o Anexo I da IN RFB
(conferido no PDF oficial da IN 1682/2016, que substituiu o Anexo I da IN
1215/2011, e cuja estrutura a IN 2060/2021 manteve) desmente a suposição em
três pontos.

### Os quadros do modelo oficial têm linhas fixas, não lista

```
3. Rendimentos Tributáveis, Deduções e Imposto sobre a Renda Retido na Fonte
   1. Total dos rendimentos (inclusive férias)
   2. Contribuição previdenciária oficial
   3. Contribuição a entidades de previdência complementar, pública ou
      privada, e a fundos de aposentadoria programada individual (Fapi)
   4. Pensão alimentícia
   5. Imposto sobre a renda retido na fonte
4. Rendimentos Isentos e Não Tributáveis — 7 linhas, a 7ª "Outros (especificar)"
5. Rendimentos Sujeitos à Tributação Exclusiva
   1. 13º (décimo terceiro) salário
   2. Imposto sobre a renda retido na fonte sobre 13º salário
   3. Outros
```

São rótulos predefinidos, numerados pelo formulário. Não há lista de tamanho
variável em quadro nenhum.

### A soma das linhas não é o total do quadro

No quadro 3, **a linha 1 já é o total**, e as linhas 2 a 4 são deduções e a 5
é imposto. Somar as cinco não produz grandeza nenhuma. No quadro 5, a linha 1
é rendimento e a linha 2 é o imposto sobre ele. E os quadros 4 e 5 **não
imprimem total**: não existe, na página, o número contra o qual conferir uma
soma.

Implementar "soma das linhas = total declarado" neste layout exigiria o
gerador imprimir um total que o documento real não tem. Seria inventar campo,
e é a distância entre corpus e documento real que a issue #1 já registra como
a limitação mais séria do projeto.

### O comprovante de fonte pagadora não tem saldo

Saldo em 31/12 é do informe de instituição financeira. E lá ele aparece **por
conta ou aplicação** — coluna de especificação, coluna de saldos —, não como
um número do documento. É dessa tabela que a ficha Bens e Direitos da DIRPF é
preenchida, com "Situação em 31/12" de dois anos consecutivos.

## Decisão

### Um schema, com a linha identificada

Quadro é uma lista de linhas `(identificador, descrição, valor)` e um total
**opcional**. O que muda entre layouts é a origem do identificador:

| Layout | Identificador da linha | Total impresso |
|---|---|---|
| `fonte_pagadora` | o número da linha no formulário: `3.1`, `4.7`, `5.2` | não |
| `instituicao_financeira` | a especificação impressa: `Conta Corrente 1219.354589420` | sim |

O ganho é que alinhamento de linha, recall, precisão e acurácia nas linhas
casadas têm **uma** implementação, com uma chave de casamento que muda de
origem mas não de natureza. E nenhum dos dois layouts precisa de campo que o
seu documento não imprime.

### A soma é conferida só onde há total impresso

Onde o total existe, divergência entre ele e a soma das linhas recusa o
documento — é o `valor_divergente` do informe, invisível ao sanitizador e
pego só pela aritmética. Onde não existe, o resultado é **`SEM_TOTAL`**, não
"aprovado". A distinção importa: aprovar por omissão faria o quadro 4 de todo
comprovante de fonte pagadora parecer conferido, quando não foi conferido
nada. Quem consome a validação recebe a lista de quadros sem cobertura.

### Os saldos são por conta, e o cruzamento entre anos casa conta a conta

`saldos` é uma lista de `(especificação, saldo em 31/12, saldo em 31/12 do ano
anterior)`. A validação cruzada entre o informe do ano N e o do ano N−1, da
mesma fonte e mesmo titular, casa por especificação e compara
`saldo_31_12_anterior` de N com `saldo_31_12` de N−1.

Casar por conta em vez de por documento dá um sinal mais forte e mais útil:
aponta **qual** conta divergiu, e não só que o documento não fecha. Vale
registrar por que o cruzamento precisa de dois documentos: o informe do ano N
imprime os dois saldos, mas ambos são afirmação dele mesmo — não há
redundância dentro de uma página. A redundância é o informe de N−1 afirmando
o mesmo saldo de 31/12/N−1 por conta própria.

Conta que existe em N e não em N−1 é conta aberta no ano, e é legítima. A
regra determinística que se aplica a ela é outra, e é real: seu
`saldo_31_12_anterior` tem de ser zero.

### Dois campos entram no schema que o escopo inicial não tinha

**`beneficiario_cpf`.** O cruzamento exige "mesmo titular", e sem o titular no
schema a validação não tem como ser escrita. CPF tem dígito verificador, então
entra com sinal próprio.

**`exercicio`.** O formulário imprime "Ano-calendário de ___ / Exercício de
___", e exercício é sempre ano-calendário + 1. É redundância aritmética de
graça. Sem ela, `ano_calendario` seria um campo sem sinal nenhum, e pela regra
desta fase não poderia entrar.

## O que a decisão não resolve

**O layout de fonte pagadora é pobre em sinal, e isso é do documento.** Ele
tem os DVs de CNPJ e CPF, o par ano-calendário/exercício, e desigualdades
fracas — o IRRF sobre o 13º não pode exceder o 13º. Não tem aritmética de
soma, porque não tem total. Os valores dos quadros dele chegam ao sistema
verificáveis apenas quanto à forma, não quanto ao conteúdo.

Isso não é motivo para deixá-lo de fora. É motivo para a cobertura ser
explícita por campo e a política de roteamento mandar à revisão o que o layout
não cobre — que é o que a Fase 1 já faz. O risco a evitar é o silencioso: um
relatório que mostra acurácia alta num corpus onde metade dos documentos não
tinha como ser conferida.

**Os nomes continuam sem sinal.** `fonte_pagadora_nome` e `beneficiario_nome`
entram no schema por serem a identidade legível do documento, e não têm
verificação possível — mesma situação de `pagador_nome` no boleto, que foi
origem dos únicos escapes da Fase 1 e está registrada na issue #2. O
cruzamento entre anos casa por CNPJ e CPF, nunca por nome, justamente por
isso.

## Consequências

**Positivas**

- Nenhum dos dois layouts precisa de campo inventado, e o corpus fica mais
  perto do documento real — que é o ataque à issue #1.
- As métricas de linha têm uma implementação só, com chave de casamento
  explícita e documentada por layout.
- A validação cruzada entre anos aponta a conta divergente, não só o
  documento.
- `SEM_TOTAL` deixa visível, no relatório, quanto do corpus não foi conferido
  por ninguém.

**Negativas / custos aceitos**

- O schema carrega campos que só um dos layouts preenche (`saldos` é vazio no
  comprovante de fonte pagadora, `total_impresso` é `None` nos quadros dele).
  A alternativa — dois schemas — dobraria alinhamento, eval e prompt.
- A acurácia média sobre um corpus com os dois layouts mistura documentos de
  cobertura muito diferente. Comparar layouts exige separar por layout, e o
  relatório precisa permitir isso.
- O identificador de linha do layout bancário é texto livre impresso na
  página. Ele é a chave de casamento, então um erro de leitura nele não vira
  erro de campo: vira linha não casada, que aparece no recall. É o
  comportamento correto, e vale saber que a chave é o elo mais frágil.
