"""Solicitud de aprobación de un número de WhatsApp para una organización."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.tenant_mixin import TenantMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.whatsapp.enums.whatsapp_enums import ChannelRequestStatus


class WhatsAppChannelRequestModel(
    TenantMixin, IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Gate de consentimiento: un caso por (organización, teléfono) que debe aprobarse
    antes de que proceda el primer envío de WhatsApp a ese teléfono.
    """

    __tablename__ = "solicitudes_canal_whatsapp"
    __table_args__ = (
        UniqueConstraint(
            "id_organizacion",
            "telefono",
            name="uq_solicitud_canal_whatsapp_org_telefono",
        ),
    )

    phone: Mapped[str] = mapped_column(
        String(30), nullable=False, index=True, name="telefono"
    )

    debtor_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("deudores.id"),
        nullable=True,
        name="id_deudor",
        index=True,
    )

    status: Mapped[ChannelRequestStatus] = mapped_column(
        Enum(
            ChannelRequestStatus,
            name="estado_solicitud_canal",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ChannelRequestStatus.PENDING,
        name="estado",
    )

    origin_campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("campanias.id"),
        nullable=True,
        name="id_campania_origen",
        index=True,
    )

    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=True,
        name="resuelta_por",
        index=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="resuelta_en"
    )
