"""Schema do informe de rendimentos e a aritmética que o confere.

O informe difere do boleto em espécie: é multi-registro. Cada quadro é uma
lista de linhas mais, **às vezes**, um total impresso. O "às vezes" é o ponto
todo, e está no ADR 007: o modelo oficial da Receita não imprime total nos
quadros 4 e 5, e no 3 a primeira linha já *é* o total, com as seguintes sendo
deduções e imposto. Conferir soma onde não há total seria conferir contra um
número que o gerador teria inventado.

Por isso a conferência de quadro tem três resultados, não dois:
`CONFERIDO`, `DIVERGENTE` e `SEM_TOTAL`. Aprovar por omissão faria todo quadro
sem total parecer verificado, e é justamente o que esta fase não pode fazer —
ver o princípio de só extrair o que é verificável.

O que é verificável aqui:

- DV do CNPJ da fonte pagadora e do CPF do beneficiário (reusa o ADR 002);
- `exercicio == ano_calendario + 1`, que é o que dá sinal ao ano;
- soma das linhas contra o total, onde o total é impresso;
- IRRF sobre o 13º não excede o 13º, no layout de fonte pagadora.

O que não é: os nomes. Entram por serem a identidade legível do documento, e
o cruzamento entre anos nunca casa por eles — ver a issue #2.
"""

from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dominio.digito_verificador import apenas_digitos, valida_cnpj, valida_cpf

TAMANHO_CPF = 11
TAMANHO_CNPJ = 14

# Os quadros do Anexo I em que o rendimento e o imposto sobre ele convivem.
# Ver `_confere_imposto_do_decimo_terceiro`.
LINHA_DECIMO_TERCEIRO = "5.1"
LINHA_IRRF_DECIMO_TERCEIRO = "5.2"

TextoNaoVazio = Annotated[str, Field(min_length=1, max_length=300)]

# Os campos comparáveis do informe, por nível. Ficam aqui porque é o domínio
# que sabe quais são, e `app.confianca.campos` declara como comparar cada um —
# a definição de igualdade mora num lugar só (ADR 005).
CAMPOS_ESCALARES = (
    "ano_calendario",
    "exercicio",
    "fonte_pagadora_cnpj",
    "fonte_pagadora_nome",
    "beneficiario_cpf",
    "beneficiario_nome",
)

CAMPOS_DE_LINHA = ("descricao", "valor")
"""`identificador` fica de fora: ele é a chave de casamento, não campo medido.
Errar a chave não vira erro de campo, vira linha não casada. Ver ADR 007."""

CAMPOS_DE_SALDO = ("saldo_31_12", "saldo_31_12_anterior")
"""`especificacao` também é chave, pela mesma razão."""


class Layout(StrEnum):
    """Qual documento se está lendo. Ver a tabela do ADR 007."""

    FONTE_PAGADORA = "fonte_pagadora"
    """Comprovante de Rendimentos Pagos, modelo da Receita. Linhas numeradas."""

    INSTITUICAO_FINANCEIRA = "instituicao_financeira"
    """Informe anual de rendimentos financeiros. Linhas por conta ou aplicação."""


class Cobertura(StrEnum):
    """O que a aritmética conseguiu afirmar sobre um quadro."""

    CONFERIDO = "conferido"
    """Há total impresso e a soma das linhas bate com ele."""

    DIVERGENTE = "divergente"
    """Há total impresso e a soma não bate. O documento não fecha."""

    SEM_TOTAL = "sem_total"
    """Não há total impresso: nada foi conferido. Não é aprovação."""


def _para_decimal(valor: Any) -> Any:
    """Aceita str, int e Decimal; recusa float antes de a precisão sumir."""
    if isinstance(valor, float):
        raise ValueError("valor monetário deve ser Decimal, int ou str — nunca float")
    if isinstance(valor, str):
        try:
            return Decimal(valor)
        except InvalidOperation as erro:
            raise ValueError(f"valor monetário inválido: {valor!r}") from erro
    return valor


def _confere_centavos(valor: Decimal) -> Decimal:
    if valor != valor.quantize(Decimal("0.01")):
        raise ValueError(f"valor {valor} tem fração de centavo")
    return valor


