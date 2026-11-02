"""Definición de un segmento de cartera (criterio dinámico de filtrado)."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class SegmentModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "segmentos"

    name: Mapped[str] = mapped_column(String, nullable=False, name="nombre")
    description: Mapped[str | None] = mapped_column(
        String, nullable=True, name="descripcion"
    )
    filter_criteria: Mapped[dict] = mapped_column(
        JSONB, nullable=False, name="criterios_filtro"
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )
