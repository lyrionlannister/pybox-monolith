"""Mixin de borrado lógico: `deleted_at`."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base


class SoftDeleteMixin(Base):
    """`deleted_at`, nulo mientras la fila está viva. Ver `SoftDeleteRepositoryBase`
    para las operaciones que lo usan (get_by_id/get_all lo filtran por defecto)."""

    __abstract__ = True

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="eliminado_en", default=None
    )
