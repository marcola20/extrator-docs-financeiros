"""Gerador de boletos sintéticos: PDF renderizado e gabarito JSON ao lado.

Nenhum documento real entra no repositório. Tudo aqui é fictício, e o lote é
reproduzível quando se passa **semente e data de referência** — só a semente
não basta, porque os vencimentos são sorteados a partir da data. As duas
ficam gravadas no gabarito de cada documento; ver `Procedencia`.

Uso:
    uv run python -m app.geradores.boleto_sintetico \
        --quantidade 15 --semente 2026 --data-referencia 2026-09-03
"""

import argparse
import json
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from faker import Faker
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import HTML

from app.dominio.boleto import Boleto
from app.dominio.digito_verificador import dv_codigo_banco
from app.dominio.linha_digitavel import (
    linha_digitavel_de_codigo_barras,
    monta_codigo_barras,
)
from app.geradores import codigo_barras_itf

DIRETORIO_PADRAO = Path("dados/sinteticos/boletos")
DIRETORIO_TEMPLATES = Path(__file__).parent / "templates"
LOCALE_FAKER = "pt_BR"


@dataclass(frozen=True, slots=True)
class Banco:
    """Banco emissor, com o código usado no início do código de barras."""

    codigo: str
    nome: str


BANCOS = (
    Banco("001", "Banco do Brasil"),
    Banco("033", "Santander"),
    Banco("077", "Banco Inter"),
    Banco("104", "Caixa Econômica Federal"),
    Banco("237", "Bradesco"),
    Banco("260", "Nu Pagamentos"),
    Banco("341", "Itaú Unibanco"),
    Banco("748", "Sicredi"),
    Banco("756", "Sicoob"),
)

CARTEIRAS = ("09", "17", "18", "11", "12")

INSTRUCOES = (
    "Após o vencimento, cobrar multa de 2% e juros de 1% ao mês.",
    "Não receber após 30 dias do vencimento.",
    "Sr. Caixa, não receber após o vencimento.",
    "Pagável em qualquer banco até o vencimento.",
    "Em caso de dúvida, entrar em contato com o beneficiário.",
)

ESPECIES_DOCUMENTO = ("DM", "DS", "NP", "RC")


