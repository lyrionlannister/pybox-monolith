"""Configuración de actualización diaria de contadores de un portafolio."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class PortfolioDailyCounterConfigModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    __tablename__ = "config_actualizacion_diaria_portafolio"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        unique=True,
        index=True,
        name="id_portafolio",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="habilitado"
    )
    reactivation_mode: Mapped[str] = mapped_column(
        String, nullable=False, default="FROM_TODAY", name="modo_reactivacion"
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        name="actualizado_por",
        index=True,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="ultima_sincronizacion_at"
    )
    last_synced_cutoff_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, name="ultima_fecha_corte_sincronizada"
    )
