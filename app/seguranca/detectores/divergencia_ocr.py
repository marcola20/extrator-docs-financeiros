"""Detector (c): texto que está na camada do PDF e não aparece na página.

É o detector que não pergunta *como* o texto foi escondido. Renderiza a
página com pypdfium2, lê o resultado com OCR, e compara com a camada de
texto que o pdfplumber entrega. Texto presente na camada e ausente da
imagem é, por definição, invisível para quem revisa — e visível para o
modelo, que lê a camada.

Por isso ele cobre o que o detector de texto invisível não alcança:
`opacity: 0`, modo de renderização invisível (`Tr 3`), texto sob uma imagem
opaca, glifos de largura zero. Nenhum desses chega aos atributos do char.

## A comparação é tolerante, e precisa ser

OCR erra. Troca `1` por `l`, come pontuação, junta e separa palavras. Uma
comparação exata acusaria todo documento honesto.

### Por que não similaridade global

Foi a primeira tentativa e é métrica ruim. Medida sobre os 15 boletos
limpos, a similaridade global entre camada e OCR variou de **0,826 a
0,999** — a diferença entre um documento limpo e outro documento limpo é
maior do que qualquer limiar sensato poderia separar. Ela também não
localiza nada: um número por página não diz ao revisor onde olhar.

### O que se usa

Cobertura de tokens **por bloco**, onde bloco é uma linha da camada de
texto. Para cada token do bloco, pergunta-se se ele aparece no conjunto de
tokens do OCR — igual, ou parecido o bastante para ser o mesmo token lido
com erro. A cobertura do bloco é a fração de tokens encontrados.

Medida em 327 blocos dos 15 boletos limpos, a **pior cobertura foi 0,750**,
e só dois blocos ficaram abaixo de 0,9. O limiar fica em **0,5**: um bloco
só é acusado quando mais da metade dele sumiu no papel. Isso deixa margem
de 50% sobre o pior caso honesto medido, enquanto um bloco injetado
invisível pontua perto de 0,0 — os dois casos não ficam perto um do outro.

Blocos com menos de 3 tokens são ignorados: são rótulos e números soltos,
onde um erro de OCR sozinho já derrubaria a fração.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.seguranca.sanitizador import (
    Achado,
    Local,
    Severidade,
    TipoAchado,
    recorta,
)

DPI_RENDERIZACAO = 200
"""Resolução do render. Medido: 150 já basta, 200 dá folga sem custar muito."""

COBERTURA_MINIMA = 0.5
"""Abaixo disto o bloco sumiu da página. Pior bloco limpo medido: 0,750."""

MIN_TOKENS_NO_BLOCO = 3
"""Bloco menor que isto é rótulo solto; um erro de OCR já o derrubaria."""

SIMILARIDADE_DE_TOKEN = 0.8
"""Quanto dois tokens precisam se parecer para contarem como o mesmo."""

DIFERENCA_MAXIMA_DE_TAMANHO = 2
"""Só compara tokens de tamanho parecido; o resto não vale o custo."""

IDIOMA_PADRAO = "por"
IDIOMA_RESERVA = "eng"

_NAO_ALFANUMERICO = re.compile(r"[^a-z0-9 ]+")
_ESPACOS = re.compile(r"\s+")


class OcrIndisponivel(RuntimeError):
    """Tesseract ou pytesseract não estão utilizáveis neste ambiente."""


def normaliza(texto: str) -> str:
    """Minúsculas, sem acento, sem pontuação, espaços colapsados."""
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return _ESPACOS.sub(" ", _NAO_ALFANUMERICO.sub(" ", sem_acento)).strip()


@dataclass(frozen=True, slots=True)
class Bloco:
    """Uma linha da camada de texto, com onde ela está na página."""

    texto: str
    local: Local


def _mesmo_token(token: str, candidatos: frozenset[str]) -> bool:
    if token in candidatos:
        return True
    return any(
        SequenceMatcher(None, token, outro).ratio() >= SIMILARIDADE_DE_TOKEN
        for outro in candidatos
        if abs(len(outro) - len(token)) <= DIFERENCA_MAXIMA_DE_TAMANHO
    )


def cobertura(bloco: str, tokens_ocr: frozenset[str]) -> float:
    """Fração dos tokens do bloco que aparecem no OCR."""
    tokens = normaliza(bloco).split()
    if not tokens:
        return 1.0
    encontrados = sum(1 for token in tokens if _mesmo_token(token, tokens_ocr))
    return encontrados / len(tokens)


def texto_da_imagem(caminho_pdf: str, pagina_indice: int) -> str:
    """Renderiza a página e devolve o que o OCR lê nela."""
    try:
        import pypdfium2
        import pytesseract
    except ImportError as erro:  # pragma: no cover - ambiente sem OCR
        raise OcrIndisponivel(str(erro)) from erro

    documento = pypdfium2.PdfDocument(caminho_pdf)
    try:
        imagem = documento[pagina_indice].render(scale=DPI_RENDERIZACAO / 72).to_pil()
    finally:
        documento.close()

    for idioma in (IDIOMA_PADRAO, IDIOMA_RESERVA):
        try:
            return str(pytesseract.image_to_string(imagem, lang=idioma))
        except pytesseract.TesseractError:
            continue
        except pytesseract.TesseractNotFoundError as erro:  # pragma: no cover
            raise OcrIndisponivel(str(erro)) from erro
    raise OcrIndisponivel("tesseract não conseguiu processar a página em por nem em eng")


def detecta(blocos: list[Bloco], texto_ocr: str) -> list[Achado]:
    """Acusa os blocos da camada de texto que não aparecem na imagem."""
    tokens_ocr = frozenset(normaliza(texto_ocr).split())

    achados = []
    for bloco in blocos:
        tokens = normaliza(bloco.texto).split()
        if len(tokens) < MIN_TOKENS_NO_BLOCO:
            continue
        fracao = cobertura(bloco.texto, tokens_ocr)
        if fracao >= COBERTURA_MINIMA:
            continue
        achados.append(
            Achado(
                tipo=TipoAchado.DIVERGENCIA_TEXTO_IMAGEM,
                severidade=Severidade.ALTA,
                local=bloco.local,
                trecho=recorta(bloco.texto),
                detalhe=(
                    f"está na camada de texto mas não na página renderizada "
                    f"(cobertura {fracao:.0%}, mínimo {COBERTURA_MINIMA:.0%})"
                ),
            )
        )
    return achados
