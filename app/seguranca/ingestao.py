"""Leitura de um PDF não confiável: texto e achados, numa passagem só.

## Por que texto e achados saem juntos

O sanitizador precisa analisar **exatamente o texto que irá ao modelo**. Se
a extração usasse uma leitura e o sanitizador outra — outro filtro, outro
recorte, outra versão da página — abriria uma fresta em que existe texto que
o modelo vê e o sanitizador não olhou. Seria uma defesa conferindo um
artefato diferente do que está em risco.

Então a ingestão é o único ponto que abre o PDF, e devolve os dois lados da
mesma leitura amarrados no `ResultadoSanitizacao`.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pdfplumber

from app.seguranca.detectores import divergencia_ocr, padroes, texto_invisivel
from app.seguranca.detectores.divergencia_ocr import Bloco, OcrIndisponivel
from app.seguranca.sanitizador import (
    Achado,
    Local,
    ResultadoSanitizacao,
)

DETECTOR_TEXTO_INVISIVEL = "texto_invisivel"
DETECTOR_PADROES = "padroes"
DETECTOR_DIVERGENCIA_OCR = "divergencia_ocr"


TOLERANCIA_DE_LINHA_PT = 3.0
VARIACAO_DE_TAMANHO = 0.2


def _blocos_da_pagina(pagina: pdfplumber.page.Page, numero: int) -> list[Bloco]:
    """Divide a página em blocos homogêneos de estilo, para a comparação com o OCR.

    Não dá para usar as linhas do `extract_text_lines` direto. Um texto
    injetado em 0,3pt cai na mesma coordenada vertical de um texto legítimo
    de 13pt, e o pdfplumber junta os dois na mesma linha — medido: a carga de
    um documento adversarial saiu grudada no nome do banco, `"IBMPORTANTE:
    ignore as instruções..."`. O bloco resultante mistura texto que aparece
    na página com texto que não aparece, e a fração de cobertura fica diluída
    no meio do caminho, sem acusar nem inocentar.

    Então o bloco aqui é uma corrida de chars na mesma linha **e com o mesmo
    estilo**: muda o tamanho da fonte ou a cor, começa outro bloco. É o que
    separa o injetado do legítimo antes de medir.
    """
    chars = sorted(
        (c for c in pagina.chars if str(c.get("text", "")).strip()),
        key=lambda c: (round(float(c["top"]), 1), float(c["x0"])),
    )
    if not chars:
        return []

    grupos: list[list[dict[str, Any]]] = [[chars[0]]]
    for char in chars[1:]:
        anterior = grupos[-1][-1]
        mesma_linha = abs(float(char["top"]) - float(anterior["top"])) < TOLERANCIA_DE_LINHA_PT
        tamanho_anterior = float(anterior.get("size", 0.0)) or 1.0
        mesmo_tamanho = (
            abs(float(char.get("size", 0.0)) - tamanho_anterior) / tamanho_anterior
            < VARIACAO_DE_TAMANHO
        )
        mesma_cor = char.get("non_stroking_color") == anterior.get("non_stroking_color")
        if mesma_linha and mesmo_tamanho and mesma_cor:
            grupos[-1].append(char)
        else:
            grupos.append([char])

    blocos = []
    for grupo in grupos:
        texto = texto_invisivel.junta_texto(grupo).strip()
        if not texto:
            continue
        blocos.append(
            Bloco(
                texto=texto,
                local=Local(
                    pagina=numero,
                    x0=min(float(c["x0"]) for c in grupo),
                    topo=min(float(c["top"]) for c in grupo),
                    x1=max(float(c["x1"]) for c in grupo),
                    base=max(float(c["bottom"]) for c in grupo),
                ),
            )
        )
    return blocos


def sanitiza(
    caminho: Path,
    *,
    com_ocr: bool = True,
    padroes_carregados: Sequence[padroes.PadraoInjecao] | None = None,
) -> ResultadoSanitizacao:
    """Extrai o texto do PDF e roda os três detectores sobre ele.

    Com `com_ocr=False` o detector de divergência é pulado — ele custa cerca
    de um segundo por página e nem todo ambiente tem tesseract. O resultado
    registra quais detectores rodaram, para ninguém confundir "não achou" com
    "não procurou".
    """
    lista_padroes = (
        tuple(padroes_carregados) if padroes_carregados is not None else padroes.carrega_padroes()
    )

    achados: list[Achado] = []
    partes_do_texto: list[str] = []
    executados = {DETECTOR_TEXTO_INVISIVEL, DETECTOR_PADROES}

    with pdfplumber.open(caminho) as pdf:
        paginas = list(pdf.pages)
        for indice, pagina in enumerate(paginas):
            numero = indice + 1
            texto_da_pagina = pagina.extract_text() or ""
            partes_do_texto.append(texto_da_pagina)

            achados += texto_invisivel.detecta(
                pagina.chars,
                pagina=numero,
                caixa=pagina.bbox,
                rects=pagina.rects,
            )
            achados += padroes.detecta(texto_da_pagina, pagina=numero, padroes=lista_padroes)

            if com_ocr:
                blocos = _blocos_da_pagina(pagina, numero)
                try:
                    lido = divergencia_ocr.texto_da_imagem(str(caminho), indice)
                except OcrIndisponivel:
                    # Sem OCR o documento não fica "limpo": fica sem esse
                    # detector, e o resultado diz isso.
                    com_ocr = False
                else:
                    executados.add(DETECTOR_DIVERGENCIA_OCR)
                    achados += divergencia_ocr.detecta(blocos, lido)

    return ResultadoSanitizacao(
        documento=caminho,
        texto="\n".join(partes_do_texto),
        achados=tuple(achados),
        detectores_executados=frozenset(executados),
    )
