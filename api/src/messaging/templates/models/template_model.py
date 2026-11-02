"""Plantilla de contenido para un canal de mensajería, propia de un portafolio."""

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from messaging.templates.enums.template_enums import TemplateChannel, TemplateStatus


class TemplateModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "plantillas"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("portafolios.id"),
        nullable=False,
        index=True,
        name="id_portafolio",
    )

    name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, name="nombre_plantilla"
    )

    channel: Mapped[TemplateChannel] = mapped_column(
        Enum(TemplateChannel), nullable=False, name="canal"
    )

    status: Mapped[TemplateStatus] = mapped_column(
        Enum(
            TemplateStatus,
            name="estado_plantilla",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=TemplateStatus.DRAFT,
        name="estado_plantilla",
    )

    # Nullable: no aplica para WHATSAPP (el contenido real vive en Meta,
    # ver datos_plantilla_whatsapp).
    body: Mapped[str | None] = mapped_column(Text, nullable=True, name="cuerpo")

    design: Mapped[str | None] = mapped_column(Text, nullable=True, name="diseno")

    subject: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="asunto"
    )

    sender_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, name="nombre_remitente"
    )

    sender_email: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="email_remitente"
    )

    reply_to: Mapped[str | None] = mapped_column(
        String(255), nullable=True, name="responder_a"
    )
