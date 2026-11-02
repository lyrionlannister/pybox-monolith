"""Relación entre un documento y el ticket de soporte al que pertenece."""

import uuid

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app_platform.support.enums.support_enums import TicketDocumentCategory
from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class TicketDocumentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Adjunto de un ticket de soporte (del reporte o de la evidencia de cierre).

    Tabla de unión por relación, misma solución que `documentos_deudor`: reemplaza
    al par `documentos.ambito='TICKET' + documentos.id_dueno`. Las dos FK son reales
    y unidireccionales (`soporte_tickets` y `documentos` no apuntan de vuelta), así
    que no hay ciclo y no hace falta `use_alter`.
    """

    __tablename__ = "documentos_ticket"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("soporte_tickets.id"),
        nullable=False,
        index=True,
        name="id_ticket",
    )
    category: Mapped[TicketDocumentCategory] = mapped_column(
        ENUM(
            TicketDocumentCategory,
            name="categoria_documento_ticket",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        name="categoria",
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documentos.id"),
        nullable=False,
        unique=True,
        name="id_documento",
    )
