"""Mixin de identidad: `id` UUID v7 como PK."""

import uuid

from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base


class IdMixin(Base):
    """PK `id` UUID v7. Los catálogos con clave natural o compuesta (p. ej.
    `CountryModel.code`, `ChatMemberModel` con `(chat_id, user_id)`) no la usan."""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid7, name="id"
    )
