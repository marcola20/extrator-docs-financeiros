"""Modelo de dados da fila de revisão.

Cinco tabelas, e nenhuma a mais: documento, extração, sinal, decisão e
correção. O que não estiver aqui é porque a tela da Fase 4 não precisa dele.

## O cuidado central: sinal não é booleano

É a decisão que as fases anteriores inteiras defenderam, e é a que uma tabela
mal desenhada apagaria em silêncio. Um sinal tem **quatro** resultados, não
dois, e a diferença entre eles é o produto do projeto:

| Estado | O que aconteceu | Bloqueia? |
|---|---|---|
| `CONFERIDO` | o sinal rodou e aprovou | não |
| `DIVERGENTE` | o sinal rodou e reprovou | sim |
| `SEM_COBERTURA` | não havia o que conferir | **sim** |
| `DISPENSADO` | o operador desligou o sinal | não |

`SEM_COBERTURA` é o que o ADR 009 fixou: quadro sem total impresso, par sem
conta em comum, PDF sem camada de texto. Guardar isso como `aprovou = false`
o confundiria com reprovação, e como `aprovou = true` o confundiria com
aprovação — as duas leituras erradas, em direções opostas. Guardar como `null`
perderia a distinção para `DISPENSADO`, que também não rodou mas foi escolha
do operador e **não** bloqueia.

A tela mostra os quatro com palavras diferentes. Um revisor precisa saber se
está olhando um documento que falhou numa conferência ou um que ninguém
conseguiu conferir: são trabalhos diferentes.

## Escopo do sinal, e por que ele é opcional

Nem todo sinal é por campo, e forçar todos a serem inventaria granularidade.
Sanitização, domínio, aritmética e cruzamento falam do **documento** (ou de um
quadro, ou de uma conta). Só o grounding fala de um lugar específico, e no
informe esse lugar é `rendimentos_isentos[LCI].valor`, não um nome de campo.

Então `escopo` é nulo quando o sinal fala do documento inteiro, e carrega o
endereço quando fala de um lugar. Uma coluna `campo` obrigatória obrigaria a
inventar um valor para os quatro sinais que não têm campo nenhum.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

# JSONB no Postgres, JSON em qualquer outro dialeto. A variante existe para os
# testes rodarem em SQLite: exigir Postgres para testar o mapeamento tornaria
# a suíte — e o CI — dependente de um serviço, e a restrição desta fase é
# justamente que o pipeline continue rodando sem banco.
JSONFlexivel = JSONB().with_variant(JSON(), "sqlite")


def coluna_de_enum[E: StrEnum](enumeracao: type[E]) -> Enum:
    """Uma coluna de texto que devolve o **enum**, não uma string parecida.

    `mapped_column(String(20))` com `Mapped[EstadoDoSinal]` grava certo e lê
    errado: volta `'sem_cobertura'`, uma `str` que a anotação promete ser
    `EstadoDoSinal`. O mypy acredita na anotação, `estado is EstadoDoSinal.X`
    dá falso em silêncio, e `estado.bloqueia` levanta `AttributeError` — no
    consumidor, longe daqui.

    `native_enum=False` guarda VARCHAR com CHECK em vez de um tipo ENUM do
    Postgres: acrescentar um estado passa a ser uma migração de constraint, e
    não um `ALTER TYPE` que não roda dentro de transação.

    `values_callable` grava o **valor** (`sem_cobertura`), não o nome do membro
    (`SEM_COBERTURA`). Sem ele o banco guardaria uma grafia que não existe em
    lugar nenhum do resto do projeto.
    """
    return Enum(
        enumeracao,
        native_enum=False,
        length=30,
        values_callable=lambda e: [membro.value for membro in e],
        validate_strings=True,
    )


class DataHoraUTC(TypeDecorator[datetime]):
    """`timestamptz`, com o fuso garantido na leitura em qualquer dialeto.

    O Postgres devolve `timestamptz` com fuso; o SQLite devolve ingênuo, porque
    não tem o tipo. Sem esta camada o mesmo código leria um `datetime` com fuso
    em produção e sem fuso no teste — e comparar os dois levanta `TypeError`,
    que apareceria só no ambiente onde ninguém testou.

    Não é conveniência de teste: é o banco de teste deixando de mentir sobre o
    tipo que a aplicação vai receber.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        # Ingênuo aqui é erro de quem chamou: não dá para adivinhar o fuso.
        if value.tzinfo is None:
            raise ValueError(f"data sem fuso não pode ser gravada: {value!r}")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def agora() -> datetime:
    """Instante atual em UTC, com fuso. Data ingênua não sobrevive a fuso."""
    return datetime.now(UTC)


