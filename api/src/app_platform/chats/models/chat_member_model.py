"""Membresía de un usuario en un chat, con su rol y estado de lectura."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import AuditModel


class ChatMemberModel(AuditModel):
    __tablename__ = "chat_members"
    __table_args__ = (
        # `user_id` es la columna no-líder de la PK compuesta: sin este índice,
        # "listar mis chats" (filtra por user_id) no tiene índice usable.
        Index("ix_chat_members_user_id", "user_id"),
        # `rol` es un IntEnum (MemberRole) sin tipo nativo de Postgres -- mismo
        # criterio que `ChatModel.type`: CHECK en vez de ENUM nativo, para no
        # cambiar el wire contract de la API (ya expone el entero tal cual).
        CheckConstraint("rol IN (0, 1, 2)", name="ck_chat_members_rol_valido"),
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        primary_key=True,
        name="chat_id",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        primary_key=True,
        name="user_id",
    )
    role: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, name="rol"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), name="fecha_union"
    )
    left_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_salida"
    )
