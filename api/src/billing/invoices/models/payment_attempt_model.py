"""Intento de pago de una factura contra la pasarela de facturación (Bold/MP)."""

import uuid
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from billing.invoices.enums.invoice_enums import PaymentAttemptStatus, PaymentProvider
from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class InvoicePaymentAttemptModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "intentos_pago_factura"

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("facturas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="factura_id",
    )

    # Los intentos nunca se sobrescriben; siempre se crea un nuevo registro.
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, name="numero_intento"
    )

    provider: Mapped[PaymentProvider] = mapped_column(
        ENUM(
            PaymentProvider,
            name="proveedor_pago",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PaymentProvider.BOLD,
        name="proveedor",
    )

    # INV-{shortId}-{attemptNumber}-{timestamp} <= 60 caracteres
    provider_reference: Mapped[str | None] = mapped_column(
        String(60), nullable=True, index=True, name="referencia_proveedor"
    )
    provider_link_id: Mapped[str | None] = mapped_column(
        String, nullable=True, name="id_enlace_proveedor"
    )
    payment_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, name="url_pago"
    )
    # Monto esperado en la moneda de facturacion (billing_currency) congelado
    # al crear el intento; se valida contra el monto reportado por el webhook
    # del proveedor antes de marcar la factura como pagada.
    expected_amount: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, name="monto_esperado"
    )
    status: Mapped[PaymentAttemptStatus] = mapped_column(
        ENUM(
            PaymentAttemptStatus,
            name="estado_intento_pago",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PaymentAttemptStatus.ACTIVE,
        name="estado",
    )
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, name="payload_proveedor"
    )

    invoice = relationship("InvoiceModel", back_populates="attempts")