class TipoDeDocumento(StrEnum):
    BOLETO = "boleto"
    INFORME = "informe"


class EstadoDoSinal(StrEnum):
    """Os quatro resultados de um sinal. Ver a nota do módulo."""

    CONFERIDO = "conferido"
    DIVERGENTE = "divergente"
    SEM_COBERTURA = "sem_cobertura"
    DISPENSADO = "dispensado"

    @property
    def bloqueia(self) -> bool:
        """Mesma regra de `app.confianca.politica.Veredito.bloqueia`.

        Está repetida aqui de propósito: a política decide, e esta propriedade
        só permite consultar a decisão já gravada sem recarregar o pipeline.
        O teste `test_o_estado_gravado_concorda_com_a_politica` é o que impede
        as duas de divergirem.
        """
        return self in (EstadoDoSinal.DIVERGENTE, EstadoDoSinal.SEM_COBERTURA)


class Rota(StrEnum):
    AUTO_APROVADO = "auto_aprovado"
    REVISAO_HUMANA = "revisao_humana"


class Base(DeclarativeBase):
    pass


class Documento(Base):
    """Um arquivo que entrou no pipeline."""

    __tablename__ = "documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    arquivo: Mapped[str] = mapped_column(String(500))
    """Caminho de onde o documento veio. Não é chave: o mesmo arquivo pode ser
    reprocessado, e o mesmo conteúdo pode chegar por caminhos diferentes."""

    hash_sha256: Mapped[str] = mapped_column(String(64), index=True)
    """Identidade do conteúdo. É por ele que se sabe que dois envios são o
    mesmo documento, e é ele que permite reprocessar sem reabrir o arquivo."""

    tipo: Mapped[TipoDeDocumento] = mapped_column(coluna_de_enum(TipoDeDocumento))
    paginas: Mapped[int | None] = mapped_column(Integer, default=None)
    ingerido_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)

    extracoes: Mapped[list["Extracao"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan", order_by="Extracao.id"
    )
    decisoes: Mapped[list["Decisao"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan", order_by="Decisao.id"
    )
    correcoes: Mapped[list["Correcao"]] = relationship(
        back_populates="documento", cascade="all, delete-orphan", order_by="Correcao.id"
    )

    __table_args__ = (
        CheckConstraint("length(hash_sha256) = 64", name="ck_documento_hash_sha256"),
        Index("ix_documento_tipo_ingerido", "tipo", "ingerido_em"),
    )


class Extracao(Base):
    """O que o modelo devolveu, e o que a chamada custou.

    `payload` guarda o **bruto**, sem conversão, exatamente como o transporte o
    entregou. Duas razões, e as duas são de auditoria:

    - reprocessar um sinal — ou um sinal novo — sobre extrações passadas não
      gasta cota nenhuma. Sem o bruto, mudar a política obrigaria a reextrair
      o corpus inteiro;
    - a pergunta "o modelo escreveu `1.847,30` ou `1847.30`?" só tem resposta
      aqui. É a mesma razão de o transporte ser todo texto (ADR 006).
    """

    __tablename__ = "extracao"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey("documento.id", ondelete="CASCADE"), index=True
    )

    payload: Mapped[dict[str, Any]] = mapped_column(JSONFlexivel)
    """O bruto do modelo, sem conversão. Ver a nota da classe."""

    prompt: Mapped[str] = mapped_column(String(120))
    """Identificador completo, com versão e digest: `informe-v1+44161a56`."""

    provedor: Mapped[str] = mapped_column(String(40))
    modelo: Mapped[str] = mapped_column(String(80))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)

    custo_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    """Dinheiro é Decimal, nunca float. Seis casas porque uma extração custa
    frações de centavo e a soma de um lote não pode sumir no arredondamento."""

    latencia_s: Mapped[Decimal] = mapped_column(Numeric(10, 3), default=Decimal("0"))
    do_cache: Mapped[bool] = mapped_column(default=False)
    erro_de_dominio: Mapped[str | None] = mapped_column(Text, default=None)
    """A mensagem da conversão que não fechou. `None` quando fechou."""

    criada_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)

    documento: Mapped[Documento] = relationship(back_populates="extracoes")
    decisao: Mapped["Decisao | None"] = relationship(back_populates="extracao", uselist=False)


