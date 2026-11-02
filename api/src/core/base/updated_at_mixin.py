"""Mixin de auditoría: `updated_at`."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base


class UpdatedAtMixin(Base):
    """`updated_at`, nulo hasta el primer UPDATE. `onupdate` solo dispara en flush del
    ORM: un UPDATE masivo armado con `update()` de SQLAlchemy Core tiene que setearlo
    a mano (ver `SoftDeleteRepositoryBase._touch`)."""

    __abstract__ = True

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        name="fecha_actualizacion",
        onupdate=func.now(),
    )
