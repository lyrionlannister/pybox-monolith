"""Factura mensual de una organización, con sus items y sus intentos de pago."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.orm import Mapped, mapped_column, relationship

from billing.invoices.enums.invoice_enums import InvoiceStatus
from billing.invoices.models.invoice_item_model import InvoiceItemModel
from billing.invoices.models.payment_attempt_model import InvoicePaymentAttemptModel
from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class InvoiceModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "facturas"
    __table_args__ = (
        UniqueConstraint(
            "id_organizacion",
            "anio_periodo",
            "mes_periodo",
            name="ux_facturas_org_periodo",
        ),
    )

    period_year: Mapped[int] = mapped_column(
        Integer, nullable=False, name="anio_periodo"
    )
    period_month: Mapped[int] = mapped_column(
        Integer, nullable=False, name="mes_periodo"
    )

    # Snapshot monetario inmutable al momento de emision
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="USD", name="moneda_base"
    )
    billing_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="COP", name="moneda_facturacion"
    )
    exchange_rate: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=0, name="tasa_cambio"
    )
    subtotal_base_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 6), nullable=False, default=0, name="subtotal_monto_base"
    )
    subtotal_billing_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, name="subtotal_monto_facturacion"
    )
    tax_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="NONE", name="tipo_impuesto"
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), nullable=False, default=0, name="tasa_impuesto"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, name="monto_impuesto"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=0, name="monto_total"
    )

    status: Mapped[InvoiceStatus] = mapped_column(
        ENUM(
            InvoiceStatus,
            name="estado_factura",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=InvoiceStatus.DRAFT,
        index=True,
        name="estado",
    )

    issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_emision"
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, name="fecha_vencimiento"
    )
    block_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, name="fecha_bloqueo"
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_pago"
    )

    items: Mapped[list[InvoiceItemModel]] = relationship(
        InvoiceItemModel,
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    attempts: Mapped[list[InvoicePaymentAttemptModel]] = relationship(
        InvoicePaymentAttemptModel, back_populates="invoice", lazy="selectin"
    )
