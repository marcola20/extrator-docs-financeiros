"""Validação cruzada entre os informes de dois anos consecutivos.

É o sinal mais forte desta fase, e vale entender por quê. Todos os outros
validadores do projeto conferem um documento contra ele mesmo: os DVs da linha
digitável, a soma de um quadro contra o total que o próprio quadro imprime. Um
adversário que controla a página inteira pode fazer qualquer um deles fechar.

Este não. O informe do ano N imprime o saldo de 31/12/N-1, e o informe de N-1
imprime esse mesmo saldo por conta própria — **dois documentos, emitidos em
momentos diferentes, afirmando a mesma grandeza**. Adulterar um deles não
adultera o outro.

O que este módulo não faz: usar os dois saldos de um mesmo informe como
verificação. Eles são afirmação da mesma página e não se cruzam. Ver ADR 007.

O casamento é por especificação de conta, não por documento, e nunca por nome
— nome não tem verificação (issue #2). Titular e fonte pagadora são
comparados por CPF e CNPJ, que têm DV.
"""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.dominio.informe import Informe


class Incomparavel(StrEnum):
    """Por que dois informes não podem ser cruzados.

    Não é reprovação do documento: é a constatação de que estes dois não se
    verificam. Confundir as duas coisas transformaria "não dá para conferir"
    em "está errado", e o corpus tem os dois casos.
    """

    TITULAR_DIFERENTE = "titular_diferente"
    FONTE_DIFERENTE = "fonte_diferente"
    ANOS_NAO_CONSECUTIVOS = "anos_nao_consecutivos"


class DivergenciaDeSaldo(BaseModel):
    """Uma conta cujo saldo os dois informes contam diferente."""

    model_config = ConfigDict(frozen=True)

    especificacao: str
    declarado_no_ano: Decimal
    """`saldo_31_12_anterior` do informe do ano N."""
    declarado_no_ano_anterior: Decimal
    """`saldo_31_12` do informe do ano N-1, sobre a mesma data."""

    @property
    def diferenca(self) -> Decimal:
        return self.declarado_no_ano - self.declarado_no_ano_anterior

    def descricao(self) -> str:
        return (
            f"{self.especificacao}: o informe do ano diz {self.declarado_no_ano} "
            f"e o do ano anterior diz {self.declarado_no_ano_anterior} "
            f"(diferença de {self.diferenca})"
        )


class ContaNovaComHistorico(BaseModel):
    """Conta que não existia no ano anterior mas declara saldo anterior não-zero.

    Conta aberta durante o ano é legítima e comum. O que não fecha é ela vir
    com saldo em 31/12 do ano anterior: naquela data ela não existia. É a única
    regra determinística que se aplica a uma conta sem par.
    """

    model_config = ConfigDict(frozen=True)

    especificacao: str
    saldo_anterior_declarado: Decimal

    def descricao(self) -> str:
        return (
            f"{self.especificacao}: não aparece no informe do ano anterior, "
            f"mas declara saldo de {self.saldo_anterior_declarado} em 31/12 daquele ano"
        )


