"""Vínculo entre un ticket de soporte y el pago/crédito sobre el que actúa."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class PaymentTicketModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Tabla intermedia que vincula un ticket de soporte con el pago y el crédito
    sobre el que actúa (solicitudes de autogestión del titular desde el calendario:
    "Reprogramación de pago" y "Validación de pago").

    Da al CUSTOMER_SERVICE que resuelve el ticket el contexto exacto de qué cuota
    tocar, y guarda el payload de la solicitud:
    - requested_date: nueva fecha propuesta por el titular (solo reprogramación).
    - new_payment_id: la cuota nueva creada al aprobar la reprogramación.
    El comprobante (validación de pago) se guarda como adjunto del ticket en el
    almacén de objetos (DocumentOwnerScope.TICKET), no aquí.
    """

    __tablename__ = "ticket_pago_credito"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("soporte_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="id_ticket",
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("pagos.id"),
        nullable=False,
        index=True,
        name="id_pago",
    )
    credit_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=False,
        index=True,
        name="id_credito",
    )
    requested_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_solicitada"
    )
    new_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("pagos.id"),
        nullable=True,
        name="id_pago_nuevo",
        index=True,
    )