class Decisao(Base):
    """A rota e a razão, com os vereditos de cada sinal pendurados."""

    __tablename__ = "decisao"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey("documento.id", ondelete="CASCADE"), index=True
    )
    extracao_id: Mapped[int | None] = mapped_column(
        ForeignKey("extracao.id", ondelete="CASCADE"), default=None, index=True
    )
    """Nulo quando o documento foi barrado **antes** de chegar ao modelo — PDF
    sem camada de texto, por exemplo. A decisão existe; a extração não."""

    rota: Mapped[Rota] = mapped_column(coluna_de_enum(Rota), index=True)
    revisada_em: Mapped[datetime | None] = mapped_column(DataHoraUTC, default=None)
    """Quando um humano fechou este item. Nulo = ainda na fila."""

    criada_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)

    documento: Mapped[Documento] = relationship(back_populates="decisoes")
    extracao: Mapped[Extracao | None] = relationship(back_populates="decisao")
    sinais: Mapped[list["Sinal"]] = relationship(
        back_populates="decisao", cascade="all, delete-orphan", order_by="Sinal.id"
    )

    __table_args__ = (Index("ix_decisao_fila", "rota", "revisada_em"),)


class Sinal(Base):
    """O veredito de um sinal, com os quatro estados preservados.

    `detalhe` é a mensagem que o próprio sinal escreveu — "não fecha: CNPJ da
    fonte pagadora inválido", "nenhum quadro tinha total impresso para
    conferir". Ela vai inteira para a tela: é o que diferencia um diagnóstico
    de um X vermelho.
    """

    __tablename__ = "sinal"

    id: Mapped[int] = mapped_column(primary_key=True)
    decisao_id: Mapped[int] = mapped_column(
        ForeignKey("decisao.id", ondelete="CASCADE"), index=True
    )

    nome: Mapped[str] = mapped_column(String(40), index=True)
    """`sanitizacao`, `dominio`, `aritmetica`, `cruzamento`, `grounding`,
    `consistencia`. Vem de `app.confianca.politica.Sinal`."""

    estado: Mapped[EstadoDoSinal] = mapped_column(coluna_de_enum(EstadoDoSinal), index=True)
    detalhe: Mapped[str] = mapped_column(Text, default="")

    escopo: Mapped[str | None] = mapped_column(String(200), default=None)
    """Onde o sinal falou, quando ele não fala do documento inteiro.

    Nulo para sanitização, domínio, aritmética e cruzamento. Preenchido para
    grounding, com o endereço do informe (`rendimentos_isentos[LCI].valor`) ou
    o nome do campo do boleto. Ver a nota do módulo."""

    decisao: Mapped[Decisao] = relationship(back_populates="sinais")


class Achado(Base):
    """Um trecho suspeito que o sanitizador encontrou, com onde ele está.

    Tabela própria, e não um JSON dentro de `Sinal`, porque a tela precisa
    listar e localizar cada trecho — é o que o revisor abre para comparar com o
    que está impresso na página.
    """

    __tablename__ = "achado"

    id: Mapped[int] = mapped_column(primary_key=True)
    decisao_id: Mapped[int] = mapped_column(
        ForeignKey("decisao.id", ondelete="CASCADE"), index=True
    )

    tipo: Mapped[str] = mapped_column(String(40))
    severidade: Mapped[str] = mapped_column(String(10))
    trecho: Mapped[str] = mapped_column(Text)
    detalhe: Mapped[str] = mapped_column(Text, default="")

    pagina: Mapped[int] = mapped_column(Integer, default=1)
    x0: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    topo: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    x1: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    base: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)

    decisao: Mapped[Decisao] = relationship()


class Correcao(Base):
    """O que um humano mudou, com o que estava lá antes.

    `valor_anterior` não é redundante com a extração: ele responde "o revisor
    corrigiu o quê?" sem precisar reconstruir o payload, e é o que permite
    medir quais campos o modelo erra na prática — que é o dado que a Fase 4
    existe para começar a coletar.
    """

    __tablename__ = "correcao"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(
        ForeignKey("documento.id", ondelete="CASCADE"), index=True
    )
    decisao_id: Mapped[int | None] = mapped_column(
        ForeignKey("decisao.id", ondelete="SET NULL"), default=None
    )

    campo: Mapped[str] = mapped_column(String(200))
    """Nome do campo no boleto, ou o endereço no informe."""

    valor_anterior: Mapped[str] = mapped_column(Text, default="")
    valor_corrigido: Mapped[str] = mapped_column(Text)
    revisor: Mapped[str] = mapped_column(String(120), default="")
    corrigido_em: Mapped[datetime] = mapped_column(DataHoraUTC, default=agora)

    documento: Mapped[Documento] = relationship(back_populates="correcoes")

    __table_args__ = (UniqueConstraint("decisao_id", "campo", name="uq_correcao_decisao_campo"),)
