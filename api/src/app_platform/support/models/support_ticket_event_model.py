"""Evento del historial de un ticket de soporte (cambio de estado, asignación)."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app_platform.support.enums.support_enums import SupportTicketEventType
from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class SupportTicketEventModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "soporte_eventos"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("soporte_tickets.id", ondelete="CASCADE"),
        nullable=False,
        name="ticket_id",
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="usuario_id",
        index=True,
    )
    event_type: Mapped[SupportTicketEventType] = mapped_column(
        ENUM(
            SupportTicketEventType,
            name="tipo_evento_ticket_soporte",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="tipo_evento",
    )
    from_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="valor_anterior"
    )
    to_value: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="valor_nuevo"
    )
