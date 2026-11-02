"""Mensaje intercambiado dentro de un ticket de soporte."""

import uuid

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class SupportTicketMessageModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "soporte_mensajes"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("soporte_tickets.id", ondelete="CASCADE"),
        nullable=False,
        name="ticket_id",
        index=True,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="remitente_id",
        index=True,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, name="cuerpo")
    is_internal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="es_interno"
    )
