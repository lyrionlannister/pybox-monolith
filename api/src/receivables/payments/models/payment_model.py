"""Cuota del cronograma de pagos de un crédito."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.payments.enums.payment_enums import PaymentStatus


class PaymentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "pagos"

    limit_pay_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="fecha_limite_pago"
    )
    payment_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_pago"
    )
    # Numeric, no Double: son montos de dinero (igual que CreditModel/InvoiceModel).
    payment_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="monto_pago"
    )
    installment_number: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="numero_cuota"
    )
    principal_payment: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="abono_capital"
    )
    current_interest_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="interes_corriente"
    )
    overdue_interest_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="interes_mora"
    )
    life_insurance_charge: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="seguro_vida"
    )
    vehicle_insurance_charge: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="seguro_vehiculo"
    )
    insurances_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="seguros_totales"
    )
    other_charges: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="otros_cargos"
    )
    total_interest_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="total_intereses"
    )
    other_concepts_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="otros_conceptos"
    )
    vat: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="iva"
    )
    commission_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="comision"
    )
    platform_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="fee_plataforma"
    )
    condonation_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="condonacion_aplicada"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="descuento_aplicado"
    )
    amount_uvr: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, name="monto_uvr"
    )
    uvr_quote_at_payment: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, name="cotizacion_uvr_pago"
    )
    status: Mapped[PaymentStatus] = mapped_column(
        # values_callable: crea el tipo PG desde los VALORES del enum ("PENDIENTE", …)
        # y no desde los NOMBRES (PENDING, …), que es el default de SQLAlchemy. Sin
        # esto, el `server_default` (que usa .value) queda fuera del tipo → CREATE TYPE
        # nunca incluye "PENDIENTE" y el INSERT falla con "invalid input value for enum
        # estado_pago".
        ENUM(
            PaymentStatus,
            name="estado_pago",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
        name="estado",
    )
    credit_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=False,
        index=True,
        name="id_credito",
    )
