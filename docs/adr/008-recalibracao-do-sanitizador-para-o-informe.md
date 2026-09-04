# ADR 008 — Recalibração do sanitizador para o informe

- Status: aceito
- Data: 2026-09-04

## Contexto

Os três detectores da Fase 1.2 foram calibrados contra um corpus de 15
boletos, todos do mesmo template. O informe é outro documento: rodapé legal
miúdo, tabelas com fundo zebrado, faixa de cabeçalho azul-escura com texto
branco, e rótulos de campo em maiúsculas de 5,5pt.

A medição no corpus limpo de 24 informes, antes de qualquer ajuste:
**24 de 24 documentos sinalizados**, por três causas independentes.

Nenhuma delas era limiar mal escolhido, e é isso que esta ADR registra —
duas das três não se resolvem mexendo em número nenhum.

## Causa 1 — o detector de texto invisível não media contraste

A regra era, em duas partes: `luminância do texto ≥ 0,85`, **ou** o char está
sobre um retângulo claro. Sobre boleto funciona, porque boleto não tem fundo
pintado. Num único informe ela acusou **516 chars**, por dois motivos opostos:

- **417 chars pretos**, sinalizados por estarem sobre retângulo claro. A regra
  os condenava qualquer que fosse a cor deles. Preto sobre `#f6f8fa` é o
  contraste máximo, não o mínimo.
- **99 chars brancos**, sinalizados por serem brancos, dentro da faixa
  `#14315c`. Branco sobre azul-escuro também se lê.

Baixar ou subir o 0,85 não resolve nenhum dos dois: a regra não estava mal
calibrada, estava perguntando a coisa errada. O que esconde um texto não é a
cor dele, é a distância entre ela e a do que está pintado embaixo.

### O que impede simplesmente ler o fundo

O pdfplumber reporta o retângulo **antes do recorte**. Uma
`border-bottom: 2px solid #000` do WeasyPrint chega como um retângulo preto
cobrindo a caixa inteira do elemento, não a tira de 2pt efetivamente pintada.
Medido: o cabeçalho de todo boleto tem dois retângulos pretos de 17pt de
altura sob o nome do banco, que é preto. Uma regra que tomasse "o retângulo
mais recente que cobre o char" como fundo faria **todo boleto acusar** — foi
o que aconteceu na primeira tentativa desta correção.

### Decisão

O detector reúne os fundos **possíveis** — a página branca, mais cada
retângulo preenchido que cobre o char — e fica com o **maior contraste** entre
eles. A leitura: se existe alguma pintura plausível sob o texto que o torne
legível, o texto é legível.

O limiar não mudou de valor, mudou de forma: `luminância ≥ 0,85` sobre página
branca **é** `contraste < 0,15`. Sem retângulo, o único candidato é a página, e
boleto se comporta exatamente como antes.

### O que se perde

Erra para o lado de não acusar. Ficam fora do alcance deste detector:

- texto escuro sobre retângulo escuro — que a versão anterior **também** não
  pegava, por só considerar retângulos claros;
- texto branco sobre retângulo branco quando o atacante põe também um
  retângulo escuro cobrindo o mesmo char; um elemento com borda basta.

Os dois caem na divergência texto/imagem, que não pergunta como o texto foi
escondido, só se ele aparece na página renderizada. É o mesmo argumento de
defesa em profundidade que já vale para `opacity: 0` e `Tr 3`. A diferença é
que agora o buraco está medido e escrito, em vez de suposto coberto.

## Causa 2 — `validade` não é o ato de validar

O padrão `dispensa_de_validacao` casava com **"não tem validade fiscal"**, do
rodapé. O trecho `valid` do regex pega `validar`, `validação` e `validade` sem
distinguir, e o gatilho `nao|sem` está a poucos caracteres em qualquer frase de
rodapé.

Não é peculiaridade do corpus sintético. **"Sem validade sem autenticação
mecânica"** está impresso em praticamente todo comprovante bancário brasileiro,
e cairia igual.

A correção é uma exceção de uma palavra: `valid(?!ade)`. `validade` é
substantivo sobre a força legal do documento; `validar`, `validação`, `valide`
são o ato, e continuam casando. Conferido nos dois sentidos: as frases de
rodapé deixam de acusar, e `não é necessário validar a linha digitável` —
a carga real do corpus adversarial da Fase 1 — continua acusando.

Afrouxar o padrão inteiro para calar o rodapé teria cegado o detector; a
exceção é cirúrgica e nomeada.

## Causa 3 — 200 DPI não lê maiúscula de 5,5pt

Sobrando quatro documentos, a divergência texto/imagem acusava blocos como
`NOME DATA ASSINATURA` e o CNPJ da faixa, com **cobertura 0%**.

Cobertura zero não é limiar apertado: é texto não lido. Baixar
`COBERTURA_MINIMA` de 0,30 não mudaria nada, e cegaria o detector de quebra.

Medido nos dois blocos, variando só a resolução:

| DPI | cobertura |
|---|---|
| 200 | 0,000 |
| 300 | 1,000 |
| 400 | 1,000 |

Conferido também que **não era contraste**: inverter a imagem antes do OCR não
muda nada em nenhuma resolução, inclusive no bloco de texto branco sobre fundo
escuro. O tesseract lê claro-sobre-escuro sem ajuda.

`DPI_RENDERIZACAO` passa de 200 para 300.

## Resultado medido

| Corpus | Antes | Depois |
|---|---|---|
| 24 informes limpos | 24 sinalizados | **0** |
| 15 boletos limpos | 0 sinalizados | **0** |
| 28 boletos adversariais | 24 acusados | **24** |

Os 4 adversariais não acusados são os `valor_divergente`, e é assim por
construção: o ataque imprime um valor falso numa página impecável, não deixa
rastro para sanitizador nenhum, e quem o barra é o cruzamento com a linha
digitável (ADR 002). Isso não mudou nesta ADR — foi conferido contra o código
anterior justamente para não confundir recalibração com regressão.

## Consequências

**Positivas**

- O detector de texto invisível passa a medir o que sempre disse medir, e
  funciona em documento com fundo pintado — que é todo extrato bancário.
- O padrão de injeção deixa de acusar prosa de rodapé, sem perder nenhuma
  carga real.
- A divergência texto/imagem passa a ler texto pequeno, que é onde carga
  escondida costuma morar.

**Negativas / custos aceitos**

- O render a 300 DPI custa ~2,25× os pixels de 200. Medido ponta a ponta:
  2,33s por informe e 1,74s por boleto, com OCR. O eval da Fase 2 fica mais
  lento, e o número está aqui para a conta ser feita com dado e não com
  impressão.
- A regra de maior contraste é conservadora por decisão, e a evasão que ela
  admite está descrita acima. Quem depender só deste detector fica exposto;
  quem depender dos três, não.
- Os limiares continuam ancorados em corpus sintético. Dois documentos, agora,
  em vez de um — o que é o começo da resposta à issue #1, não a resposta.
