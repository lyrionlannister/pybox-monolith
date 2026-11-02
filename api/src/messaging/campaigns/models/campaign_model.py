"""Campaña de mensajería de un portafolio, con su programación y estado."""

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.campaigns.enums.campaign_enums import CampaignStatus, Periodicity


class CampaignModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "campanias"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, name="nombre_campania"
    )

    # Nullable: no aplica para WHATSAPP (el contenido vive en la plantilla de Meta,
    # referenciada por template_id).
    message: Mapped[str | None] = mapped_column(Text, nullable=True, name="mensaje")

    subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="asunto"
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("canales.id"),
        nullable=False,
        name="id_canal",
        index=True,
    )

    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="descripcion_campania"
    )

    status: Mapped[CampaignStatus] = mapped_column(
        Enum(
            CampaignStatus,
            name="estado_campania",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CampaignStatus.DRAFT,
        name="estado_campania",
    )

    total_recipients: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, name="total_destinatarios"
    )

    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, name="programado_para"
    )

    timezone: Mapped[str] = mapped_column(
        String(50), default="UTC", name="zona_horaria"
    )

    fallback: Mapped[bool] = mapped_column(Boolean, default=True, name="fallback")

    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("segmentos.id"),
        nullable=True,
        index=True,
        name="id_segmento",
    )

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plantillas.id"),
        nullable=True,
        name="id_plantilla",
        index=True,
    )

    periodicity: Mapped[Periodicity | None] = mapped_column(
        Enum(
            Periodicity,
            name="periodicidad",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
        name="periodicidad",
    )

    time_to_send: Mapped[str | None] = mapped_column(
        String(8), nullable=True, name="hora_de_envio"
    )

    is_immediate: Mapped[bool] = mapped_column(
        Boolean, default=False, name="es_inmediato"
    )

    days_of_week: Mapped[list[int] | None] = mapped_column(
        ARRAY(Integer), nullable=True, name="dias_semana"
    )

    day_of_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True, name="dia_del_mes"
    )

    ivr_flow_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("flujos_ivr.id"),
        nullable=True,
        name="id_flujo_ivr",
    )
