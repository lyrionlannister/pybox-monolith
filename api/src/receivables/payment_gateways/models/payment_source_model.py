"""Fuente de pago guardada (tokenizada) de un deudor para cobros recurrentes."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.payment_gateways.enums.payment_gateway_enums import (
    PaymentSourceStatus,
    PaymentSourceType,
    ReceivablesGatewayProvider,
)


class DebtorPaymentSourceModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Medio de pago tokenizado y reutilizable de UN deudor, guardado para que la
    organización dueña de su crédito pueda cobrarle cuotas futuras sin que reingrese
    los datos (ver skill `wompi-gateway`, Paso 5). El deudor ya es de una sola
    organización (`DebtorModel.organization_id`), así que no se duplica esa columna
    aquí — se deriva en una sola pasada vía `debtor_id`."""

    __tablename__ = "fuentes_pago_deudor"

    debtor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        name="id_deudor",
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
    type: Mapped[PaymentSourceType] = mapped_column(
        ENUM(
            PaymentSourceType,
            name="tipo_fuente_pago",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="tipo",
    )
    # Id que devuelve `POST /payment_sources` de Wompi — se usa para cobrar contra
    # esta fuente (`payment_source_id` en `POST /transactions`), nunca se guarda el
    # PAN/token.
    provider_source_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, name="id_fuente_proveedor"
    )
    status: Mapped[PaymentSourceStatus] = mapped_column(
        ENUM(
            PaymentSourceStatus,
            name="estado_fuente_pago",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PaymentSourceStatus.PENDING,
        name="estado",
    )
    # Solo True si la tokenización pasó por el challenge 3DS completo exigido por el
    # protocolo 3RI (ver skill `wompi-gateway`, Paso 6) — condición necesaria (no
    # suficiente: también depende de la marca y de la activación de fraude de la
    # organización) para poder cobrar esta fuente sin que el deudor confirme.
    three_ds_enrolled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="inscrito_3ds"
    )
    # Solo para mostrarle al deudor cuál medio tiene guardado — nunca el PAN completo.
    masked_identifier: Mapped[str | None] = mapped_column(
        String(40), nullable=True, name="identificador_enmascarado"
    )
    brand: Mapped[str | None] = mapped_column(String(40), nullable=True, name="marca")
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, name="activo"
    )
    # Auditoría Ley 1581 (Habeas Data): cuándo el deudor aceptó los términos vigentes al
    # tokenizar este medio de pago (ver skill `wompi-gateway`, Paso 3).
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_aceptacion"
    )
