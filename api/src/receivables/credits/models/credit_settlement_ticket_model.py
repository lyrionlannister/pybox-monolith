"""Vínculo entre un ticket de soporte y el crédito que el titular pide dar de baja."""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import BaseModel


class CreditSettlementTicketModel(BaseModel):
    """Vincula un ticket de soporte con el crédito que el titular pide dar de baja
    (autogestión USER/SELF). El comprobante se guarda como adjunto del ticket en el
    almacén de objetos (DocumentOwnerScope.TICKET), no aquí.

    - settlement_amount: monto total del crédito al momento de solicitar (snapshot),
      que se cobra como un único pago al aprobar.
    - payment_id: el pago creado al aprobar la baja.
    """

    __tablename__ = "ticket_baja_credito"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("soporte_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="id_ticket",
    )
    credit_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=False,
        index=True,
        name="id_credito",
    )
    settlement_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0"), name="monto_baja"
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("pagos.id"),
        nullable=True,
        name="id_pago",
        index=True,
    )
