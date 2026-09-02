"""Detector (b): padrões de prompt injection no texto extraído.

Os padrões vivem em `padroes_injecao.toml`, versionado ao lado deste módulo.
Ficam fora do código porque mudam por outro motivo e em outro ritmo: um
padrão novo é conhecimento sobre ataques, não mudança de lógica.

## O limite deste detector, dito de frente

Isto é uma lista de coisas já vistas. Não é um classificador, não generaliza,
e qualquer ataque pode ser reescrito para escapar: outra língua, sinônimo,
paráfrase, codificação. **Achado aqui é sinal; ausência de achado não é
atestado de nada.** É a razão de o resultado nunca virar aprovação
automática, só encaminhamento para revisão. Ver ADR 004.
"""

import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.seguranca.sanitizador import (
    Achado,
    Local,
    Severidade,
    TipoAchado,
    recorta,
)

ARQUIVO_PADROES = Path(__file__).parent.parent / "padroes_injecao.toml"

CONTEXTO_CHARS = 70
"""Quanto de texto ao redor do casamento vai no trecho, para o revisor situar."""


@dataclass(frozen=True, slots=True)
class PadraoInjecao:
    """Um padrão de ataque conhecido."""

    nome: str
    severidade: Severidade
    descricao: str
    regex: re.Pattern[str]


def normaliza(texto: str) -> str:
    """Minúsculas e sem acento, preservando as posições o máximo possível.

    A remoção de acento usa NFKD e descarta as combinantes; como cada
    combinante é um code point separado, o índice do casamento no texto
    normalizado não bate com o do original quando há acento. Por isso o
    trecho do achado é recortado do texto normalizado, não do bruto.
    """
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def carrega_padroes(arquivo: Path = ARQUIVO_PADROES) -> tuple[PadraoInjecao, ...]:
    """Lê os padrões do TOML versionado."""
    bruto = tomllib.loads(arquivo.read_text(encoding="utf-8"))
    padroes = []
    for item in bruto.get("padrao", []):
        padroes.append(
            PadraoInjecao(
                nome=item["nome"],
                severidade=Severidade(item["severidade"]),
                descricao=item["descricao"],
                regex=re.compile(item["regex"], re.IGNORECASE | re.MULTILINE),
            )
        )
    if not padroes:
        raise ValueError(f"{arquivo} não tem nenhum padrão")
    return tuple(padroes)


def detecta(
    texto: str,
    *,
    pagina: int = 1,
    padroes: tuple[PadraoInjecao, ...] | None = None,
) -> list[Achado]:
    """Procura os padrões conhecidos no texto de uma página."""
    lista = padroes if padroes is not None else carrega_padroes()
    normalizado = normaliza(texto)

    achados = []
    for padrao in lista:
        for casamento in padrao.regex.finditer(normalizado):
            inicio = max(0, casamento.start() - CONTEXTO_CHARS)
            fim = min(len(normalizado), casamento.end() + CONTEXTO_CHARS)
            tipo = (
                TipoAchado.DELIMITADOR_FALSO
                if padrao.nome in ("delimitador_falso", "cerca_de_bloco", "marcador_de_turno")
                else TipoAchado.PADRAO_DE_INJECAO
            )
            achados.append(
                Achado(
                    tipo=tipo,
                    severidade=padrao.severidade,
                    local=Local(pagina=pagina),
                    trecho=recorta(normalizado[inicio:fim]),
                    detalhe=f"{padrao.nome}: {padrao.descricao}",
                )
            )
    return achados