class ResultadoCruzamento(BaseModel):
    """O que o cruzamento entre dois anos conseguiu afirmar."""

    model_config = ConfigDict(frozen=True)

    incomparavel: Incomparavel | None = None
    contas_conferidas: tuple[str, ...] = ()
    divergencias: tuple[DivergenciaDeSaldo, ...] = ()
    contas_novas_com_historico: tuple[ContaNovaComHistorico, ...] = ()
    contas_novas: tuple[str, ...] = ()
    """Sem par no ano anterior e com saldo anterior zerado: legítimo."""
    contas_sem_conferencia: tuple[str, ...] = ()
    """Estavam no ano anterior e sumiram: o saldo daquele ano ficou sem cruzar."""

    @property
    def comparavel(self) -> bool:
        return self.incomparavel is None

    @property
    def tem_cobertura(self) -> bool:
        """Houve ao menos uma conta para conferir.

        Dois comprovantes de fonte pagadora são comparáveis — mesmo titular,
        mesma fonte, anos consecutivos — e não têm saldo nenhum. `valido` sai
        `True` sem nada ter sido conferido, e é a mesma armadilha do
        `SEM_TOTAL` dos quadros: quem consome precisa distinguir "fecha" de
        "não havia o que fechar".
        """
        return self.comparavel and bool(self.contas_conferidas)

    @property
    def valido(self) -> bool:
        """Comparável e sem nenhuma divergência.

        Par incomparável não é válido: ele não afirma nada, e devolver `True`
        aqui faria "não conferi" passar por "conferi e está certo".
        """
        return self.comparavel and not self.divergencias and not self.contas_novas_com_historico

    def descricao(self) -> str:
        if self.incomparavel is not None:
            return f"não comparáveis: {self.incomparavel.value}"
        problemas = [d.descricao() for d in self.divergencias]
        problemas += [c.descricao() for c in self.contas_novas_com_historico]
        if not problemas:
            return f"{len(self.contas_conferidas)} conta(s) conferida(s) entre os dois anos"
        return "; ".join(problemas)


def cruza(informe_do_ano: Informe, informe_do_ano_anterior: Informe) -> ResultadoCruzamento:
    """Confere os saldos que os dois informes afirmam sobre a mesma data.

    `informe_do_ano` é o do ano N e `informe_do_ano_anterior` o de N-1. A
    ordem importa: é do primeiro que sai `saldo_31_12_anterior`, e do segundo
    que sai o `saldo_31_12` com que ele é comparado.
    """
    incomparavel = _incomparavel(informe_do_ano, informe_do_ano_anterior)
    if incomparavel is not None:
        return ResultadoCruzamento(incomparavel=incomparavel)

    anteriores = {saldo.especificacao: saldo for saldo in informe_do_ano_anterior.saldos}

    conferidas: list[str] = []
    divergencias: list[DivergenciaDeSaldo] = []
    novas_com_historico: list[ContaNovaComHistorico] = []
    novas: list[str] = []

    for saldo in informe_do_ano.saldos:
        par = anteriores.get(saldo.especificacao)
        if par is None:
            if saldo.saldo_31_12_anterior != 0:
                novas_com_historico.append(
                    ContaNovaComHistorico(
                        especificacao=saldo.especificacao,
                        saldo_anterior_declarado=saldo.saldo_31_12_anterior,
                    )
                )
            else:
                novas.append(saldo.especificacao)
            continue

        conferidas.append(saldo.especificacao)
        if saldo.saldo_31_12_anterior != par.saldo_31_12:
            divergencias.append(
                DivergenciaDeSaldo(
                    especificacao=saldo.especificacao,
                    declarado_no_ano=saldo.saldo_31_12_anterior,
                    declarado_no_ano_anterior=par.saldo_31_12,
                )
            )

    presentes = {saldo.especificacao for saldo in informe_do_ano.saldos}
    sem_conferencia = tuple(sorted(anteriores.keys() - presentes))

    return ResultadoCruzamento(
        contas_conferidas=tuple(conferidas),
        divergencias=tuple(divergencias),
        contas_novas_com_historico=tuple(novas_com_historico),
        contas_novas=tuple(novas),
        contas_sem_conferencia=sem_conferencia,
    )


def _incomparavel(do_ano: Informe, do_anterior: Informe) -> Incomparavel | None:
    if do_ano.beneficiario_cpf != do_anterior.beneficiario_cpf:
        return Incomparavel.TITULAR_DIFERENTE
    if do_ano.fonte_pagadora_cnpj != do_anterior.fonte_pagadora_cnpj:
        return Incomparavel.FONTE_DIFERENTE
    if do_ano.ano_calendario != do_anterior.ano_calendario + 1:
        return Incomparavel.ANOS_NAO_CONSECUTIVOS
    return None
