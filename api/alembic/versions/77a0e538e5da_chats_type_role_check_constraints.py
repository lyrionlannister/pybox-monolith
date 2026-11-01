"""chats_type_role_check_constraints

Revision ID: 77a0e538e5da
Revises: 0b2a0f323a2a
Create Date: 2026-10-31 14:21:08.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "77a0e538e5da"
down_revision: Union[str, None] = "0b2a0f323a2a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_chats_tipo_valido", "chats", "tipo IN (0, 1)")
    op.create_check_constraint(
        "ck_chat_members_rol_valido", "chat_members", "rol IN (0, 1, 2)"
    )


def downgrade() -> None:
    op.drop_constraint("ck_chat_members_rol_valido", "chat_members", type_="check")
    op.drop_constraint("ck_chats_tipo_valido", "chats", type_="check")
