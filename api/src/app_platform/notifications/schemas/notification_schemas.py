"""Schema de una notificación in-app."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from core.base.schema_base import BaseSchema


class NotificationSchema(BaseSchema):
    id: uuid.UUID = Field(description="ID de la notificación")
    title: str = Field(description="Título de la notificación")
    body: str = Field(description="Cuerpo del mensaje")
    category: NotificationCategory = Field(description="Categoría de la notificación")
    notif_type: NotificationType = Field(description="Tipo visual de la notificación")
    is_read: bool = Field(description="Indica si el usuario ya leyó la notificación")
    created_at: datetime = Field(description="Fecha de creación")
    link: str | None = Field(default=None, description="URL de destino al hacer clic")
    details: dict[str, Any] | None = Field(
        default=None, description="Datos adicionales de la notificación"
    )

    @field_validator("notif_type", mode="before")
    @classmethod
    def _default_type(cls, v: NotificationType | None) -> NotificationType:
        return v or NotificationType.INFO
