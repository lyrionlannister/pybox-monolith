"""Ajuste manual (condonación, corrección) aplicado a un crédito."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class CreditAdjustmentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "ajustes_credito"

    credit_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=False,
        index=True,
        name="id_credito",
    )
    adjustment_type: Mapped[str] = mapped_column(
        String, nullable=False, name="tipo_ajuste"
    )
    adjustment_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, name="monto_ajuste"
    )
    applied_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="fecha_aplicacion"
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True, name="nota")
