"""segment_execution_document_fk

Revision ID: 0b2a0f323a2a
Revises: 44a66edcff5a
Create Date: 2026-10-31 14:13:28.909149

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0b2a0f323a2a"
down_revision: Union[str, None] = "44a66edcff5a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ejecuciones_segmentos", sa.Column("id_documento", sa.UUID(), nullable=True)
    )
    op.create_index(
        op.f("ix_ejecuciones_segmentos_id_documento"),
        "ejecuciones_segmentos",
        ["id_documento"],
        unique=True,
    )
    op.create_foreign_key(
        op.f("fk_ejecuciones_segmentos_id_documento_documentos"),
        "ejecuciones_segmentos",
        "documentos",
        ["id_documento"],
        ["id"],
    )
    op.drop_column("ejecuciones_segmentos", "ruta_archivo")


def downgrade() -> None:
    op.add_column(
        "ejecuciones_segmentos",
        sa.Column("ruta_archivo", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.drop_constraint(
        op.f("fk_ejecuciones_segmentos_id_documento_documentos"),
        "ejecuciones_segmentos",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_ejecuciones_segmentos_id_documento"),
        table_name="ejecuciones_segmentos",
    )
    op.drop_column("ejecuciones_segmentos", "id_documento")
