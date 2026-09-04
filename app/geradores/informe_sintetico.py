"""Gerador de informes de rendimentos sintéticos, em pares de anos consecutivos.

Nenhum documento real entra no repositório. O lote é reproduzível quando se
passa **semente e data de referência** — as duas ficam gravadas no gabarito,
como no gerador de boletos.

## Por que pares

A validação mais forte desta fase não cabe num documento só: o saldo em
31/12/N-1 que o informe do ano N declara precisa ser conferido contra o
informe de N-1, que o afirma por conta própria (ver `app.dominio.cruzamento`).
Um corpus de documentos avulsos não teria como exercitá-la. Por isso a unidade
de geração é o **par**: dois PDFs, mesmo titular, mesma fonte, anos
consecutivos, com os saldos fechando entre eles.

O gabarito de cada documento aponta para o par em `par.arquivo_do_par`, para o
eval não precisar adivinhar quem cruza com quem.

## Dois layouts, de propósito

A issue #1 registra o corpus de template único como a limitação mais séria do
projeto. Aqui são dois desde o início, e eles diferem em estrutura, não só em
CSS: o comprovante de fonte pagadora tem linhas numeradas fixas e nenhum
saldo; o informe de instituição financeira tem listas por conta, totais
impressos e a tabela de saldos. Ver ADR 007.

Consequência que vale saber: o cruzamento entre anos só tem o que conferir no
layout bancário. Nos pares de fonte pagadora ele sai comparável e **sem
cobertura**, e é assim que deve aparecer no relatório.

Uso:
    uv run python -m app.geradores.informe_sintetico \
        --pares 12 --semente 2026 --data-referencia 2026-09-04
"""

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from faker import Faker
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import HTML

from app.dominio.informe import Informe, Layout, LinhaDeQuadro, Quadro, SaldoDeConta
from app.geradores.boleto_sintetico import formata_data, formata_documento, formata_moeda

DIRETORIO_PADRAO = Path("dados/sinteticos/informes")
DIRETORIO_TEMPLATES = Path(__file__).parent / "templates"
LOCALE_FAKER = "pt_BR"

TEMPLATES = {
    Layout.FONTE_PAGADORA: "informe_fonte_pagadora.html",
    Layout.INSTITUICAO_FINANCEIRA: "informe_instituicao_financeira.html",
}

# Rótulos das linhas do Anexo I, transcritos do modelo oficial. São fixos: o
# que varia de um comprovante para outro é quais deles têm valor. Ver ADR 007.
LINHAS_TRIBUTAVEIS = (
    ("3.1", "Total dos rendimentos (inclusive férias)"),
    ("3.2", "Contribuição previdenciária oficial"),
    ("3.3", "Contribuição a entidades de previdência complementar e a Fapi"),
    ("3.4", "Pensão alimentícia"),
    ("3.5", "Imposto sobre a renda retido na fonte"),
)

LINHAS_ISENTAS = (
    ("4.1", "Parcela isenta de proventos de aposentadoria (65 anos ou mais)"),
    ("4.2", "Diárias e ajudas de custo"),
    ("4.3", "Pensão e proventos por moléstia grave ou acidente em serviço"),
    ("4.4", "Lucros e dividendos apurados a partir de 1996"),
    ("4.5", "Valores pagos ao titular ou sócio de microempresa ou EPP"),
    ("4.6", "Indenizações por rescisão de contrato de trabalho e por acidente"),
    ("4.7", "Outros"),
)

LINHAS_EXCLUSIVAS = (
    ("5.1", "13º (décimo terceiro) salário"),
    ("5.2", "Imposto sobre a renda retido na fonte sobre 13º salário"),
    ("5.3", "Outros"),
)

TITULOS_FONTE_PAGADORA = {
    "3": "Rendimentos Tributáveis, Deduções e Imposto sobre a Renda Retido na Fonte",
    "4": "Rendimentos Isentos e Não Tributáveis",
    "5": "Rendimentos Sujeitos à Tributação Exclusiva (rendimento líquido)",
}

