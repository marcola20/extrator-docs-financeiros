"""Detector (a): texto que o pdfplumber lê e o olho humano não vê.

Três mecanismos, todos medidos sobre os `chars` do pdfplumber:

- **cor quase igual ao fundo** — branco sobre branco e variações;
- **fonte minúscula** — tamanho abaixo do que é legível impresso;
- **texto fora da página** — coordenadas fora da caixa recortada.

## O que este detector não pega, e por quê

**Opacidade zero.** Um `opacity: 0` no CSS vira `ExtGState` com alpha 0 no
PDF, e o pdfplumber não expõe alpha nenhum: o char sai com `size` e
`non_stroking_color` idênticos aos do texto normal. Medido — um parágrafo
transparente e um parágrafo preto comum produzem chars indistinguíveis.

**Modo de renderização invisível** (`Tr 3`), o mesmo truque das camadas de
OCR sobre digitalização, tem o mesmo problema: não chega ao char.

Os dois caem no detector de divergência texto/imagem, que não pergunta como
o texto foi escondido — só se ele aparece na página renderizada. É o
argumento de defesa em profundidade valendo na prática: um detector cobre o
que o outro não alcança.

## Limiares

Ancorados no corpus sintético limpo, não escolhidos no chute:

- **Contraste.** O texto legítimo mais claro nos 15 boletos é cinza 0,4, que
  sobre página branca dá contraste 0,6. O limiar fica em 0,15: menor que
  qualquer contraste legítimo do corpus, e maior que o de qualquer par
  texto/fundo que o olho não separa.
- **Tamanho.** O menor tamanho legítimo é 5,5pt (rodapé e rótulos de campo).
  O limiar fica em 3,0pt: menor que qualquer texto real do corpus, e muito
  maior que os ~0,4pt que um ataque usa para sumir.

## Por que contraste, e não luminância do texto

A primeira versão perguntava se o texto era claro — `luminância ≥ 0,85` — e,
separadamente, se ele estava sobre um retângulo claro. Para boleto funciona:
boleto não tem fundo pintado. Para informe, não. A medição no corpus limpo de
informes acusou **516 chars em falso positivo num único documento**, por duas
causas opostas que a mesma regra produz:

- 417 chars **pretos** sinalizados por estarem sobre um retângulo claro — a
  regra os condenava qualquer que fosse a cor deles. Preto sobre `#f6f8fa` é
  o contraste máximo, não o mínimo.
- 99 chars **brancos** sinalizados por serem brancos, dentro de uma faixa azul
  escura. Branco sobre `#14315c` também se lê perfeitamente.

Nenhuma das duas some mexendo no 0,85: a regra não estava mal calibrada, estava
perguntando a coisa errada. O que esconde um texto não é a cor dele, é a
distância entre ela e a do que está pintado embaixo.

## O fundo não é legível com precisão, e a regra é conservadora por isso

Ler o fundo do PDF tem um limite que precisa ficar escrito. O pdfplumber
reporta o **retângulo antes do recorte**: uma `border-bottom: 2px solid #000`
do WeasyPrint chega aqui como um retângulo preto cobrindo a caixa inteira do
elemento, e não a tira de 2pt que foi de fato pintada. Medido no boleto: o
cabeçalho tem dois retângulos pretos de 17pt de altura por baixo do nome do
banco, que é preto. Tratá-los como fundo faria todo boleto acusar.

Então o detector não escolhe *um* fundo. Ele reúne os candidatos — a página
branca, mais cada retângulo preenchido que cobre o char — e fica com o
**maior contraste** entre eles. A leitura é: se existe alguma pintura plausível
sob o texto que o torne legível, o texto é legível. Erra para o lado de não
acusar, que é o lado certo — falso positivo manda documento honesto para a
fila de revisão, e a defesa tem outros dois detectores.

O número não mudou: `luminância ≥ 0,85` sobre página branca **é** contraste
abaixo de 0,15, e sem retângulo o único candidato é a página. Boleto se
comporta exatamente como antes.

**O que esta regra não pega**, e passa a ser responsabilidade da divergência
texto/imagem: texto escuro sobre retângulo escuro, e texto branco sobre
retângulo branco quando o atacante põe também um retângulo escuro cobrindo o
mesmo char — um elemento com borda basta. A versão anterior não pegava o
primeiro caso de jeito nenhum, então isto não é perda; é um buraco que agora
está medido e escrito.
"""

