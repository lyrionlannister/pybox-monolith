"""add_contactos_org_sent_at_index

Revision ID: 44a66edcff5a
Revises: 8e27cba8fa18
Create Date: 2026-10-31 14:09:54.740897

"""

from typing import Sequence, Union

from alembic import op

revision: str = "44a66edcff5a"
down_revision: Union[str, None] = "8e27cba8fa18"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_contactos_organizacion_enviado_en",
        "contactos",
        ["id_organizacion", "enviado_en"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_contactos_organizacion_enviado_en", table_name="contactos")