TITULOS_FINANCEIRO = {
    "rendimentos_tributaveis": "Rendimentos Tributáveis",
    "rendimentos_isentos": "Rendimentos Isentos e Não Tributáveis",
    "rendimentos_exclusivos": "Rendimentos Sujeitos à Tributação Exclusiva",
}

BANCOS = (
    ("Banco Aurora S/A", "Conta Corrente"),
    ("Banco Meridiano S/A", "Conta Corrente"),
    ("Corretora Vértice CTVM", "Conta Investimento"),
    ("Banco Palmares S/A", "Conta Corrente"),
    ("Cooperativa de Crédito Sul-Norte", "Conta Corrente"),
)

PRODUTOS_ISENTOS = (
    ("Poupança", "Rendimentos de caderneta de poupança"),
    ("LCI", "Letra de Crédito Imobiliário"),
    ("LCA", "Letra de Crédito do Agronegócio"),
)

PRODUTOS_EXCLUSIVOS = (
    ("CDB", "Certificado de Depósito Bancário"),
    ("Fundo DI", "Fundo de investimento referenciado DI"),
    ("Fundo Multimercado", "Fundo de investimento multimercado"),
    ("Tesouro Selic", "Título público federal"),
    ("LF", "Letra Financeira"),
)

NATUREZAS = (
    "Rendimentos do trabalho assalariado",
    "Proventos de aposentadoria",
    "Rendimentos do trabalho sem vínculo empregatício",
)

COMPLEMENTARES = (
    "Contribuição a entidade de previdência complementar informada na linha 3 do quadro 3.",
    "Pensão alimentícia informada na linha 4 do quadro 3, conforme decisão judicial.",
    "Não houve informação complementar a declarar no ano-calendário.",
)

# Quantas linhas o quadro longo tem. Precisa ser grande o bastante para a
# tabela atravessar a quebra de página, que é o caso que o extrator multi-
# página tem de aguentar na Fase 2.2.
LINHAS_DO_QUADRO_LONGO = 46


