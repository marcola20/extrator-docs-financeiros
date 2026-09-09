"""Restringe as colunas de enum com CHECK, no banco e não só em Python.

A migração anterior criou as três colunas de enum como VARCHAR **sem restrição
nenhuma**, e ninguém percebeu até o schema ser conferido contra um Postgres de
verdade. A causa: no SQLAlchemy 2 o padrão de `Enum` é `create_constraint=False`,
então `native_enum=False` sozinho não produz o CHECK que a Fase 4.1 documentou.

Por que isso importa, e não é formalidade: o projeto inteiro se apoia em o
conjunto de estados de um sinal ser **fechado** — conferido, divergente, sem
cobertura, dispensado. Com a validação só em Python, quem escreve pelo ORM não
consegue introduzir um quinto, mas um `UPDATE` direto consegue, e a garantia
passaria a existir por convenção.

Escrita à mão porque `alembic revision --autogenerate` não compara CHECK: rodar
o autogenerate depois da correção do modelo produziu uma migração vazia.

Revision ID: a4ac89d142f4
Revises: 0a671ccf1def
Create Date: 2026-09-09
"""

from collections.abc import Sequence

from alembic import op

from app.persistencia.modelos import EstadoDoSinal, Rota, TipoDeDocumento

revision: str = "a4ac89d142f4"
down_revision: str | None = "0a671ccf1def"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Os valores vêm dos próprios enums: escrevê-los à mão aqui criaria uma segunda
# lista, e ela divergiria no dia em que um estado fosse acrescentado — que é
# justamente o dia em que esta restrição precisa estar certa.
RESTRICOES = (
    ("documento", "tipo", "ck_tipodedocumento", TipoDeDocumento),
    ("decisao", "rota", "ck_rota", Rota),
    ("sinal", "estado", "ck_estadodosinal", EstadoDoSinal),
)


def upgrade() -> None:
    """Fecha o conjunto de valores de cada coluna de enum.

    Em `batch_alter_table` porque o SQLite não sabe alterar constraint: lá o
    Alembic copia a tabela, recria com a restrição e move de volta. No Postgres
    sai um `ALTER TABLE ... ADD CONSTRAINT` normal. Sem o modo batch esta
    migração roda em produção e falha no banco de teste, que é onde ela é
    conferida contra os modelos.
    """
    for tabela, coluna, nome, enumeracao in RESTRICOES:
        valores = ", ".join(f"'{membro.value}'" for membro in enumeracao)
        with op.batch_alter_table(tabela) as lote:
            lote.create_check_constraint(nome, f"{coluna} IN ({valores})")


def downgrade() -> None:
    """Reabre o conjunto. As colunas continuam VARCHAR."""
    for tabela, _, nome, _ in RESTRICOES:
        with op.batch_alter_table(tabela) as lote:
            lote.drop_constraint(nome, type_="check")
