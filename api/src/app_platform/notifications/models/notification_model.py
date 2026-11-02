"""Notificación in-app dirigida a un usuario."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from core.base.created_at_mixin import CreatedAtMixin
from core.base.id_mixin import IdMixin
from core.base.soft_delete_mixin import SoftDeleteMixin
from core.base.updated_at_mixin import UpdatedAtMixin


class NotificationModel(IdMixin, CreatedAtMixin, UpdatedAtMixin, SoftDeleteMixin):
    __tablename__ = "notificaciones"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("usuarios.id"),
        nullable=False,
        name="id_usuario",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, name="titulo")
    body: Mapped[str] = mapped_column(String(1000), nullable=False, name="cuerpo")
    category: Mapped[NotificationCategory] = mapped_column(
        ENUM(
            NotificationCategory,
            name="categoria_notificacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        name="categoria",
    )
    notif_type: Mapped[NotificationType | None] = mapped_column(
        ENUM(
            NotificationType,
            name="tipo_notificacion",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
        name="tipo",
        default=NotificationType.INFO,
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, name="leida"
    )
    link: Mapped[str | None] = mapped_column(String(500), nullable=True, name="enlace")
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True, name="detalles")
