"""Mixin de auditoría: `created_at`."""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base


class CreatedAtMixin(Base):
    """`created_at` con default en Python y en el servidor (`server_default`): el
    servidor cubre los INSERT fuera del ORM (SQL directo, migraciones de datos)."""

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        name="fecha_creacion",
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
