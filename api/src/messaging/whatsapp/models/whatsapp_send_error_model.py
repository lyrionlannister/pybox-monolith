"""Error de envío de WhatsApp reportado por Meta vía webhook."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class WhatsAppSendErrorModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    # pylint: disable=line-too-long
    """Errores de envío reportados por Meta vía webhook (entry.changes.value.errors y/o
    statuses[].errors[]).

    Forma confirmada contra la doc (no hay campo `title` separado: Meta lo incluye
    dentro de `message`, ej. "(#131047) ..."; `error_subcode` está deprecado desde
    v16.0 y normalmente viene vacío):
    https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes

        {"error": {"message", "type", "code", "error_data": {"details"},
        "error_subcode", "fbtrace_id"}}
    """

    # pylint: enable=line-too-long

    __tablename__ = "whatsapp_errores_envio"

    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("contactos.id"),
        nullable=True,
        index=True,
        name="id_contacto",
    )

    # Id del mensaje de Meta si el error viene asociado a un envío
    # puntual (statuses[].id). Nullable: los errores de `value.errors` a
    # nivel de cuenta no siempre traen uno.
    wamid: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True, name="wamid"
    )

    error_code: Mapped[int] = mapped_column(
        Integer, nullable=False, name="codigo_error"
    )
    # Deprecado por Meta desde v16.0 — casi siempre viene null, se
    # conserva por si acaso.
    error_subcode: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="subcodigo_error"
    )
    error_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="tipo_error"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False, name="mensaje")
    details: Mapped[str | None] = mapped_column(Text, nullable=True, name="detalle")
    fbtrace_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="fbtrace_id"
    )

    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, name="payload_crudo"
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, name="ocurrido_en"
    )