@dataclass(frozen=True, slots=True)
class Procedencia:
    """Como o lote foi gerado — o que basta para produzi-lo de novo.

    A semente sozinha não reproduz corpus nenhum. O vencimento é sorteado
    como um deslocamento a partir de uma **data de referência**, que por
    padrão é o dia em que o gerador rodou: mesma semente em dia diferente dá
    outro corpus, e nada no repositório denuncia a troca. Dois evals de datas
    diferentes deixam de ser comparáveis sem que ninguém perceba.

    Por isso as duas coisas ficam gravadas no gabarito de cada documento, e
    não só no comando que alguém lembrou de anotar.
    """

    semente: int | None
    data_de_referencia: date

    def como_gabarito(self) -> dict[str, Any]:
        return {
            "semente": self.semente,
            "data_de_referencia": self.data_de_referencia.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class BoletoSintetico:
    """Um boleto gerado: o gabarito da extração mais o que só aparece impresso."""

    boleto: Boleto
    codigo_barras: str
    agencia: str
    conta: str
    carteira: str
    numero_documento: str
    data_documento: date
    especie_documento: str
    instrucoes: str
    pagador_endereco: str
    beneficiario_endereco: str
    procedencia: Procedencia

    def como_gabarito(self, arquivo_pdf: str) -> dict[str, Any]:
        """Monta o dicionário salvo em JSON ao lado do PDF."""
        return {
            "arquivo_pdf": arquivo_pdf,
            "gerado_com": self.procedencia.como_gabarito(),
            "codigo_barras": self.codigo_barras,
            "campos": self.boleto.model_dump(mode="json"),
        }


def gera_boleto(
    faker: Faker, aleatorio: random.Random, hoje: date, *, semente: int | None = None
) -> BoletoSintetico:
    """Gera um boleto fictício coerente, com todos os DVs corretos."""
    banco = aleatorio.choice(BANCOS)
    vencimento = hoje + timedelta(days=aleatorio.randint(-30, 90))
    valor = _sorteia_valor(aleatorio)

    agencia = f"{aleatorio.randint(1, 9999):04d}"
    conta = f"{aleatorio.randint(1, 9_999_999):07d}"
    carteira = aleatorio.choice(CARTEIRAS)
    nosso_numero = f"{aleatorio.randrange(10**10, 10**11):011d}"

    campo_livre = f"{agencia}{carteira}{nosso_numero}{conta}0"
    codigo_barras = monta_codigo_barras(
        banco_codigo=banco.codigo,
        vencimento=vencimento,
        valor=valor,
        campo_livre=campo_livre,
    )

    tem_pagador = aleatorio.random() < 0.85
    pagador_e_empresa = aleatorio.random() < 0.3

    boleto = Boleto(
        linha_digitavel=linha_digitavel_de_codigo_barras(codigo_barras),
        beneficiario_nome=faker.company(),
        beneficiario_cnpj=faker.cnpj(),
        pagador_nome=(faker.company() if pagador_e_empresa else faker.name())
        if tem_pagador
        else None,
        pagador_cpf_cnpj=(faker.cnpj() if pagador_e_empresa else faker.cpf())
        if tem_pagador
        else None,
        valor=valor,
        vencimento=vencimento,
        banco_codigo=banco.codigo,
        banco_nome=banco.nome,
        nosso_numero=nosso_numero,
    )

    return BoletoSintetico(
        boleto=boleto,
        codigo_barras=codigo_barras,
        agencia=agencia,
        conta=conta,
        carteira=carteira,
        numero_documento=f"{aleatorio.randint(1, 999_999):06d}",
        data_documento=vencimento - timedelta(days=aleatorio.randint(5, 40)),
        especie_documento=aleatorio.choice(ESPECIES_DOCUMENTO),
        instrucoes=aleatorio.choice(INSTRUCOES),
        pagador_endereco=_endereco(faker),
        beneficiario_endereco=_endereco(faker),
        procedencia=Procedencia(semente=semente, data_de_referencia=hoje),
    )


def gera_lote(
    quantidade: int, *, semente: int | None = None, hoje: date | None = None
) -> list[BoletoSintetico]:
    """Gera vários boletos. Com a mesma semente, o lote sai idêntico."""
    if quantidade < 1:
        raise ValueError(f"quantidade precisa ser positiva, recebida {quantidade}")

    faker = Faker(LOCALE_FAKER)
    aleatorio = random.Random(semente)
    if semente is not None:
        faker.seed_instance(semente)

    referencia = hoje or date.today()
    return [gera_boleto(faker, aleatorio, referencia, semente=semente) for _ in range(quantidade)]


def renderiza_html(
    sintetico: BoletoSintetico,
    *,
    ataque_html: str = "",
    valor_impresso: str | None = None,
    beneficiario_impresso: str | None = None,
) -> str:
    """Aplica o template Jinja2 ao boleto.

    Os três argumentos opcionais existem para o gerador adversarial. Em
    documento limpo eles ficam no padrão e o resultado é idêntico ao de
    antes: o que se imprime é o que está no gabarito.

    `valor_impresso` e `beneficiario_impresso` permitem que a página mostre
    algo diferente do que o gabarito diz — é o ataque em que o texto impresso
    diverge do que está codificado na linha digitável.
    """
    ambiente = Environment(
        loader=FileSystemLoader(DIRETORIO_TEMPLATES),
        autoescape=True,
        undefined=StrictUndefined,
    )
    template = ambiente.get_template("boleto.html")
    return template.render(
        boleto=sintetico.boleto,
        extra=sintetico,
        linha_formatada=sintetico.boleto.linha_digitavel_formatada,
        dv_banco=dv_codigo_banco(sintetico.boleto.banco_codigo),
        codigo_barras_svg=codigo_barras_itf.svg(sintetico.codigo_barras),
        moeda=formata_moeda,
        data=formata_data,
        documento=formata_documento,
        ataque_html=ataque_html,
        valor_impresso=(
            valor_impresso if valor_impresso is not None else formata_moeda(sintetico.boleto.valor)
        ),
        beneficiario_impresso=(
            beneficiario_impresso
            if beneficiario_impresso is not None
            else sintetico.boleto.beneficiario_nome
        ),
    )


def salva(sintetico: BoletoSintetico, destino: Path, nome_base: str) -> tuple[Path, Path]:
    """Escreve o PDF e o gabarito JSON com o mesmo nome base. Devolve os caminhos."""
    destino.mkdir(parents=True, exist_ok=True)
    caminho_pdf = destino / f"{nome_base}.pdf"
    caminho_json = destino / f"{nome_base}.json"

    HTML(string=renderiza_html(sintetico)).write_pdf(caminho_pdf)
    caminho_json.write_text(
        json.dumps(sintetico.como_gabarito(caminho_pdf.name), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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


def formata_moeda(valor: Decimal) -> str:
    """Formata em reais no padrão brasileiro: 1.234,56."""
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def formata_data(dia: date) -> str:
    """Formata a data como dd/mm/aaaa."""
    return dia.strftime("%d/%m/%Y")


def formata_documento(documento: str | None) -> str:
    """Formata CPF ou CNPJ com a pontuação usual."""
    if documento is None:
        return ""
    if len(documento) == 11:
        return f"{documento[:3]}.{documento[3:6]}.{documento[6:9]}-{documento[9:]}"
    if len(documento) == 14:
        return (
            f"{documento[:2]}.{documento[2:5]}.{documento[5:8]}/{documento[8:12]}-{documento[12:]}"
        )
    return documento


def _sorteia_valor(aleatorio: random.Random) -> Decimal:
    """Sorteia um valor plausível de conta, sempre em Decimal com 2 casas."""
    centavos = aleatorio.choice(
        [
            aleatorio.randrange(1_500, 30_000),  # contas do dia a dia
            aleatorio.randrange(30_000, 500_000),  # faturas maiores
            aleatorio.randrange(500_000, 5_000_000),  # boletos de empresa
        ]
    )
    return Decimal(centavos) / 100


def _endereco(faker: Faker) -> str:
    """Monta um endereço em uma linha, com o CEP sempre pontuado."""
    cep = faker.postcode().replace("-", "")
    return (
        f"{faker.street_address()} - {faker.bairro()} - "
        f"{faker.city()}/{faker.estado_sigla()} - CEP {cep[:5]}-{cep[5:]}"
    )


def _analisa_argumentos(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.geradores.boleto_sintetico",
        description="Gera boletos sintéticos em PDF com o gabarito JSON ao lado.",
    )
    parser.add_argument(
        "--quantidade", type=int, default=15, help="quantos boletos gerar (padrão: 15)"
    )
    parser.add_argument(
        "--saida",
        type=Path,
        default=DIRETORIO_PADRAO,
        help=f"diretório de destino (padrão: {DIRETORIO_PADRAO})",
    )
    parser.add_argument(
        "--semente",
        type=int,
        default=None,
        help="semente para gerar sempre o mesmo lote",
    )
    parser.add_argument(
        "--data-referencia",
        type=date.fromisoformat,
        default=None,
        help=(
            "data a partir da qual os vencimentos são sorteados, em AAAA-MM-DD "
            "(padrão: hoje). Junto com --semente é o que torna o lote reproduzível."
        ),
    )
    parser.add_argument(
        "--prefixo", default="boleto", help="prefixo do nome dos arquivos (padrão: boleto)"
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

    lote = gera_lote(
        argumentos.quantidade, semente=argumentos.semente, hoje=argumentos.data_referencia
    )
    for indice, sintetico in enumerate(lote, start=1):
        nome_base = f"{argumentos.prefixo}-{indice:03d}"
        caminho_pdf, _ = salva(sintetico, argumentos.saida, nome_base)
        print(
            f"{caminho_pdf}  {sintetico.boleto.banco_nome:<24} "
            f"R$ {formata_moeda(sintetico.boleto.valor):>12}  "
            f"venc. {formata_data(sintetico.boleto.vencimento)}"
        )

    procedencia = lote[0].procedencia
    print(f"\n{len(lote)} boletos em {argumentos.saida}")
    print(
        f"semente {procedencia.semente}, "
        f"data de referência {procedencia.data_de_referencia.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
