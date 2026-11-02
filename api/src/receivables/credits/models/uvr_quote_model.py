"""Cotización histórica de UVR usada para créditos denominados en esa unidad."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class UVRQuoteModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "cotizaciones_uvr"

    quote_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, name="fecha_cotizacion"
    )
    quote_value: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), nullable=False, name="valor_cotizacion"
    )
    credit_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=True,
        name="id_credito",
        index=True,
    )
