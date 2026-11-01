"""address_type_enum

Revision ID: dfb82fec8ec8
Revises: 4aaec891ee1e
Create Date: 2026-10-31 14:31:49.098653

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "dfb82fec8ec8"
down_revision: Union[str, None] = "4aaec891ee1e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sa.Enum("PRIMARY", "SECONDARY", name="tipo_direccion_deudor").create(op.get_bind())
    op.alter_column(
        "direcciones",
        "tipo_direccion",
        existing_type=sa.VARCHAR(),
        type_=postgresql.ENUM("PRIMARY", "SECONDARY", name="tipo_direccion_deudor"),
        existing_nullable=False,
        postgresql_using="tipo_direccion::tipo_direccion_deudor",
    )


def downgrade() -> None:
    op.alter_column(
        "direcciones",
        "tipo_direccion",
        existing_type=postgresql.ENUM(
            "PRIMARY", "SECONDARY", name="tipo_direccion_deudor"
        ),
        type_=sa.VARCHAR(),
        existing_nullable=False,
    )
    sa.Enum("PRIMARY", "SECONDARY", name="tipo_direccion_deudor").drop(op.get_bind())
