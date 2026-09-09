"""Os casos da demonstração pública, apresentados por situação.

## Por que uma página antes da fila

A fila lista arquivos, e `adversarial-014.pdf` não diz nada a quem abre o link
pela primeira vez. Quem chega de fora não vem procurar um documento: vem ver o
sistema decidir. A entrada apresenta cada caso pela **situação** que ele
demonstra — uma frase — e o clique leva direto ao diagnóstico daquele documento.

Os cinco cobrem os quadrantes que a interface tem a dizer, e nenhum é
redundante: dois em que um sinal reprovou por motivos opostos, um em que o
sanitizador achou o que o revisor não veria, um em que **nada** reprovou e
ninguém conseguiu conferir, e um em que deu certo.

## Um lugar só para "qual PDF é qual"

Três dos cinco não têm nome fixo. O corpus adversarial numera os arquivos na
ordem em que o lote foi gerado, e regerar com outra semente troca os números —
o que é legítimo (ver "Corpus reproduzível" no CLAUDE.md) e quebraria qualquer
caminho literal escrito à mão. Localizá-los é ler o gabarito ao lado do PDF e
procurar a família do ataque.

Isso mora aqui, e não em dois lugares, porque quem **semeia** a fila e quem
**apresenta** os casos precisam concordar sobre qual arquivo é qual. Um caso
apontando para um PDF que o semeador não processou vira link para uma página que
não existe. `tests/test_demo.py` é a trava.

## Este módulo não importa o pipeline

Ele é importado pela API, e a API não processa documento — é a decisão da
Fase 4.1, e é o que mantém a imagem enxuta. Só stdlib aqui: um import de
`pdfplumber` nesta linha faria a API carregar a metade do projeto que ela existe
para não carregar.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BOLETOS = Path("dados/sinteticos/boletos")
BOLETOS_ADVERSARIAIS = Path("dados/sinteticos/boletos_adversariais")
INFORMES = Path("dados/sinteticos/informes")
INFORMES_ADVERSARIAIS = Path("dados/sinteticos/informes_adversariais")

BOLETO_ALUCINADO = BOLETOS / "boleto-001.pdf"
"""O modelo lê `99.999,99` onde a página imprime outro valor. Leitura errada."""

BOLETO_NOME_TROCADO = BOLETOS / "boleto-002.pdf"
"""Nome do beneficiário trocado: o único campo sem verificação forte (issue #2)."""

BOLETO_LIMPO = BOLETOS / "boleto-003.pdf"
"""Leitura fiel, nenhum achado, cobertura completa. O contraste dos outros."""


def _gabarito(pdf: Path) -> dict[str, Any]:
    dados: dict[str, Any] = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    return dados


def _procura(diretorio: Path, aceita: Callable[[dict[str, Any]], bool]) -> Path | None:
    """O primeiro documento do lote cujo gabarito satisfaz `aceita`.

    Ordenado por nome para a escolha não depender da ordem do sistema de
    arquivos: dois ambientes precisam demonstrar o mesmo documento.
    """
    for gabarito in sorted(diretorio.glob("*.json")):
        dados = json.loads(gabarito.read_text(encoding="utf-8"))
        if aceita(dados):
            return diretorio / str(dados["arquivo_pdf"])
    return None


def por_familia_de_ataque(diretorio: Path, familia: str) -> Path | None:
    """O documento **atacado** por esta família.

    Num par adversarial de informes só um dos dois carrega o ataque, e é ele que
    tem a chave `ataque` no gabarito. O outro é o documento honesto do par.
    """
    return _procura(diretorio, lambda d: (d.get("ataque") or {}).get("nome") == familia)


def por_detector_esperado(diretorio: Path, detector: str) -> Path | None:
    """O documento cujo ataque este detector do sanitizador deve pegar."""
    return _procura(
        diretorio, lambda d: detector in (d.get("ataque") or {}).get("detectores_esperados", ())
    )


def por_layout(diretorio: Path, layout: str, papel: str = "ano") -> Path | None:
    """O documento de um layout de informe, pelo papel dele no par.

    Localizar por layout, e não por número, porque qual par saiu de qual layout
    depende da semente do lote.
    """
    return _procura(
        diretorio, lambda d: d.get("layout") == layout and d.get("par", {}).get("papel") == papel
    )


def par_de(pdf: Path) -> tuple[Path, Path]:
    """O par a que este informe pertence, na ordem (ano anterior, ano).

    A ordem importa: o cruzamento entre anos compara o saldo de 31/12 declarado
    por um com o saldo de 31/12 do ano anterior declarado pelo outro, e inverter
    os dois compararia números que não têm por que bater.
    """
    par = _gabarito(pdf)["par"]
    outro = pdf.parent / str(par["arquivo_do_par"])
    return (outro, pdf) if par["papel"] == "ano" else (pdf, outro)


Localizador = Callable[[], Path | None]
"""Como achar o PDF de um caso. `None` quando o corpus não tem o documento."""


@dataclass(frozen=True, slots=True)
class Caso:
    """Uma situação que a demonstração apresenta, e o documento que a mostra."""

    chave: str
    titulo: str
    frase: str
    """Uma frase, no indicativo, dizendo o que este documento tem de interessante.

    Não é o nome do arquivo nem o nome da família de ataque: é a situação, para
    quem nunca viu o projeto entender o que vai abrir antes de clicar."""

    localiza: Localizador

    @property
    def arquivo(self) -> Path | None:
        return self.localiza()


CASOS: tuple[Caso, ...] = (
    Caso(
        chave="valor_adulterado",
        titulo="Boleto com valor adulterado",
        frase=(
            "A página parece impecável e a extração está correta — transcrever o "
            "que está impresso é o comportamento certo. Só a linha digitável "
            "desmente."
        ),
        localiza=lambda: por_familia_de_ataque(BOLETOS_ADVERSARIAIS, "valor_divergente"),
    ),
    Caso(
        chave="saldo_trocado",
        titulo="Informe com saldo do ano anterior trocado",
        frase=(
            "O documento fecha em tudo: DVs corretos, somas batendo, nada "
            "escondido. Só o informe do ano passado desmente."
        ),
        localiza=lambda: por_familia_de_ataque(INFORMES_ADVERSARIAIS, "saldo_anterior_adulterado"),
    ),
    Caso(
        chave="instrucao_invisivel",
        titulo="Boleto com instrução invisível",
        frase="Texto que o extrator lê e o humano não vê, com a página e as coordenadas.",
        localiza=lambda: por_detector_esperado(BOLETOS_ADVERSARIAIS, "texto_invisivel"),
    ),
    Caso(
        chave="sem_cobertura",
        titulo="Comprovante sem cobertura",
        frase=(
            "Nada reprovou, e ninguém conseguiu conferir. O modelo oficial não "
            "imprime total nesses quadros, e sem total não há o que somar."
        ),
        localiza=lambda: por_layout(INFORMES, "fonte_pagadora"),
    ),
    Caso(
        chave="limpo",
        titulo="Boleto limpo, auto-aprovado",
        frase="Como é quando dá certo: os quatro sinais rodaram e os quatro aprovaram.",
        localiza=lambda: BOLETO_LIMPO if BOLETO_LIMPO.is_file() else None,
    ),
)
