"""hash verification codes

Revision ID: 0c1d2e3f4a5b
Revises: 9a1b2c3d4e5f
Create Date: 2026-11-04 13:00:00.000000

Los OTP pasan a guardarse como HMAC (64 caracteres hex). Los códigos vigentes en
claro dejan de validar al desplegar; expiran en minutos y el usuario pide otro.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0c1d2e3f4a5b"
down_revision: Union[str, None] = "9a1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "codigos_verificacion",
        "codigo",
        existing_type=sa.String(length=6),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("DELETE FROM codigos_verificacion")
    op.alter_column(
        "codigos_verificacion",
        "codigo",
        existing_type=sa.String(length=64),
        type_=sa.String(length=6),
        existing_nullable=False,
    )
