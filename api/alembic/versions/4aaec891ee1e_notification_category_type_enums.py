"""notification_category_type_enums

Revision ID: 4aaec891ee1e
Revises: 77a0e538e5da
Create Date: 2026-10-31 14:27:20.803567

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4aaec891ee1e"
down_revision: Union[str, None] = "77a0e538e5da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    sa.Enum("info", "success", "warning", "error", name="tipo_notificacion").create(
        op.get_bind()
    )
    sa.Enum(
        "support",
        "support_message",
        "org_verification",
        "identity_verification",
        "portfolio",
        "report",
        "judicial",
        name="categoria_notificacion",
    ).create(op.get_bind())
    op.alter_column(
        "notificaciones",
        "categoria",
        existing_type=sa.VARCHAR(length=100),
        type_=postgresql.ENUM(
            "support",
            "support_message",
            "org_verification",
            "identity_verification",
            "portfolio",
            "report",
            "judicial",
            name="categoria_notificacion",
        ),
        existing_nullable=False,
        postgresql_using="categoria::categoria_notificacion",
    )
    op.alter_column(
        "notificaciones",
        "tipo",
        existing_type=sa.VARCHAR(length=50),
        type_=postgresql.ENUM(
            "info", "success", "warning", "error", name="tipo_notificacion"
        ),
        existing_nullable=True,
        postgresql_using="tipo::tipo_notificacion",
    )


def downgrade() -> None:
    op.alter_column(
        "notificaciones",
        "tipo",
        existing_type=postgresql.ENUM(
            "info", "success", "warning", "error", name="tipo_notificacion"
        ),
        type_=sa.VARCHAR(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "notificaciones",
        "categoria",
        existing_type=postgresql.ENUM(
            "support",
            "support_message",
            "org_verification",
            "identity_verification",
            "portfolio",
            "report",
            "judicial",
            name="categoria_notificacion",
        ),
        type_=sa.VARCHAR(length=100),
        existing_nullable=False,
    )
    sa.Enum(
        "support",
        "support_message",
        "org_verification",
        "identity_verification",
        "portfolio",
        "report",
        "judicial",
        name="categoria_notificacion",
    ).drop(op.get_bind())
    sa.Enum("info", "success", "warning", "error", name="tipo_notificacion").drop(
        op.get_bind()
    )
