"""Notificación judicial enviada por una entidad a un deudor."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin
from receivables.judicial_notifications.enums.judicial_notification_enums import (
    JudicialPriority,
)


class JudicialNotificationModel(
    IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin
):
    """Notificación judicial que una entidad emite sobre un crédito concreto.

    Cuelga del crédito y no del deudor: la entidad acreedora, el tipo de crédito y
    el titular se derivan por join (crédito → portafolio → entidad), así que no se
    duplican.
    """

    __tablename__ = "notificaciones_judiciales"

    credit_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("creditos.id"),
        nullable=False,
        index=True,
        name="id_credito",
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, name="titulo")
    body: Mapped[str] = mapped_column(String(1000), nullable=False, name="cuerpo")
    # values_callable para persistir los VALORES del enum ("URGENTE", …) y no los
    # NOMBRES (URGENT, …), que es el default de SQLAlchemy y dejaría el
    # server_default fuera del tipo.
    priority: Mapped[JudicialPriority] = mapped_column(
        ENUM(
            JudicialPriority,
            name="prioridad_judicial",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=JudicialPriority.INFORMATIVE,
        server_default=JudicialPriority.INFORMATIVE.value,
        name="prioridad",
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", name="leida"
    )
    # Fecha del hecho judicial, que no tiene por qué ser la de captura en el sistema.
    notified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        name="fecha_notificacion",
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="creado_por",
        index=True,
    )
