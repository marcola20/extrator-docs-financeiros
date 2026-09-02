"""Dígitos verificadores de linha digitável, CPF e CNPJ.

Todas as funções aqui são determinísticas e sem efeito colateral: são a base
da confiança do pipeline, que não depende do confidence reportado pelo modelo.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

TAMANHO_LINHA_DIGITAVEL = 47
"""Quantidade de dígitos da linha digitável, já sem a formatação visual."""

TAMANHO_CODIGO_BARRAS = 44
"""Quantidade de dígitos do código de barras."""

_SOMENTE_DIGITOS = re.compile(r"\D")


class CampoLinhaDigitavel(StrEnum):
    """Identifica qual parte da linha digitável foi reprovada na validação."""

    FORMATO = "formato"
    CAMPO_1 = "campo_1"
    CAMPO_2 = "campo_2"
    CAMPO_3 = "campo_3"
    DV_GERAL = "dv_geral"


@dataclass(frozen=True, slots=True)
class ErroValidacao:
    """Uma falha específica encontrada na validação."""

    campo: CampoLinhaDigitavel
    mensagem: str
    esperado: str | None = None
    encontrado: str | None = None

    def __str__(self) -> str:
        if self.esperado is None or self.encontrado is None:
            return f"{self.campo}: {self.mensagem}"
        return (
            f"{self.campo}: {self.mensagem} "
            f"(esperado {self.esperado}, encontrado {self.encontrado})"
        )


@dataclass(frozen=True, slots=True)
class ResultadoValidacao:
    """Resultado de uma validação, dizendo *quais* campos falharam."""

    valido: bool
    erros: tuple[ErroValidacao, ...] = ()

    @classmethod
    def aprovado(cls) -> "ResultadoValidacao":
        """Cria um resultado sem nenhuma falha."""
        return cls(valido=True, erros=())

    @classmethod
    def reprovado(cls, *erros: ErroValidacao) -> "ResultadoValidacao":
        """Cria um resultado reprovado com pelo menos uma falha."""
        if not erros:
            raise ValueError("um resultado reprovado precisa de ao menos um erro")
        return cls(valido=False, erros=erros)

    @property
    def campos_invalidos(self) -> tuple[CampoLinhaDigitavel, ...]:
        """Campos que falharam, na ordem em que aparecem na linha."""
        return tuple(erro.campo for erro in self.erros)

    def descricao(self) -> str:
        """Texto legível com todas as falhas, ou 'ok' quando não há nenhuma."""
        if self.valido:
            return "ok"
        return "; ".join(str(erro) for erro in self.erros)


def apenas_digitos(texto: str) -> str:
    """Remove qualquer caractere que não seja dígito (pontos, espaços, traços)."""
    return _SOMENTE_DIGITOS.sub("", texto)


def modulo10(digitos: str) -> int:
    """Calcula o DV módulo 10 de uma sequência de dígitos.

    Pesos 2 e 1 alternados da direita para a esquerda. Produto maior que 9 tem
    os algarismos somados. O DV é a próxima dezena menos a soma (0 se o resto
    da divisão por 10 for 0).
    """
    _exige_digitos(digitos, "modulo10")

    soma = 0
    peso = 2
    for caractere in reversed(digitos):
        produto = int(caractere) * peso
        if produto > 9:
            produto = produto // 10 + produto % 10
        soma += produto
        peso = 1 if peso == 2 else 2

    resto = soma % 10
    return 0 if resto == 0 else 10 - resto


def modulo11_boleto(digitos: str) -> int:
    """Calcula o DV geral (módulo 11) do código de barras de boleto.

    Pesos de 2 a 9 ciclando da direita para a esquerda, usando o valor cheio do
    produto. O DV é 11 menos o resto da divisão por 11; se o resultado for 0,
    10 ou 11, o DV é 1.
    """
    _exige_digitos(digitos, "modulo11_boleto")

    soma = 0
    peso = 2
    for caractere in reversed(digitos):
        soma += int(caractere) * peso
        peso = 2 if peso == 9 else peso + 1

    dv = 11 - (soma % 11)
    return 1 if dv in (0, 10, 11) else dv


def codigo_barras_sem_dv(linha: str) -> str:
    """Remonta os 43 dígitos do código de barras (sem o DV geral) a partir da linha.

    A linha digitável embaralha o código de barras: o DV geral e o campo
    "fator + valor" vão para o fim, e o campo livre é quebrado em três pedaços.
    """
    digitos = apenas_digitos(linha)
    if len(digitos) != TAMANHO_LINHA_DIGITAVEL:
        raise ValueError(
            f"linha digitável precisa de {TAMANHO_LINHA_DIGITAVEL} dígitos, "
            f"recebidos {len(digitos)}"
        )
    banco_e_moeda = digitos[0:4]
    fator_e_valor = digitos[33:47]
    campo_livre = digitos[4:9] + digitos[10:20] + digitos[21:31]
    return banco_e_moeda + fator_e_valor + campo_livre


def valida_linha_digitavel(linha: str) -> ResultadoValidacao:
    """Confere os quatro dígitos verificadores da linha digitável de 47 posições.

    Aceita a linha formatada (com pontos e espaços) ou apenas os dígitos.
    Todos os campos são conferidos: o resultado lista todas as falhas, não só
    a primeira.
    """
    digitos = apenas_digitos(linha)
    if len(digitos) != TAMANHO_LINHA_DIGITAVEL:
        return ResultadoValidacao.reprovado(
            ErroValidacao(
                campo=CampoLinhaDigitavel.FORMATO,
                mensagem="quantidade de dígitos incorreta",
                esperado=str(TAMANHO_LINHA_DIGITAVEL),
                encontrado=str(len(digitos)),
            )
        )

    erros: list[ErroValidacao] = []

    campos_modulo10 = (
        (CampoLinhaDigitavel.CAMPO_1, digitos[0:9], digitos[9]),
        (CampoLinhaDigitavel.CAMPO_2, digitos[10:20], digitos[20]),
        (CampoLinhaDigitavel.CAMPO_3, digitos[21:31], digitos[31]),
    )
    for campo, corpo, dv_informado in campos_modulo10:
        dv_calculado = modulo10(corpo)
        if dv_calculado != int(dv_informado):
            erros.append(
                ErroValidacao(
                    campo=campo,
                    mensagem="DV módulo 10 não confere",
                    esperado=str(dv_calculado),
                    encontrado=dv_informado,
                )
            )

    dv_geral_calculado = modulo11_boleto(codigo_barras_sem_dv(digitos))
    dv_geral_informado = digitos[32]
    if dv_geral_calculado != int(dv_geral_informado):
        erros.append(
            ErroValidacao(
                campo=CampoLinhaDigitavel.DV_GERAL,
                mensagem="DV geral módulo 11 não confere",
                esperado=str(dv_geral_calculado),
                encontrado=dv_geral_informado,
            )
        )

    if erros:
        return ResultadoValidacao.reprovado(*erros)
    return ResultadoValidacao.aprovado()


def valida_cpf(cpf: str) -> bool:
    """Confere os dois dígitos verificadores de um CPF de 11 posições."""
    digitos = apenas_digitos(cpf)
    if len(digitos) != 11 or _todos_iguais(digitos):
        return False

    for tamanho_base in (9, 10):
        base = digitos[:tamanho_base]
        peso_inicial = tamanho_base + 1
        soma = sum(int(caractere) * (peso_inicial - i) for i, caractere in enumerate(base))
        resto = (soma * 10) % 11
        dv = 0 if resto == 10 else resto
        if dv != int(digitos[tamanho_base]):
            return False

    return True


_PESOS_CNPJ = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def valida_cnpj(cnpj: str) -> bool:
    """Confere os dois dígitos verificadores de um CNPJ numérico de 14 posições."""
    digitos = apenas_digitos(cnpj)
    if len(digitos) != 14 or _todos_iguais(digitos):
        return False

    for tamanho_base in (12, 13):
        base = digitos[:tamanho_base]
        pesos = _PESOS_CNPJ[-tamanho_base:] if tamanho_base <= 12 else (6, *_PESOS_CNPJ)
        soma = sum(int(caractere) * peso for caractere, peso in zip(base, pesos, strict=True))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(digitos[tamanho_base]):
            return False

    return True


def _todos_iguais(digitos: str) -> bool:
    """Indica se todos os dígitos são o mesmo (00000000000, 11111111111, ...)."""
    return len(set(digitos)) == 1


def _exige_digitos(digitos: str, origem: str) -> None:
    """Falha cedo quando a entrada não é uma sequência não vazia de dígitos."""
    if not digitos or not digitos.isdigit():
        raise ValueError(f"{origem} espera apenas dígitos, recebido {digitos!r}")
