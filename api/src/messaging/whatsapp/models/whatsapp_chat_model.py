"""Hilo de conversación de WhatsApp de un número dentro de una organización."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class WhatsAppChatModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Hilo de conversación de WhatsApp, uno por número de teléfono dentro de una
    organización (la organización se resuelve sin ambigüedad por el phone_number_id
    receptor, ver whatsapp_webhook_service).
    """

    __tablename__ = "whatsapp_chats"
    __table_args__ = (
        UniqueConstraint(
            "id_organizacion", "telefono", name="uq_whatsapp_chats_org_telefono"
        ),
    )

    # Portafolio y campaña del ContactModel más reciente que le escribió a
    # este telefono al momento en que se creó el hilo — ver
    # whatsapp_webhook_service._handle_message.
    # Nullable: un deudor puede escribir primero sin que exista un envío previo
    # asociado.
    portfolio_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=True,
        index=True,
        name="id_portafolio",
    )

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=True,
        index=True,
        name="id_campania",
    )

    phone: Mapped[str] = mapped_column(String(30), nullable=False, name="telefono")

    # Nombre de perfil de WhatsApp (value.contacts[].profile.name del webhook) — no es
    # el nombre real del deudor, es el que el usuario eligió mostrar en su WhatsApp.
    # Se actualiza con el valor más reciente en cada mensaje entrante que lo traiga.
    profile_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="nombre_perfil"
    )

    debtor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=True,
        name="id_deudor",
        index=True,
    )

    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        index=True,
        name="id_usuario_asignado",
    )

    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="ultimo_mensaje_en"
    )
