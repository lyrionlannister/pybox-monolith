"""Intento de cobro de una cuota contra la pasarela de pago de la organización."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.payment_gateways.enums.payment_gateway_enums import (
    ChargeMode,
    ReceivablesGatewayProvider,
    ReceivablesPaymentAttemptStatus,
)


class CreditPaymentAttemptModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Clon de `billing.invoices.models.InvoicePaymentAttemptModel`, pero para el
    cobro de cuotas de cartera (`PaymentModel`, deudor -> empresa) vía la pasarela
    propia de la organización. Los intentos nunca se sobrescriben; siempre se crea
    un nuevo registro, incluidos los que terminan DECLINED/ERROR/VOIDED (no es un
    libro de pagos confirmados, es un log de intentos).

    Sin `organization_id` propio: se deriva vía `payment_id` -> `credit_id` ->
    `portfolio_id`/`debtor_id` -> `organization_id` (mismo trade-off ya aceptado por
    `InvoicePaymentAttemptModel`, que tampoco duplica esa columna — ver reporte
    `db-schema-design`)."""

    __tablename__ = "intentos_pago_credito"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("pagos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="id_pago",
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, name="numero_intento"
    )
    provider: Mapped[ReceivablesGatewayProvider] = mapped_column(
        ENUM(
            ReceivablesGatewayProvider,
            name="proveedor_pasarela_organizacion",
            create_type=False,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReceivablesGatewayProvider.WOMPI,
        name="proveedor",
    )
    charge_mode: Mapped[ChargeMode] = mapped_column(
        ENUM(
            ChargeMode,
            name="modo_cobro",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ChargeMode.CHECKOUT,
        name="modo_cobro",
    )
    # Nuestra referencia: PAG-{shortId}-{numeroIntento}-{timestamp} <= 60 caracteres.
    provider_reference: Mapped[str | None] = mapped_column(
        String(60), nullable=True, index=True, name="referencia_proveedor"
    )
    # Id de la transaccion en Wompi (`data.id`), usado para GET /transactions/{id}
    # y para emparejar el resultado del webhook con este intento.
    provider_transaction_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True, name="id_transaccion_proveedor"
    )
    payment_source_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fuentes_pago_deudor.id"),
        nullable=True,
        name="id_fuente_pago",
    )
    # Wompi trabaja en centavos COP (amount_in_cents); se congela al crear el
    # intento y se valida contra el monto reportado por el webhook antes de marcar
    # la cuota como pagada.
    expected_amount_cents: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, name="monto_esperado_centavos"
    )
    status: Mapped[ReceivablesPaymentAttemptStatus] = mapped_column(
        ENUM(
            ReceivablesPaymentAttemptStatus,
            name="estado_intento_pago_credito",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ReceivablesPaymentAttemptStatus.PENDING,
        name="estado",
    )
    provider_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, name="payload_proveedor"
    )
    # Auditoria Ley 1581 (Habeas Data, ver skill wompi-gateway Paso 3): solo aplica
    # en CHECKOUT, donde el deudor esta presente para leer y aceptar estos
    # permalinks antes de pagar. En AUTOMATIC_3RI no hay deudor presente en el
    # momento del cobro; la aceptacion ya quedo registrada al crear la fuente de
    # pago (DebtorPaymentSourceModel).
    acceptance_permalink: Mapped[str | None] = mapped_column(
        String(500), nullable=True, name="permalink_aceptacion"
    )
    personal_data_permalink: Mapped[str | None] = mapped_column(
        String(500), nullable=True, name="permalink_datos_personales"
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_aceptacion"
    )