from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import Any

from app.seguranca.sanitizador import (
    Achado,
    Local,
    Severidade,
    TipoAchado,
    recorta,
)

CONTRASTE_MINIMO = 0.15
"""Abaixo disto o texto não se separa do fundo que está sob ele.

É o mesmo número da versão anterior, dita de outro jeito: `luminância ≥ 0,85`
sobre página branca é exatamente `1,0 - luminância < 0,15`. Ancorado no corpus
limpo de boletos, onde o pior contraste legítimo é 0,6 (cinza 0,4 no branco).
"""

LUMINANCIA_DA_PAGINA = 1.0
"""O fundo quando não há retângulo pintado sob o texto: papel branco."""

TAMANHO_MINIMO_PT = 3.0
"""Abaixo disto nenhum texto legítimo do corpus existe."""

MARGEM_FORA_DA_PAGINA_PT = 2.0
"""Folga antes de considerar um char fora da caixa, para erro de arredondamento."""

MIN_CHARS_PARA_ACHADO = 3
"""Um char solto invisível é ruído de renderização; três já são um texto."""

# Pesos de luminância perceptual (Rec. 709). Cinza puro dá o próprio valor.
_PESO_R, _PESO_G, _PESO_B = 0.2126, 0.7152, 0.0722


def luminancia(cor: Any) -> float | None:
    """Converte a cor de preenchimento do pdfplumber em luminância 0..1.

    O pdfplumber devolve o que estava no espaço de cor do PDF: 1 número para
    cinza, 3 para RGB, 4 para CMYK — ou None quando não há cor explícita.
    Devolve None quando não dá para decidir, e nesse caso não se acusa nada.
    """
    if cor is None:
        return None
    if isinstance(cor, int | float):
        return _limita(float(cor))
    if not isinstance(cor, Sequence) or isinstance(cor, str | bytes):
        return None

    valores = [float(v) for v in cor if isinstance(v, int | float)]
    if len(valores) != len(cor):
        return None

    match valores:
        case [cinza]:
            return _limita(cinza)
        case [r, g, b]:
            return _limita(_PESO_R * r + _PESO_G * g + _PESO_B * b)
        case [c, m, y, k]:
            return _limita(
                _PESO_R * (1 - c) * (1 - k)
                + _PESO_G * (1 - m) * (1 - k)
                + _PESO_B * (1 - y) * (1 - k)
            )
        case _:
            return None


def _limita(valor: float) -> float:
    return min(1.0, max(0.0, valor))


def junta_texto(chars: Sequence[dict[str, Any]]) -> str:
    """Remonta o texto do bloco, repondo os espaços.

    O PDF nem sempre grava o espaço como caractere: ele costuma virar um
    salto de posição. Sem repor, o trecho chega ao revisor como uma palavra
    só, ilegível justamente quando ele mais precisa ler.
    """
    if not chars:
        return ""
    partes = [str(chars[0].get("text", ""))]
    for anterior, atual in pairwise(chars):
        vao = float(atual["x0"]) - float(anterior["x1"])
        if vao > float(anterior.get("size", 10.0)) * 0.2:
            partes.append(" ")
        partes.append(str(atual.get("text", "")))
    return "".join(partes)


def _local(chars: Sequence[dict[str, Any]], pagina: int) -> Local:
    return Local(
        pagina=pagina,
        x0=min(float(c["x0"]) for c in chars),
        topo=min(float(c["top"]) for c in chars),
        x1=max(float(c["x1"]) for c in chars),
        base=max(float(c["bottom"]) for c in chars),
    )


def _agrupa_vizinhos(
    chars: Sequence[dict[str, Any]], distancia_max: float = 25.0
) -> list[list[dict[str, Any]]]:
    """Junta chars próximos em blocos, para o achado ser uma frase e não uma letra."""
    if not chars:
        return []
    ordenados = sorted(chars, key=lambda c: (round(float(c["top"]), 1), float(c["x0"])))
    blocos: list[list[dict[str, Any]]] = [[ordenados[0]]]
    for char in ordenados[1:]:
        anterior = blocos[-1][-1]
        mesma_linha = abs(float(char["top"]) - float(anterior["top"])) < 3.0
        perto = float(char["x0"]) - float(anterior["x1"]) < distancia_max
        if mesma_linha and perto:
            blocos[-1].append(char)
        else:
            blocos.append([char])
    return blocos


