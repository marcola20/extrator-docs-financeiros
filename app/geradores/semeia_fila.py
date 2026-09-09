"""Popula a fila de revisão com casos sintéticos, para demonstrar a tela.

**Não gasta cota.** O provedor daqui não fala com a API do modelo: ele lê o
gabarito que está ao lado do PDF no corpus sintético e devolve exatamente
aqueles campos, como um extrator perfeito devolveria. Quando um cenário precisa
que a leitura esteja errada — um valor alucinado, um nome trocado —, ele
sobrescreve o campo antes de devolver.

Isso é o que permite gravar um GIF da tela, ou abri-la numa entrevista, sem
consumir as 500 chamadas diárias do tier gratuito e sem depender de o provedor
estar no ar.

## Por que os cenários são estes

A tela existe para tornar visível **como o sistema decide**, e uma fila com
oito documentos parecidos não mostra isso. Os cenários abaixo foram escolhidos
para que cada um caia num quadrante diferente do que a interface tem a dizer:

| Cenário | O que a tela mostra |
|---|---|
| valor alucinado | dois sinais **reprovaram**, com a mensagem do DV apontando a divergência |
| nome trocado | só a auto-consistência pega — nome não tem verificação (issue #2) |
| leitura fiel | auto-aprovado; não entra na fila, e conta nas estatísticas |
| ataque com texto invisível | **trechos suspeitos** com página e coordenadas |
| valor divergente | página impecável; **só a aritmética** o barra |
| par de comprovantes | **sem cobertura**: nada reprovou, e nada foi conferido |
| par bancário | auto-aprovado com cobertura real, que é o contraste do anterior |

O de `valor_divergente` é a tese do projeto num documento só. A página não tem
defeito nenhum que um detector possa ver: nenhum texto escondido, nenhuma
instrução injetada, nada fora do lugar. Ela imprime `R$ 91,01` no campo de valor
enquanto a linha digitável codifica `R$ 9.100,99`, e o extrator **lê a página
certo** — transcrever o que está impresso é o comportamento correto (ADR 006).
O que barra é a aritmética: o valor não fecha com os dez dígitos de centavos
dentro da linha digitável, protegidos por quatro dígitos verificadores. Detecção
por padrão teria deixado passar; o cruzamento pegou.

O sexto é o mais importante da lista. Ele é o caso que o ADR 009 fixou e o
ADR 011 desenhou: um documento lido com 100% de acurácia que vai para a revisão
porque **ninguém conseguiu conferi-lo**. Sem ele na fila, a tela demonstra
metade do que o projeto tem a dizer.

## O OCR fica ligado por padrão, e o motivo não é rigor

Sem a comparação texto/imagem, a política da Fase 1.2 barra **todo** documento —
"os detectores não rodaram, e não achar é diferente de não procurar". A fila
sairia com oito documentos bloqueados pelo mesmo sinal, nenhum auto-aprovado, e
o caso de "sem cobertura" desapareceria no meio. Custa cerca de um segundo e
meio por documento, e é o que faz a demonstração ter contraste.

Uso:
    PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila
    PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --limpar
"""

import argparse
import json
import shutil
import sys
import unicodedata
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.llm.provedor import INSTRUCAO_PADRAO, ResultadoExtracao, UsoDeTokens
from app.persistencia import gravacao
from app.persistencia.modelos import Decisao, TipoDeDocumento
from app.pipeline import processa
from app.pipeline_informe import processa_par

BOLETOS = Path("dados/sinteticos/boletos")
BOLETOS_ADVERSARIAIS = Path("dados/sinteticos/boletos_adversariais")
INFORMES = Path("dados/sinteticos/informes")

TABELAS = ("sinal", "achado", "correcao", "decisao", "extracao", "documento")

CUSTO_SIMULADO = Decimal("0.000500")
"""O que uma extração de boleto custaria, para as estatísticas da tela não
saírem zeradas. Não houve chamada nenhuma — ver a nota do módulo."""

QUADROS = ("rendimentos_tributaveis", "rendimentos_isentos", "rendimentos_exclusivos")

ESCALARES_DO_INFORME = (
    "layout",
    "ano_calendario",
    "exercicio",
    "fonte_pagadora_cnpj",
    "fonte_pagadora_nome",
    "beneficiario_cpf",
    "beneficiario_nome",
)


def _digitos(texto: str) -> str:
    return "".join(c for c in texto if c.isdigit())


def _comparavel(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto.lower())
    return " ".join("".join(c for c in decomposto if not unicodedata.combining(c)).split())


