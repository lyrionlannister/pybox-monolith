"""Línea de factura: consumo snapshot de una campaña/canal en el periodo facturado."""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.base.audit_model import BaseModel


class InvoiceItemModel(BaseModel):
    __tablename__ = "items_factura"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("facturas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="factura_id",
    )

    # Snapshot de la campaña y el canal al momento de facturar
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id", ondelete="SET NULL"),
        nullable=True,
        name="campania_id",
        index=True,
    )
    campaign_name: Mapped[str] = mapped_column(
        String(255), nullable=False, name="nombre_campania"
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("canales.id", ondelete="SET NULL"),
        nullable=True,
        name="canal_id",
        index=True,
    )
    channel_name: Mapped[str] = mapped_column(
        String(100), nullable=False, name="nombre_canal"
    )
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", name="moneda_base"
    )
    # Precio unitario efectivo promedio (subtotal_base / quantity); el precio real
    # por mensaje puede variar dentro del periodo si el precio del canal cambio.
    unit_price_base: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, name="precio_unitario_base"
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, name="cantidad"
    )
    subtotal_base: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, default=0, name="subtotal_base"
    )

    invoice = relationship("InvoiceModel", back_populates="items")
