"""Montagem e conversão entre código de barras e linha digitável de boleto.

Código de barras (44 dígitos):
    1-3 banco | 4 moeda | 5 DV geral | 6-9 fator de vencimento
    | 10-19 valor em centavos | 20-44 campo livre

Linha digitável (47 dígitos): o mesmo conteúdo reorganizado em cinco campos,
os três primeiros com DV módulo 10 próprio.
"""

from datetime import date
from decimal import Decimal

from app.dominio.digito_verificador import (
    TAMANHO_CODIGO_BARRAS,
    TAMANHO_LINHA_DIGITAVEL,
    apenas_digitos,
    modulo10,
    modulo11_boleto,
)

DATA_BASE_FATOR = date(1997, 10, 7)
"""Data de referência do fator de vencimento (fator 0)."""

FATOR_MAXIMO = 9999
"""Último fator do primeiro ciclo, atingido em 21/02/2025."""

FATOR_REINICIO = 1000
"""Fator para o qual a contagem voltou em 22/02/2025."""

TAMANHO_CICLO_FATOR = FATOR_MAXIMO - FATOR_REINICIO + 1
"""Quantidade de fatores disponíveis por ciclo (1000 a 9999)."""

MOEDA_REAL = "9"
"""Código da moeda no boleto: 9 para real."""

TAMANHO_CAMPO_LIVRE = 25
"""Quantidade de dígitos do campo livre, de formato definido por cada banco."""


def fator_vencimento(vencimento: date) -> int:
    """Converte uma data de vencimento no fator de 4 dígitos do código de barras.

    O fator é a quantidade de dias desde 07/10/1997. Ele chegou a 9999 em
    21/02/2025 e reiniciou em 1000 no dia seguinte, então datas a partir de
    22/02/2025 caem no ciclo novo — é o caso de qualquer boleto atual.
    """
    dias = (vencimento - DATA_BASE_FATOR).days
    if dias < 0:
        raise ValueError(f"vencimento anterior à data base {DATA_BASE_FATOR.isoformat()}")
    if dias <= FATOR_MAXIMO:
        return dias
    dias_no_ciclo_novo = dias - FATOR_MAXIMO - 1
    return FATOR_REINICIO + dias_no_ciclo_novo % TAMANHO_CICLO_FATOR


def valor_em_centavos(valor: Decimal) -> int:
    """Converte um valor monetário em centavos, recusando frações de centavo."""
    centavos = valor * 100
    if centavos != centavos.to_integral_value():
        raise ValueError(f"valor {valor} tem fração de centavo")
    return int(centavos)


def monta_codigo_barras(
    *,
    banco_codigo: str,
    vencimento: date,
    valor: Decimal,
    campo_livre: str,
) -> str:
    """Monta os 44 dígitos do código de barras, já com o DV geral calculado."""
    if len(banco_codigo) != 3 or not banco_codigo.isdigit():
        raise ValueError(f"código do banco precisa de 3 dígitos, recebido {banco_codigo!r}")
    if len(campo_livre) != TAMANHO_CAMPO_LIVRE or not campo_livre.isdigit():
        raise ValueError(
            f"campo livre precisa de {TAMANHO_CAMPO_LIVRE} dígitos, recebido {campo_livre!r}"
        )

    sem_dv = (
        f"{banco_codigo}{MOEDA_REAL}"
        f"{fator_vencimento(vencimento):04d}"
        f"{valor_em_centavos(valor):010d}"
        f"{campo_livre}"
    )
    dv_geral = modulo11_boleto(sem_dv)
    return f"{sem_dv[:4]}{dv_geral}{sem_dv[4:]}"


def linha_digitavel_de_codigo_barras(codigo_barras: str) -> str:
    """Converte os 44 dígitos do código de barras nos 47 da linha digitável."""
    digitos = apenas_digitos(codigo_barras)
    if len(digitos) != TAMANHO_CODIGO_BARRAS:
        raise ValueError(
            f"código de barras precisa de {TAMANHO_CODIGO_BARRAS} dígitos, recebidos {len(digitos)}"
        )

    banco_e_moeda = digitos[0:4]
    dv_geral = digitos[4]
    fator_e_valor = digitos[5:19]
    campo_livre = digitos[19:44]

    campo_1 = banco_e_moeda + campo_livre[0:5]
    campo_2 = campo_livre[5:15]
    campo_3 = campo_livre[15:25]

    return (
        f"{campo_1}{modulo10(campo_1)}"
        f"{campo_2}{modulo10(campo_2)}"
        f"{campo_3}{modulo10(campo_3)}"
        f"{dv_geral}{fator_e_valor}"
    )


def codigo_barras_de_linha_digitavel(linha: str) -> str:
    """Converte os 47 dígitos da linha digitável de volta nos 44 do código de barras."""
    digitos = apenas_digitos(linha)
    if len(digitos) != TAMANHO_LINHA_DIGITAVEL:
        raise ValueError(
            f"linha digitável precisa de {TAMANHO_LINHA_DIGITAVEL} dígitos, "
            f"recebidos {len(digitos)}"
        )
    banco_e_moeda = digitos[0:4]
    dv_geral = digitos[32]
    fator_e_valor = digitos[33:47]
    campo_livre = digitos[4:9] + digitos[10:20] + digitos[21:31]
    return f"{banco_e_moeda}{dv_geral}{fator_e_valor}{campo_livre}"


def formata_linha_digitavel(linha: str) -> str:
    """Formata a linha para exibição: 00000.00000 00000.000000 00000.000000 0 00000000000000."""
    d = apenas_digitos(linha)
    if len(d) != TAMANHO_LINHA_DIGITAVEL:
        raise ValueError(
            f"linha digitável precisa de {TAMANHO_LINHA_DIGITAVEL} dígitos, recebidos {len(d)}"
        )
    return f"{d[0:5]}.{d[5:10]} {d[10:15]}.{d[15:21]} {d[21:26]}.{d[26:32]} {d[32]} {d[33:47]}"
