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
| par com saldo trocado | **só o cruzamento entre anos** reprova; os outros cinco conferem |

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

O oitavo é o único ataque do projeto que um adversário com controle da página
não consegue satisfazer sozinho. Nada no documento denuncia o saldo trocado —
medido: sanitização, domínio, aritmética e grounding dizem `conferido`, e só o
cruzamento reprova, comparando com um informe emitido em outro momento.

## O OCR fica ligado por padrão, e o motivo não é rigor

Sem a comparação texto/imagem, a política da Fase 1.2 barra **todo** documento —
"os detectores não rodaram, e não achar é diferente de não procurar". A fila
sairia com oito documentos bloqueados pelo mesmo sinal, nenhum auto-aprovado, e
o caso de "sem cobertura" desapareceria no meio. Custa cerca de um segundo e
meio por documento, e é o que faz a demonstração ter contraste.

Uso:
    PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila
    PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --limpar
    PERSISTENCIA_ATIVA=1 uv run python -m app.geradores.semeia_fila --se-vazia
"""

import argparse
import json
import shutil
import sys
import time
import unicodedata
from collections.abc import Callable, Container, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.demo import (
    BOLETO_ALUCINADO,
    BOLETO_LIMPO,
    BOLETO_NOME_TROCADO,
    BOLETOS_ADVERSARIAIS,
    CASOS,
    INFORMES,
    INFORMES_ADVERSARIAIS,
    par_de,
    por_detector_esperado,
    por_familia_de_ataque,
    por_layout,
)
from app.llm.provedor import INSTRUCAO_PADRAO, ResultadoExtracao, UsoDeTokens
from app.persistencia import gravacao
from app.persistencia.modelos import Decisao, Documento, TipoDeDocumento
from app.pipeline import processa
from app.pipeline_informe import processa_par

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


def _par(pdf: Path | None, rotulo: str) -> list[CenarioDeInforme]:
    """Um cenário de par, ou nenhum, quando o corpus não tem o documento.

    O informe é processado aos pares desde a Fase 2.1 — o cruzamento entre anos
    precisa dos dois —, e o gabarito de cada um aponta para o outro.
    """
    if pdf is None:
        return []
    anterior, atual = par_de(pdf)
    return [CenarioDeInforme(anterior, atual, rotulo)]


def cenarios_padrao() -> tuple[list[CenarioDeBoleto], list[CenarioDeInforme]]:
    """Os cenários da tabela no topo do módulo.

    Os adversariais são localizados pela família do ataque, e não pelo número do
    arquivo: regerar o lote com outra semente troca os números, e um caminho
    literal aqui passaria a apontar para outro documento em silêncio. Quem sabe
    achá-los é o `app.demo`, que é o mesmo módulo que a página de entrada lê —
    de propósito, para os dois não discordarem sobre qual arquivo é qual.
    """
    boletos = [
        CenarioDeBoleto(
            BOLETO_ALUCINADO,
            "valor alucinado: o DV e o grounding reprovam",
            {"valor": "99.999,99"},
        ),
        CenarioDeBoleto(
            BOLETO_NOME_TROCADO,
            "nome trocado: só a consistência pega (issue #2)",
            {"beneficiario_nome": "Empresa Trocada Ltda"},
        ),
        CenarioDeBoleto(BOLETO_LIMPO, "leitura fiel: auto-aprovado"),
    ]
    atacado = por_detector_esperado(BOLETOS_ADVERSARIAIS, "texto_invisivel")
    if atacado is not None:
        boletos.append(CenarioDeBoleto(atacado, "ataque invisível: trechos suspeitos"))

    # Sem `sobrescreve`: o gabarito guarda o que está **impresso** (ADR 006), que
    # já é o valor falso. Um extrator perfeito o transcreve, e é justamente aí
    # que o cruzamento com a linha digitável reprova.
    divergente = por_familia_de_ataque(BOLETOS_ADVERSARIAIS, "valor_divergente")
    if divergente is not None:
        boletos.append(
            CenarioDeBoleto(divergente, "valor divergente: página limpa, só a aritmética barra")
        )

    informes = (
        _par(
            por_layout(INFORMES, "fonte_pagadora"),
            "comprovante: sem total e sem saldo, nada foi conferido",
        )
        + _par(
            por_layout(INFORMES, "instituicao_financeira"),
            "bancário: soma e cruzamento entre anos conferem",
        )
        + _par(
            por_familia_de_ataque(INFORMES_ADVERSARIAIS, "saldo_anterior_adulterado"),
            "saldo do ano anterior trocado: só o cruzamento entre anos reprova",
        )
    )
    return boletos, informes


def arquivos_com_decisao(sessao: AbreSessao | None = None) -> set[str]:
    """Os caminhos que já têm decisão gravada.

    É o estado contra o qual `--completar` decide o que ainda falta. Por
    **arquivo**, e não um booleano para a fila inteira: uma semeadura
    interrompida no meio — o contêiner ficou sem memória, a instância foi
    reciclada — deixa parte dos documentos gravados, e um "a fila não está
    vazia" trataria isso como trabalho concluído. A demo ficaria pela metade em
    silêncio, e o defeito só apareceria para quem abrisse o link e não achasse
    um caso.
    """
    abre = sessao if sessao is not None else _sessao_padrao
    with abre() as aberta:
        return set(
            aberta.scalars(
                select(Documento.arquivo).join(Decisao, Decisao.documento_id == Documento.id)
            )
        )


def _arquivos_de(cenario: "CenarioDeBoleto | CenarioDeInforme") -> tuple[Path, ...]:
    """Os documentos que este cenário grava. Um para boleto, dois para o par."""
    if isinstance(cenario, CenarioDeBoleto):
        return (cenario.pdf,)
    return (cenario.anterior, cenario.atual)


def pendentes(
    boletos: Sequence[CenarioDeBoleto],
    informes: Sequence[CenarioDeInforme],
    *,
    ja_gravados: Container[str],
) -> tuple[list[CenarioDeBoleto], list[CenarioDeInforme]]:
    """Os cenários que ainda não estão **inteiros** no banco.

    O par de informes conta como pendente enquanto faltar qualquer um dos dois
    documentos: o cruzamento entre anos precisa dos dois, e um par pela metade
    não é meio caso, é caso nenhum. Reprocessá-lo custa o OCR de novo; gravar
    de novo o que já estava, não — ver `_semeia_par`.
    """
    return (
        [c for c in boletos if any(str(a) not in ja_gravados for a in _arquivos_de(c))],
        [c for c in informes if any(str(a) not in ja_gravados for a in _arquivos_de(c))],
    )


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
    cenario: CenarioDeInforme,
    settings: Settings,
    *,
    com_ocr: bool,
    sessao: AbreSessao,
    ja_gravados: Container[str] = frozenset(),
) -> list[tuple[Decisao, str]]:
    """O informe é processado em par: o cruzamento entre anos precisa dos dois.

    `ja_gravados` cobre a retomada de um par pela metade. Os dois documentos são
    **processados** de novo — o cruzamento não tem como conferir um sozinho —,
    mas só é gravado o que ainda não tem decisão. Sem isso, completar um par
    interrompido criaria uma segunda decisão para o documento que já estava lá, e
    a fila mostraria o mesmo informe duas vezes.
    """
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
        if str(caminho) in ja_gravados:
            continue
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


Registro = Callable[[str], None]
"""Para onde vai o progresso. Ver `semeia`."""


def _em_silencio(_: str) -> None:
    """O padrão: a biblioteca não escreve em stdout de quem a chamou."""


def registra_no_stdout(mensagem: str) -> None:
    """Escreve uma linha de progresso, **com flush**.

    O flush não é zelo: o stdout do Python é bloco-bufferizado quando não é um
    terminal, que é exatamente o caso dentro de um contêiner. Sem ele, o log da
    hospedagem fica em branco até o processo terminar — e um processo que demora
    minutos e não imprime nada é indistinguível de um processo travado. Foi o
    que aconteceu no primeiro deploy: o log tinha o `echo` do shell e mais nada.
    """
    print(mensagem, flush=True)


def semeia(
    settings: Settings,
    *,
    boletos: Sequence[CenarioDeBoleto],
    informes: Sequence[CenarioDeInforme],
    com_ocr: bool = True,
    sessao: AbreSessao | None = None,
    registra: Registro = _em_silencio,
    ja_gravados: Container[str] = frozenset(),
) -> list[tuple[Decisao, str]]:
    """Processa os cenários e grava cada decisão. Devolve o que foi gravado.

    `sessao` entra por parâmetro para o teste poder apontar para um SQLite —
    exigir Postgres de pé para testar este comando contradiria a decisão da
    Fase 4.1 de a persistência ser opcional. Em uso normal ele é omitido.

    `registra` recebe uma linha por documento, ao **começar** e ao terminar, com
    o tempo. Duas linhas e não uma porque a pergunta que o log precisa responder
    é "onde travou", e só a linha de fim não responde: o documento que trava é
    justamente o que nunca imprime nada. Cada unidade custa de 2 a 5 segundos
    aqui e muito mais numa instância compartilhada — o OCR renderiza a página a
    300 DPI e roda o tesseract em cima.

    `ja_gravados` só tem efeito dentro de um par de informes, e é o que permite
    completar um par interrompido no meio sem duplicar o documento que sobreviveu.
    Escolher **quais** cenários rodar é de `pendentes`, não daqui.
    """
    abre = sessao if sessao is not None else _sessao_padrao
    unidades = len(boletos) + len(informes)
    gravadas = []

    for indice, cenario in enumerate(list(boletos) + list(informes), start=1):
        nome = (
            cenario.pdf.name
            if isinstance(cenario, CenarioDeBoleto)
            else f"{cenario.anterior.name}+{cenario.atual.name}"
        )
        registra(f"[{indice}/{unidades}] {nome}: começando")
        inicio = time.monotonic()

        if isinstance(cenario, CenarioDeBoleto):
            novas = [_semeia_boleto(cenario, settings, com_ocr=com_ocr, sessao=abre)]
        else:
            novas = _semeia_par(
                cenario, settings, com_ocr=com_ocr, sessao=abre, ja_gravados=ja_gravados
            )

        gravadas += novas
        pulados = len(_arquivos_de(cenario)) - len(novas)
        rotas = ", ".join(decisao.rota.value for decisao, _ in novas) or "nada a gravar"
        parcial = f", {pulados} já estava(m) no banco" if pulados else ""
        registra(
            f"[{indice}/{unidades}] {nome}: {rotas}{parcial} em {time.monotonic() - inicio:.1f}s"
        )

    return gravadas


def relata_os_casos_da_entrada(ja_gravados: Container[str], registra: Registro) -> list[str]:
    """Lista, no fim do log, quais casos da página de entrada estão no banco.

    Devolve as chaves dos que faltam.

    Existe porque uma semeadura pela metade era **muda**: o comando terminava
    com "11 documentos", o serviço subia, e o buraco só aparecia para quem
    abrisse o link e não achasse um caso. O log agora responde a pergunta que
    importa para a demonstração — não "quantos documentos foram gravados", e sim
    "os cinco casos que a entrada promete estão lá?".

    Os casos vêm de `app.demo`, o mesmo módulo que a API lê. Uma segunda lista
    aqui discordaria da primeira exatamente quando a diferença importasse.
    """
    presentes, faltando = [], []
    for caso in CASOS:
        arquivo = caso.arquivo
        if arquivo is not None and str(arquivo) in ja_gravados:
            presentes.append((caso, arquivo))
        else:
            faltando.append((caso, arquivo))

    registra(f"\ncasos da página de entrada: {len(presentes)} de {len(CASOS)} presentes")
    for caso, arquivo in presentes:
        registra(f"  ok     {caso.chave:22} {arquivo.name if arquivo else '—'}")
    for caso, arquivo in faltando:
        registra(
            f"  FALTA  {caso.chave:22} {arquivo.name if arquivo else 'sem documento no corpus'}"
        )

    if faltando:
        registra(
            f"!! {len(faltando)} caso(s) da entrada sem decisão no banco. A entrada "
            f"os mostra como indisponíveis, e a próxima partida com --completar "
            f"tenta de novo só o que falta."
        )
    return [caso.chave for caso, _ in faltando]


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
        "--completar",
        action="store_true",
        help=(
            "semeia só os cenários que ainda não estão no banco. É como o "
            "contêiner da demonstração se semeia: seguro de repetir, e se "
            "conserta sozinho depois de uma semeadura interrompida"
        ),
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

    if argumentos.limpar and argumentos.completar:
        print(
            "--limpar e --completar se contradizem: um apaga a fila, o outro "
            "existe para preencher só o que falta nela.",
            file=sys.stderr,
        )
        return 2

    com_ocr = not argumentos.sem_ocr
    if com_ocr and shutil.which("tesseract") is None:
        print(
            "tesseract não está instalado. Sem a comparação texto/imagem a "
            "sanitização barra todos os documentos, e a fila sai sem contraste — "
            "seguindo assim mesmo.",
            file=sys.stderr,
        )

    todos_os_boletos, todos_os_informes = cenarios_padrao()
    inicio = time.monotonic()

    try:
        if argumentos.limpar:
            limpa(settings)
            registra_no_stdout("fila apagada")

        # Lido **depois** do `--limpar`, senão o estado consultado seria o de
        # antes de apagar e nada seria semeado.
        ja_gravados = arquivos_com_decisao()
        boletos, informes = (
            pendentes(todos_os_boletos, todos_os_informes, ja_gravados=ja_gravados)
            if argumentos.completar
            else (list(todos_os_boletos), list(todos_os_informes))
        )

        if argumentos.completar:
            faltam = len(boletos) + len(informes)
            registra_no_stdout(
                f"completando: {faltam} de "
                f"{len(todos_os_boletos) + len(todos_os_informes)} cenário(s) faltando"
            )
        if boletos or informes:
            registra_no_stdout(
                f"semeando {len(boletos)} boleto(s) e {len(informes)} par(es) de informe, "
                f"{'com' if com_ocr else 'sem'} OCR"
            )

        gravadas = semeia(
            settings,
            boletos=boletos,
            informes=informes,
            com_ocr=com_ocr,
            registra=registra_no_stdout,
            ja_gravados=ja_gravados,
        )
    except PersistenciaDesligada as erro:
        print(f"\n{erro}", file=sys.stderr)
        return 1

    for decisao, rotulo in gravadas:
        registra_no_stdout(f"  #{decisao.id:<4} {decisao.rota.value:15} {rotulo}")

    na_fila = sum(1 for decisao, _ in gravadas if decisao.rota.value == "revisao_humana")
    registra_no_stdout(
        f"\n{len(gravadas)} documento(s) gravado(s) em {time.monotonic() - inicio:.1f}s: "
        f"{na_fila} na fila, {len(gravadas) - na_fila} auto-aprovado(s)."
    )

    # Sempre, inclusive quando nada foi semeado: o log tem que responder "os
    # cinco casos estão lá?" mesmo na partida em que não houve trabalho.
    relata_os_casos_da_entrada(arquivos_com_decisao(), registra_no_stdout)
    registra_no_stdout(
        "A tela está em http://localhost:3001 (docker compose --profile revisao up -d)."
    )
    registra_no_stdout("Nenhuma chamada à API do modelo: o provedor leu os gabaritos do corpus.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
