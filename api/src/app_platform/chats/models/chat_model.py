"""Chat directo o grupal entre usuarios de la plataforma."""

import uuid

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.audit_model import BaseModel


class ChatModel(BaseModel):
    __tablename__ = "chats"
    __table_args__ = (
        UniqueConstraint("clave_dm", name="uq_chats_clave_dm"),
        # `tipo` es un IntEnum (ChatType) sin tipo nativo de Postgres -- el wire
        # contract de la API ya expone el entero (0/1) tal cual, así que convertir
        # la columna a ENUM nativo de string cambiaría ese contrato; un CHECK cierra
        # la falta de integridad (nada impedía insertar un entero fuera de rango)
        # sin tocarlo.
        CheckConstraint("tipo IN (0, 1)", name="ck_chats_tipo_valido"),
    )

    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, name="tipo")
    dm_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="clave_dm", unique=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True, name="titulo")
    # Solo relevante para grupos (`type=GROUP`); en DIRECT siempre queda NULL. Fija el
    # scope del grupo la primera vez que entra un miembro ORGANIZATION-scoped y desde
    # ahí es inmutable — ChatService es el único que la escribe, nunca por request del
    # cliente. NULL = grupo "global-only" (todos los miembros son GLOBAL-scope).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("entidades.id"),
        nullable=True,
        index=True,
        name="id_organizacion",
    )

    @staticmethod
    def build_dm_key(a: uuid.UUID, b: uuid.UUID) -> str:
        ids = sorted([str(a), str(b)])
        return f"{ids[0]}:{ids[1]}"