def gabarito_de(pdf: Path) -> dict[str, Any]:
    """Os campos que o gerador sintético imprimiu neste PDF."""
    dados: dict[str, Any] = json.loads(pdf.with_suffix(".json").read_text(encoding="utf-8"))
    campos: dict[str, Any] = dados.get("campos") or dados["extracao_correta"]
    return campos


def _transporte_de_boleto(campos: dict[str, Any]) -> dict[str, Any]:
    """O gabarito do domínio na forma do transporte: tudo texto."""
    return {chave: ("" if valor is None else str(valor)) for chave, valor in campos.items()}


def _transporte_de_informe(campos: dict[str, Any]) -> dict[str, Any]:
    carga: dict[str, Any] = {chave: str(campos[chave]) for chave in ESCALARES_DO_INFORME}
    for nome in QUADROS:
        quadro = campos[nome]
        carga[nome] = {
            "linhas": [
                {
                    "identificador": linha["identificador"],
                    "descricao": linha["descricao"],
                    "valor": str(linha["valor"]),
                }
                for linha in quadro["linhas"]
            ],
            "total_impresso": (
                "" if quadro["total_impresso"] is None else str(quadro["total_impresso"])
            ),
        }
    carga["saldos"] = [
        {
            "especificacao": saldo["especificacao"],
            "saldo_31_12": str(saldo["saldo_31_12"]),
            "saldo_31_12_anterior": str(saldo["saldo_31_12_anterior"]),
        }
        for saldo in campos["saldos"]
    ]
    return carga


@dataclass(frozen=True, slots=True)
class Conhecido:
    """Um documento que o provedor sabe responder, e como reconhecê-lo."""

    pdf: Path
    carga: dict[str, Any]
    digitos_marcadores: str
    """Dígitos que aparecem no texto deste documento e em nenhum outro."""

    marcadores_de_texto: tuple[str, ...] = ()
    """Marcas adicionais, quando os dígitos sozinhos não separam. Basta uma casar.

    Os dois informes de um par têm o mesmo CPF, e o ano-calendário de um aparece
    impresso no outro — na coluna de saldo de 31/12 do ano anterior. O exercício
    só aparece no cabeçalho, e é ele que os separa.

    São várias formas porque os dois layouts imprimem o mesmo campo diferente:
    o comprovante escreve "Exercício **de** 2025" e o informe bancário escreve
    "Exercício 2025". Uma forma só reconheceria metade do corpus.
    """


class ProvedorDeGabarito:
    """Um `ProvedorLLM` que devolve o gabarito, sem chamar API nenhuma.

    Os testes têm dublês próprios, e este não os substitui: os de lá contam
    chamadas e encenam falhas para sustentar asserções, e acoplá-los a um módulo
    de demonstração faria mexer na demo quebrar a suíte. O que os dois têm em
    comum — ler o gabarito e devolvê-lo como transporte — mora aqui, e é daqui
    que o comando de semear o consome.
    """

    def __init__(self, conhecidos: Sequence[Conhecido]) -> None:
        self._conhecidos = list(conhecidos)
        self.chamadas = 0

    @property
    def nome(self) -> str:
        return "gabarito"

    @property
    def modelo(self) -> str:
        return "gabarito-sem-rede"

    def extrai[TSchema: BaseModel](
        self,
        texto: str,
        schema: type[TSchema],
        *,
        instrucao: str = INSTRUCAO_PADRAO,
    ) -> ResultadoExtracao[TSchema]:
        self.chamadas += 1
        conhecido = self._reconhece(texto)
        return ResultadoExtracao(
            dados=schema.model_validate(conhecido.carga),
            provedor=self.nome,
            modelo=self.modelo,
            uso=UsoDeTokens(entrada=900, saida=180),
            custo_estimado_usd=CUSTO_SIMULADO,
        )

    def _reconhece(self, texto: str) -> Conhecido:
        digitos = _digitos(texto)
        comparavel = _comparavel(texto)
        for conhecido in self._conhecidos:
            if conhecido.digitos_marcadores not in digitos:
                continue
            marcas = conhecido.marcadores_de_texto
            if marcas and not any(marca in comparavel for marca in marcas):
                continue
            return conhecido
        raise AssertionError(
            "o texto não corresponde a nenhum documento conhecido; o corpus foi "
            "regerado depois de este comando ser escrito?"
        )


def _conhecido_de_boleto(pdf: Path, sobrescreve: dict[str, str]) -> Conhecido:
    campos = gabarito_de(pdf)
    carga = _transporte_de_boleto(campos)
    carga.update(sobrescreve)
    # A linha digitável tem 47 dígitos e não se repete entre documentos.
    return Conhecido(
        pdf=pdf, carga=carga, digitos_marcadores=_digitos(str(campos["linha_digitavel"]))
    )


