"""Estado de lectura de un mensaje por cada miembro del chat."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class MessageStatusModel(CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "estados_mensaje"

    message_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("mensajes_chat.id", ondelete="CASCADE"),
        primary_key=True,
        name="message_id",
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id", ondelete="CASCADE"),
        primary_key=True,
        name="user_id",
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="entregado_en"
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="leido_en"
    )