@dataclass(frozen=True, slots=True)
class Procedencia:
    """Como o lote foi gerado — o que basta para produzi-lo de novo.

    Mesma razão do gerador de boletos: a semente sozinha não reproduz lote
    nenhum, porque o ano-calendário sai da data de referência. As duas ficam
    no gabarito, e não só no comando que alguém lembrou de anotar.
    """

    semente: int | None
    data_de_referencia: date

    def como_gabarito(self) -> dict[str, Any]:
        return {
            "semente": self.semente,
            "data_de_referencia": self.data_de_referencia.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class InformeSintetico:
    """Um informe gerado: o gabarito da extração mais o que só aparece impresso."""

    informe: Informe
    par: str
    """Identificador do par a que este documento pertence."""
    papel: str
    """`ano` ou `ano_anterior`, dentro do par."""
    agencia: str
    natureza_do_rendimento: str
    informacoes_complementares: str
    responsavel_nome: str
    data_de_emissao: date
    procedencia: Procedencia

    def como_gabarito(self, arquivo_pdf: str, arquivo_do_par: str) -> dict[str, Any]:
        return {
            "arquivo_pdf": arquivo_pdf,
            "gerado_com": self.procedencia.como_gabarito(),
            "layout": self.informe.layout.value,
            "par": {
                "identificador": self.par,
                "papel": self.papel,
                "arquivo_do_par": arquivo_do_par,
            },
            "quadros_sem_cobertura": list(self.informe.quadros_sem_cobertura),
            "campos": self.informe.model_dump(mode="json"),
        }


def _dinheiro(aleatorio: random.Random, minimo: int, maximo: int) -> Decimal:
    """Sorteia um valor em reais, sempre Decimal com duas casas."""
    return Decimal(aleatorio.randrange(minimo * 100, maximo * 100)) / 100


def _quadro_fonte_pagadora(
    aleatorio: random.Random,
    identificador: str,
    rotulos: Sequence[tuple[str, str]],
    *,
    obrigatorias: Sequence[str] = (),
    faixa: tuple[int, int] = (100, 40_000),
) -> Quadro:
    """Monta um quadro do modelo oficial: linhas fixas, só as preenchidas, sem total.

    Um comprovante real não imprime linha zerada, e é daí que vem a variação
    de tamanho neste layout — não de lista livre, que ele não tem.
    """
    linhas = []
    for chave, descricao in rotulos:
        if chave not in obrigatorias and aleatorio.random() < 0.55:
            continue
        linhas.append(
            LinhaDeQuadro(
                identificador=chave,
                descricao=descricao,
                valor=_dinheiro(aleatorio, *faixa),
            )
        )
    return Quadro(
        identificador=identificador,
        titulo=TITULOS_FONTE_PAGADORA[identificador],
        linhas=tuple(linhas),
        total_impresso=None,
    )


def _quadro_financeiro(
    aleatorio: random.Random,
    identificador: str,
    produtos: Sequence[tuple[str, str]],
    *,
    quantidade: int,
    faixa: tuple[int, int] = (10, 20_000),
) -> Quadro:
    """Monta um quadro do informe bancário: uma linha por produto, com total impresso.

    O total é o que dá cobertura aritmética a este layout, e é o alvo do
    ataque de total adulterado.
    """
    linhas = []
    for indice in range(quantidade):
        sigla, descricao = produtos[indice % len(produtos)]
        sufixo = f" {indice + 1:02d}" if quantidade > len(produtos) else ""
        linhas.append(
            LinhaDeQuadro(
                identificador=f"{sigla}{sufixo}",
                descricao=descricao,
                valor=_dinheiro(aleatorio, *faixa),
            )
        )
    total = sum((linha.valor for linha in linhas), Decimal("0"))
    return Quadro(
        identificador=identificador,
        titulo=TITULOS_FINANCEIRO[identificador],
        linhas=tuple(linhas),
        total_impresso=total,
    )


def _gera_par_fonte_pagadora(
    faker: Faker,
    aleatorio: random.Random,
    ano: int,
    cpf: str,
    nome_do_titular: str,
    emissao: date,
    procedencia: Procedencia,
    par: str,
) -> tuple[InformeSintetico, InformeSintetico]:
    """Dois comprovantes do mesmo empregador, em anos consecutivos.

    Não há saldo a encadear: o comprovante de fonte pagadora não tem saldo. O
    par existe mesmo assim porque é o corpus que expõe o cruzamento saindo
    *sem cobertura* — que é informação, e some se o corpus só tiver o layout
    em que ele funciona.
    """
    cnpj = faker.cnpj()
    nome_da_fonte = faker.company()
    natureza = aleatorio.choice(NATUREZAS)
    responsavel = faker.name()
    complementares = aleatorio.choice(COMPLEMENTARES)

    def de(ano_do_documento: int, papel: str) -> InformeSintetico:
        exclusivas = _quadro_fonte_pagadora(
            aleatorio, "5", LINHAS_EXCLUSIVAS, obrigatorias=("5.1",), faixa=(500, 12_000)
        )
        decimo = exclusivas.linha("5.1")
        imposto = exclusivas.linha("5.2")
        if decimo is not None and imposto is not None and imposto.valor > decimo.valor:
            # O IRRF sobre o 13º nunca excede o 13º, e o domínio recusa se
            # exceder. Refazer a linha é mais honesto que sortear de novo até
            # dar certo: a proporção é o que o documento real tem.
            exclusivas = exclusivas.model_copy(
                update={
                    "linhas": tuple(
                        linha
                        if linha.identificador != "5.2"
                        else linha.model_copy(
                            update={"valor": (decimo.valor / 4).quantize(Decimal("0.01"))}
                        )
                        for linha in exclusivas.linhas
                    )
                }
            )
        informe = Informe(
            layout=Layout.FONTE_PAGADORA,
            ano_calendario=ano_do_documento,
            exercicio=ano_do_documento + 1,
            fonte_pagadora_cnpj=cnpj,
            fonte_pagadora_nome=nome_da_fonte,
            beneficiario_cpf=cpf,
            beneficiario_nome=nome_do_titular,
            rendimentos_tributaveis=_quadro_fonte_pagadora(
                aleatorio,
                "3",
                LINHAS_TRIBUTAVEIS,
                obrigatorias=("3.1", "3.2"),
                faixa=(1_000, 180_000),
            ),
            rendimentos_isentos=_quadro_fonte_pagadora(aleatorio, "4", LINHAS_ISENTAS),
            rendimentos_exclusivos=exclusivas,
        )
        return InformeSintetico(
            informe=informe,
            par=par,
            papel=papel,
            agencia="",
            natureza_do_rendimento=natureza,
            informacoes_complementares=complementares,
            responsavel_nome=responsavel,
            data_de_emissao=emissao.replace(year=ano_do_documento + 1),
            procedencia=procedencia,
        )

    return de(ano - 1, "ano_anterior"), de(ano, "ano")


def _gera_par_financeiro(
    faker: Faker,
    aleatorio: random.Random,
    ano: int,
    cpf: str,
    nome_do_titular: str,
    emissao: date,
    procedencia: Procedencia,
    par: str,
    *,
    quadro_longo: bool = False,
) -> tuple[InformeSintetico, InformeSintetico]:
    """Dois informes bancários com os saldos encadeados entre os anos.

    O encadeamento é o ponto: `saldo_31_12_anterior` do informe do ano N é,
    por construção, o `saldo_31_12` do informe de N-1, conta a conta. É o que
    o corpus precisa ter para o cruzamento poder reprovar quando não bate.
    """
    nome_do_banco, produto_de_conta = aleatorio.choice(BANCOS)
    cnpj = faker.cnpj()
    agencia = f"{aleatorio.randint(1, 9999):04d}"
    conta = f"{aleatorio.randint(1, 999_999_999):09d}"

    quantas_contas = aleatorio.randint(1, 3)
    contas = [f"{produto_de_conta} {agencia}.{conta}"]
    for sigla, _ in aleatorio.sample(PRODUTOS_EXCLUSIVOS, k=quantas_contas):
        contas.append(f"{sigla} {aleatorio.randrange(10**6, 10**7)}")

    # Saldos de N-2, N-1 e N por conta. O do meio é o que os dois documentos
    # precisam contar igual, e é ele que o cruzamento confere.
    saldos: dict[str, tuple[Decimal, Decimal, Decimal]] = {
        especificacao: (
            _dinheiro(aleatorio, 0, 60_000),
            _dinheiro(aleatorio, 0, 80_000),
            _dinheiro(aleatorio, 0, 120_000),
        )
        for especificacao in contas
    }

    conta_nova = f"CDB {aleatorio.randrange(10**6, 10**7)}" if aleatorio.random() < 0.4 else None
    # Conta encerrada durante o ano N: aparece no informe de N-1 e some do de
    # N. É legítimo, e deixa o saldo de 31/12/N-1 dela sem ninguém para
    # cruzar — o caso que `contas_sem_conferencia` existe para registrar.
    conta_encerrada = (
        aleatorio.choice(contas[1:]) if len(contas) > 1 and aleatorio.random() < 0.35 else None
    )

    def de(ano_do_documento: int, papel: str) -> InformeSintetico:
        do_ano_anterior = papel == "ano_anterior"
        posicoes = []
        for especificacao, (dois_atras, um_atras, atual) in saldos.items():
            if especificacao == conta_encerrada and not do_ano_anterior:
                continue
            anterior, agora = (dois_atras, um_atras) if do_ano_anterior else (um_atras, atual)
            posicoes.append(
                SaldoDeConta(
                    especificacao=especificacao,
                    saldo_31_12=agora,
                    saldo_31_12_anterior=anterior,
                )
            )
        if conta_nova is not None and not do_ano_anterior:
            # Conta aberta durante o ano N: sem par no informe anterior, e por
            # isso mesmo com saldo anterior zerado.
            posicoes.append(
                SaldoDeConta(
                    especificacao=conta_nova,
                    saldo_31_12=_dinheiro(aleatorio, 100, 50_000),
                    saldo_31_12_anterior=Decimal("0.00"),
                )
            )

        quantas_exclusivas = (
            LINHAS_DO_QUADRO_LONGO
            if quadro_longo and not do_ano_anterior
            else aleatorio.randint(1, 5)
        )
        informe = Informe(
            layout=Layout.INSTITUICAO_FINANCEIRA,
            ano_calendario=ano_do_documento,
            exercicio=ano_do_documento + 1,
            fonte_pagadora_cnpj=cnpj,
            fonte_pagadora_nome=nome_do_banco,
            beneficiario_cpf=cpf,
            beneficiario_nome=nome_do_titular,
            rendimentos_tributaveis=_quadro_financeiro(
                aleatorio, "rendimentos_tributaveis", PRODUTOS_EXCLUSIVOS, quantidade=0
            ),
            rendimentos_isentos=_quadro_financeiro(
                aleatorio,
                "rendimentos_isentos",
                PRODUTOS_ISENTOS,
                quantidade=aleatorio.randint(0, 3),
            ),
            rendimentos_exclusivos=_quadro_financeiro(
                aleatorio,
                "rendimentos_exclusivos",
                PRODUTOS_EXCLUSIVOS,
                quantidade=quantas_exclusivas,
            ),
            saldos=tuple(posicoes),
        )
        return InformeSintetico(
            informe=informe,
            par=par,
            papel=papel,
            agencia=f"{agencia}-{aleatorio.randint(0, 9)}",
            natureza_do_rendimento="",
            informacoes_complementares="",
            responsavel_nome="",
            data_de_emissao=emissao.replace(year=ano_do_documento + 1),
            procedencia=procedencia,
        )

    return de(ano - 1, "ano_anterior"), de(ano, "ano")


def gera_pares(
    quantidade: int, *, semente: int | None = None, hoje: date | None = None
) -> list[tuple[InformeSintetico, InformeSintetico]]:
    """Gera `quantidade` pares, alternando os dois layouts.

    O ano-calendário do documento mais novo é o ano anterior ao da data de
    referência: o informe de 2025 é entregue em 2026.
    """
    if quantidade < 1:
        raise ValueError(f"quantidade de pares precisa ser positiva, recebida {quantidade}")

    faker = Faker(LOCALE_FAKER)
    aleatorio = random.Random(semente)
    if semente is not None:
        faker.seed_instance(semente)

    referencia = hoje or date.today()
    procedencia = Procedencia(semente=semente, data_de_referencia=referencia)
    ano = referencia.year - 1
    emissao = date(referencia.year, 3, min(referencia.day, 28))

    pares = []
    for indice in range(quantidade):
        identificador = f"par-{indice + 1:03d}"
        cpf = faker.cpf()
        nome = faker.name()
        # Alterna os layouts para o corpus não pender para um deles, e reserva
        # o quadro longo para o segundo par bancário, que é onde ele cabe.
        if indice % 2 == 0:
            pares.append(
                _gera_par_financeiro(
                    faker,
                    aleatorio,
                    ano,
                    cpf,
                    nome,
                    emissao,
                    procedencia,
                    identificador,
                    quadro_longo=(indice == 2),
                )
            )
        else:
            pares.append(
                _gera_par_fonte_pagadora(
                    faker, aleatorio, ano, cpf, nome, emissao, procedencia, identificador
                )
            )
    return pares


def renderiza_html(
    sintetico: InformeSintetico,
    *,
    impresso: dict[str, Any] | None = None,
    ataque_html: str = "",
) -> str:
    """Aplica o template do layout ao informe.

    `impresso` existe para o gerador adversarial: ele permite que a página
    mostre algo que o domínio recusaria — soma que não fecha, quadro
    duplicado, total adulterado. Em documento limpo ele fica `None` e o que se
    imprime é exatamente o que está no gabarito, como manda o ADR 006.
    """
    ambiente = Environment(
        loader=FileSystemLoader(DIRETORIO_TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
    )
    template = ambiente.get_template(TEMPLATES[sintetico.informe.layout])
    dados = impresso if impresso is not None else sintetico.informe.model_dump()
    return template.render(
        informe=dados,
        quadros=[
            dados["rendimentos_tributaveis"],
            dados["rendimentos_isentos"],
            dados["rendimentos_exclusivos"],
        ],
        extra=sintetico,
        moeda=formata_moeda,
        data=formata_data,
        documento=formata_documento,
        ataque_html=ataque_html,
    )


def salva(
    sintetico: InformeSintetico,
    destino: Path,
    nome_base: str,
    arquivo_do_par: str,
    *,
    impresso: dict[str, Any] | None = None,
    gabarito_extra: dict[str, Any] | None = None,
    ataque_html: str = "",
) -> tuple[Path, Path]:
    """Escreve o PDF e o gabarito JSON com o mesmo nome base."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho_pdf = destino / f"{nome_base}.pdf"
    caminho_json = destino / f"{nome_base}.json"

    HTML(string=renderiza_html(sintetico, impresso=impresso, ataque_html=ataque_html)).write_pdf(
        caminho_pdf
    )
    gabarito = sintetico.como_gabarito(caminho_pdf.name, arquivo_do_par)
    if impresso is not None:
        gabarito["campos"] = json.loads(json.dumps(impresso, default=str))
    if gabarito_extra:
        gabarito.update(gabarito_extra)
    caminho_json.write_text(
        json.dumps(gabarito, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return caminho_pdf, caminho_json


def lote_existente(destino: Path, prefixo: str) -> list[Path]:
    """Lista os arquivos que uma nova geração com esse prefixo sobrescreveria."""
    if not destino.is_dir():
        return []
    return sorted(
        caminho
        for extensao in ("pdf", "json")
        for caminho in destino.glob(f"{prefixo}-*.{extensao}")
    )


def _analisa_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.geradores.informe_sintetico",
        description=(
            "Gera informes de rendimentos sintéticos em pares de anos consecutivos, "
            "alternando os dois layouts."
        ),
    )
    parser.add_argument(
        "--pares", type=int, default=12, help="quantos pares gerar (padrão: 12, ou seja 24 PDFs)"
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=DIRETORIO_PADRAO,
        help=f"diretório de destino (padrão: {DIRETORIO_PADRAO})",
    )
    parser.add_argument(
        "--semente", type=int, default=None, help="semente para gerar sempre o mesmo lote"
    )
    parser.add_argument(
        "--data-referencia",
        type=date.fromisoformat,
        default=None,
        help=(
            "data de emissão de referência, em AAAA-MM-DD (padrão: hoje). O "
            "ano-calendário é o ano anterior a ela. Junto com --semente é o que "
            "torna o lote reproduzível."
        ),
    )
    parser.add_argument(
        "--prefixo", default="informe", help="prefixo do nome dos arquivos (padrão: informe)"
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="sobrescreve um lote que já exista no diretório de saída",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada da CLI."""
    argumentos = _analisa_argumentos(argv)

    existentes = lote_existente(argumentos.saida, argumentos.prefixo)
    if existentes and not argumentos.forcar:
        print(
            f"{argumentos.saida} já tem um lote com o prefixo "
            f"{argumentos.prefixo!r} ({len(existentes)} arquivos).\n"
            f"Gerar por cima trocaria o corpus. Use --forcar para sobrescrever, "
            f"--saida para escrever em outro lugar ou --prefixo para conviver com o lote atual.",
            file=sys.stderr,
        )
        return 1

    pares = gera_pares(
        argumentos.pares, semente=argumentos.semente, hoje=argumentos.data_referencia
    )

    numero = 0
    for anterior, atual in pares:
        nome_anterior = f"{argumentos.prefixo}-{numero + 1:03d}"
        nome_atual = f"{argumentos.prefixo}-{numero + 2:03d}"
        numero += 2

        for sintetico, nome, par in (
            (anterior, nome_anterior, f"{nome_atual}.pdf"),
            (atual, nome_atual, f"{nome_anterior}.pdf"),
        ):
            caminho_pdf, _ = salva(sintetico, argumentos.saida, nome, par)
            print(
                f"{caminho_pdf}  {sintetico.informe.layout.value:<24} "
                f"{sintetico.informe.ano_calendario}  "
                f"{sintetico.informe.beneficiario_nome}"
            )

    procedencia = pares[0][0].procedencia
    print(f"\n{len(pares)} pares ({len(pares) * 2} documentos) em {argumentos.saida}")
    print(
        f"semente {procedencia.semente}, "
        f"data de referência {procedencia.data_de_referencia.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