def _conhecido_de_informe(pdf: Path) -> Conhecido:
    campos = gabarito_de(pdf)
    return Conhecido(
        pdf=pdf,
        carga=_transporte_de_informe(campos),
        digitos_marcadores=_digitos(str(campos["beneficiario_cpf"])),
        marcadores_de_texto=(
            f"exercicio de {campos['exercicio']}",
            f"exercicio {campos['exercicio']}",
        ),
    )


AbreSessao = Callable[[], AbstractContextManager[Session]]
"""Como abrir uma sessão de banco. Ver a nota de `semeia`."""


def _sessao_padrao() -> AbstractContextManager[Session]:
    from app.persistencia.sessao import sessao

    return sessao()


@dataclass(frozen=True, slots=True)
class CenarioDeBoleto:
    pdf: Path
    rotulo: str
    sobrescreve: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CenarioDeInforme:
    anterior: Path
    atual: Path
    rotulo: str


def _um_adversarial_com_texto_invisivel() -> Path | None:
    """Um documento cujo ataque o sanitizador pega e o revisor não veria."""
    for gabarito in sorted(BOLETOS_ADVERSARIAIS.glob("*.json")):
        dados = json.loads(gabarito.read_text(encoding="utf-8"))
        if "texto_invisivel" in dados["ataque"]["detectores_esperados"]:
            return BOLETOS_ADVERSARIAIS / str(dados["arquivo_pdf"])
    return None


def _um_valor_divergente() -> Path | None:
    """O documento em que a página está impecável e só a aritmética barra.

    Não precisa de `sobrescreve`: o gabarito guarda o que está **impresso**
    (ADR 006), que já é o valor falso. Um extrator perfeito o transcreve, e é
    justamente aí que o cruzamento com a linha digitável reprova.
    """
    for gabarito in sorted(BOLETOS_ADVERSARIAIS.glob("*.json")):
        dados = json.loads(gabarito.read_text(encoding="utf-8"))
        if dados["ataque"]["nome"] == "valor_divergente":
            return BOLETOS_ADVERSARIAIS / str(dados["arquivo_pdf"])
    return None


def cenarios_padrao() -> tuple[list[CenarioDeBoleto], list[CenarioDeInforme]]:
    """Os seis casos da tabela no topo do módulo."""
    boletos = [
        CenarioDeBoleto(
            BOLETOS / "boleto-001.pdf",
            "valor alucinado: o DV e o grounding reprovam",
            {"valor": "99.999,99"},
        ),
        CenarioDeBoleto(
            BOLETOS / "boleto-002.pdf",
            "nome trocado: só a consistência pega (issue #2)",
            {"beneficiario_nome": "Empresa Trocada Ltda"},
        ),
        CenarioDeBoleto(BOLETOS / "boleto-003.pdf", "leitura fiel: auto-aprovado"),
    ]
    atacado = _um_adversarial_com_texto_invisivel()
    if atacado is not None:
        boletos.append(CenarioDeBoleto(atacado, "ataque invisível: trechos suspeitos"))

    divergente = _um_valor_divergente()
    if divergente is not None:
        boletos.append(
            CenarioDeBoleto(divergente, "valor divergente: página limpa, só a aritmética barra")
        )

    informes = [
        CenarioDeInforme(
            INFORMES / "informe-003.pdf",
            INFORMES / "informe-004.pdf",
            "comprovante: sem total e sem saldo, nada foi conferido",
        ),
        CenarioDeInforme(
            INFORMES / "informe-001.pdf",
            INFORMES / "informe-002.pdf",
            "bancário: soma e cruzamento entre anos conferem",
        ),
    ]
    return boletos, informes


def limpa(settings: Settings) -> None:
    """Apaga a fila. Destrutivo, e por isso só acontece com `--limpar`."""
    from sqlalchemy import create_engine, text

    engine = create_engine(settings.database_url)
    with engine.begin() as conexao:
        for tabela in TABELAS:
            conexao.execute(text(f"delete from {tabela}"))


def _semeia_boleto(
    cenario: CenarioDeBoleto, settings: Settings, *, com_ocr: bool, sessao: AbreSessao
) -> tuple[Decisao, str]:
    provedor = ProvedorDeGabarito([_conhecido_de_boleto(cenario.pdf, cenario.sobrescreve)])
    resultado = processa(
        cenario.pdf, provedor, settings, provedor_da_segunda=provedor, com_ocr=com_ocr
    )
    with sessao() as aberta:
        decisao = gravacao.grava(
            aberta,
            caminho=cenario.pdf,
            tipo=TipoDeDocumento.BOLETO,
            ingestao=resultado.ingestao,
            decisao_final=resultado.decisao,
            extracao=resultado.extracao,
            latencia_s=resultado.latencia_s,
        )
    return decisao, cenario.rotulo


