"""Mensaje de un chat de WhatsApp, entrante o saliente."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.whatsapp.enums.whatsapp_enums import (
    MessageDirection,
    WhatsAppMessageType,
)


class WhatsAppMessageModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    """Mensajes del hilo `whatsapp_chats` — entrantes (respuestas del deudor) y
    salientes conversacionales. Los envíos masivos de campaña ya viven en `contactos`
    y no se duplican aquí.
    """

    __tablename__ = "whatsapp_mensajes"

    chat_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("whatsapp_chats.id"),
        nullable=False,
        index=True,
        name="id_chat",
    )

    direction: Mapped[MessageDirection] = mapped_column(
        Enum(
            MessageDirection,
            name="direccion_mensaje",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="direccion",
    )

    wamid: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, name="wamid"
    )

    message_type: Mapped[WhatsAppMessageType] = mapped_column(
        Enum(
            WhatsAppMessageType,
            name="tipo_mensaje_whatsapp",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="tipo",
    )

    content: Mapped[str | None] = mapped_column(Text, nullable=True, name="contenido")

    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, name="payload_crudo"
    )

    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="enviado_en"
    )
