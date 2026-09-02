"""Schema do boleto: o formato de saída da extração e o gabarito dos sintéticos."""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.dominio.digito_verificador import (
    TAMANHO_LINHA_DIGITAVEL,
    apenas_digitos,
    valida_cnpj,
    valida_cpf,
    valida_linha_digitavel,
)
from app.dominio.linha_digitavel import (
    fator_vencimento,
    formata_linha_digitavel,
    valor_em_centavos,
)

TAMANHO_CPF = 11
TAMANHO_CNPJ = 14

TextoNaoVazio = Annotated[str, Field(min_length=1, max_length=200)]


class Boleto(BaseModel):
    """Boleto de cobrança bancária.

    Os validadores são determinísticos: um boleto que instancia sem erro tem
    linha digitável, CNPJ e CPF conferidos, e os campos batem com o que está
    codificado na própria linha.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    linha_digitavel: str = Field(description="47 dígitos, sem formatação")
    beneficiario_nome: TextoNaoVazio
    beneficiario_cnpj: str = Field(description="14 dígitos, sem formatação")
    pagador_nome: TextoNaoVazio | None = None
    pagador_cpf_cnpj: str | None = Field(default=None, description="11 ou 14 dígitos")
    valor: Decimal = Field(gt=0, description="Em reais, com no máximo 2 casas")
    vencimento: date
    banco_codigo: str = Field(description="3 dígitos, ex.: 341")
    banco_nome: TextoNaoVazio
    nosso_numero: str | None = None

    @field_validator("linha_digitavel", mode="before")
    @classmethod
    def _normaliza_linha_digitavel(cls, valor: Any) -> Any:
        """Aceita a linha formatada, mas guarda só os dígitos."""
        if isinstance(valor, str):
            return apenas_digitos(valor)
        return valor

    @field_validator("linha_digitavel")
    @classmethod
    def _confere_dvs_da_linha(cls, linha: str) -> str:
        if len(linha) != TAMANHO_LINHA_DIGITAVEL:
            raise ValueError(
                f"linha digitável precisa de {TAMANHO_LINHA_DIGITAVEL} dígitos, "
                f"recebidos {len(linha)}"
            )
        resultado = valida_linha_digitavel(linha)
        if not resultado.valido:
            raise ValueError(f"linha digitável inválida: {resultado.descricao()}")
        return linha

    @field_validator("beneficiario_cnpj", mode="before")
    @classmethod
    def _normaliza_cnpj(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return apenas_digitos(valor)
        return valor

    @field_validator("beneficiario_cnpj")
    @classmethod
    def _confere_cnpj(cls, cnpj: str) -> str:
        if not valida_cnpj(cnpj):
            raise ValueError(f"CNPJ do beneficiário inválido: {cnpj}")
        return cnpj

    @field_validator("pagador_cpf_cnpj", mode="before")
    @classmethod
    def _normaliza_cpf_cnpj(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return apenas_digitos(valor) or None
        return valor

    @field_validator("pagador_cpf_cnpj")
    @classmethod
    def _confere_cpf_cnpj(cls, documento: str | None) -> str | None:
        if documento is None:
            return None
        if len(documento) == TAMANHO_CPF:
            if not valida_cpf(documento):
                raise ValueError(f"CPF do pagador inválido: {documento}")
        elif len(documento) == TAMANHO_CNPJ:
            if not valida_cnpj(documento):
                raise ValueError(f"CNPJ do pagador inválido: {documento}")
        else:
            raise ValueError(
                f"documento do pagador precisa de {TAMANHO_CPF} ou {TAMANHO_CNPJ} dígitos, "
                f"recebidos {len(documento)}"
            )
        return documento

    @field_validator("valor", mode="before")
    @classmethod
    def _recusa_float(cls, valor: Any) -> Any:
        """Valor monetário nunca passa por float: a conversão já perderia precisão."""
        if isinstance(valor, float):
            raise ValueError("valor monetário deve ser Decimal, int ou str — nunca float")
        if isinstance(valor, str):
            try:
                return Decimal(valor)
            except InvalidOperation as erro:
                raise ValueError(f"valor monetário inválido: {valor!r}") from erro
        return valor

    @field_validator("valor")
    @classmethod
    def _confere_casas_decimais(cls, valor: Decimal) -> Decimal:
        valor_em_centavos(valor)  # levanta ValueError se houver fração de centavo
        return valor

    @field_validator("banco_codigo", mode="before")
    @classmethod
    def _normaliza_banco_codigo(cls, valor: Any) -> Any:
        """Aceita 1 ou 341 e guarda sempre com 3 dígitos."""
        if isinstance(valor, int):
            return f"{valor:03d}"
        if isinstance(valor, str) and valor.strip().isdigit():
            return valor.strip().zfill(3)
        return valor

    @field_validator("banco_codigo")
    @classmethod
    def _confere_banco_codigo(cls, codigo: str) -> str:
        if len(codigo) != 3 or not codigo.isdigit():
            raise ValueError(f"código do banco precisa de 3 dígitos, recebido {codigo!r}")
        return codigo

    @field_validator("nosso_numero", mode="before")
    @classmethod
    def _normaliza_nosso_numero(cls, valor: Any) -> Any:
        if isinstance(valor, str):
            return valor.strip() or None
        return valor

    @model_validator(mode="after")
    def _confere_coerencia_com_a_linha(self) -> Self:
        """Cruza os campos avulsos com o que está codificado na linha digitável.

        É essa checagem que separa um boleto extraído corretamente de um em que
        o modelo leu certo a linha e errou o valor (ou vice-versa).
        """
        banco_na_linha = self.linha_digitavel[0:3]
        if banco_na_linha != self.banco_codigo:
            raise ValueError(
                f"banco {self.banco_codigo} não confere com a linha digitável ({banco_na_linha})"
            )

        centavos_na_linha = int(self.linha_digitavel[37:47])
        if centavos_na_linha != 0 and centavos_na_linha != valor_em_centavos(self.valor):
            esperado = Decimal(centavos_na_linha) / 100
            raise ValueError(
                f"valor {self.valor} não confere com a linha digitável (R$ {esperado})"
            )

        fator_na_linha = int(self.linha_digitavel[33:37])
        if fator_na_linha != 0 and fator_na_linha != fator_vencimento(self.vencimento):
            raise ValueError(
                f"vencimento {self.vencimento.isoformat()} não confere com o fator "
                f"da linha digitável ({fator_na_linha})"
            )

        return self

    @property
    def linha_digitavel_formatada(self) -> str:
        """Linha digitável com os pontos e espaços, como aparece impressa."""
        return formata_linha_digitavel(self.linha_digitavel)