def _semeia_par(
    cenario: CenarioDeInforme, settings: Settings, *, com_ocr: bool, sessao: AbreSessao
) -> list[tuple[Decisao, str]]:
    """O informe é processado em par: o cruzamento entre anos precisa dos dois."""
    provedor = ProvedorDeGabarito(
        [_conhecido_de_informe(cenario.anterior), _conhecido_de_informe(cenario.atual)]
    )
    resultados = processa_par(
        cenario.anterior,
        cenario.atual,
        provedor,
        settings,
        provedor_da_segunda=provedor,
        com_ocr=com_ocr,
    )

    gravadas = []
    for caminho, resultado in zip((cenario.anterior, cenario.atual), resultados, strict=True):
        with sessao() as aberta:
            decisao = gravacao.grava(
                aberta,
                caminho=caminho,
                tipo=TipoDeDocumento.INFORME,
                ingestao=resultado.ingestao,
                decisao_final=resultado.decisao,
                extracao=resultado.extracao,
                latencia_s=resultado.latencia_s,
            )
        gravadas.append((decisao, cenario.rotulo))
    return gravadas


def semeia(
    settings: Settings,
    *,
    boletos: Sequence[CenarioDeBoleto],
    informes: Sequence[CenarioDeInforme],
    com_ocr: bool = True,
    sessao: AbreSessao | None = None,
) -> list[tuple[Decisao, str]]:
    """Processa os cenários e grava cada decisão. Devolve o que foi gravado.

    `sessao` entra por parâmetro para o teste poder apontar para um SQLite —
    exigir Postgres de pé para testar este comando contradiria a decisão da
    Fase 4.1 de a persistência ser opcional. Em uso normal ele é omitido.
    """
    abre = sessao if sessao is not None else _sessao_padrao
    gravadas = [_semeia_boleto(c, settings, com_ocr=com_ocr, sessao=abre) for c in boletos]
    for cenario in informes:
        gravadas += _semeia_par(cenario, settings, com_ocr=com_ocr, sessao=abre)
    return gravadas


def _analisa_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.geradores.semeia_fila",
        description=(
            "Popula a fila de revisão com casos sintéticos, para demonstrar a tela. "
            "Não chama a API do modelo: usa o gabarito que está ao lado de cada PDF."
        ),
    )
    parser.add_argument(
        "--limpar",
        action="store_true",
        help="apaga a fila antes de semear. Destrutivo: some com as correções também",
    )
    parser.add_argument(
        "--sem-ocr",
        action="store_true",
        help=(
            "pula a comparação texto/imagem. Mais rápido, e a fila sai sem "
            "contraste: sem ela a sanitização barra todos os documentos e nenhum "
            "chega a ser auto-aprovado"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from app.persistencia.sessao import PersistenciaDesligada

    argumentos = _analisa_argumentos(argv)
    settings = get_settings()

    if not settings.persistencia_ativa:
        print(
            "a persistência está desligada, e sem ela não há fila para povoar.\n"
            "  PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila",
            file=sys.stderr,
        )
        return 1

    com_ocr = not argumentos.sem_ocr
    if com_ocr and shutil.which("tesseract") is None:
        print(
            "tesseract não está instalado. Sem a comparação texto/imagem a "
            "sanitização barra todos os documentos, e a fila sai sem contraste — "
            "seguindo assim mesmo.",
            file=sys.stderr,
        )

    boletos, informes = cenarios_padrao()

    try:
        if argumentos.limpar:
            limpa(settings)
            print("fila apagada")
        gravadas = semeia(settings, boletos=boletos, informes=informes, com_ocr=com_ocr)
    except PersistenciaDesligada as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    for decisao, rotulo in gravadas:
        print(f"  #{decisao.id:<4} {decisao.rota.value:15} {rotulo}")

    na_fila = sum(1 for decisao, _ in gravadas if decisao.rota.value == "revisao_humana")
    print(
        f"\n{len(gravadas)} documento(s): {na_fila} na fila, "
        f"{len(gravadas) - na_fila} auto-aprovado(s)."
    )
    print("A tela está em http://localhost:3001 (docker compose --profile revisao up -d).")
    print("Nenhuma chamada à API do modelo: o provedor leu os gabaritos do corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
