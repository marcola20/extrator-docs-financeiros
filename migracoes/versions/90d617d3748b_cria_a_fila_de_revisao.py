"""Cria a fila de revisão: documento, extração, sinal, achado, decisão e correção.

Primeira migração do projeto. O Postgres já estava no docker-compose desde a
Fase 1 e nunca tinha sido usado — até aqui o pipeline não persistia nada, e a
correção humana não sobrevivia ao reinício.

O tipo de `payload` é a variante do modelo: JSONB no Postgres, JSON em SQLite.
É o que permite aplicar esta migração num banco de teste sem subir Postgres, e
é como o teste confere que a migração e os modelos descrevem o mesmo schema.

Revision ID: 90d617d3748b
Revises:
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.sqltypes import Text

revision: str = "90d617d3748b"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Cria as seis tabelas."""
    op.create_table(
        "documento",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("arquivo", sa.String(length=500), nullable=False),
        sa.Column("hash_sha256", sa.String(length=64), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("paginas", sa.Integer(), nullable=True),
        sa.Column("ingerido_em", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(hash_sha256) = 64", name="ck_documento_hash_sha256"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documento_hash_sha256"), "documento", ["hash_sha256"], unique=False)
    op.create_index(
        "ix_documento_tipo_ingerido", "documento", ["tipo", "ingerido_em"], unique=False
    )
    op.create_table(
        "extracao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.Integer(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=Text()).with_variant(sa.JSON(), "sqlite"),
            nullable=False,
        ),
        sa.Column("prompt", sa.String(length=120), nullable=False),
        sa.Column("provedor", sa.String(length=40), nullable=False),
        sa.Column("modelo", sa.String(length=80), nullable=False),
        sa.Column("tokens_entrada", sa.Integer(), nullable=False),
        sa.Column("tokens_saida", sa.Integer(), nullable=False),
        sa.Column("custo_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("latencia_s", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column("do_cache", sa.Boolean(), nullable=False),
        sa.Column("erro_de_dominio", sa.Text(), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documento.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_extracao_documento_id"), "extracao", ["documento_id"], unique=False)
    op.create_table(
        "decisao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.Integer(), nullable=False),
        sa.Column("extracao_id", sa.Integer(), nullable=True),
        sa.Column("rota", sa.String(length=20), nullable=False),
        sa.Column("revisada_em", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criada_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["documento_id"], ["documento.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extracao_id"], ["extracao.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decisao_documento_id"), "decisao", ["documento_id"], unique=False)
    op.create_index(op.f("ix_decisao_extracao_id"), "decisao", ["extracao_id"], unique=False)
    op.create_index("ix_decisao_fila", "decisao", ["rota", "revisada_em"], unique=False)
    op.create_index(op.f("ix_decisao_rota"), "decisao", ["rota"], unique=False)
    op.create_table(
        "achado",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decisao_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=40), nullable=False),
        sa.Column("severidade", sa.String(length=10), nullable=False),
        sa.Column("trecho", sa.Text(), nullable=False),
        sa.Column("detalhe", sa.Text(), nullable=False),
        sa.Column("pagina", sa.Integer(), nullable=False),
        sa.Column("x0", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("topo", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("x1", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("base", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.ForeignKeyConstraint(["decisao_id"], ["decisao.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_achado_decisao_id"), "achado", ["decisao_id"], unique=False)
    op.create_table(
        "correcao",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("documento_id", sa.Integer(), nullable=False),
        sa.Column("decisao_id", sa.Integer(), nullable=True),
        sa.Column("campo", sa.String(length=200), nullable=False),
        sa.Column("valor_anterior", sa.Text(), nullable=False),
        sa.Column("valor_corrigido", sa.Text(), nullable=False),
        sa.Column("revisor", sa.String(length=120), nullable=False),
        sa.Column("corrigido_em", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decisao_id"], ["decisao.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["documento_id"], ["documento.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decisao_id", "campo", name="uq_correcao_decisao_campo"),
    )
    op.create_index(op.f("ix_correcao_documento_id"), "correcao", ["documento_id"], unique=False)
    op.create_table(
        "sinal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decisao_id", sa.Integer(), nullable=False),
        sa.Column("nome", sa.String(length=40), nullable=False),
        sa.Column("estado", sa.String(length=20), nullable=False),
        sa.Column("detalhe", sa.Text(), nullable=False),
        sa.Column("escopo", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["decisao_id"], ["decisao.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sinal_decisao_id"), "sinal", ["decisao_id"], unique=False)
    op.create_index(op.f("ix_sinal_estado"), "sinal", ["estado"], unique=False)
    op.create_index(op.f("ix_sinal_nome"), "sinal", ["nome"], unique=False)


def downgrade() -> None:
    """Desfaz, na ordem inversa das dependências."""
    op.drop_index(op.f("ix_sinal_nome"), table_name="sinal")
    op.drop_index(op.f("ix_sinal_estado"), table_name="sinal")
    op.drop_index(op.f("ix_sinal_decisao_id"), table_name="sinal")
    op.drop_table("sinal")
    op.drop_index(op.f("ix_correcao_documento_id"), table_name="correcao")
    op.drop_table("correcao")
    op.drop_index(op.f("ix_achado_decisao_id"), table_name="achado")
    op.drop_table("achado")
    op.drop_index(op.f("ix_decisao_rota"), table_name="decisao")
    op.drop_index("ix_decisao_fila", table_name="decisao")
    op.drop_index(op.f("ix_decisao_extracao_id"), table_name="decisao")
    op.drop_index(op.f("ix_decisao_documento_id"), table_name="decisao")
    op.drop_table("decisao")
    op.drop_index(op.f("ix_extracao_documento_id"), table_name="extracao")
    op.drop_table("extracao")
    op.drop_index("ix_documento_tipo_ingerido", table_name="documento")
    op.drop_index(op.f("ix_documento_hash_sha256"), table_name="documento")
    op.drop_table("documento")