class LinhaDeQuadro(BaseModel):
    """Uma linha de um quadro, com a chave que a identifica na página.

    `identificador` é a chave de casamento das métricas de linha, e de onde ele
    vem depende do layout: no comprovante de fonte pagadora é o número impresso
    pelo formulário (`3.1`, `4.7`), e no informe bancário é a especificação da
    conta ou aplicação. Ver ADR 007.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identificador: TextoNaoVazio
    descricao: str = Field(default="", max_length=300)
    valor: Decimal

    _normaliza_valor = field_validator("valor", mode="before")(_para_decimal)

    @field_validator("valor")
    @classmethod
    def _valor_com_centavos(cls, valor: Decimal) -> Decimal:
        return _confere_centavos(valor)


class ConferenciaDeQuadro(BaseModel):
    """O que a soma disse sobre um quadro — inclusive quando não disse nada."""

    model_config = ConfigDict(frozen=True)

    quadro: str
    cobertura: Cobertura
    soma_das_linhas: Decimal
    total_impresso: Decimal | None

    @property
    def divergiu(self) -> bool:
        return self.cobertura is Cobertura.DIVERGENTE

    @property
    def tem_cobertura(self) -> bool:
        """Falso quando ninguém conferiu nada. Não confundir com aprovação."""
        return self.cobertura is not Cobertura.SEM_TOTAL

    def descricao(self) -> str:
        if self.cobertura is Cobertura.SEM_TOTAL:
            return f"quadro {self.quadro}: sem total impresso, soma não conferida"
        if self.cobertura is Cobertura.CONFERIDO:
            return f"quadro {self.quadro}: soma confere ({self.soma_das_linhas})"
        return (
            f"quadro {self.quadro}: soma das linhas {self.soma_das_linhas} "
            f"diverge do total impresso {self.total_impresso}"
        )


class Quadro(BaseModel):
    """Um quadro do informe: linhas identificadas e, quando a página traz, o total."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    identificador: TextoNaoVazio
    titulo: str = Field(default="", max_length=300)
    linhas: tuple[LinhaDeQuadro, ...] = ()
    total_impresso: Decimal | None = None
    """`None` quando a página não imprime total. Ver ADR 007."""

    _normaliza_total = field_validator("total_impresso", mode="before")(_para_decimal)

    @field_validator("total_impresso")
    @classmethod
    def _total_com_centavos(cls, valor: Decimal | None) -> Decimal | None:
        return None if valor is None else _confere_centavos(valor)

    @field_validator("linhas")
    @classmethod
    def _identificadores_unicos(
        cls, linhas: tuple[LinhaDeQuadro, ...]
    ) -> tuple[LinhaDeQuadro, ...]:
        """A chave de casamento tem que casar uma linha só.

        Identificador repetido é o quadro duplicado do corpus adversarial: sem
        esta recusa, o alinhamento de linha casaria a mesma chave duas vezes e
        a duplicata sumiria da métrica em vez de aparecer nela.
        """
        vistos = [linha.identificador for linha in linhas]
        repetidos = sorted({chave for chave in vistos if vistos.count(chave) > 1})
        if repetidos:
            raise ValueError(f"identificador de linha repetido no quadro: {', '.join(repetidos)}")
        return linhas

    @property
    def soma_das_linhas(self) -> Decimal:
        return sum((linha.valor for linha in self.linhas), Decimal("0"))

    def confere(self) -> ConferenciaDeQuadro:
        """Compara a soma das linhas com o total impresso, se houver um."""
        soma = self.soma_das_linhas
        if self.total_impresso is None:
            cobertura = Cobertura.SEM_TOTAL
        elif self.total_impresso == soma:
            cobertura = Cobertura.CONFERIDO
        else:
            cobertura = Cobertura.DIVERGENTE
        return ConferenciaDeQuadro(
            quadro=self.identificador,
            cobertura=cobertura,
            soma_das_linhas=soma,
            total_impresso=self.total_impresso,
        )

    def linha(self, identificador: str) -> LinhaDeQuadro | None:
        for linha in self.linhas:
            if linha.identificador == identificador:
                return linha
        return None


class SaldoDeConta(BaseModel):
    """Saldo de uma conta ou aplicação em 31/12, com o do ano anterior ao lado.

    Os dois saldos são afirmação do mesmo documento, então não se cruzam entre
    si. A redundância que vale é entre documentos de anos consecutivos — ver
    `app.dominio.cruzamento`.
    """

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    especificacao: TextoNaoVazio
    saldo_31_12: Decimal
    saldo_31_12_anterior: Decimal

    _normaliza_saldos = field_validator("saldo_31_12", "saldo_31_12_anterior", mode="before")(
        _para_decimal
    )

    @field_validator("saldo_31_12", "saldo_31_12_anterior")
    @classmethod
    def _saldo_com_centavos(cls, valor: Decimal) -> Decimal:
        return _confere_centavos(valor)


