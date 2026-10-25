"""audit_fixes_indices_and_fks

Revision ID: 8e27cba8fa18
Revises: f6a7b8c9d0e1
Create Date: 2026-10-24 05:23:00.954871

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "8e27cba8fa18"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_chat_members_user_id", "chat_members", ["user_id"], unique=False
    )
    op.create_index(
        "ix_codigos_verificacion_usuario_canal_consumido",
        "codigos_verificacion",
        ["id_usuario", "canal", "consumido_en"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_ejecuciones_ivr_id_organizacion_entidades"),
        "ejecuciones_ivr",
        "entidades",
        ["id_organizacion"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_interacciones_ivr_id_organizacion_entidades"),
        "interacciones_ivr",
        "entidades",
        ["id_organizacion"],
        ["id"],
    )
    op.alter_column("items_factura", "canal_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        op.f("ix_items_factura_canal_id"), "items_factura", ["canal_id"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_items_factura_canal_id_canales"),
        "items_factura",
        "canales",
        ["canal_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        op.f("uq_membresia_usuario_entidad"), "membresias_organizacion", type_="unique"
    )
    op.create_index(
        "uq_membresia_usuario_entidad",
        "membresias_organizacion",
        ["id_usuario", "id_entidad"],
        unique=True,
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )
    op.create_index(
        op.f("ix_soporte_tickets_estado"), "soporte_tickets", ["estado"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_soporte_tickets_estado"), table_name="soporte_tickets")
    op.drop_index(
        "uq_membresia_usuario_entidad",
        table_name="membresias_organizacion",
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )
    op.create_unique_constraint(
        op.f("uq_membresia_usuario_entidad"),
        "membresias_organizacion",
        ["id_usuario", "id_entidad"],
    )
    op.drop_constraint(
        op.f("fk_items_factura_canal_id_canales"), "items_factura", type_="foreignkey"
    )
    op.drop_index(op.f("ix_items_factura_canal_id"), table_name="items_factura")
    op.alter_column(
        "items_factura", "canal_id", existing_type=sa.UUID(), nullable=False
    )
    op.drop_constraint(
        op.f("fk_interacciones_ivr_id_organizacion_entidades"),
        "interacciones_ivr",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_ejecuciones_ivr_id_organizacion_entidades"),
        "ejecuciones_ivr",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_codigos_verificacion_usuario_canal_consumido",
        table_name="codigos_verificacion",
    )
    op.drop_index("ix_chat_members_user_id", table_name="chat_members")
