"""Crédito de un deudor dentro de un portafolio."""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.credits.enums.credit_enums import CreditTypes


def _enum_values(enum_cls: type[StrEnum]) -> list[str]:
    """values_callable para los ENUM de este modelo.

    Hace que el tipo PG se arme con los VALORES del enum ("TARJETA_CREDITO", …) y
    no con los NOMBRES (CREDIT_CARD, …), que es el default de SQLAlchemy. Sin esto, el
    `server_default` (que usa .value) queda fuera del tipo. Mismo criterio que
    PaymentStatus en payment_model.
    """
    return [m.value for m in enum_cls]


class CreditModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "creditos"

    __table_args__ = (
        # numero_credito lo asigna el sistema de cada empresa: dos empresas (o dos
        # portafolios) pueden reusar el mismo número sin que sea un conflicto real.
        # Único global rompía esto y además permitía que el upsert masivo por CSV
        # reasignara silenciosamente un crédito de una empresa a otra si coincidía
        # el número (ver CreditRepository.bulk_upsert_by_credit_number).
        UniqueConstraint(
            "id_portafolio", "numero_credito", name="uq_creditos_portafolio_numero"
        ),
    )

    credit_number: Mapped[str] = mapped_column(
        String, index=True, nullable=False, name="numero_credito"
    )
    credit_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_credito"
    )
    # Qué se debe, desde la perspectiva del titular: es el eje que colorea el
    # calendario del home SELF. El sector de la entidad acreedora vive en
    # `entidades.sector`, no aquí: no varía entre los créditos de una misma entidad.
    credit_type: Mapped[CreditTypes] = mapped_column(
        ENUM(CreditTypes, name="credittypes", values_callable=_enum_values),
        nullable=False,
        default=CreditTypes.OTHER_SERVICE,
        server_default=CreditTypes.OTHER_SERVICE.value,
        name="tipo_credito",
    )
    agreed_interest_rate: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="tasa_interes_pactada"
    )
    balance_disbursed: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="saldo_desembolsado"
    )
    disbursed_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="fecha_desembolso"
    )
    court_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="fecha_corte"
    )
    initial_term: Mapped[int] = mapped_column(
        Integer, nullable=False, name="plazo_inicial"
    )
    total_credit_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="saldo_total_credito"
    )
    overdue_principal_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="saldo_capital_mora"
    )
    current_interest: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="interes_corriente"
    )
    overdue_interest: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="interes_mora"
    )
    other_concepts: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="otros_conceptos"
    )
    overdue_installments: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, name="cuotas_en_mora"
    )
    days_overdue_at_cutoff: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, name="dias_mora_al_corte"
    )
    amortization_system: Mapped[str | None] = mapped_column(
        String, nullable=True, name="sistema_amortizacion"
    )
    charged_effective_annual_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True, default=0, name="tasa_efectiva_anual_cobrada"
    )
    pending_installments: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, name="cuotas_pendientes"
    )
    insurance_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="seguros_totales"
    )
    commission_accum: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="comision_acumulada"
    )
    platform_fee_accum: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="fee_plataforma_acumulado"
    )
    vat_accum: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="iva_acumulado"
    )
    subproduct: Mapped[str | None] = mapped_column(
        String, nullable=True, name="subproducto"
    )
    uvr_last_quote: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, name="uvr_ultima_cotizacion"
    )
    condonations_accum: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="condonaciones_acumuladas"
    )
    discounts_accum: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, name="descuentos_acumulados"
    )
    # Un crédito activo está vigente; se desactiva (activo=False) cuando el titular
    # lo da de baja (autogestión USER/SELF: comprobante → ticket a la org → al
    # aprobar se registra el pago total).
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true", name="activo"
    )

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )
    debtor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=False,
        index=True,
        name="id_deudor",
    )
    codebtor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=True,
        index=True,
        name="id_codeudor",
    )