class Informe(BaseModel):
    """Informe de rendimentos anual.

    Um informe que instancia sem erro tem CNPJ e CPF conferidos por DV, o ano
    coerente com o exercício, e todo quadro com total impresso fechando com a
    soma das próprias linhas. O que ele **não** garante está em
    `quadros_sem_cobertura`, e essa lista é informação, não sobra.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    layout: Layout
    ano_calendario: int = Field(ge=1900, le=2200)
    exercicio: int = Field(ge=1900, le=2200)
    fonte_pagadora_cnpj: str = Field(description="14 dígitos, sem formatação")
    fonte_pagadora_nome: TextoNaoVazio
    beneficiario_cpf: str = Field(description="11 dígitos, sem formatação")
    beneficiario_nome: TextoNaoVazio
    rendimentos_tributaveis: Quadro
    rendimentos_isentos: Quadro
    rendimentos_exclusivos: Quadro
    saldos: tuple[SaldoDeConta, ...] = ()
    """Vazio no comprovante de fonte pagadora, que não tem saldo. Ver ADR 007."""

    @field_validator("fonte_pagadora_cnpj", "beneficiario_cpf", mode="before")
    @classmethod
    def _so_digitos(cls, valor: Any) -> Any:
        return apenas_digitos(valor) if isinstance(valor, str) else valor

    @field_validator("fonte_pagadora_cnpj")
    @classmethod
    def _confere_cnpj(cls, cnpj: str) -> str:
        if len(cnpj) != TAMANHO_CNPJ or not valida_cnpj(cnpj):
            raise ValueError(f"CNPJ da fonte pagadora inválido: {cnpj}")
        return cnpj

    @field_validator("beneficiario_cpf")
    @classmethod
    def _confere_cpf(cls, cpf: str) -> str:
        if len(cpf) != TAMANHO_CPF or not valida_cpf(cpf):
            raise ValueError(f"CPF do beneficiário inválido: {cpf}")
        return cpf

    @model_validator(mode="after")
    def _confere_exercicio(self) -> Self:
        """Exercício é sempre ano-calendário + 1, e é o único sinal do ano."""
        if self.exercicio != self.ano_calendario + 1:
            raise ValueError(
                f"exercício {self.exercicio} não confere com o ano-calendário "
                f"{self.ano_calendario}; esperado {self.ano_calendario + 1}"
            )
        return self

    @model_validator(mode="after")
    def _confere_somas_dos_quadros(self) -> Self:
        divergentes = [c.descricao() for c in self.conferencias() if c.divergiu]
        if divergentes:
            raise ValueError("; ".join(divergentes))
        return self

    @model_validator(mode="after")
    def _confere_imposto_do_decimo_terceiro(self) -> Self:
        """O IRRF sobre o 13º não pode exceder o 13º.

        Desigualdade fraca, e é quase tudo que o layout de fonte pagadora
        oferece de aritmética — ele não tem total para conferir soma. Vale o
        que vale: pega troca de casa decimal e sinal invertido, não pega erro
        de leitura pequeno.
        """
        if self.layout is not Layout.FONTE_PAGADORA:
            return self
        decimo = self.rendimentos_exclusivos.linha(LINHA_DECIMO_TERCEIRO)
        imposto = self.rendimentos_exclusivos.linha(LINHA_IRRF_DECIMO_TERCEIRO)
        if decimo is not None and imposto is not None and imposto.valor > decimo.valor:
            raise ValueError(
                f"IRRF sobre o 13º ({imposto.valor}) excede o próprio 13º ({decimo.valor})"
            )
        return self

    @model_validator(mode="after")
    def _confere_saldos_do_layout(self) -> Self:
        """Comprovante de fonte pagadora não tem saldo, e inventar um seria pior."""
        if self.layout is Layout.FONTE_PAGADORA and self.saldos:
            raise ValueError(
                "comprovante de fonte pagadora não tem saldo em 31/12; "
                f"recebidos {len(self.saldos)}"
            )
        return self

    @field_validator("saldos")
    @classmethod
    def _especificacoes_unicas(cls, saldos: tuple[SaldoDeConta, ...]) -> tuple[SaldoDeConta, ...]:
        """A especificação é a chave do cruzamento entre anos; repetida, não casa."""
        vistas = [saldo.especificacao for saldo in saldos]
        repetidas = sorted({chave for chave in vistas if vistas.count(chave) > 1})
        if repetidas:
            raise ValueError(f"especificação de saldo repetida: {', '.join(repetidas)}")
        return saldos

    @property
    def quadros(self) -> tuple[Quadro, ...]:
        return (
            self.rendimentos_tributaveis,
            self.rendimentos_isentos,
            self.rendimentos_exclusivos,
        )

    def conferencias(self) -> tuple[ConferenciaDeQuadro, ...]:
        """A aritmética de cada quadro, incluindo os que não deu para conferir."""
        return tuple(quadro.confere() for quadro in self.quadros)

    @property
    def quadros_sem_cobertura(self) -> tuple[str, ...]:
        """Quadros que ninguém conferiu, por não haver total impresso.

        Existe para o relatório poder dizer quanto do documento passou sem
        verificação. Um corpus em que isso é alto tem acurácia alta barata.
        """
        return tuple(c.quadro for c in self.conferencias() if not c.tem_cobertura)
