"""O que sai da ingestão de um PDF."""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from app.seguranca.sanitizador import ResultadoSanitizacao


class CaminhoDeLeitura(StrEnum):
    """Como o conteúdo do documento chegou até aqui."""

    TEXTO = "texto"
    """O PDF tem camada de texto útil; é ela que vai ao modelo."""

    VISAO = "visao"
    """Sem camada de texto: o documento foi rasterizado em imagens."""


@dataclass(frozen=True, slots=True)
class DocumentoIngerido:
    """Texto, imagens e achados de sanitização, amarrados numa leitura só.

    O amarrado é o ponto do tipo. O sanitizador precisa analisar exatamente o
    que vai ao modelo; se a extração relesse o PDF por conta própria, a defesa
    estaria conferindo um artefato diferente do que está em risco.
    """

    caminho: Path
    leitura: CaminhoDeLeitura
    texto: str
    sanitizacao: ResultadoSanitizacao
    paginas_png: tuple[bytes, ...] = ()
    """Páginas rasterizadas. Vazio no caminho de texto."""

    aviso: str | None = None
    metadados: dict[str, str] = field(default_factory=dict)

    @property
    def por_visao(self) -> bool:
        return self.leitura is CaminhoDeLeitura.VISAO

    @property
    def sanitizacao_teve_cobertura(self) -> bool:
        """Se os detectores tiveram material para inspecionar.

        No caminho de visão isto é sempre falso: os três detectores da Fase
        1.2 operam sobre a camada de texto, e ela não existe. Ver ADR 005.
        """
        return self.sanitizacao.houve_o_que_inspecionar
