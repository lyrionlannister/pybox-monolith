"""whatsapp phone_number_id unico

Revision ID: 9a1b2c3d4e5f
Revises: 468b2a8ec175
Create Date: 2026-11-04 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "9a1b2c3d4e5f"
down_revision: Union[str, None] = "468b2a8ec175"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_whatsapp_credenciales_id_numero_telefono",
        "whatsapp_credenciales_organizacion",
        ["id_numero_telefono"],
        unique=True,
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_whatsapp_credenciales_id_numero_telefono",
        table_name="whatsapp_credenciales_organizacion",
    )
