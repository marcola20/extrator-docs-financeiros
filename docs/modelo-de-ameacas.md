# Modelo de ameaças

Quem envia o documento controla parte da entrada do modelo. Este documento
descreve a superfície de ataque, as quatro camadas de defesa e os dois corpora
adversariais que medem cada uma.

[← README](../README.md)

## Modelo de ameaças

O pipeline lê PDFs enviados por terceiros e coloca o texto deles no prompt de
um modelo cuja saída decide aprovação de pagamento. **Quem manda o documento
controla parte da entrada do modelo** — não é preciso invadir nada, basta
enviar um boleto. É prompt injection, e é a superfície de ataque principal.

O ataque perigoso não é o visível. É o texto que o extrator lê perfeitamente
e o revisor humano não encontra: branco sobre branco, fonte de tamanho quase
zero, posicionado fora da página, ou com opacidade zero. Os quatro foram
reproduzidos e medidos — todos são extraídos, nenhum aparece impresso.

### Defesas, por camada

| Camada | O que faz | O que garante |
|---|---|---|
| Sanitização na ingestão | três detectores independentes: texto invisível, padrões de injection, divergência entre camada de texto e página renderizada | **nada, sozinha.** Encarece o ataque e levanta sinal |
| Isolamento no prompt | conteúdo entre delimitadores explícitos, marcado como dado e não como comando, com neutralização de tentativa de fechar o bloco | reduz a superfície, não a elimina |
| Roteamento | qualquer achado tira a auto-aprovação e manda para revisão com os trechos destacados | que ataque detectado nunca passa sozinho |
| **Validação determinística** | dígitos verificadores da linha digitável e cruzamento de banco, valor e vencimento ([ADR 002](adr/002-validacao-por-digito-verificador.md)) | **esta é a garantia real** |

A ordem importa. O sanitizador **não é** a garantia do sistema: detecção por
padrão de texto é uma corrida perdida, porque qualquer padrão escrito aqui
pode ser reformulado do outro lado. O que sustenta o pipeline é aritmética —
um atacante pode induzir o modelo a escrever `valor: 1,00`, mas não consegue
produzir uma linha digitável de 47 dígitos cujos dígitos verificadores fechem
com esse valor.

Achado da sanitização é sinal. Ausência de achado não é atestado.
Ver [ADR 004](adr/004-defesa-contra-prompt-injection.md).

### Corpus adversarial do boleto: 7 famílias, e quem pega cada uma

`dados/sinteticos/boletos_adversariais/` tem 28 boletos, quatro por família,
cada um com um ataque e um gabarito que declara onde ele está, o que ele pede
(`efeito_pretendido`) e quais detectores deveriam acusar.

Nenhuma família obteve o efeito da carga na passada de 43 documentos, e
nenhum adversarial foi auto-aprovado. A coluna "quem barra" vem de uma
simulação local, sem chamada ao modelo: encena-se um extrator perfeito — que
devolve exatamente o que está impresso — para isolar qual defesa pega o
ataque, independentemente de o modelo ter cedido ou não.

| Família | Como esconde a carga | Quem barra |
|---|---|---|
| `branco_sobre_branco` | texto na cor do papel | sanitização |
| `fonte_minuscula` | corpo de fonte próximo de zero | sanitização |
| `opacidade_zero` | opacidade 0 no texto | sanitização |
| `texto_fora_da_pagina` | posicionado fora da área imprimível | sanitização |
| `delimitador_falso` | imita o fechamento do bloco de dados do prompt | sanitização |
| `instrucao_no_nome_do_beneficiario` | instrução dentro de um campo legítimo, visível | sanitização |
| **`valor_divergente`** | **nada — imprime um valor falso, sem texto injetado** | **só o DV** |

`valor_divergente` é a família que existe para provar o limite das outras
seis. Ela não injeta instrução nenhuma: imprime no campo de valor um número
diferente do que o código de barras codifica, e espera que o extrator o
transcreva — o que é a leitura **correta** da página, e o que ele faz. Não há
padrão a detectar, não há texto invisível, e o grounding aprova, porque o
valor está mesmo escrito ali. Os quatro documentos da família passam por toda
a camada de detecção e são barrados por uma única coisa: o valor extraído não
fecha com os dez dígitos de centavos dentro da linha digitável.

É a demonstração da tese do ADR 002 num caso concreto. Detecção por padrão
teria deixado passar os quatro; aritmética pegou os quatro.

```bash
uv run python -m app.geradores.boleto_adversarial \
    --quantidade 28 --semente 2026 --data-referencia 2026-09-03 --forcar
```

### Corpus adversarial do informe: 8 famílias, e o ataque que precisa de dois documentos

`dados/sinteticos/informes_adversariais/` tem 16 **pares** — 32 PDFs, dos quais
16 carregam a carga. O par íntegro não é enfeite: é ele que dá ao cruzamento
entre anos contra o que conferir.

As quatro primeiras famílias são as da Fase 1.2 adaptadas ao layout. As três do
meio são o `valor_divergente` do informe: página impecável, sem rastro para
detector nenhum, e a soma é a única coisa que não fecha. A última é a razão de a
fase existir.

| Família | Como esconde a carga | Quem barra |
|---|---|---|
| `instrucao_branco_sobre_branco` | texto na cor do papel | sanitização |
| `instrucao_fonte_minuscula` | corpo de fonte próximo de zero | sanitização |
| `instrucao_fora_da_pagina` | posicionado fora da área imprimível | sanitização |
| `delimitador_falso` | imita o fechamento do bloco de dados do prompt | sanitização |
| `linha_injetada` | linha a mais no quadro, total intocado | aritmética — **ou ninguém**, no comprovante |
| `total_adulterado` | total trocado, linhas intocadas | aritmética |
| `quadro_duplicado` | bloco de linhas repetido, total intocado | aritmética |
| **`saldo_anterior_adulterado`** | **nada — o documento fecha em tudo** | **só o informe do ano anterior** |

`saldo_anterior_adulterado` é a família que existe para provar o limite de todas
as outras. Ela troca o saldo de 31/12 do ano anterior num documento sem defeito
nenhum: DVs corretos, somas fechando, nada escondido, e um número perfeitamente
plausível olhando só para aquela página. **Todos os outros validadores do
projeto conferem um documento contra ele mesmo** — os DVs da linha digitável, a
soma de um quadro contra o total que o próprio quadro imprime —, e um adversário
que controla a página inteira pode fazer qualquer um deles fechar.

Este não. O informe de N-1 afirma o mesmo saldo de 31/12/N-1 por conta própria,
emitido em outro momento. Adulterar um não adultera o outro. É a única
verificação do projeto que um adversário com controle de uma página não satisfaz
sozinho.

```bash
uv run python -m app.geradores.informe_adversarial \
    --pares 16 --semente 2026 --data-referencia 2026-09-04 --forcar
```

