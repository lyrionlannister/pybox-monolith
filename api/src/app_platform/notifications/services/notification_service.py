"""Creación, listado y marcado de notificaciones, con push en vivo por SSE."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app_platform.notifications.enums.notification_enums import (
    NotificationCategory,
    NotificationType,
)
from app_platform.notifications.models.notification_model import NotificationModel
from app_platform.notifications.repository.notification_repository import (
    NotificationRepository,
)
from app_platform.notifications.schemas.notification_schemas import NotificationSchema
from core.sse.sse_emitter import sse_emitter


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = NotificationRepository(session)

    async def get_notifications(self, user_id: uuid.UUID) -> list[NotificationSchema]:
        items = await self._repo.get_by_user_id(user_id)
        return [NotificationSchema.model_validate(n) for n in items]

    async def get_notification(
        self, notification_id: uuid.UUID, user_id: uuid.UUID
    ) -> NotificationSchema | None:
        n = await self._repo.get_by_id_and_user(notification_id, user_id)
        return NotificationSchema.model_validate(n) if n else None

    async def mark_all_read(self, user_id: uuid.UUID) -> None:
        await self._repo.mark_all_read(user_id)

    async def create_notification(
        self,
        user_id: uuid.UUID,
        title: str,
        body: str,
        category: NotificationCategory,
        notif_type: NotificationType = NotificationType.INFO,
        link: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> NotificationSchema:
        notification = await self._repo.add(
            NotificationModel(
                user_id=user_id,
                title=title,
                body=body,
                category=category,
                notif_type=notif_type,
                link=link,
                details=details,
            )
        )
        schema = NotificationSchema.model_validate(notification)
        await sse_emitter.emit(
            user_id, "notification", schema.model_dump(mode="json", by_alias=True)
        )
        return schema