def _cobre(rect: dict[str, Any], char: dict[str, Any]) -> bool:
    return (
        float(rect["x0"]) <= float(char["x0"])
        and float(rect["x1"]) >= float(char["x1"])
        and float(rect["top"]) <= float(char["top"])
        and float(rect["bottom"]) >= float(char["bottom"])
    )


def fundos_possiveis(char: dict[str, Any], rects: Iterable[dict[str, Any]]) -> list[float]:
    """Luminâncias que podem estar sob o char: a página e cada retângulo que o cobre.

    Plural de propósito. O retângulo do pdfplumber vem sem o recorte que o PDF
    aplica, então a presença de um retângulo cobrindo o char é indício de
    pintura, não prova — ver a nota do módulo.
    """
    candidatos = [LUMINANCIA_DA_PAGINA]
    for rect in rects:
        if not rect.get("fill", True):
            continue
        if _cobre(rect, char) and (lum := luminancia(rect.get("non_stroking_color"))) is not None:
            candidatos.append(lum)
    return candidatos


def contraste(char: dict[str, Any], rects: Iterable[dict[str, Any]]) -> float | None:
    """O maior contraste entre o texto e algum fundo plausível sob ele, de 0 a 1."""
    lum = luminancia(char.get("non_stroking_color"))
    if lum is None:
        return None
    return max(abs(lum - fundo) for fundo in fundos_possiveis(char, rects))


def detecta(
    chars: Sequence[dict[str, Any]],
    *,
    pagina: int,
    caixa: tuple[float, float, float, float],
    rects: Sequence[dict[str, Any]] = (),
) -> list[Achado]:
    """Procura texto invisível nos chars de uma página."""
    achados: list[Achado] = []

    quase_invisiveis = [
        c
        for c in chars
        if (medido := contraste(c, rects)) is not None
        and medido < CONTRASTE_MINIMO
        and str(c.get("text", "")).strip()
    ]
    achados += _achados_de(
        quase_invisiveis,
        pagina=pagina,
        tipo=TipoAchado.TEXTO_QUASE_INVISIVEL,
        detalhe=f"contraste com o fundo abaixo de {CONTRASTE_MINIMO}",
    )

    minusculos = [
        c
        for c in chars
        if float(c.get("size", 0.0)) < TAMANHO_MINIMO_PT and str(c.get("text", "")).strip()
    ]
    achados += _achados_de(
        minusculos,
        pagina=pagina,
        tipo=TipoAchado.FONTE_MINUSCULA,
        detalhe=f"fonte abaixo de {TAMANHO_MINIMO_PT}pt",
    )

    x0_pag, topo_pag, x1_pag, base_pag = caixa
    fora = [
        c
        for c in chars
        if str(c.get("text", "")).strip()
        and (
            float(c["x1"]) < x0_pag + MARGEM_FORA_DA_PAGINA_PT
            or float(c["x0"]) > x1_pag - MARGEM_FORA_DA_PAGINA_PT
            or float(c["bottom"]) < topo_pag + MARGEM_FORA_DA_PAGINA_PT
            or float(c["top"]) > base_pag - MARGEM_FORA_DA_PAGINA_PT
        )
    ]
    achados += _achados_de(
        fora,
        pagina=pagina,
        tipo=TipoAchado.TEXTO_FORA_DA_PAGINA,
        detalhe="texto posicionado fora da área visível da página",
    )

    return achados


def _achados_de(
    chars: Sequence[dict[str, Any]],
    *,
    pagina: int,
    tipo: TipoAchado,
    detalhe: str,
) -> list[Achado]:
    achados = []
    for bloco in _agrupa_vizinhos(chars):
        texto = junta_texto(bloco).strip()
        if len(bloco) < MIN_CHARS_PARA_ACHADO or not texto:
            continue
        achados.append(
            Achado(
                tipo=tipo,
                severidade=Severidade.ALTA,
                local=_local(bloco, pagina),
                trecho=recorta(texto),
                detalhe=detalhe,
            )
        )
    return achados
